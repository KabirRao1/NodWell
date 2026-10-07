"""Spike 5 self-test: proves a frozen (PyInstaller) build can load everything M1 needs.

Checks, in order: bundled model present and matching its pinned SHA-256; MediaPipe
native library loads; Face Landmarker runs on a synthetic in-memory frame; Qt starts and
shows a widget; pynput can read the cursor position (it never moves it). Optionally opens
the camera for a few seconds. The network is blocked throughout. Exit code 0 = all passed.

    nodwell-selftest                # headless checks
    nodwell-selftest --camera       # also run the live camera for 5 s
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

T_START = time.perf_counter()

# When frozen, PyInstaller unpacks data next to the modules (onedir: the _internal dir).
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # find spikes/_common.py

from _common import NetworkTripwire, env_info, percentiles, print_result  # noqa: E402

TRIPWIRE = NetworkTripwire().install()
MODEL = BUNDLE_DIR / "models" / "face_landmarker.task"
CHECKSUM = BUNDLE_DIR / "models" / "face_landmarker.sha256"


def check_model() -> dict[str, Any]:
    expected = CHECKSUM.read_text(encoding="utf-8").split()[0]
    actual = hashlib.sha256(MODEL.read_bytes()).hexdigest()
    assert actual == expected, f"model checksum {actual} != pinned {expected}"
    return {"path": str(MODEL), "bytes": MODEL.stat().st_size, "sha256_ok": True}


def check_landmarker() -> dict[str, Any]:
    import mediapipe as mp
    import numpy as np
    from mediapipe.tasks.python import BaseOptions, vision

    t = time.perf_counter()
    landmarker = vision.FaceLandmarker.create_from_options(
        vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(MODEL)),
            running_mode=vision.RunningMode.VIDEO,
            output_face_blendshapes=True,
            output_facial_transformation_matrixes=True,
        )
    )
    create_s = time.perf_counter() - t
    frame = np.full((480, 640, 3), 128, dtype=np.uint8)  # synthetic grey frame, no face
    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame)
    timings = []
    for i in range(20):
        t = time.perf_counter()
        result = landmarker.detect_for_video(image, i * 33)
        timings.append((time.perf_counter() - t) * 1000)
    landmarker.close()
    return {
        "mediapipe": mp.__version__,
        "create_seconds": round(create_s, 2),
        "blank_frame_ms": percentiles(timings),
        "faces_on_blank_frame": len(result.face_landmarks),
    }


def check_qt() -> dict[str, Any]:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QLabel

    app = QApplication.instance() or QApplication(sys.argv)
    label = QLabel("Nodwell self-test")
    label.show()
    QTimer.singleShot(200, app.quit)
    app.exec()
    label.close()
    return {"platform": QApplication.platformName()}


def check_pynput() -> dict[str, Any]:
    from pynput import mouse

    return {"cursor_position": list(mouse.Controller().position)}


def check_camera(seconds: float = 5.0) -> dict[str, Any]:
    import cv2

    cap = cv2.VideoCapture(0)
    ok, _ = cap.read()
    frames = 0
    t = time.perf_counter()
    while ok and time.perf_counter() - t < seconds:
        ok, _ = cap.read()  # frames are discarded immediately
        frames += ok
    cap.release()
    assert frames, "camera produced no frames"
    return {"frames": frames, "fps": round(frames / seconds, 1)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Nodwell spike 5 self-test")
    parser.add_argument("--camera", action="store_true")
    parser.add_argument("--skip-gui", action="store_true", help="skip Qt and pynput checks")
    args = parser.parse_args()

    checks: list[tuple[str, Callable[[], dict[str, Any]]]] = [
        ("model", check_model),
        ("landmarker", check_landmarker),
    ]
    if not args.skip_gui:
        checks += [("qt", check_qt), ("pynput", check_pynput)]
    if args.camera:
        checks.append(("camera", check_camera))

    results: dict[str, Any] = {}
    all_ok = True
    for name, fn in checks:
        try:
            results[name] = {"ok": True, **fn()}
        except Exception as exc:
            all_ok = False
            results[name] = {"ok": False, "error": repr(exc), "trace": traceback.format_exc()}

    no_network = not TRIPWIRE.attempts
    print_result(
        {
            "spike": "s5_pyinstaller_selftest",
            "env": env_info(),
            "bundle_dir": str(BUNDLE_DIR),
            "checks": results,
            "network_attempts": TRIPWIRE.attempts,
            "seconds_since_python_start": round(time.perf_counter() - T_START, 2),
            "all_ok": all_ok and no_network,
        }
    )
    return 0 if all_ok and no_network else 1


if __name__ == "__main__":
    sys.exit(main())
