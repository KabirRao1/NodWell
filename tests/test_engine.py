"""Scenario tests for the interaction engine, driven by synthetic FeatureFrames."""

from collections.abc import Iterator

import pytest

from nodwell.core.engine import (
    ApplySettings,
    EngineOutput,
    InteractionEngine,
    Mode,
    Pause,
    PauseReason,
    Recenter,
    Resume,
)
from nodwell.core.frame import FeatureFrame
from nodwell.core.pointer import ScreenRect
from nodwell.core.settings import Settings

FPS = 30
DT = 1 / FPS
SCREEN = ScreenRect(0, 0, 3000, 2000)
BROW = "browInnerUp"


def face(t: float, yaw: float = 0.0, pitch: float = 0.0, brow: float = 0.0) -> FeatureFrame:
    return FeatureFrame(
        t=t,
        face=True,
        yaw=yaw,
        pitch=pitch,
        face_size=0.15,
        brightness=120,
        blendshapes={BROW: brow, "jawOpen": 0.0},
    )


def no_face(t: float) -> FeatureFrame:
    return FeatureFrame(t=t, face=False, brightness=120)


def times(start: float, seconds: float) -> Iterator[float]:
    n = round(seconds * FPS)
    return (start + i * DT for i in range(n))


class Harness:
    """Feeds frames and plays the OS: the cursor goes wherever the engine moved it."""

    def __init__(self, settings: Settings | None = None) -> None:
        # Smoothness 0 keeps filter lag small so positions are easy to reason about.
        s = settings or Settings()
        s = s.model_copy(update={"pointer": s.pointer.model_copy(update={"smoothness": 0.0})})
        self.engine = InteractionEngine(s, SCREEN)
        self.cursor: tuple[float, float] | None = None
        self.clicks: list[tuple[float, float]] = []
        self.moves = 0
        self.t = 0.0
        self.last: EngineOutput | None = None

    def run(self, seconds: float, make=face, **kw: float) -> EngineOutput:
        out = None
        for t in times(self.t, seconds):
            out = self.engine.update(make(t, **kw), self.cursor)
            if out.move_to is not None:
                self.cursor = out.move_to
                self.moves += 1
            if out.click_at is not None:
                self.clicks.append(out.click_at)
        self.t += seconds
        assert out is not None
        self.last = out
        return out

    def started(self) -> "Harness":
        self.run(1.2)
        assert self.engine.mode is Mode.ACTIVE
        return self


def test_starts_only_after_stable_face() -> None:
    h = Harness()
    h.run(0.5)
    assert h.engine.mode is Mode.STARTING
    h.run(0.2, make=no_face)
    h.run(0.9)
    assert h.engine.mode is Mode.STARTING  # stability timer restarted after the dropout
    h.run(0.3)
    assert h.engine.mode is Mode.ACTIVE


def test_no_moves_or_clicks_while_starting() -> None:
    h = Harness()
    h.run(0.9)
    assert h.moves == 0 and h.clicks == []


def test_startup_recenters_on_current_pose() -> None:
    h = Harness()
    h.run(1.5, yaw=7.0, pitch=-3.0)  # user sits slightly turned
    assert h.cursor == pytest.approx(SCREEN.center, abs=2)


def test_absolute_mode_follows_head() -> None:
    h = Harness().started()
    h.run(1.0, yaw=7.5)  # half of the 15 degree range, toward the user's right
    assert h.cursor is not None
    assert h.cursor[0] == pytest.approx(1500 + 750, abs=15)
    h.run(1.0, pitch=5.0)  # half of 10 degrees up
    assert h.cursor[1] == pytest.approx(1000 - 500, abs=15)


def test_dwell_clicks_once_then_requires_leaving() -> None:
    h = Harness().started()
    h.run(3.0)  # hold still for 3 s
    assert len(h.clicks) == 1
    h.run(0.5, yaw=10.0)  # move away
    h.run(1.5, yaw=10.0)  # dwell at the new spot
    assert len(h.clicks) == 2


def test_dwell_disabled_never_clicks() -> None:
    s = Settings()
    s = s.model_copy(update={"dwell": s.dwell.model_copy(update={"enabled": False})})
    h = Harness(s).started()
    h.run(3.0)
    assert h.clicks == []


def test_face_lost_freezes_and_auto_pauses() -> None:
    h = Harness().started()
    h.run(0.5, yaw=5.0)
    frozen = h.cursor
    moves_before = h.moves
    out = h.run(4.0, make=no_face)
    assert h.moves == moves_before and h.cursor == frozen
    assert out.move_to is None and out.click_at is None
    assert h.engine.mode is Mode.ACTIVE  # not yet: default auto-pause is 5 s
    h.run(1.1, make=no_face)
    assert h.engine.mode is Mode.PAUSED
    assert h.engine.pause_reason is PauseReason.FACE_LOST


def test_face_back_does_not_auto_resume() -> None:
    h = Harness().started()
    h.run(6.0, make=no_face)
    h.run(3.0)
    assert h.engine.mode is Mode.PAUSED
    assert h.clicks == []


def test_short_face_loss_cancels_dwell() -> None:
    h = Harness().started()
    h.run(0.6)  # dwell 60 % done
    h.run(0.2, make=no_face)
    h.run(0.6)  # 0.3 s grace, then dwell restarts: not enough to click
    assert h.clicks == []


