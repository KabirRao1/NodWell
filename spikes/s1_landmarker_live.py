"""Spike 1: does MediaPipe Face Landmarker run live on the webcam, how fast, and what
does it output?

Prints fps, per-stage timings, landmark count, transformation-matrix shape, and the
full blendshape name list read from the model at runtime. Frames live only in memory:
nothing is written to disk and the network is blocked for the whole run.

    uv run python spikes/s1_landmarker_live.py                 # VIDEO mode, 30 s
    uv run python spikes/s1_landmarker_live.py --live          # LIVE_STREAM mode
    uv run python spikes/s1_landmarker_live.py --preview       # show an in-memory preview window
    uv run python spikes/s1_landmarker_live.py --backend dshow # try another capture backend
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path
from typing import Any

from _common import NetworkTripwire, env_info, percentiles, print_result

TRIPWIRE = NetworkTripwire().install()

import cv2  # noqa: E402  (imported after the tripwire on purpose)
import mediapipe as mp  # noqa: E402
from mediapipe.tasks.python import BaseOptions, vision  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = REPO_ROOT / "models" / "face_landmarker.task"

# Candidate names from CLAUDE.md §8 P1.1, checked against what the model really emits.
SPEC_CANDIDATES = [
    "jawOpen",
    "browInnerUp",
    "browOuterUpLeft",
    "browOuterUpRight",
    "mouthSmileLeft",
    "mouthSmileRight",
    "mouthPucker",
    "cheekPuff",
    "eyeBlinkLeft",
    "eyeBlinkRight",
]

BACKENDS = {
    "any": cv2.CAP_ANY,
    "msmf": cv2.CAP_MSMF,
    "dshow": cv2.CAP_DSHOW,
    "avfoundation": cv2.CAP_AVFOUNDATION,
    "v4l2": cv2.CAP_V4L2,
}


def open_camera(index: int, backend: str, width: int, height: int, fps: int) -> tuple[Any, float]:
    """Open the camera and request a resolution/fps. Returns (capture, open_seconds)."""
    t0 = time.perf_counter()
    cap = cv2.VideoCapture(index, BACKENDS[backend])
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)
    ok, _ = cap.read()  # first frame is often slow; count it as part of "open"
    if not cap.isOpened() or not ok:
        sys.exit(f"could not open camera {index} with backend {backend!r}")
    return cap, time.perf_counter() - t0


def main() -> int:
    parser = argparse.ArgumentParser(description="Spike 1: live Face Landmarker")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--backend", choices=sorted(BACKENDS), default="any")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--seconds", type=float, default=30.0)
    parser.add_argument("--live", action="store_true", help="LIVE_STREAM mode instead of VIDEO")
    parser.add_argument("--preview", action="store_true", help="show an in-memory preview")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    args = parser.parse_args()

    if not args.model.is_file():
        sys.exit(f"model not found at {args.model}; run: uv run python scripts/fetch_model.py")

    # --- LIVE_STREAM results arrive on a MediaPipe thread through this callback.
    live_lock = threading.Lock()
    live_latency_ms: list[float] = []
    submit_times: dict[int, float] = {}
    latest: dict[str, Any] = {"result": None}

    def on_result(result: Any, _image: Any, timestamp_ms: int) -> None:
        with live_lock:
            sent = submit_times.pop(timestamp_ms, None)
            if sent is not None:
                live_latency_ms.append((time.perf_counter() - sent) * 1000)
            latest["result"] = result

    mode = vision.RunningMode.LIVE_STREAM if args.live else vision.RunningMode.VIDEO
    options = vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(args.model)),
        running_mode=mode,
        num_faces=1,
        output_face_blendshapes=True,
        output_facial_transformation_matrixes=True,
        result_callback=on_result if args.live else None,
    )

    t0 = time.perf_counter()
    landmarker = vision.FaceLandmarker.create_from_options(options)
    create_s = time.perf_counter() - t0

    cap, open_s = open_camera(args.camera, args.backend, args.width, args.height, args.fps)
    actual = (
        int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        cap.get(cv2.CAP_PROP_FPS),
    )
    backend_name = cap.getBackendName()
    print(f"camera open in {open_s:.2f}s via {backend_name} at {actual}; running...")
    print("Look at the camera, move your head, try smiling / raising brows / blinking.")

    capture_ms: list[float] = []
    convert_ms: list[float] = []
    infer_ms: list[float] = []
    frames = faces = 0
    blendshape_names: list[str] = []
    landmark_count = None
    matrix_shape = None
    last_ts = -1

    cpu0, wall0 = time.process_time(), time.perf_counter()
    try:
        while time.perf_counter() - wall0 < args.seconds:
            a = time.perf_counter()
            ok, frame_bgr = cap.read()
            b = time.perf_counter()
            if not ok:
                continue
            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
            c = time.perf_counter()

            # MediaPipe needs strictly increasing millisecond timestamps.
            ts = max(int(time.monotonic() * 1000), last_ts + 1)
            last_ts = ts
            if args.live:
                with live_lock:
                    submit_times[ts] = time.perf_counter()
                landmarker.detect_async(image, ts)
                with live_lock:
                    result = latest["result"]
            else:
                result = landmarker.detect_for_video(image, ts)
            d = time.perf_counter()

            frames += 1
            capture_ms.append((b - a) * 1000)
            convert_ms.append((c - b) * 1000)
            if not args.live:
                infer_ms.append((d - c) * 1000)

            if result is not None and result.face_landmarks:
                faces += 1
                landmark_count = len(result.face_landmarks[0])
                if result.facial_transformation_matrixes:
                    matrix_shape = list(result.facial_transformation_matrixes[0].shape)
                if result.face_blendshapes and not blendshape_names:
                    blendshape_names = [cat.category_name for cat in result.face_blendshapes[0]]

            if args.preview:
                view = frame_bgr.copy()  # in memory only; never written anywhere
                if result is not None and result.face_landmarks:
                    h, w = view.shape[:2]
                    for lm in result.face_landmarks[0][::4]:
                        cv2.circle(view, (int(lm.x * w), int(lm.y * h)), 1, (0, 200, 255), -1)
                cv2.imshow("spike 1 preview (q to quit)", view)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    finally:
        wall = time.perf_counter() - wall0
        cpu = time.process_time() - cpu0
        cap.release()
        landmarker.close()
        if args.preview:
            cv2.destroyAllWindows()

    missing = [n for n in SPEC_CANDIDATES if blendshape_names and n not in blendshape_names]
    print_result(
        {
            "spike": "s1_landmarker_live",
            "env": env_info(),
            "mediapipe_api": "mediapipe.tasks.python.vision.FaceLandmarker",
            "has_legacy_solutions_api": hasattr(mp, "solutions"),
            "mode": "LIVE_STREAM" if args.live else "VIDEO",
            "camera": {
                "index": args.camera,
                "backend": backend_name,
                "requested": [args.width, args.height, args.fps],
                "reported": list(actual),
                "open_seconds": round(open_s, 2),
            },
            "landmarker_create_seconds": round(create_s, 2),
            "seconds": round(wall, 1),
            "frames": frames,
            "frames_with_face": faces,
            "end_to_end_fps": round(frames / wall, 1) if wall else None,
            "cpu_percent_of_one_core": round(100 * cpu / wall, 1) if wall else None,
            "capture_ms": percentiles(capture_ms),
            "convert_ms": percentiles(convert_ms),
            "inference_ms": percentiles(infer_ms) if not args.live else None,
            "live_result_latency_ms": percentiles(live_latency_ms) if args.live else None,
            "live_results_received": len(live_latency_ms) if args.live else None,
            "landmark_count": landmark_count,
            "transformation_matrix_shape": matrix_shape,
            "blendshape_count": len(blendshape_names),
            "blendshape_names": blendshape_names,
            "spec_candidates_missing": missing,
            "network_attempts": TRIPWIRE.attempts,
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
