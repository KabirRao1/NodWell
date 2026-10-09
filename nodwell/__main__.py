"""Entry point: `python -m nodwell` or the packaged Nodwell executable."""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import sys
from pathlib import Path

from nodwell import __version__, paths


def setup_logging() -> Path | None:
    """Log events (never images) to a small rotating file, plus stderr when there is one."""
    handlers: list[logging.Handler] = []
    log_file: Path | None = None
    try:
        folder = paths.log_dir()
        folder.mkdir(parents=True, exist_ok=True)
        log_file = folder / "nodwell.log"
        handlers.append(
            logging.handlers.RotatingFileHandler(
                log_file, maxBytes=1_000_000, backupCount=2, encoding="utf-8"
            )
        )
    except OSError:
        log_file = None
    if sys.stderr is not None:  # windowed builds have no console
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )
    return log_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nodwell", description="Hands-free computer control with head movement."
    )
    parser.add_argument("--version", action="version", version=f"Nodwell {__version__}")
    parser.add_argument("--camera", type=int, help="camera index (overrides settings)")
    parser.add_argument(
        "--dry-run", action="store_true", help="track and show status, but never move or click"
    )
    parser.add_argument(
        "--replay", type=Path, help="drive the app from a recorded FeatureFrame JSONL file"
    )
    parser.add_argument(
        "--record",
        type=Path,
        help="opt-in: save FeatureFrames (numbers only, never images) to this JSONL file",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="start everything with synthetic frames, quit after 30 frames; exit 0 on success",
    )
    args = parser.parse_args(argv)

    log_file = setup_logging()
    logging.getLogger(__name__).info("Nodwell %s starting; log at %s", __version__, log_file)

    from nodwell.app import Options, run

    return run(
        Options(
            camera=args.camera,
            dry_run=args.dry_run,
            replay=args.replay,
            record=args.record,
            smoke_test=args.smoke_test,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
