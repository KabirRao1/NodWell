"""Scenario tests for the interaction engine, driven by synthetic FeatureFrames."""

from collections.abc import Callable, Iterator

import pytest

from nodwell.core.actions import Button, ClickAction, ClickType, GestureAction
from nodwell.core.engine import (
    ApplySettings,
    EngineOutput,
    InteractionEngine,
    Mode,
    Pause,
    PauseReason,
    Recenter,
    Resume,
    SetClickType,
    SetOwnUi,
)
from nodwell.core.frame import FeatureFrame
from nodwell.core.pointer import ScreenRect
from nodwell.core.settings import Settings

FPS = 30
DT = 1 / FPS
SCREEN = ScreenRect(0, 0, 3000, 2000)
CENTER = SCREEN.center
RIGHT = ClickAction("click", Button.RIGHT)
DOUBLE = ClickAction("click", Button.LEFT, 2)
LEFT = ClickAction("click")
PRESS = ClickAction("press")
RELEASE = ClickAction("release")


def face(
    t: float,
    yaw: float = 0.0,
    pitch: float = 0.0,
    roll: float = 0.0,
    brow: float = 0.0,
    jaw: float = 0.0,
) -> FeatureFrame:
    return FeatureFrame(
        t=t,
        face=True,
        yaw=yaw,
        pitch=pitch,
        roll=roll,
        face_size=0.15,
        brightness=120,
        blendshapes={
            "browInnerUp": brow,
            "jawOpen": jaw,
            "mouthSmileLeft": 0.0,
            "mouthSmileRight": 0.0,
        },
    )


def no_face(t: float) -> FeatureFrame:
    return FeatureFrame(t=t, face=False, brightness=120)


def times(start: float, seconds: float) -> Iterator[float]:
    n = round(seconds * FPS)
    return (start + i * DT for i in range(n))


def with_updates(settings: Settings, **sections: dict[str, object]) -> Settings:
    """Copy settings with some fields of some sections replaced."""
    return settings.model_copy(
        update={
            name: getattr(settings, name).model_copy(update=fields)
            for name, fields in sections.items()
        }
    )


def with_binding(settings: Settings, binding_id: str, **fields: object) -> Settings:
    bindings = tuple(
        b.model_copy(update=fields) if b.id == binding_id else b for b in settings.gestures.bindings
    )
    return with_updates(settings, gestures={"bindings": bindings})


class Harness:
    """Feeds frames and collects everything the engine asks the OS to do."""

    def __init__(self, settings: Settings | None = None) -> None:
        # Smoothness 0 keeps filter lag small so positions are easy to reason about.
        s = with_updates(settings or Settings(), pointer={"smoothness": 0.0})
        self.engine = InteractionEngine(s, SCREEN)
        self.cursor: tuple[float, float] | None = None
        self.clicks: list[tuple[ClickAction, tuple[float, float] | None]] = []
        self.scrolled = 0.0
        self.releases = 0
        self.moves = 0
        self.t = 0.0

    def run(
        self,
        seconds: float,
        make: Callable[..., FeatureFrame] = face,
        manual: tuple[float, float] | None = None,
        **kw: float,
    ) -> EngineOutput:
        out = None
        for t in times(self.t, seconds):
            out = self.engine.update(make(t, **kw), manual)
            manual = None
            if out.move_to is not None:
                self.cursor = out.move_to
                self.moves += 1
            for c in out.clicks:
                self.clicks.append((c, out.click_at))
            if out.scroll is not None:
                self.scrolled += out.scroll[1]
            self.releases += out.release_all
        self.t += seconds
        assert out is not None
        return out

    @property
    def actions(self) -> list[ClickAction]:
        return [c for c, _ in self.clicks]

    def started(self) -> "Harness":
        self.run(1.2)
        assert self.engine.mode is Mode.ACTIVE
        return self


# ---------------------------------------------------------------- start-up and pointer


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
    assert h.cursor == pytest.approx(CENTER, abs=2)


