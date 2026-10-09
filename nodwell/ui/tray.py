"""System tray icon with the same core actions as the panel (CLAUDE.md §8 P0.6)."""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from nodwell.core.engine import Mode
from nodwell.i18n import _
from nodwell.ui import theme


def _icon(color: str) -> QIcon:
    """A simple drawn icon (no image assets): a ring with a centre dot."""
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(4, 4, 56, 56)
    p.setBrush(QColor("white"))
    p.drawEllipse(22, 22, 20, 20)
    p.end()
    return QIcon(pm)


class Tray(QObject):
    toggle_pause = Signal()
    recenter = Signal()
    show_panel = Signal()
    quit = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._icons = {
            Mode.ACTIVE: _icon(theme.ACCENT),
            Mode.PAUSED: _icon(theme.MUTED),
            Mode.STARTING: _icon("#E0A36B"),
        }
        self.icon = QSystemTrayIcon(self._icons[Mode.STARTING])
        self.icon.setToolTip("Nodwell")
        menu = QMenu()
        self._pause_action = QAction(_("Pause"), menu)
        self._pause_action.triggered.connect(self.toggle_pause)
        menu.addAction(self._pause_action)
        menu.addAction(_("Recenter"), self.recenter.emit)
        menu.addAction(_("Show Nodwell"), self.show_panel.emit)
        menu.addSeparator()
        menu.addAction(_("Quit"), self.quit.emit)
        self._menu = menu
        self.icon.setContextMenu(menu)
        self.icon.activated.connect(self._on_activated)
        self._mode: Mode | None = None

    def show(self) -> None:
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.icon.show()

    def hide(self) -> None:
        self.icon.hide()

    def set_mode(self, mode: Mode) -> None:
        if mode is self._mode:
            return
        self._mode = mode
        self.icon.setIcon(self._icons[mode])
        self.icon.setToolTip(f"Nodwell: {mode.value}")
        self._pause_action.setText(_("Pause") if mode is Mode.ACTIVE else _("Resume"))

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason is QSystemTrayIcon.ActivationReason.Trigger:
            self.show_panel.emit()
