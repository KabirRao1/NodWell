import math

import pytest

from nodwell.core.features import Quality, extract, eye_distance, head_pose, quality
from nodwell.core.frame import FeatureFrame, RawFace


def rotation_y(deg: float) -> list[list[float]]:
    a = math.radians(deg)
    return [[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]]


def rotation_x(deg: float) -> list[list[float]]:
    a = math.radians(deg)
    return [[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]]


def rotation_z(deg: float) -> list[list[float]]:
    a = math.radians(deg)
    return [[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]]


def to_matrix4(r: list[list[float]]) -> tuple[float, ...]:
    """Row-major 4x4 with a translation, as MediaPipe returns (face ~50 cm in front)."""
    return (*r[0], 1.0, *r[1], 2.0, *r[2], -50.0, 0.0, 0.0, 0.0, 1.0)


def test_identity_is_zero_pose() -> None:
    assert head_pose(to_matrix4(rotation_y(0))) == pytest.approx((0, 0, 0))


def test_yaw_sign_turning_toward_users_right_is_positive() -> None:
    # Turning toward the user's right points the nose to the camera's left (-x),
    # which is a negative rotation about camera +y.
    yaw, pitch, roll = head_pose(to_matrix4(rotation_y(-20)))
    assert yaw == pytest.approx(20)
    assert pitch == pytest.approx(0, abs=1e-9)
    assert roll == pytest.approx(0, abs=1e-9)


def test_pitch_up_is_positive() -> None:
    # Looking up tilts the nose toward +y: a negative rotation about +x.
    yaw, pitch, _ = head_pose(to_matrix4(rotation_x(-15)))
    assert pitch == pytest.approx(15)
    assert yaw == pytest.approx(0, abs=1e-9)


def test_roll() -> None:
    _, _, roll = head_pose(to_matrix4(rotation_z(10)))
    assert roll == pytest.approx(10)


def test_combined_yaw_pitch_recovered() -> None:
    ry, rx = rotation_y(-12), rotation_x(-8)
    combined = [[sum(ry[i][k] * rx[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    yaw, pitch, _ = head_pose(to_matrix4(combined))
    assert yaw == pytest.approx(12, abs=0.5)
    assert pitch == pytest.approx(8, abs=0.5)


def make_face(**overrides: object) -> RawFace:
    base: dict[str, object] = {
        "matrix": to_matrix4(rotation_y(0)),
        "nose_tip": (0.5, 0.5),
        "eye_outer_left": (0.42, 0.45),
        "eye_outer_right": (0.58, 0.45),
        "blendshapes": {"jawOpen": 0.1},
        "image_size": (640, 480),
    }
    base.update(overrides)
    return RawFace(**base)  # type: ignore[arg-type]


def test_eye_distance_accounts_for_aspect() -> None:
    assert eye_distance(make_face()) == pytest.approx(0.16)
    vertical = make_face(eye_outer_left=(0.5, 0.3), eye_outer_right=(0.5, 0.5))
    assert eye_distance(vertical) == pytest.approx(0.2 * 480 / 640)


def test_extract_with_and_without_face() -> None:
    frame = extract(make_face(), t=1.5, brightness=120)
    assert frame.face and frame.t == 1.5 and frame.blendshapes == {"jawOpen": 0.1}
    assert frame.face_size == pytest.approx(0.16)
    empty = extract(None, t=2.0, brightness=10)
    assert not empty.face and empty.brightness == 10


def test_quality() -> None:
    assert quality(extract(make_face(), 0, 120)) is Quality.GOOD
    assert quality(extract(None, 0, 120)) is Quality.NO_FACE
    assert quality(extract(None, 0, 5)) is Quality.LOW_LIGHT
    far = make_face(eye_outer_left=(0.49, 0.45), eye_outer_right=(0.51, 0.45))
    assert quality(extract(far, 0, 120)) is Quality.TOO_FAR
    close = make_face(eye_outer_left=(0.1, 0.45), eye_outer_right=(0.9, 0.45))
    assert quality(extract(close, 0, 120)) is Quality.TOO_CLOSE
    assert quality(extract(make_face(), 0, 20)) is Quality.LOW_LIGHT


def test_feature_frame_roundtrip() -> None:
    frame = extract(make_face(), t=1.23456, brightness=99.94)
    again = FeatureFrame.from_dict(frame.to_dict())
    assert again.t == pytest.approx(frame.t, abs=1e-4)
    assert again.face_size == pytest.approx(frame.face_size, abs=1e-4)
    assert again.blendshapes == frame.blendshapes
