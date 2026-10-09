"""Map head pose to cursor position.

Inputs are head angles relative to the user's neutral pose, in degrees (positive yaw =
turned right, positive pitch = looking up). Outputs are screen coordinates in physical
pixels (DECISIONS.md D12); screen y grows downward, so looking up decreases y.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ScreenRect:
    """The area the pointer may move in, in physical pixels."""

    left: float
    top: float
    width: float
    height: float

    @property
    def center(self) -> tuple[float, float]:
        return (self.left + self.width / 2, self.top + self.height / 2)

    def clamp(self, x: float, y: float) -> tuple[float, float]:
        """Keep a point inside the rectangle (the last pixel row/column included)."""
        return (
            min(max(x, self.left), self.left + self.width - 1),
            min(max(y, self.top), self.top + self.height - 1),
        )


@dataclass(frozen=True, slots=True)
class AxisConfig:
    """Per-axis pointer tuning.

    Attributes:
        range_deg: head angle that reaches the screen edge (absolute) or full speed (relative).
        invert: flip the direction of this axis.
        dead_zone_deg: relative mode only; offsets smaller than this don't move the cursor.
    """

    range_deg: float
    invert: bool = False
    dead_zone_deg: float = 0.0


def absolute_position(
    yaw: float, pitch: float, x_axis: AxisConfig, y_axis: AxisConfig, screen: ScreenRect
) -> tuple[float, float]:
    """Absolute mode: head pose maps straight to a screen position.

    Neutral pose is the screen centre; +/- range_deg reaches the edges. Beyond that the
    cursor is clamped to the edge.
    """
    nx = _clamp_unit(yaw / x_axis.range_deg) * (-1 if x_axis.invert else 1)
    ny = _clamp_unit(pitch / y_axis.range_deg) * (-1 if y_axis.invert else 1)
    cx, cy = screen.center
    return screen.clamp(cx + nx * screen.width / 2, cy - ny * screen.height / 2)


def relative_velocity(offset_deg: float, axis: AxisConfig, max_speed: float, accel: float) -> float:
    """Relative (joystick) mode: speed along one axis, in px/s, for a head offset.

    Offsets inside the dead zone give 0. Beyond it, the remaining offset is normalised to
    0..1 over (range - dead zone) and raised to `accel`: accel=1 is linear, larger values
    make small offsets very slow (precise) while large offsets still reach `max_speed`.
    """
    magnitude = abs(offset_deg) - axis.dead_zone_deg
    if magnitude <= 0.0:
        return 0.0
    span = max(axis.range_deg - axis.dead_zone_deg, 1e-6)
    speed = max_speed * math.pow(min(magnitude / span, 1.0), accel)
    sign = math.copysign(1.0, offset_deg) * (-1 if axis.invert else 1)
    return sign * speed


def relative_step(
    position: tuple[float, float],
    yaw: float,
    pitch: float,
    dt: float,
    x_axis: AxisConfig,
    y_axis: AxisConfig,
    max_speed: float,
    accel: float,
    screen: ScreenRect,
) -> tuple[float, float]:
    """Advance the cursor by one frame of relative-mode motion."""
    vx = relative_velocity(yaw, x_axis, max_speed, accel)
    vy = relative_velocity(pitch, y_axis, max_speed, accel)
    x, y = position
    return screen.clamp(x + vx * dt, y - vy * dt)


def _clamp_unit(v: float) -> float:
    return min(max(v, -1.0), 1.0)
