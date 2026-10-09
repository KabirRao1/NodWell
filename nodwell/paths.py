"""Where Nodwell's files live: the bundled model, settings, and logs."""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

from platformdirs import user_cache_dir, user_config_dir, user_log_dir

APP_NAME = "Nodwell"


def resource_dir() -> Path:
    """Directory holding bundled read-only files.

    In a PyInstaller build this is the bundle's `_internal` folder (`sys._MEIPASS`);
    when running from source, it's the repository root.
    """
    bundle = getattr(sys, "_MEIPASS", None)
    return Path(bundle) if bundle else Path(__file__).resolve().parents[1]


def model_path() -> Path:
    return resource_dir() / "models" / "face_landmarker.task"


def model_checksum_path() -> Path:
    return resource_dir() / "models" / "face_landmarker.sha256"


def settings_path() -> Path:
    return Path(user_config_dir(APP_NAME, appauthor=False)) / "settings.json"


def log_dir() -> Path:
    return Path(user_log_dir(APP_NAME, appauthor=False))


def prepare_matplotlib() -> None:
    """Configure matplotlib before MediaPipe imports it (DECISIONS.md D10).

    Non-GUI backend, and in a frozen build a persistent cache folder: PyInstaller's
    matplotlib hook otherwise uses a temp folder deleted at exit, so the font cache would
    be rebuilt on every launch. The cache holds font metadata only.
    """
    os.environ.setdefault("MPLBACKEND", "Agg")
    if getattr(sys, "frozen", False):
        cache = Path(user_cache_dir(APP_NAME, appauthor=False)) / "matplotlib"
        cache.mkdir(parents=True, exist_ok=True)
        os.environ["MPLCONFIGDIR"] = str(cache)


class ModelError(RuntimeError):
    """The face model is missing or doesn't match its pinned checksum."""


def verify_model() -> Path:
    """Check the model against its pinned SHA-256 (DECISIONS.md D5); return its path.

    Same check as scripts/fetch_model.py, repeated at startup so a damaged or swapped
    model file is refused instead of silently changing tracking behaviour.
    """
    model, checksum = model_path(), model_checksum_path()
    if not model.is_file() or not checksum.is_file():
        raise ModelError(
            f"Face model not found at {model}. "
            "From source, run: uv run python scripts/fetch_model.py"
        )
    expected = checksum.read_text(encoding="utf-8").split()[0].lower()
    actual = hashlib.sha256(model.read_bytes()).hexdigest()
    if actual != expected:
        raise ModelError(f"Face model {model} failed its checksum check")
    return model
