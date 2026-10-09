"""Turn a tracked face (RawFace) into a FeatureFrame: head pose, nose, size, quality.

Head pose math
--------------
MediaPipe's facial transformation matrix M maps the canonical face model into camera space.
Camera space is right-handed: x to the camera's right (the right of the unmirrored image),
y up, and z toward the viewer, with the camera looking down -z. In the canonical model, the
face looks along +z (out of the nose).

So the face's "forward" direction in camera space is M's rotation applied to +z, which is
simply the third column of its upper-left 3x3 block: f = (M[0][2], M[1][2], M[2][2]).
A face looking straight at the camera has f = (0, 0, 1).

- yaw   = atan2(f.x, f.z): left/right turn.
- pitch = atan2(f.y, sqrt(f.x^2 + f.z^2)): up/down.
- roll  = atan2(r.y, r.x), with r = the rotated +x axis (first column): head tilt.

Using the forward vector avoids choosing an Euler-angle order. The user's right is the
camera's left (they face each other), so turning right gives f.x < 0; yaw is negated so
that positive yaw means "turned toward the user's right". If a camera driver mirrors the
image, the direction flips; the per-axis invert setting covers that.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from .frame import FeatureFrame, RawFace


def head_pose(matrix: tuple[float, ...]) -> tuple[float, float, float]:
    """(yaw, pitch, roll) in degrees from a row-major 4x4 transformation matrix."""
    fx, fy, fz = matrix[2], matrix[6], matrix[10]  # third column
    rx, ry = matrix[0], matrix[4]  # first column, x and y
    yaw = -math.degrees(math.atan2(fx, fz))
    pitch = math.degrees(math.atan2(fy, math.hypot(fx, fz)))
    roll = math.degrees(math.atan2(ry, rx))
    return yaw, pitch, roll


def eye_distance(face: RawFace) -> float:
    """Outer-eye-corner distance as a fraction of image width (a proxy for face size)."""
    width, height = face.image_size
    dx = face.eye_outer_right[0] - face.eye_outer_left[0]
    dy = (face.eye_outer_right[1] - face.eye_outer_left[1]) * height / max(width, 1)
    return math.hypot(dx, dy)


def extract(face: RawFace | None, t: float, brightness: float) -> FeatureFrame:
    """Build the FeatureFrame for one camera frame (`face` is None when no face was found)."""
    if face is None:
        return FeatureFrame(t=t, face=False, brightness=brightness)
    yaw, pitch, roll = head_pose(face.matrix)
    return FeatureFrame(
        t=t,
        face=True,
        yaw=yaw,
        pitch=pitch,
        roll=roll,
        nose_x=face.nose_tip[0],
        nose_y=face.nose_tip[1],
        face_size=eye_distance(face),
        brightness=brightness,
        blendshapes=face.blendshapes,
    )


class Quality(StrEnum):
    GOOD = "good"
    NO_FACE = "no_face"
    TOO_FAR = "too_far"
    TOO_CLOSE = "too_close"
    LOW_LIGHT = "low_light"


@dataclass(frozen=True, slots=True)
class QualityThresholds:
    """Heuristic limits for the tracking-quality badge (plain advice, not measurements)."""

    min_face_size: float = 0.07
    max_face_size: float = 0.40
    min_brightness: float = 40.0  # mean 0..255


DEFAULT_QUALITY_THRESHOLDS = QualityThresholds()


def quality(frame: FeatureFrame, limits: QualityThresholds = DEFAULT_QUALITY_THRESHOLDS) -> Quality:
    """Classify tracking conditions, most important problem first."""
    if not frame.face:
        return Quality.LOW_LIGHT if frame.brightness < limits.min_brightness else Quality.NO_FACE
    if frame.face_size < limits.min_face_size:
        return Quality.TOO_FAR
    if frame.face_size > limits.max_face_size:
        return Quality.TOO_CLOSE
    if frame.brightness < limits.min_brightness:
        return Quality.LOW_LIGHT
    return Quality.GOOD
