"""Tiny ctypes helpers for the Windows parts of spikes 3 and 4. No-ops elsewhere."""

from __future__ import annotations

import sys

IS_WINDOWS = sys.platform == "win32"

GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000

_EXSTYLE_NAMES = {
    WS_EX_TOPMOST: "TOPMOST",
    WS_EX_TRANSPARENT: "TRANSPARENT",
    WS_EX_TOOLWINDOW: "TOOLWINDOW",
    WS_EX_LAYERED: "LAYERED",
    WS_EX_NOACTIVATE: "NOACTIVATE",
}

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    _user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    _user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetDpiForWindow.argtypes = [wintypes.HWND]
    _user32.GetDpiForWindow.restype = wintypes.UINT


def get_exstyle(hwnd: int) -> int:
    """Return the window's extended style bits (0 off Windows)."""
    if not IS_WINDOWS:
        return 0
    return int(_user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE))


def add_exstyle(hwnd: int, bits: int) -> int:
    """OR `bits` into the window's extended style; return the new value."""
    if not IS_WINDOWS:
        return 0
    _user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, get_exstyle(hwnd) | bits)
    return get_exstyle(hwnd)


def describe_exstyle(value: int) -> list[str]:
    """Names of the extended-style bits this spike cares about."""
    return [name for bit, name in _EXSTYLE_NAMES.items() if value & bit]


def foreground_window() -> tuple[int, str]:
    """(hwnd, title) of the window that currently has keyboard focus."""
    if not IS_WINDOWS:
        return (0, "")
    hwnd = _user32.GetForegroundWindow() or 0
    buf = ctypes.create_unicode_buffer(256)
    _user32.GetWindowTextW(hwnd, buf, 256)
    return (int(hwnd), buf.value)


def dpi_for_window(hwnd: int) -> int | None:
    """Effective DPI of a window (96 = 100% scaling), or None off Windows."""
    if not IS_WINDOWS:
        return None
    return int(_user32.GetDpiForWindow(hwnd))
