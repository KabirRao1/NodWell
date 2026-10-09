import pytest

from nodwell.core.pointer import (
    AxisConfig,
    ScreenRect,
    absolute_position,
    relative_step,
    relative_velocity,
)

SCREEN = ScreenRect(0, 0, 2000, 1000)
X = AxisConfig(range_deg=10.0)
Y = AxisConfig(range_deg=5.0)


def test_neutral_is_center() -> None:
    assert absolute_position(0, 0, X, Y, SCREEN) == (1000, 500)


def test_full_range_reaches_edges_and_clamps() -> None:
    assert absolute_position(10, 0, X, Y, SCREEN) == (1999, 500)  # right edge (last pixel)
    assert absolute_position(-30, 0, X, Y, SCREEN) == (0, 500)  # clamped left
    assert absolute_position(0, 5, X, Y, SCREEN) == (1000, 0)  # looking up -> top
    assert absolute_position(0, -5, X, Y, SCREEN) == (1000, 999)


def test_half_range_is_halfway() -> None:
    assert absolute_position(5, -2.5, X, Y, SCREEN) == (1500, 750)


def test_invert() -> None:
    inv = AxisConfig(range_deg=10.0, invert=True)
    assert absolute_position(5, 0, inv, Y, SCREEN) == (500, 500)


def test_screen_offset_respected() -> None:
    screen = ScreenRect(-2000, 100, 2000, 1000)
    assert absolute_position(0, 0, X, Y, screen) == (-1000, 600)


def test_dead_zone() -> None:
    axis = AxisConfig(range_deg=10.0, dead_zone_deg=2.0)
    assert relative_velocity(1.9, axis, 1000, 1.0) == 0.0
    assert relative_velocity(-1.9, axis, 1000, 1.0) == 0.0
    assert relative_velocity(6.0, axis, 1000, 1.0) == pytest.approx(500.0)
    assert relative_velocity(-6.0, axis, 1000, 1.0) == pytest.approx(-500.0)


def test_speed_saturates_at_range() -> None:
    axis = AxisConfig(range_deg=10.0, dead_zone_deg=2.0)
    assert relative_velocity(30.0, axis, 1000, 2.0) == pytest.approx(1000.0)


def test_acceleration_slows_small_offsets() -> None:
    axis = AxisConfig(range_deg=10.0)
    linear = relative_velocity(2.0, axis, 1000, 1.0)
    curved = relative_velocity(2.0, axis, 1000, 2.0)
    assert curved < linear
    assert curved == pytest.approx(1000 * 0.2**2)


def test_relative_step_moves_and_clamps() -> None:
    axis = AxisConfig(range_deg=10.0)
    x, y = relative_step((1000, 500), 10, 10, 0.1, axis, axis, 1000, 1.0, SCREEN)
    assert (x, y) == pytest.approx((1100, 400))  # right and up
    x, y = relative_step((1990, 5), 10, 10, 1.0, axis, axis, 1000, 1.0, SCREEN)
    assert (x, y) == (1999, 0)
