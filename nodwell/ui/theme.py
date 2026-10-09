"""Colours and the Qt stylesheet. Calm and warm (CLAUDE.md §7); light theme only in M1."""

from __future__ import annotations

from PySide6.QtGui import QColor

BG = "#FBF7F2"
SURFACE = "#FFFFFF"
TEXT = "#2B2724"
MUTED = "#6B625B"
BORDER = "#E4DCD3"
ACCENT = "#B4561A"  # warm orange; white text on it has 4.9:1 contrast (WCAG AA)
ACCENT_HOVER = "#9C4A14"
FOCUS = "#1F5FAD"

# Status pill: (background, text). Each state also has its own word, so colour is never
# the only signal.
PILL = {
    "active": ("#DDF0E1", "#1D5A2C"),
    "paused": ("#ECE7E1", "#4A433D"),
    "starting": ("#FCEBD9", "#7A3D0E"),
    "warning": ("#FBE0DC", "#8A2117"),
}

RING_TRACK = QColor(255, 255, 255, 110)
RING_FILL = QColor(232, 140, 48, 235)
RING_EDGE = QColor(43, 39, 36, 140)

MIN_TARGET_PX = 64  # CLAUDE.md §7: every interactive element at least 64 px

STYLESHEET = f"""
QWidget#Panel {{ background: {BG}; }}
QWidget {{ color: {TEXT}; font-size: 15px; }}
QLabel#Title {{ font-size: 22px; font-weight: 600; }}
QLabel#Detail {{ color: {MUTED}; font-size: 15px; }}
QLabel#Hint {{ color: {MUTED}; font-size: 13px; }}
QLabel#Section {{ font-size: 13px; font-weight: 600; color: {MUTED}; }}
QLabel#Pill {{ border-radius: 14px; padding: 6px 18px; font-size: 16px; font-weight: 600; }}
QLabel#Error {{ color: #8A2117; font-weight: 600; }}
QPushButton {{
    min-height: {MIN_TARGET_PX}px; min-width: 120px; padding: 0 20px;
    border: 2px solid {BORDER}; border-radius: 14px; background: {SURFACE};
    font-size: 17px; font-weight: 600;
}}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:focus {{ border: 3px solid {FOCUS}; }}
QPushButton:checked {{ background: {ACCENT}; border-color: {ACCENT}; color: white; }}
QPushButton#Primary {{ background: {ACCENT}; border-color: {ACCENT}; color: white; }}
QPushButton#Primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#Suggest {{ border: 3px solid {ACCENT}; }}
QPushButton#Tab {{
    border: none; border-bottom: 4px solid transparent; border-radius: 0;
    background: transparent; color: {MUTED}; min-width: 90px;
}}
QPushButton#Tab:checked {{
    color: {TEXT}; border-bottom: 4px solid {ACCENT}; background: transparent;
}}
QPushButton#Tab:focus {{ border-bottom: 4px solid {FOCUS}; }}
QPushButton#Step {{
    min-width: {MIN_TARGET_PX}px; max-width: {MIN_TARGET_PX}px; padding: 0; font-size: 24px;
}}
QPushButton#Compact {{ min-width: 84px; padding: 0 10px; }}
QLabel#Value {{ font-size: 17px; font-weight: 600; min-width: 70px; }}
QLabel#RowTitle {{ font-size: 16px; font-weight: 600; }}
QLabel#RowSub {{ color: {MUTED}; font-size: 13px; }}
QWidget#Toolbar {{ background: {BG}; border: 2px solid {BORDER}; border-radius: 16px; }}
QWidget#Toolbar QPushButton {{
    min-width: 88px; max-width: 88px; min-height: 72px; font-size: 15px;
}}
"""
