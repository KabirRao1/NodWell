"""Fail-safe primitives shared by the engine and the input backend (CLAUDE.md §4.4)."""

from __future__ import annotations

import threading


class SafetyGate:
    """A process-wide on/off switch for OS input, safe to flip from any thread.

    The input backend checks it before every move and click. The panic hotkey clears it
    straight from the hotkey thread, so actions stop even if the pipeline thread is busy
    or stuck. Starts closed: nothing happens until the engine is Active.
    """

    def __init__(self) -> None:
        self._open = threading.Event()

    def allow(self) -> None:
        self._open.set()

    def block(self) -> None:
        self._open.clear()

    def allows(self) -> bool:
        return self._open.is_set()


class ClickRateLimiter:
    """Allows at most one click per `min_interval_s`. Not thread-safe: one owner."""

    def __init__(self, min_interval_s: float) -> None:
        self.min_interval_s = min_interval_s
        self._last = -float("inf")

    def try_acquire(self, t: float) -> bool:
        """Return True (and record the click) if a click at time `t` is allowed."""
        if t - self._last < self.min_interval_s:
            return False
        self._last = t
        return True
