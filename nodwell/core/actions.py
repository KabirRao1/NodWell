"""Click types, mouse actions, gesture actions, and scroll-speed math."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class ClickType(StrEnum):
    """What the next dwell does (chosen on the click-type toolbar)."""

    LEFT = "left"
    RIGHT = "right"
    DOUBLE = "double"
    MIDDLE = "middle"
    DRAG = "drag"  # first dwell presses, next dwell releases
    SCROLL = "scroll"  # dwell anchors head-controlled scrolling


class Button(StrEnum):
    LEFT = "left"
    RIGHT = "right"
    MIDDLE = "middle"


@dataclass(frozen=True, slots=True)
class ClickAction:
    """One mouse-button action for the input backend."""

    kind: Literal["click", "press", "release"]
    button: Button = Button.LEFT
    count: int = 1  # clicks only: 2 = double click


LEFT_CLICK = ClickAction("click")
PRESS_LEFT = ClickAction("press")
RELEASE_LEFT = ClickAction("release")

SIMPLE_CLICKS: dict[ClickType, ClickAction] = {
    ClickType.LEFT: LEFT_CLICK,
    ClickType.RIGHT: ClickAction("click", Button.RIGHT),
    ClickType.DOUBLE: ClickAction("click", Button.LEFT, 2),
    ClickType.MIDDLE: ClickAction("click", Button.MIDDLE),
}


class GestureAction(StrEnum):
    """What a facial or head gesture does when it fires."""

    NONE = "none"
    LEFT_CLICK = "left_click"
    RIGHT_CLICK = "right_click"
    DOUBLE_CLICK = "double_click"
    MIDDLE_CLICK = "middle_click"
    DRAG_TOGGLE = "drag_toggle"
    SCROLL_TOGGLE = "scroll_toggle"
    PAUSE_TOGGLE = "pause_toggle"
    RECENTER = "recenter"


GESTURE_CLICKS: dict[GestureAction, ClickType] = {
    GestureAction.LEFT_CLICK: ClickType.LEFT,
    GestureAction.RIGHT_CLICK: ClickType.RIGHT,
    GestureAction.DOUBLE_CLICK: ClickType.DOUBLE,
    GestureAction.MIDDLE_CLICK: ClickType.MIDDLE,
}


def scroll_speed(
    offset_deg: float, dead_zone_deg: float, full_deg: float, max_speed: float
) -> float:
    """Scroll speed (wheel notches/s, signed) for a head-pitch offset from the scroll anchor.

    Zero inside the dead zone; then rises with the square of the normalised offset, so
    small nods scroll slowly enough to read while a big tilt scrolls fast. Positive offset
    (looking up) gives positive speed, which is "scroll up" for a mouse wheel.
    """
    magnitude = abs(offset_deg) - dead_zone_deg
    if magnitude <= 0.0:
        return 0.0
    n = min(magnitude / max(full_deg - dead_zone_deg, 1e-6), 1.0)
    return math.copysign(max_speed * n * n, offset_deg)
