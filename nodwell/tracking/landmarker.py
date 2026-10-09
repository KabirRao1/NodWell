"""MediaPipe Face Landmarker wrapper: BGR frame in, plain-number RawFace out."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from nodwell.paths import prepare_matplotlib

# mediapipe.tasks.python.vision imports matplotlib eagerly; configure it first.
prepare_matplotlib()

import cv2  # noqa: E402
import mediapipe as mp  # noqa: E402
from mediapipe.tasks.python import BaseOptions, vision  # noqa: E402

from nodwell.core.frame import RawFace  # noqa: E402

# Face mesh landmark indices (canonical MediaPipe topology).
NOSE_TIP = 1
EYE_OUTER_LEFT = 33  # the image-left eye's outer corner (the user's right eye)
EYE_OUTER_RIGHT = 263


@dataclass(slots=True)
class TrackResult:
    face: RawFace | None
    brightness: float
    convert_ms: float
    inference_ms: float


class FaceTracker:
    """Synchronous (VIDEO mode) Face Landmarker, one face (DECISIONS.md D14).

    Not thread-safe: create and use it on one thread.
    """

    def __init__(self, model: bytes) -> None:
        """`model` is the verified model file content (see paths.load_model)."""
        options = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_buffer=model),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1,
            output_face_blendshapes=True,
            output_facial_transformation_matrixes=True,
        )
        self._landmarker = vision.FaceLandmarker.create_from_options(options)
        self._last_ts_ms = -1
        self.blendshape_names: list[str] = []  # as reported by the model, once seen

    def close(self) -> None:
        self._landmarker.close()

    def process(self, bgr: Any, t: float) -> TrackResult:
        """Track the face in one BGR frame captured at time `t` (seconds)."""
        a = time.perf_counter()
        # Brightness from every 8th pixel in each direction: ~1/64 of the work, plenty for
        # a "low light" hint.
        brightness = float(bgr[::8, ::8].mean())
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        b = time.perf_counter()
        # VIDEO mode needs strictly increasing millisecond timestamps.
        ts = max(int(t * 1000), self._last_ts_ms + 1)
        self._last_ts_ms = ts
        result = self._landmarker.detect_for_video(image, ts)
        c = time.perf_counter()
        return TrackResult(
            self._to_raw(result, bgr.shape), brightness, (b - a) * 1000, (c - b) * 1000
        )

    def _to_raw(self, result: Any, shape: tuple[int, ...]) -> RawFace | None:
        if not result.face_landmarks or not result.facial_transformation_matrixes:
            return None
        landmarks = result.face_landmarks[0]
        blendshapes: dict[str, float] = {}
        if result.face_blendshapes:
            blendshapes = {c.category_name: float(c.score) for c in result.face_blendshapes[0]}
            if not self.blendshape_names:
                self.blendshape_names = list(blendshapes)
        matrix = tuple(float(v) for v in result.facial_transformation_matrixes[0].flatten())
        height, width = shape[0], shape[1]
        return RawFace(
            matrix=matrix,
            nose_tip=(landmarks[NOSE_TIP].x, landmarks[NOSE_TIP].y),
            eye_outer_left=(landmarks[EYE_OUTER_LEFT].x, landmarks[EYE_OUTER_LEFT].y),
            eye_outer_right=(landmarks[EYE_OUTER_RIGHT].x, landmarks[EYE_OUTER_RIGHT].y),
            blendshapes=blendshapes,
            image_size=(width, height),
        )
