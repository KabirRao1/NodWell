"""Security and safety regression tests (docs/SECURITY_AUDIT.md).

Static guards keep dangerous capabilities out of the package; fuzz tests check that hostile
or broken input (settings files, replay files, tracker output, command sequences) never
crashes the app or makes it act when it must not.
"""

from __future__ import annotations

import ast
import json
import math
import random
from pathlib import Path
from typing import Any

import pytest

from nodwell import paths
from nodwell.core.actions import ClickType
from nodwell.core.engine import (
    InteractionEngine,
    Mode,
    Pause,
    Recenter,
    Resume,
    SetClickType,
    SetOwnUi,
)
from nodwell.core.frame import FeatureFrame
from nodwell.core.pointer import ScreenRect
from nodwell.core.recording import read_frames
from nodwell.core.safety import SafetyGate
from nodwell.core.settings import Settings, load_settings
from nodwell.pipeline import Pipeline, ReplaySource
from nodwell.platform.input_backend import DryRunBackend, GatedInput

PACKAGE = Path(__file__).resolve().parents[1] / "nodwell"

# ---------------------------------------------------------------- static guards

# Network, process spawning, and unsafe deserialisation have no place in this app.
FORBIDDEN_MODULES = {
    "socket": {"diagnostics.py"},  # the smoke-test tripwire imports it only to block it
    "ssl": set(),
    "urllib": set(),
    "http": set(),
    "requests": set(),
    "httpx": set(),
    "aiohttp": set(),
    "ftplib": set(),
    "smtplib": set(),
    "telnetlib": set(),
    "xmlrpc": set(),
    "subprocess": set(),
    "multiprocessing": set(),
    "pickle": set(),
    "marshal": set(),
    "shelve": set(),
    "dill": set(),
}
FORBIDDEN_CALLS = {"eval", "exec", "compile", "__import__"}
FORBIDDEN_OS_CALLS = {"system", "popen", "spawnl", "spawnv", "execv", "execl", "startfile"}
# Anything that could write camera pixels to disk (CLAUDE.md §4.1).
FORBIDDEN_ATTR_CALLS = {"imwrite", "imencode", "VideoWriter", "tofile", "save"}


def package_files() -> list[Path]:
    files = sorted(PACKAGE.rglob("*.py"))
    assert files, "package not found"
    return files


def test_no_network_process_or_unsafe_deserialisation_imports() -> None:
    violations = []
    for path in package_files():
        rel = path.relative_to(PACKAGE).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                top = name.split(".")[0]
                if top in FORBIDDEN_MODULES and path.name not in FORBIDDEN_MODULES[top]:
                    violations.append(f"{rel}: import {name}")
    assert violations == []


def test_no_dynamic_code_shell_or_pixel_writing_calls() -> None:
    violations = []
    for path in package_files():
        rel = path.relative_to(PACKAGE).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if isinstance(f, ast.Name) and f.id in FORBIDDEN_CALLS:
                violations.append(f"{rel}:{node.lineno} {f.id}()")
            if isinstance(f, ast.Attribute):
                owner = f.value.id if isinstance(f.value, ast.Name) else ""
                if owner == "os" and f.attr in FORBIDDEN_OS_CALLS:
                    violations.append(f"{rel}:{node.lineno} os.{f.attr}()")
                if f.attr in FORBIDDEN_ATTR_CALLS:
                    violations.append(f"{rel}:{node.lineno} .{f.attr}()")
    assert violations == []


def test_log_calls_never_include_click_positions() -> None:
    """Persistent logs must not become a usage trace (SECURITY_AUDIT F1).

    INFO and above reach the log file; per-action details may only be logged at DEBUG.
    """
    suspicious = {"click_at", "move_to", "pointer", "cursor", "position", "_pos"}
    violations = []
    for path in package_files():
        rel = path.relative_to(PACKAGE).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr not in {"info", "warning", "error", "critical", "exception"}:
                continue
            owner = node.func.value
            if not (isinstance(owner, ast.Name) and owner.id in {"log", "logging"}):
                continue
            for arg in node.args[1:]:
                names = {n.id for n in ast.walk(arg) if isinstance(n, ast.Name)}
                attrs = {n.attr for n in ast.walk(arg) if isinstance(n, ast.Attribute)}
                if (names | attrs) & suspicious:
                    violations.append(f"{rel}:{node.lineno}")
    assert violations == []


# ---------------------------------------------------------------- settings fuzzing