def test_absolute_mode_follows_head() -> None:
    h = Harness().started()
    h.run(1.0, yaw=7.5)  # half of the 15 degree range, toward the user's right
    assert h.cursor is not None
    assert h.cursor[0] == pytest.approx(1500 + 750, abs=15)
    h.run(1.0, pitch=5.0)  # half of 10 degrees up
    assert h.cursor[1] == pytest.approx(1000 - 500, abs=15)


def test_relative_mode_moves_with_offset_and_stops_in_dead_zone() -> None:
    h = Harness(with_updates(Settings(), pointer={"mode": "relative"})).started()
    start = h.cursor
    h.run(1.0, yaw=1.0)  # inside the 2 degree dead zone
    assert h.cursor == pytest.approx(start, abs=1)
    h.run(0.5, yaw=10.0)
    assert h.cursor is not None and start is not None and h.cursor[0] > start[0] + 200


def test_apply_settings_switches_mode_live() -> None:
    h = Harness().started()
    h.engine.handle(ApplySettings(with_updates(h.engine.settings, pointer={"mode": "relative"})))
    h.run(0.5, yaw=10.0)
    assert h.engine.settings.pointer.mode == "relative"


# ---------------------------------------------------------------- dwell and safety


def test_dwell_clicks_once_then_requires_leaving() -> None:
    h = Harness().started()
    h.run(3.0)  # hold still for 3 s
    assert h.actions == [LEFT]
    h.run(0.5, yaw=10.0)  # move away
    h.run(1.5, yaw=10.0)  # dwell at the new spot
    assert h.actions == [LEFT, LEFT]


def test_dwell_disabled_never_clicks() -> None:
    h = Harness(with_updates(Settings(), dwell={"enabled": False})).started()
    h.run(3.0)
    assert h.clicks == []


def test_face_lost_freezes_and_auto_pauses() -> None:
    h = Harness().started()
    h.run(0.5, yaw=5.0)
    frozen, moves_before = h.cursor, h.moves
    out = h.run(4.0, make=no_face)
    assert h.moves == moves_before and h.cursor == frozen
    assert out.move_to is None and out.clicks == ()
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
    assert h.cursor == pytest.approx(CENTER, abs=2)


def test_recenter_command() -> None:
    h = Harness().started()
    h.run(1.0, yaw=6.0)
    assert h.cursor is not None and h.cursor[0] > 2000
    h.engine.handle(Recenter())
    h.run(0.5, yaw=6.0)
    assert h.cursor == pytest.approx(CENTER, abs=2)


def test_manual_override_yields_to_real_mouse() -> None:
    h = Harness().started()
    h.run(0.5, yaw=3.0)
    out = h.run(0.5, manual=(100.0, 100.0), yaw=3.0)  # a caregiver grabs the mouse
    assert out.status.manual_override
    assert out.move_to is None  # the engine does not fight the person
    h.run(1.5, yaw=3.0)  # override (1.5 s) expires; head control returns
    assert h.cursor is not None and h.cursor[0] > 1500


@pytest.mark.parametrize(("min_interval", "lo", "hi"), [(0.1, 10, 10), (2.0, 3, 4)])
def test_click_rate_limited(min_interval: float, lo: int, hi: int) -> None:
    s = with_updates(
        Settings(), dwell={"dwell_s": 0.2}, safety={"min_click_interval_s": min_interval}
    )
    h = Harness(s).started()
    # Hop between two spots every 0.6 s; each stop is long enough to settle and dwell.
    for i in range(10):
        h.run(0.6, yaw=8.0 if i % 2 else -8.0)
    # Without a meaningful limit every hop clicks; with 2 s, at most one per 2 s of 6 s.
    assert lo <= len(h.clicks) <= hi


def test_drift_suggestion() -> None:
    h = Harness().started()
    out = h.run(5.0, yaw=0.5)
    assert not out.status.drift_suggested
    out = h.run(90.0, yaw=9.0)
    assert out.status.drift_suggested
    h.engine.handle(Recenter())
    out = h.run(1.0, yaw=9.0)
    assert not out.status.drift_suggested


