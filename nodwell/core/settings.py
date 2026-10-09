"""User settings: pydantic models persisted as versioned JSON.

Models are frozen; a change produces a new Settings object (`model_copy(update=...)`) that
is handed to the engine as a whole, so no thread ever sees a half-updated setting.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .actions import GestureAction

log = logging.getLogger(__name__)

SCHEMA_VERSION = 2


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class CameraSettings(_Model):
    index: int = Field(default=0, ge=0, le=63)
    backend: Literal["any", "msmf", "dshow", "avfoundation", "v4l2"] = "any"
    width: int = Field(default=640, ge=160, le=1920)
    height: int = Field(default=480, ge=120, le=1080)
    fps: int = Field(default=30, ge=5, le=120)
    paused_fps: float = Field(default=10.0, ge=1.0, le=60.0)


class PointerSettings(_Model):
    mode: Literal["absolute", "relative"] = "absolute"
    yaw_range_deg: float = Field(default=15.0, ge=3.0, le=60.0)
    pitch_range_deg: float = Field(default=10.0, ge=3.0, le=60.0)
    invert_x: bool = False
    invert_y: bool = False
    dead_zone_deg: float = Field(default=2.0, ge=0.0, le=15.0)
    max_speed_screens_per_s: float = Field(default=0.8, gt=0.0, le=5.0)
    acceleration: float = Field(default=1.5, ge=1.0, le=3.0)
    smoothness: float = Field(default=0.5, ge=0.0, le=1.0)
    # Advanced One Euro parameters (units: degrees and seconds).
    beta: float = Field(default=0.08, ge=0.0, le=5.0)
    d_cutoff_hz: float = Field(default=1.0, gt=0.0, le=10.0)
    # Output easing between camera frames (DECISIONS.md D16). 0 = off.
    motion_smoothing_ms: float = Field(default=16.0, ge=0.0, le=100.0)


class DwellSettings(_Model):
    enabled: bool = True
    dwell_s: float = Field(default=1.0, ge=0.2, le=5.0)
    radius_px: float = Field(default=30.0, ge=5.0, le=200.0)  # logical px; scaled by DPR
    # False: a toolbar choice (right, double, ...) applies to the next dwell only.
    sticky_click_type: bool = False


class GestureBinding(_Model):
    """One gesture and what it does (DECISIONS.md D18).

    `source` is a blendshape name read from the model at runtime, or one of the derived
    sources in core/gestures.py (`smile`, `head_tilt_left`, `head_tilt_right`). Scores are
    0..1 for every source, so thresholds read the same way everywhere.
    """

    id: str = Field(min_length=1, max_length=40)
    label: str = Field(max_length=60)
    source: str = Field(min_length=1, max_length=60)
    action: GestureAction = GestureAction.NONE
    enabled: bool = True
    on_threshold: float = Field(default=0.5, gt=0.0, le=1.0)
    off_threshold: float = Field(default=0.35, ge=0.0, le=1.0)
    hold_s: float = Field(default=0.5, ge=0.1, le=10.0)
    cooldown_s: float = Field(default=0.8, ge=0.0, le=10.0)

    @model_validator(mode="after")
    def _off_not_above_on(self) -> Self:
        if self.off_threshold > self.on_threshold:
            raise ValueError("off_threshold must not exceed on_threshold")
        return self


DEFAULT_BINDINGS: tuple[GestureBinding, ...] = (
    GestureBinding(
        id="brows",
        label="Raise eyebrows",
        source="browInnerUp",
        action=GestureAction.PAUSE_TOGGLE,
        hold_s=2.0,
        cooldown_s=1.0,
    ),
    GestureBinding(
        id="tilt_right",
        label="Tilt head right",
        source="head_tilt_right",
        action=GestureAction.RIGHT_CLICK,
        on_threshold=0.4,  # 12 degrees with tilt_full_deg = 30
        off_threshold=0.25,
        hold_s=0.4,
    ),
    GestureBinding(
        id="tilt_left",
        label="Tilt head left",
        source="head_tilt_left",
        action=GestureAction.DOUBLE_CLICK,
        on_threshold=0.4,
        off_threshold=0.25,
        hold_s=0.4,
    ),
    GestureBinding(
        id="mouth",
        label="Open mouth",
        source="jawOpen",
        action=GestureAction.LEFT_CLICK,
        enabled=False,  # talking opens the jaw; opt in only
        hold_s=0.5,
    ),
    GestureBinding(
        id="smile",
        label="Smile",
        source="smile",
        action=GestureAction.DRAG_TOGGLE,
        enabled=False,
        on_threshold=0.6,
        off_threshold=0.4,
        hold_s=0.6,
    ),
)


class GestureSettings(_Model):
    bindings: tuple[GestureBinding, ...] = DEFAULT_BINDINGS
    tilt_full_deg: float = Field(default=30.0, ge=5.0, le=60.0)  # head tilt that scores 1.0
    swap_tilt: bool = False  # if left and right tilts are detected the wrong way round
    freeze_pointer: bool = True  # hold the cursor still while a gesture is building


class ScrollSettings(_Model):
    dead_zone_deg: float = Field(default=2.0, ge=0.0, le=15.0)
    full_speed_deg: float = Field(default=10.0, ge=3.0, le=40.0)
    max_notches_per_s: float = Field(default=8.0, gt=0.0, le=60.0)
    exit_yaw_deg: float = Field(default=12.0, ge=3.0, le=60.0)
    exit_yaw_hold_s: float = Field(default=0.3, ge=0.0, le=5.0)
    idle_exit_s: float = Field(default=2.5, ge=0.5, le=30.0)


class ToolbarSettings(_Model):
    visible: bool = True
    edge: Literal["left", "right"] = "left"


class SafetySettings(_Model):
    min_click_interval_s: float = Field(default=0.5, ge=0.1, le=10.0)
    face_lost_pause_s: float = Field(default=5.0, ge=0.5, le=120.0)
    reacquire_grace_s: float = Field(default=0.3, ge=0.0, le=5.0)
    startup_stable_s: float = Field(default=1.0, ge=0.0, le=10.0)
    manual_override_s: float = Field(default=1.5, ge=0.0, le=10.0)


class DriftSettings(_Model):
    enabled: bool = True
    threshold_deg: float = Field(default=5.0, ge=1.0, le=30.0)
    time_constant_s: float = Field(default=30.0, ge=5.0, le=600.0)


class HotkeySettings(_Model):
    # pynput GlobalHotKeys syntax.
    pause: str = Field(default="<ctrl>+<alt>+p", max_length=60)
    recenter: str = Field(default="<ctrl>+<alt>+r", max_length=60)
    quit: str = Field(default="<ctrl>+<alt>+q", max_length=60)


class Settings(_Model):
    schema_version: int = SCHEMA_VERSION
    camera: CameraSettings = CameraSettings()
    pointer: PointerSettings = PointerSettings()
    dwell: DwellSettings = DwellSettings()
    gestures: GestureSettings = GestureSettings()
    scroll: ScrollSettings = ScrollSettings()
    toolbar: ToolbarSettings = ToolbarSettings()
    safety: SafetySettings = SafetySettings()
    drift: DriftSettings = DriftSettings()
    hotkeys: HotkeySettings = HotkeySettings()


def _v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    """v2 replaced the single `pause_gesture` with a list of gesture bindings."""
    old = data.pop("pause_gesture", None)
    bindings = [b.model_dump(mode="json") for b in DEFAULT_BINDINGS]
    if isinstance(old, dict):
        first = bindings[0]
        for key in ("enabled", "on_threshold", "off_threshold", "hold_s", "cooldown_s"):
            if key in old:
                first[key] = old[key]
        if "blendshape" in old:
            first["source"] = old["blendshape"]
    data["gestures"] = {"bindings": bindings}
    return data


# Migrations: MIGRATIONS[n] turns a version-n dict into a version-(n+1) dict.
MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {1: _v1_to_v2}


def migrate(data: dict[str, Any]) -> dict[str, Any]:
    """Upgrade a settings dict step by step to SCHEMA_VERSION."""
    raw = data.get("schema_version", 1)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"schema_version must be an integer, got {raw!r}")
    version = raw
    if version > SCHEMA_VERSION or version < 1:
        raise ValueError(f"settings schema {version} is not supported by this app")
    while version < SCHEMA_VERSION:
        data = MIGRATIONS[version](data)
        version += 1
        data["schema_version"] = version
    return data


def load_settings(path: Path) -> Settings:
    """Load settings, falling back to defaults.

    A missing file gives defaults. An unreadable, invalid, or unsupported file is moved
    aside to `<name>.bak` (so nothing the user had is destroyed) and defaults are used.
    """
    if not path.is_file():
        return Settings()
    try:
        if path.stat().st_size > 1_000_000:
            raise ValueError("settings file is implausibly large")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("settings file does not contain a JSON object")
        return Settings.model_validate(migrate(data))
    except (OSError, ValueError, TypeError, RecursionError, ValidationError) as exc:
        backup = path.with_suffix(path.suffix + ".bak")
        log.warning("settings file %s unusable (%s); moved to %s", path, exc, backup.name)
        try:
            path.replace(backup)
        except OSError:
            log.exception("could not move bad settings file aside")
        return Settings()


def save_settings(path: Path, settings: Settings) -> None:
    """Write settings atomically: a crash mid-write never leaves a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(settings.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)