def random_json(rng: random.Random, depth: int = 0) -> Any:
    kind = rng.randrange(9 if depth < 4 else 6)
    if kind == 0:
        return None
    if kind == 1:
        return rng.choice([True, False])
    if kind == 2:
        return rng.choice([0, -1, 1, 2, 10**30, -(10**30), rng.randint(-1000, 1000)])
    if kind == 3:
        return rng.choice([0.0, -0.5, 0.5, 1e308, -1e308, rng.uniform(-100, 100)])
    if kind == 4:
        return rng.choice(["", "x" * 500, "browInnerUp", "<ctrl>+<alt>+p", "\u0000", "🙂"])
    if kind == 5:
        return rng.choice(["absolute", "relative", "left", "any", "head_tilt_left"])
    if kind == 6:
        return [random_json(rng, depth + 1) for _ in range(rng.randrange(4))]
    keys = [
        "schema_version", "camera", "pointer", "dwell", "gestures", "bindings", "scroll",
        "toolbar", "safety", "hotkeys", "index", "mode", "dwell_s", "enabled", "id",
        "source", "action", "on_threshold", "off_threshold", "pause_gesture", "blendshape",
    ]  # fmt: skip
    return {rng.choice(keys): random_json(rng, depth + 1) for _ in range(rng.randrange(6))}


def test_random_settings_files_never_crash(tmp_path: Path) -> None:
    rng = random.Random(1234)
    path = tmp_path / "settings.json"
    for _ in range(400):
        doc = random_json(rng)
        path.write_text(json.dumps(doc), encoding="utf-8")
        s = load_settings(path)
        assert isinstance(s, Settings)
        Settings.model_validate(s.model_dump())  # whatever came back is valid


@pytest.mark.parametrize(
    "content",
    [
        "",
        "null",
        "[]",
        '"text"',
        "NaN",
        '{"schema_version": "2"}',
        '{"schema_version": {"a": 1}}',
        '{"schema_version": true}',
        '{"schema_version": 0}',
        '{"schema_version": -5}',
        '{"pointer": {"smoothness": NaN}}',
        '{"pointer": {"smoothness": Infinity}}',
        '{"camera": {"index": 99999}}',
        '{"gestures": {"bindings": [{"id": "x"}]}}',
        '{"gestures": {"bindings": [{"id": "a", "label": "a", "source": "s",'
        ' "on_threshold": 0.2, "off_threshold": 0.9}]}}',
        "[" * 100_000 + "]" * 100_000,  # deep nesting -> RecursionError
    ],
    ids=lambda content: repr(content[:40]),  # short ids: Windows caps env vars at 32 KB
)
def test_hostile_settings_fall_back_to_defaults(tmp_path: Path, content: str) -> None:
    path = tmp_path / "settings.json"
    path.write_text(content, encoding="utf-8")
    assert load_settings(path) == Settings()


def test_oversized_settings_file_refused(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"x": "' + "a" * 2_000_000 + '"}', encoding="utf-8")
    assert load_settings(path) == Settings()


