"""Spike 4: can a Qt window take dwell "presses" and send keystrokes without stealing focus?

Shows a small always-on-top keyboard. Click into Notepad first, then:
  (a) hover a key for 1 s (a "dwell", no OS click): the key should type into Notepad;
  (b) actually click a key with the mouse: it should *also* type into Notepad.
Notepad must keep focus the whole time. The script logs which window had focus
before and after every press, and whether our app ever became the active app.

    uv run python spikes/s4_nofocus_keyboard.py                     # Qt flags only
    uv run python spikes/s4_nofocus_keyboard.py --win32-noactivate  # also WS_EX_NOACTIVATE
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from typing import Any

from _common import env_info, print_result
from _win32 import IS_WINDOWS, WS_EX_NOACTIVATE, add_exstyle, describe_exstyle, foreground_window
from _win32 import get_exstyle as win_get_exstyle
from pynput import keyboard
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter
from PySide6.QtWidgets import QApplication, QGridLayout, QWidget

DWELL_SECONDS = 1.0
KEY_PX = 96

# label -> what pynput sends
KEYS: list[tuple[str, Any]] = [
    ("H", "h"),
    ("I", "i"),
    ("!", "!"),
    ("Space", keyboard.Key.space),
    ("Enter", keyboard.Key.enter),
    ("Bksp", keyboard.Key.backspace),
]


class PressLog:
    """Collects one record per key press, with focus evidence."""

    def __init__(self) -> None:
        self.presses: list[dict[str, Any]] = []
        self.app_became_active = 0
        self.our_hwnd = 0
        self.kbd = keyboard.Controller()

    def send(self, label: str, key: Any, method: str) -> None:
        before = foreground_window()
        self.kbd.tap(key)
        record: dict[str, Any] = {
            "t": round(time.perf_counter(), 2),
            "key": label,
            "method": method,
            "foreground_before": before[1],
            "ours_was_foreground": IS_WINDOWS and before[0] == self.our_hwnd,
            "qt_app_active": QGuiApplication.applicationState()
            == Qt.ApplicationState.ApplicationActive,
        }
        self.presses.append(record)

        def after() -> None:
            record["foreground_after"] = foreground_window()[1]

        QTimer.singleShot(150, after)
        print(f"  {method:5s} {label:5s} -> focus was on {before[1]!r}")


class DwellKey(QWidget):
    """A large key that fires after hovering for DWELL_SECONDS, or immediately on click."""

    def __init__(self, label: str, key: Any, log: PressLog) -> None:
        super().__init__()
        self.label, self.key, self.log = label, key, log
        self.setFixedSize(KEY_PX * (2 if len(label) > 1 else 1), KEY_PX)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.hover_start: float | None = None
        self.progress = 0.0

    def enterEvent(self, _event: Any) -> None:
        self.hover_start = time.perf_counter()

    def leaveEvent(self, _event: Any) -> None:
        self.hover_start = None  # moving away cancels the dwell
        self.progress = 0.0
        self.update()

    def mousePressEvent(self, _event: Any) -> None:
        self.log.send(self.label, self.key, "click")

    def tick(self) -> None:
        if self.hover_start is None:
            return
        self.progress = min(1.0, (time.perf_counter() - self.hover_start) / DWELL_SECONDS)
        if self.progress >= 1.0:
            self.log.send(self.label, self.key, "dwell")
            self.hover_start = time.perf_counter()  # require a fresh full dwell to repeat
            self.progress = 0.0
        self.update()

    def paintEvent(self, _event: Any) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(250, 244, 235))
        p.drawRoundedRect(r, 14, 14)
        if self.progress > 0:
            fill = QRectF(r.x(), r.bottom() - r.height() * self.progress, r.width(), r.height())
            fill = fill.intersected(r)
            p.setBrush(QColor(232, 140, 48, 140))
            p.drawRoundedRect(fill, 14, 14)
        p.setPen(QColor(40, 34, 28))
        p.setFont(QFont("Segoe UI", 20, QFont.Weight.DemiBold))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.label)
        p.end()


class Keyboard(QWidget):
    def __init__(self, log: PressLog) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setStyleSheet("background: #3a332c;")
        grid = QGridLayout(self)
        grid.setSpacing(16)  # generous spacing so dwell does not hit neighbours
        self.keys = [DwellKey(label, key, log) for label, key in KEYS]
        for i, k in enumerate(self.keys):
            grid.addWidget(k, i // 3, i % 3)
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: [k.tick() for k in self.keys])
        self.timer.start(16)


def main() -> int:
    parser = argparse.ArgumentParser(description="Spike 4: non-focus-stealing keyboard")
    parser.add_argument("--win32-noactivate", action="store_true")
    parser.add_argument("--seconds", type=float, default=90.0)
    args = parser.parse_args()

    app = QApplication(sys.argv)
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    log = PressLog()

    def on_state(state: Qt.ApplicationState) -> None:
        if state == Qt.ApplicationState.ApplicationActive:
            log.app_became_active += 1
            print("  !! our app became the active app (focus stolen)")

    app.applicationStateChanged.connect(on_state)

    kb = Keyboard(log)
    kb.adjustSize()
    screen = app.primaryScreen().availableGeometry()
    kb.move(screen.center().x() - kb.width() // 2, screen.bottom() - kb.height() - 40)
    kb.show()
    log.our_hwnd = int(kb.winId())
    exstyle_qt = win_get_exstyle(log.our_hwnd)
    exstyle_final = exstyle_qt
    if args.win32_noactivate and IS_WINDOWS:
        exstyle_final = add_exstyle(log.our_hwnd, WS_EX_NOACTIVATE)

    print(f"Keyboard running for {args.seconds:.0f}s. Click into Notepad first, then:")
    print("  - hover keys for 1 s (dwell), and")
    print("  - click keys with the mouse.")
    QTimer.singleShot(int(args.seconds * 1000), app.quit)
    app.exec()

    stolen = [p for p in log.presses if p["ours_was_foreground"]]
    print_result(
        {
            "spike": "s4_nofocus_keyboard",
            "env": env_info(),
            "win32_noactivate_forced": args.win32_noactivate,
            "qt_platform": app.platformName(),
            "exstyle_set_by_qt": describe_exstyle(exstyle_qt),
            "exstyle_final": describe_exstyle(exstyle_final),
            "presses_total": len(log.presses),
            "presses_by_method": {
                m: sum(1 for p in log.presses if p["method"] == m) for m in ("dwell", "click")
            },
            "presses_while_ours_foreground": len(stolen),
            "times_our_app_became_active": log.app_became_active,
            "presses": log.presses,
        }
    )
    print("Please also answer in your reply:")
    print("  1. Did dwell presses type into Notepad? Did click presses?")
    print("  2. Did Notepad's caret/title bar ever look inactive?")
    print("  3. Did the keyboard stay on top and out of the taskbar?")
    return 0


if __name__ == "__main__":
    sys.exit(main())
