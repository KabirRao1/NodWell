"""The pipeline thread end to end, from a replayed fixture, with no camera or Qt."""

from pathlib import Path

from nodwell.core.actions import LEFT_CLICK, PRESS_LEFT, RELEASE_LEFT, ClickType
from nodwell.core.engine import (
    Command,
    InteractionEngine,
    Mode,
    Pause,
    PauseReason,
    SetClickType,
)
from nodwell.core.pointer import ScreenRect
from nodwell.core.safety import SafetyGate
from nodwell.core.settings import Settings
from nodwell.pipeline import Pipeline, PipelineStatus, ReplaySource
from nodwell.platform.input_backend import DryRunBackend, GatedInput

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE = FIXTURES / "dwell_then_face_lost.jsonl"
SCREEN = ScreenRect(0, 0, 1920, 1080)


def run_pipeline(
    commands_before_start: list[Command] | None = None,
    fixture: Path = FIXTURE,
) -> tuple[Pipeline, DryRunBackend, SafetyGate, list[PipelineStatus]]:
    gate = SafetyGate()
    backend = DryRunBackend()
    statuses: list[PipelineStatus] = []
    pipeline = Pipeline(
        ReplaySource(fixture, realtime=False),
        InteractionEngine(Settings(), SCREEN),
        # Replays run faster than real time; the wall-clock limiter would see every click as
        # "too soon". The engine still rate-limits on frame time.
        GatedInput(backend, gate, min_click_interval_s=0.0),
        gate,
        on_status=statuses.append,
        status_hz=1000.0,
    )
    for command in commands_before_start or []:
        pipeline.send(command)
    pipeline.start()
    pipeline.join(timeout=20)
    assert not pipeline.is_alive()
    return pipeline, backend, gate, statuses


def test_replay_moves_clicks_then_auto_pauses() -> None:
    pipeline, backend, gate, statuses = run_pipeline()
    assert pipeline.error is None
    assert pipeline.frames == 12 * 30
    assert backend.moves > 0
    assert len(backend.clicks) >= 1  # the dwell in the fixture
    final = statuses[-1].engine
    assert final.mode is Mode.PAUSED
    assert final.pause_reason is PauseReason.FACE_LOST
    assert not gate.allows()  # gate closed after the run


def test_paused_before_start_never_touches_the_os() -> None:
    _, backend, _, statuses = run_pipeline([Pause()])
    assert backend.moves == 0 and backend.clicks == []
    assert all(s.engine.mode is not Mode.ACTIVE for s in statuses)


def test_closed_gate_blocks_output_even_when_engine_is_active() -> None:
    gate = SafetyGate()
    backend = DryRunBackend()
    out = GatedInput(backend, gate, min_click_interval_s=0.0)
    assert not out.move_to(10, 10) and not out.perform(LEFT_CLICK) and not out.scroll(0, 1)
    gate.allow()
    assert out.move_to(10, 10) and out.perform(LEFT_CLICK)
    assert backend.moves == 1 and len(backend.clicks) == 1


def test_release_always_goes_through_even_with_gate_closed() -> None:
    gate = SafetyGate()
    gate.allow()
    backend = DryRunBackend()
    out = GatedInput(backend, gate, min_click_interval_s=0.0)
    assert out.perform(PRESS_LEFT)
    gate.block()  # panic while the button is held
    out.release_all()
    assert [name for name, _ in backend.actions] == ["press left", "release left"]
    out.release_all()  # nothing held any more: no extra release
    assert not out.perform(RELEASE_LEFT)
    assert len(backend.actions) == 2


def test_gated_click_rate_limit() -> None:
    gate = SafetyGate()
    gate.allow()
    out = GatedInput(DryRunBackend(), gate, min_click_interval_s=10.0)
    assert out.perform(LEFT_CLICK)
    assert not out.perform(LEFT_CLICK)


def test_external_move_detection() -> None:
    gate = SafetyGate()
    gate.allow()
    backend = DryRunBackend()
    out = GatedInput(backend, gate, min_click_interval_s=0.0)
    assert out.external_move(12) is None  # we have written nothing yet
    out.move_to(100, 100)
    assert out.external_move(12) is None
    backend.move_to(300, 300)  # a person moves the mouse
    assert out.external_move(12) == (300, 300)
    assert out.external_move(12) is None  # reported once


def test_scroll_carries_fractions() -> None:
    gate = SafetyGate()
    gate.allow()
    backend = DryRunBackend()
    out = GatedInput(backend, gate, min_click_interval_s=0.0)
    for _ in range(30):
        out.scroll(0, 0.05)
    assert abs(backend.scrolled + out._scroll_rest[1] - 1.5) < 1e-9


def test_animator_eases_toward_target_and_snaps_exactly() -> None:
    import time

    from nodwell.platform.pointer_animator import PointerAnimator

    gate = SafetyGate()
    gate.allow()
    backend = DryRunBackend()
    anim = PointerAnimator(GatedInput(backend, gate, 0.0), tau_s=0.016)
    anim.start()
    try:
        anim.set_target(0, 0)  # first target: jump straight there
        assert backend.position() == (0, 0)
        anim.set_target(1000, 0)  # later targets: eased, not jumped
        assert backend.position() == (0, 0)
        time.sleep(0.4)
        pos = backend.position()
        assert pos is not None and pos[0] >= 999
        anim.snap_to(123, 456)
        assert backend.position() == (123, 456)
    finally:
        anim.stop()
        anim.join(timeout=2)


def test_replay_drag_by_dwell_then_right_click_by_head_tilt() -> None:
    pipeline, backend, gate, _ = run_pipeline(
        [SetClickType(ClickType.DRAG)], FIXTURES / "drag_then_tilt_right.jsonl"
    )
    assert pipeline.error is None
    names = [name for name, _ in backend.actions]
    assert names[:3] == ["press left", "release left", "click right x1"]
    (_, grab), (_, drop) = backend.actions[0], backend.actions[1]
    assert grab is not None and drop is not None and drop[0] > grab[0] + 300  # dragged right
    assert not gate.allows()  # closed at the end of the run
