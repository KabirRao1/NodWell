"""Windows extended window styles for overlays. Every function is a no-op elsewhere.

Qt's window flags request most of this, but M0's S3 spike couldn't yet confirm that Qt
sets every bit on Windows, so the overlay also sets them directly (belt and braces).
"""

from __future__ import annotations

import sys

IS_WINDOWS = sys.platform == "win32"

GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020  # mouse input passes through
WS_EX_TOOLWINDOW = 0x00000080  # no taskbar button, not in Alt+Tab
WS_EX_LAYERED = 0x00080000  # per-pixel transparency
WS_EX_NOACTIVATE = 0x08000000  # never takes focus

OVERLAY_EXSTYLE = (
    WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOPMOST | WS_EX_TOOLWINDOW
)


def add_exstyle(hwnd: int, bits: int) -> None:
    """OR `bits` into a window's extended style."""
    if not IS_WINDOWS:
        return
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    current = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, current | bits)
