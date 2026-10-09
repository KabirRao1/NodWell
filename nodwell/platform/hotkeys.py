"""System-wide hotkeys for caregivers (pause/panic, recenter, quit)."""

from __future__ import annotations

import logging
from collections.abc import Callable

log = logging.getLogger(__name__)


class GlobalHotkeys:
    """Runs pynput's hotkey listener on its own thread.

    Callbacks run on that listener thread, so they must be thread-safe (put a command on
    a queue, flip the safety gate, or emit a Qt signal).
    """

    def __init__(self, bindings: dict[str, Callable[[], None]]) -> None:
        self._bindings = bindings
        self._listener: object | None = None
        self.error: str | None = None

    def start(self) -> None:
        try:
            from pynput import keyboard

            listener = keyboard.GlobalHotKeys(self._bindings)
            listener.daemon = True
            listener.start()
            self._listener = listener
            log.info("hotkeys active: %s", ", ".join(self._bindings))
        except Exception as exc:  # bad combo string, or no permission (macOS)
            self.error = f"Hotkeys unavailable: {exc}"
            log.exception("could not start hotkeys")

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()  # type: ignore[attr-defined]