# ---------------------------------------------------------------- click types (toolbar)


@pytest.mark.parametrize(
    ("click_type", "expected"), [(ClickType.RIGHT, RIGHT), (ClickType.DOUBLE, DOUBLE)]
)
def test_toolbar_click_type_applies_once(click_type: ClickType, expected: ClickAction) -> None:
    h = Harness().started()
    h.engine.handle(SetClickType(click_type))
    h.run(1.5)
    assert h.actions == [expected]
    assert h.engine.click_type is ClickType.LEFT  # one-shot: back to left
    h.run(0.5, yaw=8.0)
    h.run(1.5, yaw=8.0)
    assert h.actions == [expected, LEFT]


def test_sticky_click_type_stays() -> None:
    h = Harness(with_updates(Settings(), dwell={"sticky_click_type": True})).started()
    h.engine.handle(SetClickType(ClickType.RIGHT))
    h.run(1.5)
    h.run(0.5, yaw=8.0)
    h.run(1.5, yaw=8.0)
    assert h.actions == [RIGHT, RIGHT]


def test_drag_presses_then_releases() -> None:
    h = Harness().started()
    h.engine.handle(SetClickType(ClickType.DRAG))
    h.run(1.5)
    assert h.actions == [PRESS] and h.engine.dragging
    h.run(0.5, yaw=8.0)  # drag to the right
    h.run(1.5, yaw=8.0)
    assert h.actions == [PRESS, RELEASE] and not h.engine.dragging
    assert h.clicks[1][1] is not None and h.clicks[1][1][0] > 2000  # released over there
    assert h.engine.click_type is ClickType.LEFT


@pytest.mark.parametrize("interrupt", ["pause", "face_lost", "manual_mouse"])
def test_held_drag_button_released_on_interruption(interrupt: str) -> None:
    h = Harness().started()
    h.engine.handle(SetClickType(ClickType.DRAG))
    h.run(1.5)
    assert h.engine.dragging
    if interrupt == "pause":
        h.engine.handle(Pause())
        h.run(0.1)
    elif interrupt == "face_lost":
        h.run(0.1, make=no_face)
    else:
        h.run(0.1, manual=(10.0, 10.0))
    assert not h.engine.dragging
    assert h.releases == 1


def test_scroll_mode_scrolls_with_pitch_and_holds_cursor() -> None:
    h = Harness().started()
    h.engine.handle(SetClickType(ClickType.SCROLL))
    out = h.run(1.5)  # dwell anchors scrolling at the centre
    assert out.status.scrolling and h.clicks == []
    moves = h.moves
    h.run(1.0, pitch=8.0)  # look up: scroll up
    assert h.scrolled > 1.0
    assert h.moves == moves  # the cursor stays at the anchor
    up = h.scrolled
    h.run(1.0, pitch=-8.0)  # look down: scroll down
    assert h.scrolled < up


def test_scroll_ends_when_idle_or_turning_away() -> None:
    h = Harness().started()
    h.engine.handle(SetClickType(ClickType.SCROLL))
    h.run(1.5)
    out = h.run(3.0)  # rest in the dead zone for > 2.5 s
    assert not out.status.scrolling
    assert h.engine.click_type is ClickType.LEFT

    h.engine.handle(SetClickType(ClickType.SCROLL))
    h.run(0.5, yaw=3.0)
    out = h.run(1.5, yaw=3.0)
    assert out.status.scrolling
    out = h.run(0.6, yaw=20.0)  # turn well away
    assert not out.status.scrolling


def test_own_ui_always_gets_plain_left_click() -> None:
    h = Harness().started()
    cx, cy = CENTER
    h.engine.handle(SetOwnUi(((cx - 50, cy - 50, 100, 100),)))
    h.engine.handle(SetClickType(ClickType.RIGHT))
    h.run(1.5)  # dwell on our own toolbar button
    assert h.actions == [LEFT]
    assert h.engine.click_type is ClickType.RIGHT  # the pending choice is kept