def test_pause_command_stops_everything() -> None:
    h = Harness().started()
    h.engine.handle(Pause())
    moves = h.moves
    h.run(3.0, yaw=10.0)
    assert h.moves == moves and h.clicks == []
    assert h.engine.pause_reason is PauseReason.USER


def test_resume_recenters() -> None:
    h = Harness().started()
    h.engine.handle(Pause())
    h.run(1.0, yaw=8.0)  # user rests with head turned
    h.engine.handle(Resume())
    h.run(0.5, yaw=8.0)
    assert h.engine.mode is Mode.ACTIVE
    assert h.cursor == pytest.approx(SCREEN.center, abs=2)


def test_recenter_command() -> None:
    h = Harness().started()
    h.run(1.0, yaw=6.0)
    assert h.cursor is not None and h.cursor[0] > 2000
    h.engine.handle(Recenter())
    h.run(0.5, yaw=6.0)
    assert h.cursor == pytest.approx(SCREEN.center, abs=2)


def test_gesture_hold_pauses_and_resumes() -> None:
    h = Harness().started()
    h.run(1.0, brow=0.8)  # 1 s: not enough (hold is 2 s)
    assert h.engine.mode is Mode.ACTIVE
    h.run(1.1, brow=0.8)
    assert h.engine.mode is Mode.PAUSED
    assert h.engine.pause_reason is PauseReason.GESTURE
    h.run(3.0, brow=0.8)  # still holding: latched, no toggle back
    assert h.engine.mode is Mode.PAUSED
    h.run(0.5)  # release
    h.run(2.1, brow=0.8)
    assert h.engine.mode is Mode.ACTIVE


def test_gesture_in_progress_suppresses_dwell() -> None:
    h = Harness().started()
    h.run(1.9, brow=0.8)  # still head, brows up: would dwell-click if not suppressed
    assert h.clicks == []


def test_brief_brow_raises_do_nothing() -> None:
    h = Harness().started()
    for _ in range(5):
        h.run(0.4, brow=0.9, yaw=float(_ * 3))
        h.run(0.4, yaw=float(_ * 3))
    assert h.engine.mode is Mode.ACTIVE


def test_gesture_availability_reported() -> None:
    h = Harness()
    out = h.run(0.1)
    assert out.status.gesture_available is True
    s = Settings()
    s = s.model_copy(
        update={"pause_gesture": s.pause_gesture.model_copy(update={"blendshape": "notReal"})}
    )
    h2 = Harness(s)
    out = h2.run(0.1)
    assert out.status.gesture_available is False


def test_manual_override_yields_to_real_mouse() -> None:
    h = Harness().started()
    h.run(0.5, yaw=3.0)
    h.cursor = (100.0, 100.0)  # a caregiver grabs the mouse
    out = h.run(0.5, yaw=3.0)
    assert out.status.manual_override
    assert h.cursor == (100.0, 100.0)  # engine did not fight the person
    h.run(1.5, yaw=3.0)  # override (1.5 s) expires; head control returns
    assert h.cursor != (100.0, 100.0)


@pytest.mark.parametrize(("min_interval", "lo", "hi"), [(0.1, 10, 10), (2.0, 3, 4)])
def test_click_rate_limited(min_interval: float, lo: int, hi: int) -> None:
    s = Settings()
    s = s.model_copy(
        update={
            "dwell": s.dwell.model_copy(update={"dwell_s": 0.2}),
            "safety": s.safety.model_copy(update={"min_click_interval_s": min_interval}),
        }
    )
    h = Harness(s).started()
    # Hop between two spots every 0.6 s; each stop is long enough to settle and dwell.
    for i in range(10):
        h.run(0.6, yaw=8.0 if i % 2 else -8.0)
    # Without a meaningful limit every hop clicks; with 2 s, at most one per 2 s of 6 s.
    assert lo <= len(h.clicks) <= hi


def test_relative_mode_moves_with_offset_and_stops_in_dead_zone() -> None:
    s = Settings()
    s = s.model_copy(update={"pointer": s.pointer.model_copy(update={"mode": "relative"})})
    h = Harness(s).started()
    start = h.cursor
    h.run(1.0, yaw=1.0)  # inside the 2 degree dead zone
    assert h.cursor == pytest.approx(start, abs=1)
    h.run(0.5, yaw=10.0)
    assert h.cursor is not None and start is not None and h.cursor[0] > start[0] + 200


def test_apply_settings_switches_mode_live() -> None:
    h = Harness().started()
    s = h.engine.settings
    relative = s.model_copy(update={"pointer": s.pointer.model_copy(update={"mode": "relative"})})
    h.engine.handle(ApplySettings(relative))
    h.run(0.5, yaw=10.0)
    assert h.engine.settings.pointer.mode == "relative"


def test_drift_suggestion() -> None:
    h = Harness().started()
    out = h.run(5.0, yaw=0.5)
    assert not out.status.drift_suggested
    out = h.run(90.0, yaw=9.0)
    assert out.status.drift_suggested
    h.engine.handle(Recenter())
    out = h.run(1.0, yaw=9.0)
    assert not out.status.drift_suggested
