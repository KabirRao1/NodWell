"""The status panel: a compact, head-pointer-friendly window (replaced by the M2 Control Center).

Three tabs: Home (status and main controls), Gestures (one row per gesture binding with a
live meter), and Pointer (mode and tuning). Every control is at least 64 px with wide gaps
so dwell doesn't hit neighbours, is reachable by Tab, and has an accessible name. Values
are changed with -/+ buttons rather than sliders, because sliders are hard to drag by dwell.
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
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from nodwell.core.actions import ClickType, GestureAction
from nodwell.core.engine import GestureReading, Mode, PauseReason
from nodwell.core.features import Quality
from nodwell.core.settings import GestureBinding, Settings
from nodwell.i18n import _
from nodwell.pipeline import PipelineStatus
from nodwell.ui import theme

QUALITY_TEXT = {
    Quality.GOOD: "Tracking well",
    Quality.NO_FACE: "Face not found. Move into view of the camera.",
    Quality.TOO_FAR: "Move a little closer to the camera.",
    Quality.TOO_CLOSE: "Move back a little from the camera.",
    Quality.LOW_LIGHT: "Add light in front of you.",
}

ACTION_TEXT = {
    GestureAction.NONE: "Does nothing",
    GestureAction.LEFT_CLICK: "Left click",
    GestureAction.RIGHT_CLICK: "Right click",
    GestureAction.DOUBLE_CLICK: "Double click",
    GestureAction.MIDDLE_CLICK: "Middle click",
    GestureAction.DRAG_TOGGLE: "Drag: grab / drop",
    GestureAction.SCROLL_TOGGLE: "Scroll on / off",
    GestureAction.PAUSE_TOGGLE: "Pause / resume",
    GestureAction.RECENTER: "Recenter",
}
ACTION_CYCLE = list(GestureAction)

CLICK_TYPE_TEXT = {
    ClickType.LEFT: "Left click",
    ClickType.RIGHT: "Right click",
    ClickType.DOUBLE: "Double click",
    ClickType.MIDDLE: "Middle click",
    ClickType.DRAG: "Drag",
    ClickType.SCROLL: "Scroll",
}

MOTION_SMOOTHING_ON_MS = 16.0


def _button(text: str, object_name: str = "", checkable: bool = False) -> QPushButton:
    b = QPushButton(text)
    if object_name:
        b.setObjectName(object_name)
    b.setCheckable(checkable)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setAccessibleName(text)
    return b


def _label(text: str, object_name: str = "") -> QLabel:
    label = QLabel(text)
    if object_name:
        label.setObjectName(object_name)
    label.setWordWrap(True)
    return label


class GestureMeter(QWidget):
    """Live gesture score with the trigger threshold marked on the bar (CLAUDE.md §7)."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(24)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.value: float | None = None
        self.threshold = 0.5

    def set_state(self, value: float | None, threshold: float) -> None:
        if (value, threshold) == (self.value, self.threshold):
            return
        self.value, self.threshold = value, threshold
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
        bar = QRectF(1, 5, self.width() - 2, self.height() - 10)
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.setBrush(QColor(theme.SURFACE))
        p.drawRoundedRect(bar, 7, 7)
        if self.value is not None:
            fill = QRectF(bar)
            fill.setWidth(bar.width() * min(max(self.value, 0.0), 1.0))
            above = self.value >= self.threshold
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.ACCENT if above else theme.MUTED))
            p.drawRoundedRect(fill, 7, 7)
        # Threshold marker: a dark vertical line that extends past the bar.
        x = bar.left() + bar.width() * self.threshold
        p.setPen(QPen(QColor(theme.TEXT), 3))
        p.drawLine(int(x), 0, int(x), self.height())
        p.end()


