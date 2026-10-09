# Status

_Last updated: 2026-10-09_

## Current milestone: M1, pointer MVP, plus pulled-forward click types and gestures

Branch `m1-pointer-mvp`. M0 is still **not marked done**: spikes S1 to S4 were never run by
hand. The M1 manual test covers the same ground.

### Done (built; automated checks green)
- **M1 pointer MVP:** head pointer (absolute and relative), One Euro smoothing, dwell click
  with progress ring, recenter, pause and resume (button, tray, hotkey, eyebrow hold),
  freeze on face loss, auto-pause, panic hotkey, latency bench, settings file, Windows exe.
- **Owner request, "smooth things out":** cursor glides between camera frames (D16); the
  panel is reorganised into Home, Gestures, and Pointer tabs with live −/+ tuning.
- **Owner request, more click types:**
  - Click-type toolbar with Left, Right, Double, Drag, and Scroll (D17); the same choices
    are on the panel for keyboard users.
  - Gesture bindings with live meters (D18): tilt right = right click, tilt left = double
    click, eyebrows = pause. Mouth and smile are available but off.
  - Settings schema v2 with a migration from v1.
- **Owner request, VAPT and audit:** `docs/SECURITY_AUDIT.md`. 13 findings, 11 fixed and
  2 accepted with reasons.
  - Most important: MediaPipe 1.0.1 sent usage telemetry to Google; it's now pinned to
    0.10.21 (D20, owner's choice), and the packaged app was verified to open no sockets.
  - `tests/test_security.py` adds static guards, fuzzing, and supply-chain guards.
- **Checks:** ruff, ruff format, mypy (strict on core), and **183 tests** pass. `--smoke-test`
  passes from source and from the exe (run with Python hidden from PATH). Exe: 302 MB, 343
  files.

### Waiting on the owner
- **Manual tests on Windows** (`docs/MANUAL_TESTS.md`): the "M1 pointer MVP" steps and the new
  "Click types, gestures, and smoothing" steps. They include the first real latency run and
  the head-tilt direction check.
- Whether to restore Intel Mac support, now possible with MediaPipe 0.10.21 (D20 note, D2).
- M0: S1 to S4 manual runs.
- Pushed to https://github.com/KabirRao1/NodWell on 2026-10-09; the first CI runs on macOS and
  Linux are the first time the code has been tested on those systems.

### Known gaps and risks
- Not yet measured: yaw/pitch and tilt directions, gesture thresholds (calibration is M2),
  the camera frame rate (about 20 fps in one short low-light check), and real latency.
- Socket and file probes ran on Windows only.
- Not done yet: edge scroll zones (optional in P0.5), multi-monitor beyond the primary
  screen, code signing.

### Next
- Fix whatever the manual tests turn up, record latency in METRICS.md, then report M1.
- M2 (Control Center, calibration, onboarding) only after owner approval.

### Open questions
- License: deferred by the owner (no LICENSE file yet).
