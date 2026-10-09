"""Mouse output behind an interface, with the safety gate in front of it.

Coordinates are physical pixels (DECISIONS.md D12). `PynputBackend` must be created after
the QApplication, because Qt makes the process DPI-aware on startup and pynput's
coordinates depend on that.
"""

from __future__ import annotations

import logging
import time
from typing import Protocol

from nodwell.core.safety import ClickRateLimiter, SafetyGate

log = logging.getLogger(__name__)


class InputBackend(Protocol):
    """Minimal mouse interface the pipeline needs in M1."""

    def position(self) -> tuple[float, float] | None: ...
    def move_to(self, x: float, y: float) -> None: ...
    def click(self) -> None: ...


class PynputBackend:
    """Real OS input through pynput (X11 on Linux; Wayland is unsupported, CLAUDE.md §12)."""

    def __init__(self) -> None:
        from pynput import mouse

        self._button = mouse.Button.left
        self._mouse = mouse.Controller()

    def position(self) -> tuple[float, float] | None:
        try:
            x, y = self._mouse.position
        except Exception:  # e.g. no permission on macOS
            return None
        return (float(x), float(y))

    def move_to(self, x: float, y: float) -> None:
        self._mouse.position = (round(x), round(y))

    def click(self) -> None:
        self._mouse.click(self._button)


class DryRunBackend:
    """Records actions instead of performing them (replays, smoke tests, benchmarks)."""

    def __init__(self) -> None:
        self._pos: tuple[float, float] | None = None
        self.moves = 0
        self.clicks: list[tuple[float, float] | None] = []

    def position(self) -> tuple[float, float] | None:
        return self._pos

    def move_to(self, x: float, y: float) -> None:
        self._pos = (round(x), round(y))
        self.moves += 1

    def click(self) -> None:
        self.clicks.append(self._pos)
        log.info("dry-run click at %s", self._pos)


class GatedInput:
    """Wraps a backend so nothing reaches the OS while the safety gate is closed.

    This is the second line of defence: the engine already refuses to act when paused or
    without a face, but the gate also stops output instantly when the panic hotkey fires,
    even if the pipeline thread hasn't processed the pause yet. Clicks are also rate
    limited here, independently of the engine.
    """

    def __init__(self, backend: InputBackend, gate: SafetyGate, min_click_interval_s: float):
        self.backend = backend
        self.gate = gate
        self._limiter = ClickRateLimiter(min_click_interval_s)

    def position(self) -> tuple[float, float] | None:
        return self.backend.position()

    def move_to(self, x: float, y: float) -> bool:
        if not self.gate.allows():
            return False
        self.backend.move_to(x, y)
        return True

    def click(self) -> bool:
        if not self.gate.allows() or not self._limiter.try_acquire(time.monotonic()):
            return False
        self.backend.click()
        return True