class GestureRow(QWidget):
    """One gesture binding: on/off, name and action with a live meter, and "Action ▸"."""

    toggled = Signal(str, bool)
    cycle_action = Signal(str)

    def __init__(self, binding: GestureBinding) -> None:
        super().__init__()
        self.binding_id = binding.id
        self.toggle = _button("", "Compact", checkable=True)
        self.toggle.setFixedWidth(90)
        self.toggle.clicked.connect(lambda on: self.toggled.emit(self.binding_id, on))
        self.title = _label("", "RowTitle")
        self.sub = _label("", "RowSub")
        self.meter = GestureMeter()
        self.action_btn = _button(_("Action ▸"), "Compact")
        self.action_btn.setFixedWidth(120)
        self.action_btn.clicked.connect(lambda: self.cycle_action.emit(self.binding_id))
        middle = QVBoxLayout()
        middle.setSpacing(2)
        middle.addWidget(self.title)
        middle.addWidget(self.sub)
        middle.addWidget(self.meter)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 4, 0, 4)
        row.setSpacing(14)
        row.addWidget(self.toggle)
        row.addLayout(middle, 1)
        row.addWidget(self.action_btn)
        self._unavailable = False
        self.set_binding(binding)

    def set_binding(self, b: GestureBinding) -> None:
        self._binding = b
        self.toggle.setChecked(b.enabled)
        self.toggle.setText(_("On") if b.enabled else _("Off"))
        self.toggle.setAccessibleName(
            _("{name}: {state}").format(name=b.label, state=_("on") if b.enabled else _("off"))
        )
        self.title.setText(_(b.label))
        self._show_sub()
        self.action_btn.setAccessibleName(_("Change what {name} does").format(name=b.label))
        self.meter.threshold = b.on_threshold

    def _show_sub(self) -> None:
        if self._unavailable:
            self.sub.setText(_("Not available: the face model has no reading for this."))
        else:
            b = self._binding
            self.sub.setText(
                _("{action} · {s:g} s").format(action=_(ACTION_TEXT[b.action]), s=b.hold_s)
            )

    def set_reading(self, r: GestureReading) -> None:
        self.meter.set_state(r.value, r.threshold)
        unavailable = r.available is False
        if unavailable != self._unavailable:
            self._unavailable = unavailable
            self._show_sub()


class Stepper(QWidget):
    """A labelled value with large − and + buttons."""

    changed = Signal(int)  # -1 or +1

    def __init__(self, title: str, hint: str) -> None:
        super().__init__()
        self.title = title
        text = QVBoxLayout()
        text.setSpacing(0)
        text.addWidget(_label(title, "RowTitle"))
        text.addWidget(_label(hint, "RowSub"))
        self.minus = _button("−", "Step")
        self.plus = _button("+", "Step")
        self.minus.setAccessibleName(_("Decrease {t}").format(t=title))
        self.plus.setAccessibleName(_("Increase {t}").format(t=title))
        self.value = QLabel("")
        self.value.setObjectName("Value")
        self.value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.minus.clicked.connect(lambda: self.changed.emit(-1))
        self.plus.clicked.connect(lambda: self.changed.emit(+1))
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 4, 0, 4)
        row.setSpacing(12)
        row.addLayout(text, 1)
        row.addWidget(self.minus)
        row.addWidget(self.value)
        row.addWidget(self.plus)

    def set_value(self, text: str) -> None:
        self.value.setText(text)
        self.value.setAccessibleName(f"{self.title}: {text}")


