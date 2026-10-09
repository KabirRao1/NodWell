"""Regenerate the synthetic FeatureFrame fixtures: `uv run python tests/fixtures/make_fixtures.py`.

These are scripted, not recorded from a camera. Real recordings (made with `--record`)
join them as M1 manual testing produces them.
"""

from __future__ import annotations

from pathlib import Path

from nodwell.core.frame import FeatureFrame
from nodwell.core.recording import Recorder

HERE = Path(__file__).resolve().parent
FPS = 30


def face(
    t: float, yaw: float = 0.0, pitch: float = 0.0, roll: float = 0.0, brow: float = 0.02
) -> FeatureFrame:
    return FeatureFrame(
        t=t,
        face=True,
        yaw=yaw,
        pitch=pitch,
        roll=roll,
        face_size=0.15,
        brightness=120.0,
        blendshapes={"browInnerUp": brow, "jawOpen": 0.01},
    )


class Script:
    """Builds a frame list from (seconds, frame maker, pose) steps at FPS."""

    def __init__(self) -> None:
        self.frames: list[FeatureFrame] = []
        self.t = 0.0

    def add(self, seconds: float, make: object = face, **kw: float) -> None:
        for _ in range(round(seconds * FPS)):
            self.frames.append(make(self.t, **kw))  # type: ignore[operator]
            self.t += 1 / FPS


def dwell_then_face_lost() -> list[FeatureFrame]:
    """Start (2 s), turn right and dwell (2 s), face lost (6 s), face back (2 s)."""
    s = Script()
    s.add(2.0)
    s.add(2.0, yaw=6.0)
    s.add(6.0, lambda t: FeatureFrame(t=t, face=False, brightness=120.0))
    s.add(2.0)
    return s.frames


def drag_then_tilt_right() -> list[FeatureFrame]:
    """With Drag chosen on the toolbar: dwell (grab), move right and dwell (drop), come
    back, then tilt the head right for 0.8 s (right click)."""
    s = Script()
    s.add(2.5)
    s.add(2.0, yaw=6.0)
    s.add(0.5)
    s.add(0.8, roll=15.0)
    s.add(0.6)
    return s.frames


def main() -> None:
    for name, frames in (
        ("dwell_then_face_lost", dwell_then_face_lost()),
        ("drag_then_tilt_right", drag_then_tilt_right()),
    ):
        path = HERE / f"{name}.jsonl"
        path.unlink(missing_ok=True)
        with Recorder(path) as rec:
            for frame in frames:
                rec.write(frame)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