def test_v1_settings_migrate_to_v2(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    v1 = {
        "schema_version": 1,
        "dwell": {"dwell_s": 1.4},
        "pause_gesture": {"enabled": False, "blendshape": "jawOpen", "hold_s": 3.0},
    }
    path.write_text(json.dumps(v1), encoding="utf-8")
    s = load_settings(path)
    assert s.schema_version == 2 and s.dwell.dwell_s == 1.4
    first = s.gestures.bindings[0]
    assert (first.id, first.enabled, first.source, first.hold_s) == ("brows", False, "jawOpen", 3.0)
    assert len(s.gestures.bindings) == len(Settings().gestures.bindings)


# ---------------------------------------------------------------- engine fuzzing

SCREEN = ScreenRect(0, 0, 1920, 1080)
WEIRD = [float("nan"), float("inf"), float("-inf"), 1e9, -1e9, 0.0]


def random_frame(rng: random.Random, t: float) -> FeatureFrame:
    if rng.random() < 0.15:
        return FeatureFrame(t=t, face=False, brightness=rng.uniform(0, 255))

    def angle() -> float:
        return rng.choice(WEIRD) if rng.random() < 0.02 else rng.gauss(0, 12)

    def score() -> float:
        return rng.choice(WEIRD) if rng.random() < 0.02 else rng.uniform(-0.2, 1.2)

    names = ["browInnerUp", "jawOpen", "mouthSmileLeft", "mouthSmileRight"]
    return FeatureFrame(
        t=t,
        face=True,
        yaw=angle(),
        pitch=angle(),
        roll=angle(),
        face_size=0.15,
        brightness=120,
        blendshapes={n: score() for n in names if rng.random() > 0.1},
    )


def random_command(rng: random.Random) -> Any:
    return rng.choice(
        [
            Pause(),
            Resume(),
            Recenter(),
            SetClickType(rng.choice(list(ClickType))),
            SetOwnUi(((rng.uniform(0, 1900), rng.uniform(0, 1000), 200.0, 300.0),)),
            SetOwnUi(()),
        ]
    )


@pytest.mark.parametrize("seed", range(40))
def test_engine_invariants_under_random_input(seed: int) -> None:
    rng = random.Random(seed)
    settings = Settings()
    if rng.random() < 0.5:  # fast dwell and all gestures on, to provoke many actions
        bindings = tuple(b.model_copy(update={"enabled": True}) for b in settings.gestures.bindings)
        settings = settings.model_copy(
            update={
                "dwell": settings.dwell.model_copy(update={"dwell_s": 0.2}),
                "gestures": settings.gestures.model_copy(update={"bindings": bindings}),
            }
        )
    engine = InteractionEngine(settings, SCREEN)
    min_interval = settings.safety.min_click_interval_s
    last_click_t = -math.inf
    t = 0.0
    for _ in range(600):
        if rng.random() < 0.03:
            engine.handle(random_command(rng))
        t += rng.choice([1 / 30, 1 / 30, 1 / 15, 0.0, 0.5])
        frame = random_frame(rng, t)
        manual = (rng.uniform(0, 1920), rng.uniform(0, 1080)) if rng.random() < 0.01 else None
        out = engine.update(frame, manual)

        acting = [c for c in out.clicks if c.kind != "release"]
        if not frame.face or engine.mode is not Mode.ACTIVE:
            assert out.move_to is None and not acting and out.scroll is None
            assert not engine.dragging
        if out.move_to is not None:
            x, y = out.move_to
            assert math.isfinite(x) and math.isfinite(y)
            assert 0 <= x < SCREEN.width and 0 <= y < SCREEN.height
        if out.scroll is not None:
            assert all(math.isfinite(v) for v in out.scroll)
        for _c in acting:
            assert t - last_click_t >= min_interval - 1e-9
            last_click_t = t
        if acting:
            assert out.click_at is not None
            assert all(math.isfinite(v) for v in out.click_at)


# ---------------------------------------------------------------- replay files


@pytest.mark.parametrize(
    "line",
    [
        "not json",
        "{}",
        '{"t": "soon", "face": true}',
        '{"t": 0, "face": true, "yaw": "left"}',
        '{"t": 0, "face": true, "blendshapes": [1, 2]}',
        "[1, 2, 3]",
    ],
)
def test_garbage_replay_fails_cleanly_and_never_acts(tmp_path: Path, line: str) -> None:
    path = tmp_path / "bad.jsonl"
    good = FeatureFrame(t=0.0, face=True).to_dict()
    path.write_text(json.dumps(good) + "\n" + line + "\n", encoding="utf-8")
    with pytest.raises((ValueError, KeyError, TypeError, AttributeError)):
        list(read_frames(path))

    gate = SafetyGate()
    backend = DryRunBackend()
    pipeline = Pipeline(
        ReplaySource(path, realtime=False),
        InteractionEngine(Settings(), SCREEN),
        GatedInput(backend, gate, 0.0),
        gate,
        on_status=lambda _s: None,
    )
    pipeline.start()
    pipeline.join(timeout=10)
    assert not pipeline.is_alive()
    assert pipeline.error is not None  # reported to the UI, not silently ignored
    assert backend.actions == [] and not gate.allows()


# ---------------------------------------------------------------- model integrity


def test_tampered_model_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    models = tmp_path / "models"
    models.mkdir()
    real = paths.model_checksum_path().read_text(encoding="utf-8")
    (models / "face_landmarker.sha256").write_text(real, encoding="utf-8")
    (models / "face_landmarker.task").write_bytes(b"not the real model")
    monkeypatch.setattr(paths, "resource_dir", lambda: tmp_path)
    with pytest.raises(paths.ModelError):
        paths.load_model()


def test_missing_model_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paths, "resource_dir", lambda: tmp_path)
    with pytest.raises(paths.ModelError):
        paths.load_model()


# ---------------------------------------------------------------- supply chain


def test_mediapipe_native_code_has_no_usage_telemetry() -> None:
    """MediaPipe 1.0.1 (and, per a public report, releases after 0.10.21) embeds a Clearcut
    client that uploads usage analytics to play.googleapis.com from native code
    (SECURITY_AUDIT F0). 0.10.21 does not. This guards against an accidental upgrade: it
    fails if the uploader shows up in the installed wheel.
    """
    import mediapipe

    root = Path(mediapipe.__file__).parent
    natives = [p for p in root.rglob("*") if p.suffix.lower() in {".pyd", ".dll", ".so", ".dylib"}]
    assert natives, "no native MediaPipe libraries found"
    markers = (b"play.googleapis.com", b"ClearcutLoggingClient", b"clearcut backend")
    offenders = [
        f"{p.relative_to(root)}: {m.decode()}"
        for p in natives
        for m in markers
        if m in p.read_bytes()
    ]
    assert offenders == []


def test_vulnerable_protobuf_json_parser_is_not_reachable() -> None:
    """protobuf 4.25.x (pinned by MediaPipe 0.10.21) has CVE-2026-0994, a DoS in
    json_format.ParseDict(). Nodwell never parses protobuf JSON; this checks that loading
    the tracker doesn't pull that module in either (SECURITY_AUDIT F9).
    """
    import subprocess
    import sys

    code = (
        "import os, sys; os.environ['MPLBACKEND'] = 'Agg'\n"
        "import nodwell.tracking.landmarker\n"
        "print('google.protobuf.json_format' in sys.modules)\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip().splitlines()[-1] == "False"
