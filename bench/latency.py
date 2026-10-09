"""Latency benchmark: per-stage timings of the real pipeline (CLAUDE.md §9.1, §9.5).

Runs the same camera -> MediaPipe -> features -> engine -> OS input path as the app, with
no UI, for a fixed time, and prints p50/p95 per stage plus fps, CPU, and peak memory.
Dwell clicking is disabled, so it never clicks. By default the cursor really moves (to
time the OS event); use --no-move to keep the mouse still.

    uv run python bench/latency.py --seconds 60
    uv run python bench/latency.py --seconds 60 --no-move --camera 1

Sit in front of the camera as usual and move your head now and then. Paste the result
block into docs/METRICS.md together with the camera model and lighting.

Stage meanings: capture = time inside the camera read (mostly waiting for the next
frame); queue = wait before the pipeline picked the frame up; convert = colour
conversion; inference = MediaPipe; features = pose/quality extraction; engine = filters
and state machine; dispatch = OS input calls; end_to_end = camera read returned -> OS
input sent. Sensor-to-driver camera latency happens before any of this and cannot be
seen from software.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from importlib import metadata
from typing import Any

from nodwell import paths
from nodwell.core.engine import InteractionEngine
from nodwell.core.frame import FeatureFrame
from nodwell.core.safety import SafetyGate
from nodwell.core.settings import load_settings
from nodwell.pipeline import LiveSource, Pipeline
from nodwell.platform.input_backend import (
    DryRunBackend,
    GatedInput,
    InputBackend,
    PynputBackend,
)

PACKAGES = ("mediapipe", "opencv-contrib-python", "numpy", "PySide6", "pynput")


class FaceCounter:
    """Frame sink that counts frames with a tracked face."""

    def __init__(self) -> None:
        self.frames = 0
        self.with_face = 0

    def write(self, frame: FeatureFrame) -> None:
        self.frames += 1
        self.with_face += frame.face

    def close(self) -> None:
        pass


def peak_rss_mb() -> float | None:
    """Peak resident memory of this process, in MB."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        psapi = ctypes.WinDLL("psapi")
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        ok = psapi.GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        )
        return round(counters.PeakWorkingSetSize / 2**20, 1) if ok else None
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(peak / (2**20 if sys.platform == "darwin" else 2**10), 1)


def env_info() -> dict[str, Any]:
    versions: dict[str, str | None] = {}
    for pkg in PACKAGES:
        try:
            versions[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            versions[pkg] = None
    return {
        "os": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "python": sys.version.split()[0],
        "packages": versions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--camera", type=int, help="camera index (default: from settings)")
    parser.add_argument("--no-move", action="store_true", help="never move the real cursor")
    args = parser.parse_args()

    from PySide6.QtGui import QGuiApplication

    from nodwell.app import primary_screen_rect

    app = QGuiApplication(sys.argv)  # noqa: F841 - screen info and DPI awareness, as in the app
    screen, scale = primary_screen_rect()

    settings = load_settings(paths.settings_path())
    cam = settings.camera
    if args.camera is not None:
        cam = cam.model_copy(update={"index": args.camera})
    settings = settings.model_copy(
        update={
            "camera": cam,
            "dwell": settings.dwell.model_copy(update={"enabled": False}),  # never click
        }
    )

    gate = SafetyGate()
    backend: InputBackend = DryRunBackend() if args.no_move else PynputBackend()
    counter = FaceCounter()
    source = LiveSource(settings.camera, paths.verify_model())
    pipeline = Pipeline(
        source,
        InteractionEngine(settings, screen, scale),
        GatedInput(backend, gate, settings.safety.min_click_interval_s),
        gate,
        on_status=lambda _s: None,
        paused_fps=settings.camera.paused_fps,
        recorder=counter,
    )

    print(
        f"Loading tracking, then measuring for {args.seconds:.0f} s. Move your head now and then."
    )
    pipeline.start()
    while pipeline.frames == 0 and pipeline.is_alive():  # wait out MediaPipe start-up
        time.sleep(0.05)
    pipeline.stats = type(pipeline.stats)()  # discard warm-up samples
    cpu0, wall0, frames0 = time.process_time(), time.perf_counter(), pipeline.frames
    face0 = counter.with_face
    while time.perf_counter() - wall0 < args.seconds and pipeline.is_alive():
        time.sleep(0.1)
    wall = time.perf_counter() - wall0
    cpu = time.process_time() - cpu0
    frames = pipeline.frames - frames0
    with_face = counter.with_face - face0
    pipeline.stop()
    pipeline.join(timeout=5)

    result = {
        "tool": "bench/latency.py",
        "date": time.strftime("%Y-%m-%d %H:%M"),
        "env": env_info(),
        "camera": source.description,
        "screen": {"width": screen.width, "height": screen.height, "scale": scale},
        "settings": {
            "pointer_mode": settings.pointer.mode,
            "smoothness": settings.pointer.smoothness,
            "moved_real_cursor": not args.no_move,
        },
        "seconds": round(wall, 1),
        "frames": frames,
        "frames_with_face": with_face,
        "fps": round(frames / wall, 1) if wall else None,
        "camera_frames_dropped": source.dropped_frames,
        "cpu_percent_of_one_core": round(100 * cpu / wall, 1) if wall else None,
        "peak_memory_mb": peak_rss_mb(),
        "stages_ms": pipeline.stats.summary(),
        "error": pipeline.error or source.error,
    }
    if frames and with_face < 0.8 * frames:
        print(
            f"\nWARNING: a face was tracked in only {with_face} of {frames} frames. Without a"
            " face the app idles at the paused rate, so these numbers are not representative."
            " Sit in front of the camera and run again."
        )
    print("\n===== LATENCY RESULT (paste into docs/METRICS.md) =====")
    print(json.dumps(result, indent=2))
    print("===== END LATENCY RESULT =====")
    return 0 if result["error"] is None and frames else 1


if __name__ == "__main__":
    sys.exit(main())
