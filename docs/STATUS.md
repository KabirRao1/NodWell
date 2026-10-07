# Status

_Last updated: 2026-10-07_

## Current milestone: M0, scaffolding and risk spikes

### Done
- Repo scaffolding: `pyproject.toml` (Python 3.12, pinned deps), `uv.lock`, `.gitignore`
  (blocks image/video files), `nodwell/` and `nodwell/core/` packages (empty).
- Tooling: ruff (lint + format), mypy (strict flags on `nodwell.core.*`, verified with a probe),
  pytest. All pass locally on Windows (11 tests).
- `tests/test_import_boundaries.py`: `core/` can't import Qt, OpenCV, MediaPipe, pynput, or pyttsx3.
- `scripts/fetch_model.py`: downloads the Face Landmarker model and verifies the pinned
  SHA-256 (tested: good, tampered, missing, and failed-download cases).
- CI workflow (`ci.yml`): lint, format, types, and tests on Windows, macOS 14 (arm64), and Ubuntu 24.04.
- Build workflow (`build-spike.yml`): PyInstaller self-test bundle on all three OSes.
- Spikes S1 to S5 written. **S5 passes locally on Windows** (see SPIKE_NOTES).
- Docs: DECISIONS (D1 to D10), SPIKE_NOTES, MANUAL_TESTS, METRICS template.

### In progress / waiting on the owner
- **S1 to S4 manual runs on Windows** (steps in `docs/MANUAL_TESTS.md`).
- **First push to GitHub** so CI and the build workflow run. The owner creates an empty repo.

### Blocked
- macOS arm64 and Linux X11 manual spikes: no hardware yet.
- S5 true clean-machine test: no second PC/VM (Windows 11 Home has no Windows Sandbox).

### Next
- Fill in SPIKE_NOTES from the S1 to S4 results; fix anything they turn up.
- Report M0 to the owner. M1 starts only after approval (CLAUDE.md §11).

### Open questions
- License: deferred by the owner (no LICENSE file yet).
