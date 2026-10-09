"""Smooth cursor motion between camera frames (DECISIONS.md D16).

The camera delivers 20 to 30 frames a second, so moving the cursor once per frame looks
like small jumps. This thread moves the real cursor about 125 times a second, easing it
toward the engine's latest target with an exponential approach:

    pos += (target - pos) * (1 - exp(-dt / tau))

After one time constant tau the cursor has covered 63 % of the remaining distance, after
three about 95 %. With tau = 16 ms that is under 50 ms behind the target: smooth, without
noticeable lag. tau = 0 turns easing off (the cursor jumps straight to each target).
"""

from __future__ import annotations

import logging
import math
import threading
import time

from nodwell.platform.input_backend import GatedInput

log = logging.getLogger(__name__)

Point = tuple[float, float]

TICK_S = 0.008  # ~125 Hz


class PointerAnimator(threading.Thread):
    def __init__(self, output: GatedInput, tau_s: float) -> None:
        super().__init__(name="pointer-animator", daemon=True)
        self.output = output
        self.tau_s = tau_s
        self._lock = threading.Lock()
        self._target: Point | None = None
        self._current: Point | None = None
        self._stop_event = threading.Event()

    def set_target(self, x: float, y: float) -> None:
        """New destination from the engine. Jumps there if easing is off or just restarted."""
        with self._lock:
            self._target = (x, y)
            if self.tau_s <= 0.0 or self._current is None:
                self._current = self._target
                self.output.move_to(x, y)

    def snap_to(self, x: float, y: float) -> None:
        """Put the cursor exactly on (x, y) now, e.g. right before a click."""
        with self._lock:
            self._target = self._current = (x, y)
            self.output.move_to(x, y)

    def clear(self) -> None:
        """Forget the current position (paused, or someone else moved the mouse)."""
        with self._lock:
            self._target = self._current = None

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        last = time.perf_counter()
        while not self._stop_event.wait(TICK_S):
            now = time.perf_counter()
            dt, last = now - last, now
            with self._lock:
                if self._target is None or self._current is None or self.tau_s <= 0.0:
                    continue
                (cx, cy), (tx, ty) = self._current, self._target
                if math.dist((cx, cy), (tx, ty)) < 0.5:
                    continue  # arrived (sub-pixel): nothing to send
                k = 1.0 - math.exp(-dt / self.tau_s)
                self._current = (cx + (tx - cx) * k, cy + (ty - cy) * k)
                # Written under our lock so a snap_to (before a click) can never be
                # followed by a stale in-between position. Lock order: ours, then output's.
                try:
                    self.output.move_to(*self._current)
                except Exception:  # keep gliding next tick rather than dying silently
                    log.exception("pointer animator could not move the cursor")
