# Status

_Last updated: 2026-10-09_

## Current milestone: M1, pointer MVP (branch `m1-pointer-mvp`)

M1 was started at the owner's request before M0's manual spike runs. **M0 is not marked
done**: S1 to S4 were never run. The M1 manual test (docs/MANUAL_TESTS.md) covers the same
ground: camera fps, DPI coordinates, and the overlay.

### Done (built, automated checks green)
- `nodwell/core/`: head pose from the transformation matrix, One Euro filter with a
  Smoothness mapping, absolute and relative pointer (dead zone, acceleration, invert), dwell
  detector (radius tolerance, no repeat until you move away), hold gesture (hysteresis, hold,
  latch, cooldown), safety gate, click rate limiter, versioned settings with safe fallback,
  latest-frame slot, stage timing, FeatureFrame recorder and replayer, interaction engine.
- Engine behaviour: waits for a stable face, then recenters and goes Active; freezes the
  instant the face is lost; auto-pauses after 5 s; 0.3 s grace when the face returns; pause
  and resume by eyebrow hold (resume recenters); yields to a real mouse; suggests (never
  applies) recentering when the resting pose drifts.
- `tracking/`, `platform/`, `pipeline.py`: camera thread, MediaPipe VIDEO-mode tracker,
  pynput backend behind the safety gate, global hotkeys (Ctrl+Alt+P / R / Q).
- UI: status panel (64 px controls, live gesture meter with the threshold marked, quality
  messages), click-through dwell ring, tray icon, single-instance lock.
- `bench/latency.py`: per-stage p50/p95, fps, CPU, peak memory.
- `packaging/nodwell.spec`: windowed onedir build `dist/Nodwell/Nodwell.exe`, 303 MB (was 376 MB
  before trimming).
- Checks: ruff, ruff format, mypy (strict on core), **87 tests** pass. `--smoke-test` passes
  from source and from the exe (exe run with Python hidden from PATH). `bench/latency.py`
  runs (5 s check, no face in view, so no numbers recorded).
- Docs: DECISIONS D11 to D15, MANUAL_TESTS (M1 section).

### Waiting on the owner
- **M1 manual test on Windows** (docs/MANUAL_TESTS.md › M1). Includes the first real latency
  run, which goes into METRICS.md.
- M0: S1 to S4 manual runs (now partly covered by M1's test), first push to GitHub.

### Known gaps and risks
- Yaw/pitch direction and the eyebrow threshold come from documentation and reasoning, not
  measurement. Manual steps 2 and 8 check them; both are one-line settings changes if wrong.
- The camera read waited about 50 ms per frame in the one short bench run, i.e. the camera
  delivered roughly 20 fps rather than 30. Low light can cause this (longer exposure). The
  real latency run will tell.
- The dev machine's primary screen reported 1920x1080 at 100%, but SPIKE_NOTES lists a
  2880x1800 panel. Step 3 checks this.
- Only the primary monitor is supported (P0 minimum). macOS and Linux are untested.

### Next
- Fix whatever the manual test turns up, record latency in METRICS.md, then report M1.
- M2 (Control Center, calibration, onboarding) only after owner approval.

### Open questions
- License: deferred by the owner (no LICENSE file yet).
