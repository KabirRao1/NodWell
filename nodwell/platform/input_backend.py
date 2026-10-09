"""Mouse output behind an interface, with the safety gate in front of it.

Coordinates are physical pixels on Windows/X11 and points on macOS (DECISIONS.md D12).
`PynputBackend` must be created after the QApplication, because Qt makes the process
DPI-aware on startup and pynput's coordinates depend on that.
"""

from __future__ import annotations

import logging
import math
import sys
import threading
import time
from typing import Protocol

from nodwell.core.actions import Button, ClickAction
from nodwell.core.safety import ClickRateLimiter, SafetyGate

log = logging.getLogger(__name__)

Point = tuple[float, float]


class InputBackend(Protocol):
    """Mouse interface the pipeline needs."""

    def position(self) -> Point | None: ...
    def move_to(self, x: float, y: float) -> None: ...
    def press(self, button: Button) -> None: ...
    def release(self, button: Button) -> None: ...
    def click(self, button: Button, count: int) -> None: ...
    def scroll(self, dx: float, dy: float) -> None: ...


class PynputBackend:
    """Real OS input through pynput (X11 on Linux; Wayland is unsupported, CLAUDE.md §12)."""

    def __init__(self) -> None:
        from pynput import mouse

        self._mouse = mouse.Controller()
        self._buttons = {
            Button.LEFT: mouse.Button.left,
            Button.RIGHT: mouse.Button.right,
            Button.MIDDLE: mouse.Button.middle,
        }

    def position(self) -> Point | None:
        try:
            x, y = self._mouse.position
        except Exception:  # e.g. no permission on macOS
            return None
        return (float(x), float(y))

    def move_to(self, x: float, y: float) -> None:
        self._mouse.position = (round(x), round(y))

    def press(self, button: Button) -> None:
        self._mouse.press(self._buttons[button])

    def release(self, button: Button) -> None:
        self._mouse.release(self._buttons[button])

    def click(self, button: Button, count: int) -> None:
        self._mouse.click(self._buttons[button], count)

    def scroll(self, dx: float, dy: float) -> None:
        self._mouse.scroll(dx, dy)


class DryRunBackend:
    """Records actions instead of performing them (replays, smoke tests, benchmarks)."""

    def __init__(self) -> None:
        self._pos: Point | None = None
        self.moves = 0
        self.actions: list[tuple[str, Point | None]] = []
        self.scrolled = 0.0

    @property
    def clicks(self) -> list[Point | None]:
        return [pos for name, pos in self.actions if name.startswith("click")]

    def position(self) -> Point | None:
        return self._pos

    def move_to(self, x: float, y: float) -> None:
        self._pos = (round(x), round(y))
        self.moves += 1

    def press(self, button: Button) -> None:
        self.actions.append((f"press {button}", self._pos))

    def release(self, button: Button) -> None:
        self.actions.append((f"release {button}", self._pos))

    def click(self, button: Button, count: int) -> None:
        self.actions.append((f"click {button} x{count}", self._pos))

    def scroll(self, dx: float, dy: float) -> None:
        self.scrolled += dy


class GatedInput:
    """Wraps a backend so nothing reaches the OS while the safety gate is closed.

    The second line of defence: the engine already refuses to act when paused or without a
    face, but the gate also stops output instantly when the panic hotkey fires, even if the
    pipeline thread hasn't processed the pause yet. Clicks are rate limited here too.

    Thread-safe: the pipeline, the pointer animator, and the hotkey thread all call in, so
    every backend call happens under one lock. Releasing held buttons always goes through,
    even with the gate closed, so a drag can never leave a button stuck down.
    """

    def __init__(
        self, backend: InputBackend, gate: SafetyGate, min_click_interval_s: float
    ) -> None:
        self.backend = backend
        self.gate = gate
        self._limiter = ClickRateLimiter(min_click_interval_s)
        self._lock = threading.RLock()
        self._last_written: Point | None = None
        self._held: set[Button] = set()
        self._scroll_rest = [0.0, 0.0]
        # Windows accepts fractional wheel steps (smooth scrolling); X11/macOS via pynput
        # only whole notches, so the remainder is carried over between frames.
        self._scroll_unit = 1 / 12 if sys.platform == "win32" else 1.0

    def position(self) -> Point | None:
        with self._lock:
            return self.backend.position()

    def move_to(self, x: float, y: float) -> bool:
        with self._lock:
            if not self.gate.allows():
                return False
            self.backend.move_to(x, y)
            self._last_written = (round(x), round(y))
            return True

    def perform(self, action: ClickAction) -> bool:
        """Do one click, press, or release. Returns whether it reached the OS."""
        with self._lock:
            if action.kind == "release":
                if action.button not in self._held:
                    return False
                self._held.discard(action.button)
                self.backend.release(action.button)
                return True
            if not self.gate.allows() or not self._limiter.try_acquire(time.monotonic()):
                return False
            if action.kind == "press":
                self._held.add(action.button)
                self.backend.press(action.button)
            else:
                self.backend.click(action.button, action.count)
            log.debug("%s %s x%d", action.kind, action.button, action.count)
            return True

    def scroll(self, dx: float, dy: float) -> bool:
        with self._lock:
            if not self.gate.allows():
                self._scroll_rest = [0.0, 0.0]
                return False
            out = []
            for i, amount in enumerate((dx, dy)):
                total = self._scroll_rest[i] + amount
                steps = math.trunc(total / self._scroll_unit) * self._scroll_unit
                self._scroll_rest[i] = total - steps
                out.append(steps)
            if out[0] or out[1]:
                self.backend.scroll(out[0], out[1])
            return True

    def release_all(self) -> None:
        """Release every button we hold. Bypasses the gate: releasing is always safe."""
        with self._lock:
            for button in sorted(self._held):
                try:
                    self.backend.release(button)
                except Exception:
                    log.exception("could not release %s", button)
            self._held.clear()

    def external_move(self, threshold: float) -> Point | None:
        """The real cursor position if a person moved the mouse since our last write.

        Compares against what we last wrote (not the engine's target), because the pointer
        animator lags the target on purpose. Reports each takeover once.
        """
        with self._lock:
            if self._last_written is None:
                return None
            pos = self.backend.position()
            if pos is None or math.dist(pos, self._last_written) <= threshold:
                return None
            self._last_written = None
            return pos

    def forget_written(self) -> None:
        """Called on resume: moves made while paused weren't ours to judge."""
        with self._lock:
            self._last_written = None
