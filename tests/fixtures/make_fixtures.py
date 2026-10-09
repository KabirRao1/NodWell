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


def face(t: float, yaw: float = 0.0, pitch: float = 0.0, brow: float = 0.02) -> FeatureFrame:
    return FeatureFrame(
        t=t,
        face=True,
        yaw=yaw,
        pitch=pitch,
        face_size=0.15,
        brightness=120.0,
        blendshapes={"browInnerUp": brow, "jawOpen": 0.01},
    )


def dwell_then_face_lost() -> list[FeatureFrame]:
    """Start (2 s), turn right and dwell (2 s), face lost (6 s), face back (2 s)."""
    frames: list[FeatureFrame] = []
    t = 0.0

    def add(seconds: float, make: object, **kw: float) -> None:
        nonlocal t
        for _ in range(round(seconds * FPS)):
            frames.append(make(t, **kw))  # type: ignore[operator]
            t += 1 / FPS

    add(2.0, face)
    add(2.0, face, yaw=6.0)
    add(6.0, lambda t: FeatureFrame(t=t, face=False, brightness=120.0))
    add(2.0, face)
    return frames


def main() -> None:
    path = HERE / "dwell_then_face_lost.jsonl"
    path.unlink(missing_ok=True)
    with Recorder(path) as rec:
        for frame in dwell_then_face_lost():
            rec.write(frame)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
