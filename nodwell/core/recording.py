"""Save and replay FeatureFrame streams as JSONL (numbers only, never pixels).

Recording is opt-in (`--record`). Replays drive deterministic tests and benchmarks without
a camera (CLAUDE.md §6).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from types import TracebackType
from typing import IO

from .frame import FeatureFrame


class Recorder:
    """Appends one JSON object per FeatureFrame to a file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._file: IO[str] = path.open("a", encoding="utf-8")

    def write(self, frame: FeatureFrame) -> None:
        self._file.write(json.dumps(frame.to_dict(), separators=(",", ":")) + "\n")

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> Recorder:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def read_frames(path: Path) -> Iterator[FeatureFrame]:
    """Yield the FeatureFrames stored in a JSONL file, skipping blank lines."""
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield FeatureFrame.from_dict(json.loads(line))
