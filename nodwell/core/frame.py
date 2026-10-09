"""Plain data passed between the tracker and the core.

`RawFace` is what the tracking layer hands over: numbers copied out of MediaPipe's result,
with no MediaPipe types attached. `FeatureFrame` is what the rest of the core consumes, and
what the opt-in Recorder writes to JSONL (numbers only, never pixels; CLAUDE.md §4.1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

Point2 = tuple[float, float]


@dataclass(frozen=True, slots=True)
class RawFace:
    """One tracked face, as plain numbers.

    Attributes:
        matrix: MediaPipe's 4x4 facial transformation matrix, row-major (16 floats).
        nose_tip: landmark 1, normalised image coordinates (0..1).
        eye_outer_left: landmark 33, normalised image coordinates.
        eye_outer_right: landmark 263, normalised image coordinates.
        blendshapes: category name -> score (0..1), names read from the model at runtime.
        image_size: (width, height) of the analysed frame, in pixels.
    """

    matrix: tuple[float, ...]
    nose_tip: Point2
    eye_outer_left: Point2
    eye_outer_right: Point2
    blendshapes: dict[str, float]
    image_size: tuple[int, int]


@dataclass(frozen=True, slots=True)
class FeatureFrame:
    """Everything the interaction engine needs from one camera frame.

    Angles are in degrees with the user's point of view: positive yaw means the head turned
    toward the user's right, positive pitch means looking up. `t` is a monotonic timestamp
    in seconds (time of capture).
    """

    t: float
    face: bool
    yaw: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0
    nose_x: float = 0.0
    nose_y: float = 0.0
    face_size: float = 0.0
    brightness: float = 0.0
    blendshapes: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready dict, rounded so recordings stay small."""
        return {
            "t": round(self.t, 4),
            "face": self.face,
            "yaw": round(self.yaw, 3),
            "pitch": round(self.pitch, 3),
            "roll": round(self.roll, 3),
            "nose_x": round(self.nose_x, 4),
            "nose_y": round(self.nose_y, 4),
            "face_size": round(self.face_size, 4),
            "brightness": round(self.brightness, 1),
            "blendshapes": {k: round(v, 4) for k, v in self.blendshapes.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FeatureFrame:
        """Inverse of `to_dict`; missing optional fields take their defaults."""
        return cls(
            t=float(data["t"]),
            face=bool(data["face"]),
            yaw=float(data.get("yaw", 0.0)),
            pitch=float(data.get("pitch", 0.0)),
            roll=float(data.get("roll", 0.0)),
            nose_x=float(data.get("nose_x", 0.0)),
            nose_y=float(data.get("nose_y", 0.0)),
            face_size=float(data.get("face_size", 0.0)),
            brightness=float(data.get("brightness", 0.0)),
            blendshapes={str(k): float(v) for k, v in data.get("blendshapes", {}).items()},
        )
