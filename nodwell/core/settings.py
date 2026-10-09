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
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class CameraSettings(_Model):
    index: int = Field(default=0, ge=0)
    backend: Literal["any", "msmf", "dshow", "avfoundation", "v4l2"] = "any"
    width: int = Field(default=640, ge=160)
    height: int = Field(default=480, ge=120)
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


class DwellSettings(_Model):
    enabled: bool = True
    dwell_s: float = Field(default=1.0, ge=0.2, le=5.0)
    radius_px: float = Field(default=30.0, ge=5.0, le=200.0)  # logical px; scaled by DPR


class PauseGestureSettings(_Model):
    enabled: bool = True
    blendshape: str = "browInnerUp"
    on_threshold: float = Field(default=0.5, gt=0.0, le=1.0)
    off_threshold: float = Field(default=0.35, ge=0.0, le=1.0)
    hold_s: float = Field(default=2.0, ge=0.5, le=10.0)
    cooldown_s: float = Field(default=1.0, ge=0.0, le=10.0)


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
    pause: str = "<ctrl>+<alt>+p"
    recenter: str = "<ctrl>+<alt>+r"
    quit: str = "<ctrl>+<alt>+q"


class Settings(_Model):
    schema_version: int = SCHEMA_VERSION
    camera: CameraSettings = CameraSettings()
    pointer: PointerSettings = PointerSettings()
    dwell: DwellSettings = DwellSettings()
    pause_gesture: PauseGestureSettings = PauseGestureSettings()
    safety: SafetySettings = SafetySettings()
    drift: DriftSettings = DriftSettings()
    hotkeys: HotkeySettings = HotkeySettings()


# Migrations: MIGRATIONS[n] turns a version-n dict into a version-(n+1) dict.
MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}


def migrate(data: dict[str, Any]) -> dict[str, Any]:
    """Upgrade a settings dict step by step to SCHEMA_VERSION."""
    version = int(data.get("schema_version", 1))
    if version > SCHEMA_VERSION:
        raise ValueError(f"settings schema {version} is newer than this app ({SCHEMA_VERSION})")
    while version < SCHEMA_VERSION:
        data = MIGRATIONS[version](data)
        version += 1
        data["schema_version"] = version
    return data


def load_settings(path: Path) -> Settings:
    """Load settings, falling back to defaults.

    A missing file gives defaults. An unreadable, invalid, or too-new file is moved aside
    to `<name>.bak` (so nothing the user had is destroyed) and defaults are used.
    """
    if not path.is_file():
        return Settings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("settings file does not contain a JSON object")
        return Settings.model_validate(migrate(data))
    except (OSError, ValueError, ValidationError) as exc:
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
