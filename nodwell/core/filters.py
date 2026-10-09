"""One Euro filter (Casiez, Roussel & Vogel, CHI 2012) and the "Smoothness" slider mapping.

The One Euro filter is a low-pass filter whose cutoff frequency rises with the signal's
speed. Holding still gives a low cutoff (heavy smoothing, no jitter); moving fast raises the
cutoff (little smoothing, little lag). Two parameters matter:

- `min_cutoff` (Hz): smoothing when still. Lower = smoother but laggier.
- `beta`: how quickly the cutoff rises with speed. Higher = less lag on fast moves.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def _alpha(cutoff_hz: float, dt: float) -> float:
    """Smoothing factor of a first-order low-pass filter with this cutoff, sampled every dt.

    tau = 1 / (2*pi*cutoff) is the filter's time constant; alpha = dt / (dt + tau) is the
    weight given to the new sample.
    """
    tau = 1.0 / (2.0 * math.pi * cutoff_hz)
    return 1.0 / (1.0 + tau / dt)


class OneEuroFilter:
    """Adaptive low-pass filter for one scalar signal sampled at irregular times."""

    def __init__(self, min_cutoff: float, beta: float, d_cutoff: float = 1.0) -> None:
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self._x: float | None = None
        self._dx = 0.0
        self._t = 0.0

    def reset(self) -> None:
        """Forget history; the next sample passes through unchanged."""
        self._x = None
        self._dx = 0.0

    def __call__(self, x: float, t: float) -> float:
        """Filter sample `x` taken at time `t` (seconds) and return the smoothed value."""
        if self._x is None:
            self._x, self._t = x, t
            return x
        dt = t - self._t
        if dt <= 0.0:
            return self._x
        # 1. Estimate the speed, itself low-passed so noise doesn't open the filter.
        raw_dx = (x - self._x) / dt
        self._dx += _alpha(self.d_cutoff, dt) * (raw_dx - self._dx)
        # 2. Cutoff grows linearly with speed.
        cutoff = self.min_cutoff + self.beta * abs(self._dx)
        # 3. Low-pass the value with that cutoff.
        self._x += _alpha(cutoff, dt) * (x - self._x)
        self._t = t
        return self._x


@dataclass(frozen=True, slots=True)
class OneEuroParams:
    """Filter parameters, as derived from the user-facing settings."""

    min_cutoff: float
    beta: float
    d_cutoff: float


# Smoothness 0 -> 3 Hz (light smoothing), 1 -> 0.1 Hz (very heavy, for tremor).
SMOOTHNESS_MAX_CUTOFF_HZ = 3.0
SMOOTHNESS_MIN_CUTOFF_HZ = 0.1


def smoothness_to_min_cutoff(smoothness: float) -> float:
    """Map the 0..1 "Smoothness" slider to `min_cutoff` on a log scale.

    A log scale makes each slider step feel equally large: halving the cutoff roughly
    doubles the perceived smoothing.
    """
    s = min(max(smoothness, 0.0), 1.0)
    lo, hi = math.log(SMOOTHNESS_MIN_CUTOFF_HZ), math.log(SMOOTHNESS_MAX_CUTOFF_HZ)
    return math.exp(hi + s * (lo - hi))
