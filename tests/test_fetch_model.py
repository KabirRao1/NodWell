"""Tests for scripts/fetch_model.py. No network: downloads are faked."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.fetch_model import (
    CHECKSUM_PATH,
    ChecksumError,
    Downloader,
    ensure_model,
    read_pinned_hash,
    sha256_of,
    verify,
)

GOOD = b"pretend model bytes"
GOOD_HASH = hashlib.sha256(GOOD).hexdigest()


@pytest.fixture
def checksum_file(tmp_path: Path) -> Path:
    path = tmp_path / "model.sha256"
    path.write_text(f"{GOOD_HASH}  model.task\n", encoding="utf-8")
    return path


def fake_download(payload: bytes, calls: list[str] | None = None) -> Downloader:
    def _download(url: str, dest: Path) -> None:
        if calls is not None:
            calls.append(url)
        dest.write_bytes(payload)

    return _download


def test_repo_checksum_file_is_well_formed() -> None:
    assert len(read_pinned_hash(CHECKSUM_PATH)) == 64


def test_sha256_of_matches_hashlib(tmp_path: Path) -> None:
    f = tmp_path / "x"
    f.write_bytes(GOOD)
    assert sha256_of(f) == GOOD_HASH


def test_verify_rejects_tampered_file(tmp_path: Path) -> None:
    f = tmp_path / "x"
    f.write_bytes(GOOD + b"!")
    with pytest.raises(ChecksumError, match="expected"):
        verify(f, GOOD_HASH)


def test_verify_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ChecksumError, match="missing"):
        verify(tmp_path / "nope", GOOD_HASH)


def test_read_pinned_hash_rejects_garbage(tmp_path: Path) -> None:
    f = tmp_path / "bad.sha256"
    f.write_text("not-a-hash\n", encoding="utf-8")
    with pytest.raises(ValueError):
        read_pinned_hash(f)


def test_ensure_model_downloads_and_verifies(tmp_path: Path, checksum_file: Path) -> None:
    calls: list[str] = []
    model = tmp_path / "models" / "model.task"
    ensure_model(model, checksum_file, url="u", download=fake_download(GOOD, calls))
    assert model.read_bytes() == GOOD
    assert calls == ["u"]


def test_ensure_model_skips_download_when_present(tmp_path: Path, checksum_file: Path) -> None:
    calls: list[str] = []
    model = tmp_path / "model.task"
    model.write_bytes(GOOD)
    ensure_model(model, checksum_file, download=fake_download(GOOD, calls))
    assert calls == []


def test_ensure_model_bad_download_leaves_nothing_behind(
    tmp_path: Path, checksum_file: Path
) -> None:
    model_dir = tmp_path / "models"
    model = model_dir / "model.task"
    with pytest.raises(ChecksumError):
        ensure_model(model, checksum_file, download=fake_download(b"evil"))
    assert not model.exists()
    assert list(model_dir.iterdir()) == []  # no leftover .part file
