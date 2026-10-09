"""The pipeline thread end to end, from a replayed fixture, with no camera or Qt."""

from pathlib import Path

from nodwell.core.engine import InteractionEngine, Mode, Pause, PauseReason
from nodwell.core.pointer import ScreenRect
from nodwell.core.safety import SafetyGate
from nodwell.core.settings import Settings
from nodwell.pipeline import Pipeline, PipelineStatus, ReplaySource
from nodwell.platform.input_backend import DryRunBackend, GatedInput

FIXTURE = Path(__file__).parent / "fixtures" / "dwell_then_face_lost.jsonl"
SCREEN = ScreenRect(0, 0, 1920, 1080)


def run_pipeline(
    commands_before_start: list[Pause] | None = None,
) -> tuple[Pipeline, DryRunBackend, SafetyGate, list[PipelineStatus]]:
    gate = SafetyGate()
    backend = DryRunBackend()
    statuses: list[PipelineStatus] = []
    pipeline = Pipeline(
        ReplaySource(FIXTURE, realtime=False),
        InteractionEngine(Settings(), SCREEN),
        GatedInput(backend, gate, min_click_interval_s=0.5),
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
    assert not out.move_to(10, 10) and not out.click()
    gate.allow()
    assert out.move_to(10, 10) and out.click()
    assert backend.moves == 1 and len(backend.clicks) == 1
