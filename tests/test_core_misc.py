"""Settings persistence, recording, the latest-frame slot, timing, and safety primitives."""

import json
import threading
from pathlib import Path

import pytest

from nodwell.core.frame import FeatureFrame
from nodwell.core.latest import LatestSlot
from nodwell.core.recording import Recorder, read_frames
from nodwell.core.safety import ClickRateLimiter, SafetyGate
from nodwell.core.settings import (
    SCHEMA_VERSION,
    Settings,
    load_settings,
    migrate,
    save_settings,
)
from nodwell.core.timing import StageStats, summarize

# ---------------------------------------------------------------- settings


def test_missing_settings_file_gives_defaults(tmp_path: Path) -> None:
    assert load_settings(tmp_path / "nope.json") == Settings()


def test_settings_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "settings.json"
    s = Settings().model_copy(
        update={"pointer": Settings().pointer.model_copy(update={"mode": "relative"})}
    )
    save_settings(path, s)
    assert load_settings(path) == s
    assert not path.with_suffix(".json.tmp").exists()


def test_corrupt_settings_moved_aside(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_settings(path) == Settings()
    assert not path.exists()
    assert path.with_suffix(".json.bak").read_text(encoding="utf-8") == "{not json"


def test_invalid_values_moved_aside(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"dwell": {"dwell_s": -3}}), encoding="utf-8")
    assert load_settings(path) == Settings()
    assert path.with_suffix(".json.bak").exists()


def test_partial_file_fills_defaults_and_ignores_unknown(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"dwell": {"dwell_s": 2.0}, "future_key": 1}), encoding="utf-8")
    s = load_settings(path)
    assert s.dwell.dwell_s == 2.0
    assert s.pointer == Settings().pointer


def test_newer_schema_rejected() -> None:
    with pytest.raises(ValueError):
        migrate({"schema_version": SCHEMA_VERSION + 1})


def test_settings_are_frozen() -> None:
    with pytest.raises(Exception):  # noqa: B017 - pydantic raises its ValidationError
        Settings().dwell.dwell_s = 3.0


# ---------------------------------------------------------------- recording


def test_recorder_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "rec.jsonl"
    frames = [
        FeatureFrame(t=0.0, face=False, brightness=50),
        FeatureFrame(t=0.033, face=True, yaw=1.5, pitch=-2.0, blendshapes={"jawOpen": 0.2}),
    ]
    with Recorder(path) as rec:
        for f in frames:
            rec.write(f)
    assert list(read_frames(path)) == frames


# ---------------------------------------------------------------- latest slot


def test_latest_slot_keeps_newest_and_counts_drops() -> None:
    slot: LatestSlot[int] = LatestSlot()
    slot.put(1)
    slot.put(2)
    slot.put(3)
    assert slot.get(timeout=0.1) == 3
    assert slot.dropped == 2
    assert slot.get(timeout=0.01) is None


def test_latest_slot_wakes_waiter_across_threads() -> None:
    slot: LatestSlot[str] = LatestSlot()
    got: list[str | None] = []
    t = threading.Thread(target=lambda: got.append(slot.get(timeout=5)))
    t.start()
    slot.put("frame")
    t.join(timeout=5)
    assert got == ["frame"]


def test_latest_slot_close_releases_waiter() -> None:
    slot: LatestSlot[str] = LatestSlot()
    got: list[str | None] = []
    t = threading.Thread(target=lambda: got.append(slot.get(timeout=5)))
    t.start()
    slot.close()
    t.join(timeout=5)
    assert got == [None]


# ---------------------------------------------------------------- timing & safety


def test_summarize() -> None:
    assert summarize([]) == {"n": 0, "p50": None, "p95": None, "max": None}
    s = summarize([float(i) for i in range(1, 101)])
    assert s["n"] == 100 and s["p50"] == 50.5 and s["p95"] == 95.0 and s["max"] == 100.0


def test_stage_stats_ring_buffer() -> None:
    stats = StageStats(maxlen=3)
    for v in (1.0, 2.0, 3.0, 4.0):
        stats.add("inference", v)
    assert stats.summary()["inference"]["n"] == 3


def test_safety_gate_starts_closed() -> None:
    gate = SafetyGate()
    assert not gate.allows()
    gate.allow()
    assert gate.allows()
    gate.block()
    assert not gate.allows()


def test_click_rate_limiter() -> None:
    lim = ClickRateLimiter(0.5)
    assert lim.try_acquire(1.0)
    assert not lim.try_acquire(1.4)
    assert lim.try_acquire(1.5)