# ---------------------------------------------------------------- gestures


def test_brow_hold_pauses_and_resumes() -> None:
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
    for i in range(5):
        h.run(0.4, brow=0.9, yaw=float(i * 3))
        h.run(0.4, yaw=float(i * 3))
    assert h.engine.mode is Mode.ACTIVE


@pytest.mark.parametrize(("roll", "expected"), [(15.0, RIGHT), (-15.0, DOUBLE)])
def test_head_tilt_gestures(roll: float, expected: ClickAction) -> None:
    h = Harness(with_updates(Settings(), dwell={"enabled": False})).started()
    h.run(0.5, yaw=4.0)
    target = h.cursor
    h.run(0.6, yaw=4.0, roll=roll)  # tilt past 12 degrees for 0.6 s (hold is 0.4 s)
    assert h.actions == [expected]
    assert h.clicks[0][1] == pytest.approx(target, abs=2)


def test_tilt_click_lands_at_anchor_despite_head_drift() -> None:
    """Tilting nudges yaw too; the click must land where the pointer was before."""
    h = Harness(with_updates(Settings(), dwell={"enabled": False})).started()
    h.run(0.5, yaw=4.0)
    target = h.cursor
    h.run(0.6, yaw=6.0, roll=15.0)  # the head turns 2 degrees while tilting
    assert h.clicks and h.clicks[0][1] == pytest.approx(target, abs=2)


def test_swap_tilt() -> None:
    s = with_updates(Settings(), dwell={"enabled": False}, gestures={"swap_tilt": True})
    h = Harness(s).started()
    h.run(0.6, roll=15.0)
    assert h.actions == [DOUBLE]


def test_small_tilts_do_nothing() -> None:
    h = Harness(with_updates(Settings(), dwell={"enabled": False})).started()
    h.run(2.0, roll=8.0)  # below 12 degrees
    h.run(0.2, roll=20.0)  # past it, but too briefly
    h.run(0.5)
    assert h.clicks == []


def test_disabled_binding_never_fires() -> None:
    h = Harness(with_updates(Settings(), dwell={"enabled": False})).started()
    h.run(2.0, jaw=0.9)  # mouth binding is off by default
    assert h.clicks == []
    h2 = Harness(
        with_binding(with_updates(Settings(), dwell={"enabled": False}), "mouth", enabled=True)
    ).started()
    h2.run(0.8, jaw=0.9)
    assert h2.actions == [LEFT]


def test_gesture_click_on_own_ui_is_left() -> None:
    h = Harness(with_updates(Settings(), dwell={"enabled": False})).started()
    cx, cy = CENTER
    h.engine.handle(SetOwnUi(((cx - 50, cy - 50, 100, 100),)))
    h.run(0.6, roll=15.0)  # right-click gesture over our own window
    assert h.actions == [LEFT]


def test_drag_toggle_gesture() -> None:
    s = with_binding(
        with_updates(Settings(), dwell={"enabled": False}),
        "tilt_right",
        action=GestureAction.DRAG_TOGGLE,
    )
    h = Harness(s).started()
    h.run(0.6, roll=15.0)
    assert h.engine.dragging and h.actions == [PRESS]
    h.run(0.5)  # release the tilt
    h.run(1.0, yaw=6.0)
    h.run(0.6, yaw=6.0, roll=15.0)
    assert h.actions == [PRESS, RELEASE] and not h.engine.dragging


def test_gesture_availability_reported() -> None:
    out = Harness().run(0.1)
    readings = {r.id: r for r in out.status.gestures}
    assert readings["brows"].available is True
    assert readings["tilt_right"].available is True
    h2 = Harness(with_binding(Settings(), "brows", source="notReal"))
    readings = {r.id: r for r in h2.run(0.1).status.gestures}
    assert readings["brows"].available is False
