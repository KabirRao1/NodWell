"""Facial gesture detection with hysteresis, hold time, and cooldown.

M1 uses one gesture (the pause/resume hold). The full gesture-to-action mapping is M4.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True, slots=True)
class GestureUpdate:
    """Result of one gesture update: hold progress 0..1 and whether it fires now."""

    progress: float
    fired: bool


class _State(Enum):
    IDLE = "idle"
    HOLDING = "holding"
    LATCHED = "latched"  # fired; waiting for the score to fall below the off threshold


class HoldGesture:
    """Fires when a blendshape score stays above a threshold for `hold_s` seconds.

    - Hysteresis: the hold starts at `on_threshold` but only breaks below `off_threshold`
      (lower), so a score hovering around one value doesn't flicker on and off.
    - Hold time: short movements (a natural blink, a word) never complete the hold.
    - Latch: after firing, the score must drop below `off_threshold` before it can fire
      again, so holding the gesture longer doesn't repeat it.
    - Cooldown: no new hold may start until `cooldown_s` after the last firing.
    """

    def __init__(
        self, on_threshold: float, off_threshold: float, hold_s: float, cooldown_s: float
    ) -> None:
        if off_threshold > on_threshold:
            raise ValueError("off_threshold must not exceed on_threshold")
        self.on_threshold = on_threshold
        self.off_threshold = off_threshold
        self.hold_s = hold_s
        self.cooldown_s = cooldown_s
        self._state = _State.IDLE
        self._start = 0.0
        self._last_fire = -float("inf")

    def reset(self) -> None:
        """Cancel a hold in progress (e.g. the face was lost). The cooldown is kept."""
        self._state = _State.IDLE

    def update(self, value: float, t: float) -> GestureUpdate:
        """Feed the current score at time `t` (seconds)."""
        if self._state is _State.LATCHED:
            if value < self.off_threshold:
                self._state = _State.IDLE
            return GestureUpdate(0.0, False)

        if self._state is _State.HOLDING:
            if value < self.off_threshold:
                self._state = _State.IDLE
                return GestureUpdate(0.0, False)
            progress = (t - self._start) / self.hold_s
            if progress >= 1.0:
                self._state = _State.LATCHED
                self._last_fire = t
                return GestureUpdate(1.0, True)
            return GestureUpdate(progress, False)

        if value >= self.on_threshold and t - self._last_fire >= self.cooldown_s:
            self._state, self._start = _State.HOLDING, t
        return GestureUpdate(0.0, False)
