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


def load_model() -> bytes:
    """Read the face model and check it against its pinned SHA-256 (DECISIONS.md D5).

    Returns the verified bytes, which are handed to MediaPipe as-is. Reading once and
    loading from memory means the file can't be swapped between the check and the load
    (a time-of-check/time-of-use gap; docs/SECURITY_AUDIT.md F3).
    """
    model, checksum = model_path(), model_checksum_path()
    if not model.is_file() or not checksum.is_file():
        raise ModelError(
            f"Face model not found at {model}. "
            "From source, run: uv run python scripts/fetch_model.py"
        )
    expected = checksum.read_text(encoding="utf-8").split()[0].lower()
    data = model.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ModelError(f"Face model {model} failed its checksum check")
    return data


def lock_path() -> Path:
    """Single-instance lock file, in a per-user folder.

    Not the shared temp folder: on Linux and macOS another user could create the lock
    there first and stop Nodwell from starting (docs/SECURITY_AUDIT.md F4).
    """
    folder = Path(user_cache_dir(APP_NAME, appauthor=False))
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "nodwell.lock"
