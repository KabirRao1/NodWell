"""The M1 status panel: a compact, head-pointer-friendly window (replaced in M2).

Shows what the app is doing and offers the few controls M1 needs. Every button is at
least 64 px tall with wide gaps so dwell doesn't hit neighbours, is reachable by Tab, and
has an accessible name.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QCloseEvent, QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from nodwell.core.engine import Mode, PauseReason
from nodwell.core.features import Quality
from nodwell.core.settings import Settings
from nodwell.i18n import _
from nodwell.pipeline import PipelineStatus
from nodwell.ui import theme

# Friendly names for blendshapes used as the pause gesture.
GESTURE_LABELS = {
    "browInnerUp": "Raise your eyebrows",
    "jawOpen": "Open your mouth",
    "mouthSmileLeft": "Smile",
    "mouthSmileRight": "Smile",
}

QUALITY_TEXT = {
    Quality.GOOD: "Tracking well",
    Quality.NO_FACE: "Face not found. Move into view of the camera.",
    Quality.TOO_FAR: "Move a little closer to the camera.",
    Quality.TOO_CLOSE: "Move back a little from the camera.",
    Quality.LOW_LIGHT: "Add light in front of you.",
}


class GestureMeter(QWidget):
    """Live gesture score with the trigger threshold marked on the bar (CLAUDE.md §7)."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(28)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.value: float | None = None
        self.threshold = 0.5
        self.progress = 0.0

    def set_state(self, value: float | None, threshold: float, progress: float) -> None:
        if (value, threshold, progress) == (self.value, self.threshold, self.progress):
            return
        self.value, self.threshold, self.progress = value, threshold, progress
        pct = "no reading" if value is None else f"{round(value * 100)} percent"
        self.setAccessibleDescription(
            _("Gesture strength {pct}, triggers at {thr} percent").format(
                pct=pct, thr=round(threshold * 100)
            )
        )
        self.update()

    def paintEvent(self, _event: object) -> None:  # noqa: N802 (Qt override)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bar = QRectF(1, 6, self.width() - 2, self.height() - 12)
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.setBrush(QColor(theme.SURFACE))
        p.drawRoundedRect(bar, 8, 8)
        if self.value is not None:
            fill = QRectF(bar)
            fill.setWidth(bar.width() * min(max(self.value, 0.0), 1.0))
            color = QColor(theme.ACCENT if self.value >= self.threshold else theme.MUTED)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawRoundedRect(fill, 8, 8)
        # Threshold marker: a dark vertical line that extends past the bar.
        x = bar.left() + bar.width() * self.threshold
        p.setPen(QPen(QColor(theme.TEXT), 3))
        p.drawLine(int(x), 0, int(x), self.height())
        p.end()


