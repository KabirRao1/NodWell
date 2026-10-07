"""Spike 2: can pynput move and click the cursor, type, and scroll in another app?

Open Notepad (or TextEdit / gedit), run this, and during the countdown hover the mouse
over the editor's text area. The script then moves the cursor in a small square, clicks,
types a line, and scrolls. Press Esc at any time to abort.

Afterwards it creates a Qt application in the same process and checks whether pynput
and Qt agree on cursor coordinates (display-scaling / DPI awareness question).

    uv run python spikes/s2_pynput_inject.py
    uv run python spikes/s2_pynput_inject.py --label "notepad elevated"   # UIPI check
"""

from __future__ import annotations

import argparse
import ctypes
import sys
import time
from typing import Any

from _common import countdown, env_info, percentiles, print_result
from pynput import keyboard, mouse

TEST_TEXT = "nodwell spike 2: hello from pynput"
SQUARE_PX = 80


def dpi_awareness() -> str | None:
    """Windows only: the calling thread's DPI awareness (unaware / system / per-monitor)."""
    if sys.platform != "win32":
        return None
    user32 = ctypes.windll.user32
    user32.GetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    user32.GetAwarenessFromDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    ctx = user32.GetThreadDpiAwarenessContext()
    value = user32.GetAwarenessFromDpiAwarenessContext(ctx)
    return {0: "unaware", 1: "system", 2: "per_monitor"}.get(value, f"unknown({value})")


def win_screen_metrics() -> list[int] | None:
    """Windows only: primary screen size as GetSystemMetrics reports it to this process."""
    if sys.platform != "win32":
        return None
    return [ctypes.windll.user32.GetSystemMetrics(0), ctypes.windll.user32.GetSystemMetrics(1)]


def mac_accessibility_trusted() -> bool | None:
    """macOS only: whether this process may post input events (Accessibility permission)."""
    if sys.platform != "darwin":
        return None
    lib = ctypes.cdll.LoadLibrary(
        "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
    )
    lib.AXIsProcessTrusted.restype = ctypes.c_bool
    return bool(lib.AXIsProcessTrusted())


def qt_coordinate_check(mouse_ctl: mouse.Controller) -> dict[str, Any]:
    """Create Qt in this process, move with pynput, and read the position back via Qt."""
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QCursor, QGuiApplication

    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    screen = app.primaryScreen()
    geo = screen.geometry()
    target = (300, 300)
    mouse_ctl.position = target
    time.sleep(0.1)
    app.processEvents()
    qt_pos: QPoint = QCursor.pos()
    return {
        "dpi_awareness_after_qt": dpi_awareness(),
        "win_screen_metrics_after_qt": win_screen_metrics(),
        "qt_primary_geometry": [geo.x(), geo.y(), geo.width(), geo.height()],
        "qt_device_pixel_ratio": screen.devicePixelRatio(),
        "pynput_set": list(target),
        "pynput_readback": list(mouse_ctl.position),
        "qt_cursor_pos": [qt_pos.x(), qt_pos.y()],
        "coordinates_agree": [qt_pos.x(), qt_pos.y()] == list(target),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Spike 2: pynput input injection")
    parser.add_argument("--label", default="", help="free text describing this run")
    args = parser.parse_args()

    result: dict[str, Any] = {
        "spike": "s2_pynput_inject",
        "label": args.label,
        "env": env_info(),
        "mac_accessibility_trusted": mac_accessibility_trusted(),
        "dpi_awareness_before_qt": dpi_awareness(),
        "win_screen_metrics_before_qt": win_screen_metrics(),
    }
    if sys.platform.startswith("linux") and result["env"]["session_type"] == "wayland":
        print("WARNING: Wayland session. Global injection is expected to fail (CLAUDE.md §12).")

    aborted = {"flag": False}

    def on_press(key: Any) -> None:
        if key == keyboard.Key.esc:
            aborted["flag"] = True

    listener = keyboard.Listener(on_press=on_press)
    listener.start()
    m = mouse.Controller()
    k = keyboard.Controller()

    countdown(5, "Hover your mouse over the target app's text area now. Esc aborts.")
    start = m.position
    result["start_position"] = list(start)

    move_ms: list[float] = []
    readback_errors: list[list[float]] = []
    x0, y0 = start
    corners = [
        (x0 + SQUARE_PX, y0),
        (x0 + SQUARE_PX, y0 + SQUARE_PX),
        (x0, y0 + SQUARE_PX),
        (x0, y0),
    ]
    for _lap in range(2):
        for cx, cy in corners:
            if aborted["flag"]:
                break
            t = time.perf_counter()
            m.position = (cx, cy)
            move_ms.append((time.perf_counter() - t) * 1000)
            rx, ry = m.position
            if (rx, ry) != (cx, cy):
                readback_errors.append([cx, cy, rx, ry])
            time.sleep(0.2)

    click_ms = type_ms = scroll_ms = None
    if not aborted["flag"]:
        t = time.perf_counter()
        m.click(mouse.Button.left)
        click_ms = (time.perf_counter() - t) * 1000
        time.sleep(0.3)
    if not aborted["flag"]:
        t = time.perf_counter()
        k.type(TEST_TEXT)
        k.tap(keyboard.Key.enter)
        type_ms = (time.perf_counter() - t) * 1000
        time.sleep(0.3)
    if not aborted["flag"]:
        t = time.perf_counter()
        m.scroll(0, -3)
        time.sleep(0.3)
        m.scroll(0, 3)
        scroll_ms = (time.perf_counter() - t - 0.3) * 1000

    listener.stop()
    result.update(
        {
            "aborted": aborted["flag"],
            "move_call_ms": percentiles(move_ms),
            "position_readback_mismatches": readback_errors,
            "click_call_ms": click_ms and round(click_ms, 2),
            "type_call_ms_total": type_ms and round(type_ms, 2),
            "type_chars": len(TEST_TEXT) + 1,
            "scroll_calls_ms": scroll_ms and round(scroll_ms, 2),
        }
    )
    try:
        result["qt_check"] = qt_coordinate_check(m)
    except Exception as exc:  # spike: report, don't crash
        result["qt_check"] = {"error": repr(exc)}

    print_result(result)
    print("Please also answer in your reply:")
    print(f"  1. Did the cursor visibly trace a square twice (~{SQUARE_PX} px)?")
    print(f"  2. Did '{TEST_TEXT}' appear in the target app, followed by a new line?")
    print("  3. Did the target app scroll (if it had enough text to scroll)?")
    print("  4. Your display scaling (Settings > System > Display > Scale), e.g. 125%.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
