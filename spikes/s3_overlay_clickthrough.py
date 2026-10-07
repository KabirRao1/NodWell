"""Spike 3: can a Qt overlay be transparent, click-through, and always on top?

Draws an animated dwell-style progress ring that follows the mouse. While it runs,
click and type in other apps *through* the ring, switch windows, maximise something,
and check the taskbar / Alt+Tab. Quits after --seconds (default 60) or Ctrl+C.

    uv run python spikes/s3_overlay_clickthrough.py                 # Qt flags only, small window
    uv run python spikes/s3_overlay_clickthrough.py --mode full     # full-screen transparent canvas
    uv run python spikes/s3_overlay_clickthrough.py --win32         # also force Win32 ex-styles
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from typing import Any

from _common import env_info, percentiles, print_result
from _win32 import (
    IS_WINDOWS,
    WS_EX_LAYERED,
    WS_EX_NOACTIVATE,
    WS_EX_TOOLWINDOW,
    WS_EX_TOPMOST,
    WS_EX_TRANSPARENT,
    add_exstyle,
    describe_exstyle,
    dpi_for_window,
    get_exstyle,
)
from PySide6.QtCore import QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

RING_SIZE = 96
RING_WIDTH = 8
DWELL_SECONDS = 1.5


class RingOverlay(QWidget):
    """Transparent, input-transparent, always-on-top window that paints a progress ring."""

    def __init__(self, full_screen: bool, fps: int) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool  # keeps it out of the taskbar
            | Qt.WindowType.WindowTransparentForInput  # clicks fall through
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.full_screen = full_screen
        self.progress = 0.0
        self.ring_center = QPoint(RING_SIZE // 2, RING_SIZE // 2)
        self.paints = 0
        self.tick_gaps_ms: list[float] = []
        self._last_tick = time.perf_counter()

        if full_screen:
            self.setGeometry(QApplication.primaryScreen().geometry())
        else:
            self.resize(RING_SIZE, RING_SIZE)

        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.tick)
        self.timer.start(max(1, 1000 // fps))

    def tick(self) -> None:
        now = time.perf_counter()
        dt = now - self._last_tick
        self.tick_gaps_ms.append(dt * 1000)
        self._last_tick = now
        self.progress = (self.progress + dt / DWELL_SECONDS) % 1.0

        cursor = QCursor.pos()
        if self.full_screen:
            self.ring_center = self.mapFromGlobal(cursor)
        else:
            self.move(cursor.x() - RING_SIZE // 2, cursor.y() - RING_SIZE // 2)
        self.update()

    def paintEvent(self, _event: Any) -> None:
        self.paints += 1
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        inset = RING_WIDTH / 2 + 2
        c = self.ring_center
        rect = QRectF(
            c.x() - RING_SIZE / 2 + inset,
            c.y() - RING_SIZE / 2 + inset,
            RING_SIZE - 2 * inset,
            RING_SIZE - 2 * inset,
        )
        p.setPen(QPen(QColor(255, 255, 255, 90), RING_WIDTH))
        p.drawEllipse(rect)
        pen = QPen(QColor(232, 140, 48, 230), RING_WIDTH)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        # Qt angles are in 1/16 degree; start at 12 o'clock and sweep clockwise.
        p.drawArc(rect, 90 * 16, -int(self.progress * 360 * 16))
        p.end()


def main() -> int:
    parser = argparse.ArgumentParser(description="Spike 3: click-through overlay")
    parser.add_argument("--mode", choices=["small", "full"], default="small")
    parser.add_argument("--win32", action="store_true", help="force Win32 extended styles")
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--fps", type=int, default=60)
    args = parser.parse_args()

    app = QApplication(sys.argv)
    signal.signal(signal.SIGINT, lambda *_: app.quit())  # Python runs every tick, so this fires

    overlay = RingOverlay(full_screen=args.mode == "full", fps=args.fps)
    overlay.show()
    hwnd = int(overlay.winId())
    exstyle_qt = get_exstyle(hwnd)
    exstyle_final = exstyle_qt
    if args.win32 and IS_WINDOWS:
        exstyle_final = add_exstyle(
            hwnd,
            WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOPMOST | WS_EX_TOOLWINDOW,
        )

    print(f"Overlay running for {args.seconds:.0f}s. Click and type in other apps through it.")
    print("Ctrl+C in this terminal stops it early.")
    QTimer.singleShot(int(args.seconds * 1000), app.quit)

    cpu0, wall0 = time.process_time(), time.perf_counter()
    app.exec()
    wall, cpu = time.perf_counter() - wall0, time.process_time() - cpu0

    print_result(
        {
            "spike": "s3_overlay_clickthrough",
            "env": env_info(),
            "mode": args.mode,
            "win32_forced": args.win32,
            "qt_platform": app.platformName(),
            "device_pixel_ratio": overlay.devicePixelRatio(),
            "window_dpi": dpi_for_window(hwnd),
            "exstyle_set_by_qt": describe_exstyle(exstyle_qt),
            "exstyle_final": describe_exstyle(exstyle_final),
            "seconds": round(wall, 1),
            "paints": overlay.paints,
            "paint_fps": round(overlay.paints / wall, 1) if wall else None,
            "tick_gap_ms": percentiles(overlay.tick_gaps_ms[1:]),
            "cpu_percent_of_one_core": round(100 * cpu / wall, 1) if wall else None,
        }
    )
    print("Please also answer in your reply (yes / no / partly + notes):")
    print("  1. Was the ring visible, smooth, and transparent around the edges (no black box)?")
    print("  2. Did clicks and typing reach the app under the ring?")
    print("  3. Did it stay on top after you clicked other windows / opened Start?")
    print("  4. Did it stay on top over a maximised window? Over borderless-fullscreen video?")
    print("  5. Did it appear in the taskbar or Alt+Tab?")
    print("  6. Did your keyboard focus ever jump to the overlay?")
    return 0


if __name__ == "__main__":
    sys.exit(main())