class StatusPanel(QWidget):
    """Status pill, main buttons, and the pause-gesture meter."""

    pause_clicked = Signal()
    resume_clicked = Signal()
    recenter_clicked = Signal()
    mode_selected = Signal(str)
    dwell_toggled = Signal(bool)
    quit_clicked = Signal()

    def __init__(self, settings: Settings) -> None:
        super().__init__(None, Qt.WindowType.WindowStaysOnTopHint)
        self.setObjectName("Panel")
        self.setWindowTitle("Nodwell")
        self.setStyleSheet(theme.STYLESHEET)
        self._mode: Mode | None = None
        self._quitting = False
        self._showing_hold = False
        self._settings = settings

        title = QLabel("Nodwell")
        title.setObjectName("Title")
        self.pill = QLabel(_("Starting"))
        self.pill.setObjectName("Pill")
        self.pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail = QLabel(_("Loading face tracking..."))
        self.detail.setObjectName("Detail")
        self.detail.setWordWrap(True)
        self.error = QLabel("")
        self.error.setObjectName("Error")
        self.error.setWordWrap(True)
        self.error.hide()

        self.pause_btn = self._button(_("Pause"), "Primary")
        self.pause_btn.clicked.connect(self._on_pause_clicked)
        self.recenter_btn = self._button(_("Recenter"))
        self.recenter_btn.clicked.connect(self.recenter_clicked)

        self.absolute_btn = self._button(_("Absolute"), checkable=True)
        self.relative_btn = self._button(_("Relative"), checkable=True)
        self.absolute_btn.setToolTip(_("Where you point your head is where the cursor goes"))
        self.relative_btn.setToolTip(_("Tilt your head to push the cursor, like a joystick"))
        group = QButtonGroup(self)
        group.setExclusive(True)
        group.addButton(self.absolute_btn)
        group.addButton(self.relative_btn)
        self.absolute_btn.clicked.connect(lambda: self.mode_selected.emit("absolute"))
        self.relative_btn.clicked.connect(lambda: self.mode_selected.emit("relative"))

        self.dwell_btn = self._button("", checkable=True)
        self.dwell_btn.toggled.connect(self._on_dwell_toggled)

        self.gesture_label = QLabel("")
        self.gesture_label.setWordWrap(True)
        self.meter = GestureMeter()

        quit_btn = self._button(_("Quit Nodwell"))
        quit_btn.clicked.connect(self.quit_clicked)

        hint = QLabel(
            _("Caregiver keys: Ctrl+Alt+P pause or resume · Ctrl+Alt+R recenter · Ctrl+Alt+Q quit")
        )
        hint.setObjectName("Hint")
        hint.setWordWrap(True)

        head = QHBoxLayout()
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.pill)

        row1 = QHBoxLayout()
        row1.setSpacing(20)
        row1.addWidget(self.pause_btn, 1)
        row1.addWidget(self.recenter_btn, 1)

        row2 = QHBoxLayout()
        row2.setSpacing(20)
        row2.addWidget(self.absolute_btn, 1)
        row2.addWidget(self.relative_btn, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)
        layout.addLayout(head)
        layout.addWidget(self.detail)
        layout.addWidget(self.error)
        layout.addLayout(row1)
        layout.addWidget(self._section(_("Pointer")))
        layout.addLayout(row2)
        layout.addWidget(self._section(_("Clicking")))
        layout.addWidget(self.dwell_btn)
        layout.addWidget(self._section(_("Pause gesture")))
        layout.addWidget(self.gesture_label)
        layout.addWidget(self.meter)
        layout.addSpacing(6)
        layout.addWidget(quit_btn)
        layout.addWidget(hint)
        self.setFixedWidth(480)

        self.apply_settings(settings)
        self._set_pill("starting", _("Starting"))

    # ------------------------------------------------------------ helpers

    def _button(self, text: str, object_name: str = "", checkable: bool = False) -> QPushButton:
        b = QPushButton(text)
        if object_name:
            b.setObjectName(object_name)
        b.setCheckable(checkable)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        return b

    def _section(self, text: str) -> QLabel:
        label = QLabel(text.upper())
        label.setObjectName("Section")
        return label

    def _set_pill(self, kind: str, text: str) -> None:
        bg, fg = theme.PILL[kind]
        self.pill.setStyleSheet(
            f"background: {bg}; color: {fg}; border-radius: 14px; padding: 6px 18px;"
        )
        self.pill.setText(text)
        self.pill.setAccessibleName(_("Status: {text}").format(text=text))

    def _on_pause_clicked(self) -> None:
        if self._mode is Mode.ACTIVE:
            self.pause_clicked.emit()
        else:
            self.resume_clicked.emit()

    def _on_dwell_toggled(self, on: bool) -> None:
        self.dwell_btn.setText(_("Dwell click: On") if on else _("Dwell click: Off"))
        self.dwell_btn.setAccessibleName(self.dwell_btn.text())
        self.dwell_toggled.emit(on)

    # ------------------------------------------------------------ updates

    def apply_settings(self, settings: Settings) -> None:
        """Reflect settings in the controls without re-emitting change signals."""
        self._settings = settings
        self.absolute_btn.setChecked(settings.pointer.mode == "absolute")
        self.relative_btn.setChecked(settings.pointer.mode == "relative")
        self.dwell_btn.blockSignals(True)
        self.dwell_btn.setChecked(settings.dwell.enabled)
        self.dwell_btn.blockSignals(False)
        self.dwell_btn.setText(
            _("Dwell click: On") if settings.dwell.enabled else _("Dwell click: Off")
        )
        g = settings.pause_gesture
        name = GESTURE_LABELS.get(g.blendshape, g.blendshape)
        self.gesture_label.setText(
            _("{name} and hold for {s:g} seconds to pause or resume.").format(name=name, s=g.hold_s)
            if g.enabled
            else _("Pause gesture is off.")
        )
        self.meter.threshold = g.on_threshold

    def show_error(self, message: str | None) -> None:
        self.error.setVisible(bool(message))
        self.error.setText(message or "")

    def update_status(self, ps: PipelineStatus) -> None:
        s = ps.engine
        self._mode = s.mode
        if s.mode is Mode.ACTIVE and not s.face:
            self._set_pill("warning", _("Face not found"))
        elif s.mode is Mode.ACTIVE:
            self._set_pill("active", _("Active"))
        elif s.mode is Mode.PAUSED:
            self._set_pill("paused", _("Paused"))
        else:
            self._set_pill("starting", _("Starting"))

        self.pause_btn.setText(_("Pause") if s.mode is Mode.ACTIVE else _("Resume"))
        self.pause_btn.setAccessibleName(self.pause_btn.text())

        if s.manual_override:
            detail = _("Mouse in use. Head control returns in a moment.")
        elif s.mode is Mode.STARTING:
            detail = (
                _("Look at the screen and hold still. Starting in a moment.")
                if s.face
                else _(QUALITY_TEXT[s.quality])
            )
        elif s.mode is Mode.PAUSED:
            why = {
                PauseReason.FACE_LOST: _("Paused because your face was out of view."),
                PauseReason.GESTURE: _("Paused by gesture."),
            }.get(s.pause_reason, _("Paused."))
            detail = why + " " + _("Hold the pause gesture or press Resume to continue.")
        else:
            detail = _(QUALITY_TEXT[s.quality])
        if s.drift_suggested and s.mode is Mode.ACTIVE:
            detail = _("Your resting position seems to have moved. Recenter?")
        self.recenter_btn.setObjectName("Suggest" if s.drift_suggested else "")
        self.recenter_btn.setStyle(self.recenter_btn.style())  # re-apply object-name styling
        self.detail.setText(f"{detail}   ·   {ps.fps:.0f} fps" if ps.fps else detail)

        if s.gesture_progress > 0.0:
            self.gesture_label.setText(
                _("Holding... {pct}%. Keep going.").format(pct=round(s.gesture_progress * 100))
            )
            self._showing_hold = True
        elif self._showing_hold:
            self._showing_hold = False
            self.apply_settings(self._settings)
        if s.gesture_available is False:
            self.gesture_label.setText(
                _("Pause gesture unavailable: this face model has no '{name}' reading.").format(
                    name=s.gesture_name
                )
            )
        self.meter.set_state(s.gesture_value, self.meter.threshold, s.gesture_progress)
        self.show_error(ps.error)

    def allow_close(self) -> None:
        self._quitting = True

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt override)
        # Closing the window quits the app: a hidden head pointer would be confusing.
        if not self._quitting:
            event.ignore()
            self.quit_clicked.emit()
            return
        event.accept()
