"""Dwell detection: holding the pointer still for a while produces a click."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DwellUpdate:
    """Result of one dwell update: progress 0..1 and whether a click fires now."""

    progress: float
    fired: bool


class DwellDetector:
    """Fires once when the pointer stays within `radius` of where it settled for `dwell_s`.

    The anchor is the point where the pointer settled, not a moving average, so a slow drift
    still counts as leaving once it exceeds the radius. After firing, the detector is
    disarmed until the pointer leaves the radius, so resting on a target never repeats the
    click.
    """

    def __init__(self, dwell_s: float, radius: float) -> None:
        self.dwell_s = dwell_s
        self.radius = radius
        self._anchor: tuple[float, float] | None = None
        self._start = 0.0
        self._armed = True

    def reset(self, *, armed: bool = True) -> None:
        """Cancel any dwell in progress."""
        self._anchor = None
        self._armed = armed

    def update(self, x: float, y: float, t: float) -> DwellUpdate:
        """Feed the pointer position at time `t` (seconds)."""
        if self._anchor is None or math.dist((x, y), self._anchor) > self.radius:
            if self._anchor is not None:
                self._armed = True  # left the old spot: allowed to dwell again
            self._anchor, self._start = (x, y), t
            return DwellUpdate(0.0, False)
        if not self._armed:
            return DwellUpdate(0.0, False)
        progress = (t - self._start) / self.dwell_s
        if progress >= 1.0:
            self._armed = False
            return DwellUpdate(1.0, True)
        return DwellUpdate(progress, False)
