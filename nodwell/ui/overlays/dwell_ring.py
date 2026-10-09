"""The dwell progress ring that follows the cursor.

A small transparent window that never takes focus and lets every click through (window
flags from M0 spike S3, plus Windows extended styles). It's only shown while a dwell is
in progress, and only then runs its 60 Hz animation timer, so it costs nothing at rest.

Status updates arrive at about 15 Hz. To animate smoothly in between, the ring
extrapolates: it knows when the dwell started (from the reported progress) and how long a
dwell takes.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QCursor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from nodwell.platform.win32 import OVERLAY_EXSTYLE, add_exstyle
from nodwell.ui import theme

RING_PX = 72
RING_WIDTH = 9.0


class DwellRing(QWidget):
    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.resize(RING_PX, RING_PX)
        self._styled = False
        self._started_at = 0.0
        self._dwell_s = 1.0
        self.progress = 0.0
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def set_progress(self, progress: float, dwell_s: float) -> None:
        """Called with each status update; 0 hides the ring."""
        if progress <= 0.0:
            if self.isVisible():
                self._timer.stop()
                self.hide()
            self.progress = 0.0
            return
        self._dwell_s = dwell_s
        self._started_at = time.perf_counter() - progress * dwell_s
        if not self.isVisible():
            self._tick()
            self.show()
            if not self._styled:
                add_exstyle(int(self.winId()), OVERLAY_EXSTYLE)
                self._styled = True
            self._timer.start()

    def _tick(self) -> None:
        self.progress = min((time.perf_counter() - self._started_at) / self._dwell_s, 1.0)
        pos = QCursor.pos()
        self.move(pos.x() - RING_PX // 2, pos.y() - RING_PX // 2)
        self.update()

    def paintEvent(self, _event: object) -> None:  # noqa: N802 (Qt override)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        inset = RING_WIDTH / 2 + 3
        rect = QRectF(inset, inset, RING_PX - 2 * inset, RING_PX - 2 * inset)
        # Thin dark edge first so the ring stays visible on light and dark backgrounds.
        p.setPen(QPen(theme.RING_EDGE, RING_WIDTH + 3))
        p.drawEllipse(rect)
        p.setPen(QPen(theme.RING_TRACK, RING_WIDTH))
        p.drawEllipse(rect)
        pen = QPen(theme.RING_FILL, RING_WIDTH)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        # Qt angles are in 1/16 degree; start at 12 o'clock, sweep clockwise.
        p.drawArc(rect, 90 * 16, -int(self.progress * 360 * 16))
        p.end()
