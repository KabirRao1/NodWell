"""Click-type toolbar (CLAUDE.md §8 P0.4): chooses what the next dwell does.

A narrow vertical strip docked to a screen edge, always on top. It never takes focus: a
dwell on one of its buttons must not pull keyboard focus away from the app the user is
working in (Qt flags plus WS_EX_NOACTIVATE on Windows, as tested in M0 spike S4).
Dwells and gestures that land on it always arrive as plain left clicks, so choosing
"Right" doesn't itself become a right click (the engine handles that, see SetOwnUi).
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QButtonGroup, QPushButton, QVBoxLayout, QWidget

from nodwell.core.actions import ClickType
from nodwell.core.engine import Status
from nodwell.i18n import _
from nodwell.platform.win32 import WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_TOPMOST, add_exstyle
from nodwell.ui import theme

BUTTONS = [
    (ClickType.LEFT, "Left", "Left click (normal)"),
    (ClickType.RIGHT, "Right", "Right click on the next dwell"),
    (ClickType.DOUBLE, "Double", "Double click on the next dwell"),
    (ClickType.DRAG, "Drag", "Drag: dwell to grab, dwell again to drop"),
    (ClickType.SCROLL, "Scroll", "Scroll: dwell on the page, then look up or down"),
]
EDGE_MARGIN = 8


class ClickToolbar(QWidget):
    click_type_selected = Signal(object)  # ClickType

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setObjectName("Toolbar")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setStyleSheet(theme.STYLESHEET)
        self.setAccessibleName(_("Click type"))
        self._styled = False
        self._current = ClickType.LEFT
        self.buttons: dict[ClickType, QPushButton] = {}
        group = QButtonGroup(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(14)
        for click_type, text, tip in BUTTONS:
            b = QPushButton(_(text))
            b.setCheckable(True)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # never steal keyboard focus
            b.setToolTip(_(tip))
            b.setAccessibleName(_(tip))
            b.clicked.connect(lambda _checked=False, ct=click_type: self._on_clicked(ct))
            group.addButton(b)
            layout.addWidget(b)
            self.buttons[click_type] = b
        self.buttons[ClickType.LEFT].setChecked(True)

    def _on_clicked(self, click_type: ClickType) -> None:
        # Choosing the type that is already selected switches back to a normal left click.
        chosen = ClickType.LEFT if click_type is self._current else click_type
        self.click_type_selected.emit(chosen)
        self._show_selected(chosen)

    def _show_selected(self, click_type: ClickType) -> None:
        self._current = click_type
        self.buttons[click_type].setChecked(True)

    def update_status(self, status: Status) -> None:
        if status.click_type is not self._current:
            self._show_selected(status.click_type)
        drag = self.buttons[ClickType.DRAG]
        drag.setText(_("Drop") if status.dragging else _("Drag"))
        scroll = self.buttons[ClickType.SCROLL]
        scroll.setText(_("Stop") if status.scrolling else _("Scroll"))

    def dock(self, edge: str) -> None:
        """Place against the left or right edge, vertically centred."""
        self.adjustSize()
        area: QRect = QGuiApplication.primaryScreen().availableGeometry()
        x = (
            area.left() + EDGE_MARGIN
            if edge == "left"
            else area.right() - self.width() - EDGE_MARGIN
        )
        self.move(x, area.top() + (area.height() - self.height()) // 2)

    def show_docked(self, edge: str) -> None:
        self.dock(edge)
        self.show()
        if not self._styled:
            add_exstyle(int(self.winId()), WS_EX_NOACTIVATE | WS_EX_TOPMOST | WS_EX_TOOLWINDOW)
            self._styled = True
