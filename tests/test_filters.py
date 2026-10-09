import math
import random
import statistics

from nodwell.core.filters import (
    SMOOTHNESS_MAX_CUTOFF_HZ,
    SMOOTHNESS_MIN_CUTOFF_HZ,
    OneEuroFilter,
    smoothness_to_min_cutoff,
)

DT = 1 / 30


def test_first_sample_passes_through() -> None:
    f = OneEuroFilter(min_cutoff=1.0, beta=0.0)
    assert f(5.0, 0.0) == 5.0


def test_constant_input_stays_constant() -> None:
    f = OneEuroFilter(min_cutoff=1.0, beta=0.1)
    out = [f(3.0, i * DT) for i in range(100)]
    assert all(math.isclose(v, 3.0) for v in out)


def test_reduces_jitter() -> None:
    rng = random.Random(1)
    f = OneEuroFilter(min_cutoff=0.5, beta=0.0)
    noisy = [rng.gauss(0.0, 1.0) for _ in range(600)]
    smoothed = [f(v, i * DT) for i, v in enumerate(noisy)]
    assert statistics.pstdev(smoothed[100:]) < 0.3 * statistics.pstdev(noisy[100:])


def test_beta_reduces_lag_on_fast_moves() -> None:
    """With the same min_cutoff, a larger beta tracks a fast ramp more closely."""

    def lag(beta: float) -> float:
        f = OneEuroFilter(min_cutoff=0.5, beta=beta)
        out = 0.0
        for i in range(30):
            out = f(i * 2.0, i * DT)  # 60 units/s ramp
        return 29 * 2.0 - out

    assert lag(0.5) < 0.5 * lag(0.0)


def test_non_increasing_time_returns_previous_value() -> None:
    f = OneEuroFilter(min_cutoff=1.0, beta=0.0)
    f(0.0, 1.0)
    held = f(10.0, 1.1)
    assert f(99.0, 1.1) == held


def test_reset_forgets_history() -> None:
    f = OneEuroFilter(min_cutoff=0.1, beta=0.0)
    f(0.0, 0.0)
    f(0.0, DT)
    f.reset()
    assert f(50.0, 2 * DT) == 50.0


def test_smoothness_mapping_endpoints_and_monotonic() -> None:
    assert math.isclose(smoothness_to_min_cutoff(0.0), SMOOTHNESS_MAX_CUTOFF_HZ)
    assert math.isclose(smoothness_to_min_cutoff(1.0), SMOOTHNESS_MIN_CUTOFF_HZ)
    values = [smoothness_to_min_cutoff(s / 10) for s in range(11)]
    assert values == sorted(values, reverse=True)
    assert smoothness_to_min_cutoff(-1) == smoothness_to_min_cutoff(0)
