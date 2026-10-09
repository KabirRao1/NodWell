"""The dwell progress ring that follows the cursor.

A small transparent window that never takes focus and lets every click through (window
flags from M0 spike S3, plus Windows extended styles). It's shown while a dwell is in
progress or while scrolling, and only then runs its 60 Hz animation timer, so it costs
nothing at rest.

A label in the middle says what the dwell will do (R = right, 2× = double, and so on) and
scroll arrows show the scroll direction, so colour is never the only signal.

Status updates arrive at about 15 Hz. To animate smoothly in between, the ring
extrapolates: it knows when the dwell started (from the reported progress) and how long a
dwell takes.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from nodwell.core.actions import ClickType
from nodwell.platform.win32 import OVERLAY_EXSTYLE, add_exstyle
from nodwell.ui import theme

RING_PX = 76
RING_WIDTH = 9.0

LABELS = {
    ClickType.LEFT: "",
    ClickType.RIGHT: "R",
    ClickType.DOUBLE: "2×",
    ClickType.MIDDLE: "M",
    ClickType.DRAG: "⇲",
    ClickType.SCROLL: "↕",
}


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
        self._label = ""
        self._scroll_dir: int | None = None  # None: not scrolling
        self.progress = 0.0
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def set_state(
        self,
        progress: float,
        dwell_s: float,
        click_type: ClickType,
        dragging: bool,
        scrolling: bool,
        scroll_direction: int,
    ) -> None:
        """Called with each status update."""
        self._label = "⇱" if dragging else LABELS[click_type]
        self._scroll_dir = scroll_direction if scrolling else None
        if progress <= 0.0 and not scrolling:
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
        if self._scroll_dir is None:
            self.progress = min((time.perf_counter() - self._started_at) / self._dwell_s, 1.0)
        pos = QCursor.pos()
        self.move(pos.x() - RING_PX // 2, pos.y() - RING_PX // 2)
        self.update()

    def paintEvent(self, _event: object) -> None:  # noqa: N802 (Qt override)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        inset = RING_WIDTH / 2 + 3
        rect = QRectF(inset, inset, RING_PX - 2 * inset, RING_PX - 2 * inset)
        if self._scroll_dir is not None:
            self._paint_scroll(p, rect)
        else:
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
        if self._label and self._scroll_dir is None:
            self._paint_label(p, rect)
        p.end()

    def _paint_label(self, p: QPainter, rect: QRectF) -> None:
        font = QFont()
        font.setPixelSize(22)
        font.setBold(True)
        p.setFont(font)
        # Dark halo then light text: readable on any background.
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            p.setPen(theme.RING_EDGE)
            p.drawText(rect.translated(dx, dy), Qt.AlignmentFlag.AlignCenter, self._label)
        p.setPen(QColor("white"))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._label)

    def _paint_scroll(self, p: QPainter, rect: QRectF) -> None:
        """Two arrows; the active direction is filled, the other outlined."""
        cx = rect.center().x()
        for direction, tip_y, base_y in (
            (1, rect.top(), rect.top() + 24),
            (-1, rect.bottom(), rect.bottom() - 24),
        ):
            path = QPainterPath(QPointF(cx, tip_y))
            path.lineTo(cx - 16, base_y)
            path.lineTo(cx + 16, base_y)
            path.closeSubpath()
            p.setPen(QPen(theme.RING_EDGE, 3))
            p.setBrush(
                theme.RING_FILL if self._scroll_dir == direction else QColor(255, 255, 255, 160)
            )
            p.drawPath(path)
        p.setBrush(theme.RING_FILL)
        p.drawEllipse(rect.center(), 6, 6)
