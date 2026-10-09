"""A one-item mailbox that always holds the newest value (DECISIONS.md D11).

The camera thread puts every frame; the pipeline thread takes the newest one. If the
pipeline falls behind, older frames are overwritten instead of queued, so latency can
never build up.
"""

from __future__ import annotations

import threading


class LatestSlot[T]:
    """Thread-safe single-slot buffer: `put` overwrites, `get` takes and empties."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._item: T | None = None
        self._closed = False
        self.dropped = 0  # items overwritten before anyone took them

    def put(self, item: T) -> None:
        with self._cond:
            if self._item is not None:
                self.dropped += 1
            self._item = item
            self._cond.notify()

    def get(self, timeout: float) -> T | None:
        """Wait up to `timeout` seconds for an item. Returns None on timeout or close."""
        with self._cond:
            self._cond.wait_for(lambda: self._item is not None or self._closed, timeout)
            item, self._item = self._item, None
            return item

    def close(self) -> None:
        """Wake any waiting `get` so its thread can exit."""
        with self._cond:
            self._closed = True
            self._cond.notify_all()
