"""Download the MediaPipe Face Landmarker model and verify its pinned SHA-256.

Used at build time and by the spikes; the app itself never downloads anything
(CLAUDE.md §4.2). The URL is the one given in the official Face Landmarker docs:
https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker

The pinned checksum lives in models/face_landmarker.sha256 in `sha256sum` format,
so `sha256sum -c models/face_landmarker.sha256` (run inside models/) also works.

Usage:
    python scripts/fetch_model.py           # download if missing, then verify
    python scripts/fetch_model.py --verify  # verify only, never touch the network
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import tempfile
import urllib.request
from collections.abc import Callable
from pathlib import Path

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "face_landmarker/face_landmarker/float16/latest/face_landmarker.task"
)
REPO_ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = REPO_ROOT / "models"
MODEL_PATH = MODELS_DIR / "face_landmarker.task"
CHECKSUM_PATH = MODELS_DIR / "face_landmarker.sha256"

Downloader = Callable[[str, Path], None]


class ChecksumError(RuntimeError):
    """Raised when a model file does not match its pinned SHA-256."""


def sha256_of(path: Path) -> str:
    """Return the lowercase hex SHA-256 digest of the file at `path`."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_pinned_hash(checksum_path: Path) -> str:
    """Read the hex digest from a `sha256sum`-format file (`<hex>  <filename>`)."""
    text = checksum_path.read_text(encoding="utf-8").split()
    if not text or len(text[0]) != 64:
        raise ValueError(f"{checksum_path} does not contain a SHA-256 digest")
    return text[0].lower()


def verify(path: Path, expected: str) -> None:
    """Raise ChecksumError unless `path` exists and hashes to `expected`."""
    if not path.is_file():
        raise ChecksumError(f"{path} is missing")
    actual = sha256_of(path)
    if actual != expected:
        raise ChecksumError(f"{path} has SHA-256 {actual}, expected {expected}")


def _urllib_download(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url, timeout=60) as resp, dest.open("wb") as out:
        while chunk := resp.read(1 << 20):
            out.write(chunk)


def ensure_model(
    model_path: Path = MODEL_PATH,
    checksum_path: Path = CHECKSUM_PATH,
    url: str = MODEL_URL,
    download: Downloader = _urllib_download,
) -> Path:
    """Make sure a verified model exists at `model_path`, downloading it if needed.

    The download goes to a temporary file in the same directory and is only moved
    into place after its checksum matches, so a failed or tampered download never
    leaves a bad model behind.
    """
    expected = read_pinned_hash(checksum_path)
    if model_path.is_file():
        verify(model_path, expected)
        return model_path

    model_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=model_path.parent, suffix=".part", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        download(url, tmp_path)
        verify(tmp_path, expected)
        tmp_path.replace(model_path)
    finally:
        tmp_path.unlink(missing_ok=True)
    return model_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--verify", action="store_true", help="only verify an existing model; no network"
    )
    args = parser.parse_args(argv)
    try:
        if args.verify:
            verify(MODEL_PATH, read_pinned_hash(CHECKSUM_PATH))
        else:
            ensure_model()
    except (ChecksumError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"ok: {MODEL_PATH} matches {CHECKSUM_PATH.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
