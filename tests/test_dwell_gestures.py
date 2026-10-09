import pytest

from nodwell.core.dwell import DwellDetector
from nodwell.core.gestures import HoldGesture

# ---------------------------------------------------------------- dwell


def test_dwell_fires_after_time_within_radius() -> None:
    d = DwellDetector(dwell_s=1.0, radius=10)
    assert not d.update(100, 100, 0.0).fired
    mid = d.update(105, 100, 0.5)
    assert mid.progress == pytest.approx(0.5) and not mid.fired
    assert d.update(103, 104, 1.0).fired


def test_leaving_radius_restarts() -> None:
    d = DwellDetector(dwell_s=1.0, radius=10)
    d.update(100, 100, 0.0)
    d.update(100, 100, 0.9)
    assert d.update(150, 100, 0.95).progress == 0.0
    assert not d.update(150, 100, 1.5).fired
    assert d.update(150, 100, 1.95).fired


def test_no_repeat_click_until_pointer_leaves() -> None:
    d = DwellDetector(dwell_s=1.0, radius=10)
    d.update(100, 100, 0.0)
    assert d.update(100, 100, 1.0).fired
    assert not any(d.update(100, 100, 1.0 + i * 0.1).fired for i in range(1, 40))
    d.update(200, 100, 5.0)  # leave
    assert d.update(200, 100, 6.0).fired


def test_reset_cancels_progress() -> None:
    d = DwellDetector(dwell_s=1.0, radius=10)
    d.update(100, 100, 0.0)
    d.update(100, 100, 0.9)
    d.reset()
    assert d.update(100, 100, 1.0).progress == 0.0
    assert not d.update(100, 100, 1.5).fired
    assert d.update(100, 100, 2.0).fired


# ---------------------------------------------------------------- hold gesture


def make_gesture() -> HoldGesture:
    return HoldGesture(on_threshold=0.5, off_threshold=0.3, hold_s=1.0, cooldown_s=2.0)


def test_hold_fires_after_hold_time() -> None:
    g = make_gesture()
    assert not g.update(0.6, 0.0).fired
    assert g.update(0.6, 0.5).progress == pytest.approx(0.5)
    assert g.update(0.6, 1.0).fired


def test_short_activation_does_not_fire() -> None:
    """A natural blink or a word: above threshold briefly, never long enough."""
    g = make_gesture()
    g.update(0.9, 0.0)
    g.update(0.9, 0.3)
    g.update(0.1, 0.4)
    assert not g.update(0.9, 1.1).fired


def test_hysteresis_keeps_hold_between_thresholds() -> None:
    g = make_gesture()
    g.update(0.6, 0.0)
    g.update(0.4, 0.5)  # below on, above off: still holding
    assert g.update(0.4, 1.0).fired


def test_below_off_threshold_breaks_hold() -> None:
    g = make_gesture()
    g.update(0.6, 0.0)
    g.update(0.2, 0.5)
    g.update(0.4, 0.6)  # below on threshold: does not restart
    assert not g.update(0.4, 1.2).fired


def test_latch_prevents_repeat_while_held() -> None:
    g = make_gesture()
    g.update(0.6, 0.0)
    assert g.update(0.6, 1.0).fired
    assert not any(g.update(0.9, 1.0 + i * 0.1).fired for i in range(1, 60))


def test_cooldown_blocks_new_hold() -> None:
    g = make_gesture()
    g.update(0.6, 0.0)
    assert g.update(0.6, 1.0).fired
    g.update(0.0, 1.1)  # release
    g.update(0.6, 1.5)  # within cooldown (until 3.0): ignored
    assert not g.update(0.6, 2.6).fired
    g.update(0.6, 3.0)  # cooldown over: hold starts now
    assert g.update(0.6, 4.0).fired


def test_off_above_on_rejected() -> None:
    with pytest.raises(ValueError):
        HoldGesture(on_threshold=0.3, off_threshold=0.5, hold_s=1.0, cooldown_s=0.0)