class StatusPanel(QWidget):
    """Status header plus Home / Gestures / Pointer tabs."""

    pause_clicked = Signal()
    resume_clicked = Signal()
    recenter_clicked = Signal()
    quit_clicked = Signal()
    settings_changed = Signal(object)  # a new Settings object

    def __init__(self, settings: Settings) -> None:
        super().__init__(None, Qt.WindowType.WindowStaysOnTopHint)
        self.setObjectName("Panel")
        self.setWindowTitle("Nodwell")
        self.setStyleSheet(theme.STYLESHEET)
        self._settings = settings
        self._mode: Mode | None = None
        self._quitting = False

        title = QLabel("Nodwell")
        title.setObjectName("Title")
        self.pill = QLabel(_("Starting"))
        self.pill.setObjectName("Pill")
        self.pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail = _label(_("Loading face tracking..."), "Detail")
        self.error = _label("", "Error")
        self.error.hide()
        head = QHBoxLayout()
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.pill)

        self.pages = QStackedWidget()
        tabs = QHBoxLayout()
        tabs.setSpacing(4)
        group = QButtonGroup(self)
        self.tab_buttons: list[QPushButton] = []
        pages = [
            (_("Home"), self._home_page()),
            (_("Gestures"), self._gestures_page()),
            (_("Pointer"), self._pointer_page()),
        ]
        for i, (name, page) in enumerate(pages):
            tab = _button(name, "Tab", checkable=True)
            tab.setChecked(i == 0)
            tab.clicked.connect(lambda _checked=False, i=i: self.pages.setCurrentIndex(i))
            group.addButton(tab)
            tabs.addWidget(tab, 1)
            self.tab_buttons.append(tab)
            self.pages.addWidget(page)
        # Keep the underline on the visible page however the page was changed.
        self.pages.currentChanged.connect(lambda i: self.tab_buttons[i].setChecked(True))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(10)
        layout.addLayout(head)
        layout.addWidget(self.detail)
        layout.addWidget(self.error)
        layout.addLayout(tabs)
        layout.addWidget(self.pages)
        self.setFixedWidth(520)

        self.apply_settings(settings)
        self._set_pill("starting", _("Starting"))

    # ------------------------------------------------------------ pages

    def _home_page(self) -> QWidget:
        page = QWidget()
        self.pause_btn = _button(_("Pause"), "Primary")
        self.pause_btn.clicked.connect(self._on_pause_clicked)
        self.recenter_btn = _button(_("Recenter"))
        self.recenter_btn.clicked.connect(self.recenter_clicked)
        self.dwell_btn = _button("", checkable=True)
        self.dwell_btn.clicked.connect(
            lambda on: self._change(dwell=self._settings.dwell.model_copy(update={"enabled": on}))
        )
        self.toolbar_btn = _button("", checkable=True)
        self.toolbar_btn.clicked.connect(
            lambda on: self._change(
                toolbar=self._settings.toolbar.model_copy(update={"visible": on})
            )
        )
        self.click_hint = _label("", "Detail")
        quit_btn = _button(_("Quit Nodwell"))
        quit_btn.clicked.connect(self.quit_clicked)
        hint = _label(
            _("Caregiver keys: Ctrl+Alt+P pause or resume · Ctrl+Alt+R recenter · Ctrl+Alt+Q quit"),
            "Hint",
        )
        row1 = QHBoxLayout()
        row1.setSpacing(20)
        row1.addWidget(self.pause_btn, 1)
        row1.addWidget(self.recenter_btn, 1)
        row2 = QHBoxLayout()
        row2.setSpacing(20)
        row2.addWidget(self.dwell_btn, 1)
        row2.addWidget(self.toolbar_btn, 1)
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 10, 0, 0)
        v.setSpacing(16)
        v.addLayout(row1)
        v.addLayout(row2)
        v.addWidget(self.click_hint)
        v.addStretch(1)
        v.addWidget(quit_btn)
        v.addWidget(hint)
        return page

    def _gestures_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 10, 0, 0)
        v.setSpacing(4)
        v.addWidget(
            _label(_("Hold a gesture until the bar passes the line to trigger it."), "RowSub")
        )
        self.gesture_rows: dict[str, GestureRow] = {}
        for b in self._settings.gestures.bindings:
            row = GestureRow(b)
            row.toggled.connect(self._on_gesture_toggled)
            row.cycle_action.connect(self._on_gesture_cycle)
            self.gesture_rows[b.id] = row
            v.addWidget(row)
        self.swap_btn = _button("", checkable=True)
        self.swap_btn.clicked.connect(
            lambda on: self._change(
                gestures=self._settings.gestures.model_copy(update={"swap_tilt": on})
            )
        )
        v.addSpacing(6)
        v.addWidget(self.swap_btn)
        v.addStretch(1)
        return page

    def _pointer_page(self) -> QWidget:
        page = QWidget()
        self.absolute_btn = _button(_("Absolute"), checkable=True)
        self.relative_btn = _button(_("Relative"), checkable=True)
        self.absolute_btn.setToolTip(_("Where you point your head is where the cursor goes"))
        self.relative_btn.setToolTip(_("Tilt your head to push the cursor, like a joystick"))
        group = QButtonGroup(self)
        group.addButton(self.absolute_btn)
        group.addButton(self.relative_btn)
        self.absolute_btn.clicked.connect(lambda: self._set_pointer(mode="absolute"))
        self.relative_btn.clicked.connect(lambda: self._set_pointer(mode="relative"))
        modes = QHBoxLayout()
        modes.setSpacing(20)
        modes.addWidget(self.absolute_btn, 1)
        modes.addWidget(self.relative_btn, 1)

        self.smooth_step = Stepper(_("Smoothness"), _("More = steadier, a little slower"))
        self.smooth_step.changed.connect(self._step_smoothness)
        self.reach_step = Stepper(
            _("Head turn to reach the edge"), _("Less = faster pointer, smaller movements")
        )
        self.reach_step.changed.connect(self._step_reach)
        self.dwell_step = Stepper(_("Dwell time"), _("How long to hold still to click"))
        self.dwell_step.changed.connect(self._step_dwell)
        self.motion_btn = _button("", checkable=True)
        self.motion_btn.clicked.connect(
            lambda on: self._set_pointer(motion_smoothing_ms=MOTION_SMOOTHING_ON_MS if on else 0.0)
        )
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 10, 0, 0)
        v.setSpacing(10)
        v.addWidget(_label(_("POINTER MODE"), "Section"))
        v.addLayout(modes)
        v.addSpacing(6)
        v.addWidget(self.smooth_step)
        v.addWidget(self.reach_step)
        v.addWidget(self.dwell_step)
        v.addWidget(self.motion_btn)
        v.addStretch(1)
        return page

    # ------------------------------------------------------------ settings changes

    def _change(self, **sections: object) -> None:
        """Publish a new Settings with some sections replaced."""
        new = self._settings.model_copy(update=sections)
        self.apply_settings(new)
        self.settings_changed.emit(new)

    def _set_pointer(self, **fields: object) -> None:
        self._change(pointer=self._settings.pointer.model_copy(update=fields))

    def _step_smoothness(self, direction: int) -> None:
        value = round(min(max(self._settings.pointer.smoothness + 0.1 * direction, 0.0), 1.0), 2)
        self._set_pointer(smoothness=value)

    def _step_reach(self, direction: int) -> None:
        p = self._settings.pointer
        yaw = min(max(p.yaw_range_deg + 1.5 * direction, 6.0), 40.0)
        # Keep the vertical/horizontal proportion the user had.
        pitch = min(max(p.pitch_range_deg * yaw / p.yaw_range_deg, 3.0), 40.0)
        self._set_pointer(yaw_range_deg=yaw, pitch_range_deg=round(pitch, 2))

    def _step_dwell(self, direction: int) -> None:
        d = self._settings.dwell
        value = round(min(max(d.dwell_s + 0.1 * direction, 0.4), 3.0), 2)
        self._change(dwell=d.model_copy(update={"dwell_s": value}))

    def _replace_binding(self, binding_id: str, **fields: object) -> None:
        g = self._settings.gestures
        bindings = tuple(
            b.model_copy(update=fields) if b.id == binding_id else b for b in g.bindings
        )
        self._change(gestures=g.model_copy(update={"bindings": bindings}))

    def _on_gesture_toggled(self, binding_id: str, on: bool) -> None:
        self._replace_binding(binding_id, enabled=on)

    def _on_gesture_cycle(self, binding_id: str) -> None:
        current = next(b for b in self._settings.gestures.bindings if b.id == binding_id)
        nxt = ACTION_CYCLE[(ACTION_CYCLE.index(current.action) + 1) % len(ACTION_CYCLE)]
        self._replace_binding(binding_id, action=nxt)

    # ------------------------------------------------------------ helpers

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

    @staticmethod
    def _set_toggle(button: QPushButton, on: bool, on_text: str, off_text: str) -> None:
        button.setChecked(on)
        button.setText(on_text if on else off_text)
        button.setAccessibleName(button.text())

    # ------------------------------------------------------------ updates

    def apply_settings(self, settings: Settings) -> None:
        """Reflect settings in the controls (programmatic changes emit no signals)."""
        self._settings = settings
        p, d = settings.pointer, settings.dwell
        self._set_toggle(self.dwell_btn, d.enabled, _("Dwell click: On"), _("Dwell click: Off"))
        self._set_toggle(
            self.toolbar_btn, settings.toolbar.visible, _("Toolbar: Shown"), _("Toolbar: Hidden")
        )
        self._set_toggle(
            self.swap_btn,
            settings.gestures.swap_tilt,
            _("Left and right tilt: swapped"),
            _("Left and right tilt: normal"),
        )
        self._set_toggle(
            self.motion_btn,
            p.motion_smoothing_ms > 0,
            _("Glide between frames: On"),
            _("Glide between frames: Off"),
        )
        self.absolute_btn.setChecked(p.mode == "absolute")
        self.relative_btn.setChecked(p.mode == "relative")
        self.smooth_step.set_value(f"{round(p.smoothness * 100)}%")
        self.reach_step.set_value(f"{p.yaw_range_deg:g}°")
        self.dwell_step.set_value(f"{d.dwell_s:.1f} s")
        for b in settings.gestures.bindings:
            row = self.gesture_rows.get(b.id)
            if row is not None:
                row.set_binding(b)

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

        holding = next((r for r in s.gestures if r.progress > 0.0), None)
        if s.manual_override:
            detail = _("Mouse in use. Head control returns in a moment.")
        elif holding is not None:
            detail = _("{name}: holding {pct}%").format(
                name=_(holding.label), pct=round(holding.progress * 100)
            )
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
            detail = why + " " + _("Raise your eyebrows for 2 s or press Resume to continue.")
        elif s.drift_suggested:
            detail = _("Your resting position seems to have moved. Recenter?")
        else:
            detail = _(QUALITY_TEXT[s.quality])
        self.recenter_btn.setObjectName("Suggest" if s.drift_suggested else "")
        self.recenter_btn.setStyle(self.recenter_btn.style())  # re-apply object-name styling
        self.detail.setText(f"{detail}   ·   {ps.fps:.0f} fps" if ps.fps else detail)

        if s.scrolling:
            hint = _("Scrolling: look up or down. Turn your head aside or rest to stop.")
        elif s.dragging:
            hint = _("Dragging: dwell again where you want to drop.")
        elif s.click_type is not ClickType.LEFT:
            hint = _("Next dwell: {t}.").format(t=_(CLICK_TYPE_TEXT[s.click_type]))
        else:
            hint = _("Right click, double click, drag and scroll are on the toolbar.")
        self.click_hint.setText(hint)

        for reading in s.gestures:
            row = self.gesture_rows.get(reading.id)
            if row is not None:
                row.set_reading(reading)
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
