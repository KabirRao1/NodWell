# Security and privacy audit (VAPT), 2026-10-09

Scope: the Nodwell app as of branch `m1-pointer-mvp` (M1 plus click types, gestures, and the
click-type toolbar), from source and as the packaged Windows build `dist/Nodwell/Nodwell.exe`.
Performed by Claude Code at the owner's request. **Not** an independent third-party audit.

## Summary

| ID | Finding | Severity | Status |
|---|---|---|---|
| F0 | MediaPipe 1.0.1 uploads usage telemetry to Google from native code | **High** (breaks CLAUDE.md §4.2) | **Fixed**: pinned 0.10.21, verified, regression test |
| F1 | Log file recorded the screen position of every click | Medium (privacy) | Fixed, guard test |
| F5 | A drag could leave the mouse button held down | Medium (safety) | Fixed by design, tests |
| F6 | NaN/infinite pose values crashed the pipeline | Medium (robustness) | Fixed, fuzz test |
| F7 | Build copied system DLLs from an unrelated program on the build machine | Medium (supply chain) | Fixed in the spec |
| F2 | Settings file with a wrong-type `schema_version` crashed start-up | Low | Fixed, fuzz test |
| F3 | Model hashed, then re-read by path (check/use gap) | Low (integrity) | Fixed |
| F4 | Single-instance lock in a shared temp folder (Linux/macOS) | Low (local DoS) | Fixed |
| F8 | Dev tools (mypy and helpers) shipped inside the app | Low | Fixed |
| F9 | protobuf 4.25.9: CVE-2026-0994 (DoS in `json_format`) | Low (not reachable) | Accepted, guard test |
| F10 | MediaPipe 0.10.21 ships its own OpenCV 3.4.10 (2020) | Low | Accepted |
| F11 | UI-made settings changes skipped validation | Low | Fixed |
| F12 | Cursor-easing thread could die silently on an input error | Low | Fixed |
| A1 | Click types not reachable by keyboard (toolbar never takes focus) | Accessibility | Fixed |

After the fixes, all automated checks pass (183 tests), and the packaged app opened **no
network sockets** in 3 of 3 probed runs.

## Threat model

- **What it is:** a local desktop app. It has no server, no accounts, and is meant to make
  no network calls. It reads the webcam and injects mouse input.
- **Assets:** the camera stream and the face data derived from it (privacy); control of the
  user's mouse (safety: unwanted clicks, a stuck button, being unable to stop it); files
  on disk (settings, logs).
- **Adversaries considered:** malicious or broken input files (settings, replay recordings);
  other local users and processes; third-party dependencies (supply chain); the build
  machine itself.
- **Out of scope:** an attacker who already runs code as the same user. They can already
  read the camera and move the mouse without Nodwell. Physical attacks. macOS and Linux
  runtime behaviour (no hardware; see residual risks).

## Method

1. **Code review** of everything written in M1 and after: threading and locks, error paths,
   cleanup, fail-safes, and what gets persisted or logged.
2. **Automated security tests** (`tests/test_security.py`, run in CI on all three OSes):
   - Static guards: the package imports no networking, process-spawning, or unsafe
     deserialisation modules, calls no `eval`/`exec`/shell, has no pixel-writing calls, and
     its log calls never include click positions.
   - Fuzzing, seeded and reproducible:
     - 400 random settings documents plus 16 hostile cases (wrong types, NaN, infinity,
       100,000-deep nesting, oversized files).
     - Engine invariants over 40 seeds × 600 random frames and commands, with NaN,
       infinity, and huge values mixed in.
     - Six kinds of corrupt replay file.
   - Model integrity: a tampered or missing model is refused.
   - Supply-chain guards: no telemetry client in MediaPipe's native code; protobuf's
     vulnerable parser stays unreachable.
3. **Runtime probes on the packaged exe (Windows):**
   - Sockets: the OS connection tables (`Get-NetTCPConnection`/`Get-NetUDPEndpoint`, then
     `netstat` at 40 ms intervals) were polled for the process during `--smoke-test` runs.
     This catches native code that the Python-level tripwire cannot see.
   - Files: every file under the user profile created or modified during a run was listed.
4. **Bundle review:** every DLL, `.pyd`, and `.exe` in `dist/Nodwell`, with its Authenticode
   signer and where the build took it from (`build/nodwell/Analysis-00.toc`).
5. **Dependency CVE scan:** `pip-audit` (run through `uvx`, not added to the project) over every
   locked runtime package for all three OSes. Only package names and versions were sent to
   the PyPI/OSV advisory service, as approved in the plan.

## Findings

### F0. MediaPipe 1.0.1 sends usage telemetry to Google (High). Fixed

- **What:** while running, the packaged app opened an HTTPS connection to
  `172.217.118.4:443` (2 of 2 runs, at about 5 s, around shutdown). The Python tripwire saw
  nothing, so it came from native code.
- **Evidence:**
  - `libmediapipe.dll` (MediaPipe 1.0.1) contains a `ClearcutLoggingClient` in
    `mediapipe::tasks::core::google_internal::logging`, Google's Clearcut uploader classes,
    and the endpoint string `https://play.googleapis.com/log`.
  - MediaPipe's Python wrapper passes it a TLS certificate bundle plus the host OS, Python
    version, and app-ID fields.
  - In the local DNS cache, `play.googleapis.com` resolved to exactly that IP.
  - The IP is a shared Google front end, so this is strong circumstantial evidence, not a
    packet capture.
- **Outside corroboration:**
  - A public report found telemetry added between 0.10.21 and 0.10.35, and none in 0.10.21:
    [google-ai-edge/mediapipe#6291](https://github.com/google-ai-edge/mediapipe/issues/6291).
  - Google's [MediaPipe terms](https://ai.google.dev/edge/mediapipe/legal/tos) say the APIs
    send usage and performance metrics to Google, and describe no opt-out.
- **Not established:** exactly what the uploads contain. Google's terms say input data
  (camera frames) stays on the device; we did not decrypt the traffic. We also did not find
  what triggers the upload: a plain Python harness never connected in 4 runs, while the exe
  did every time.
- **Fix (owner's decision):** pinned `mediapipe==0.10.21`. Its native code contains no
  Clearcut client and no endpoint. The packaged app opened **zero sockets in 3 of 3**
  probed runs.
- **Guard:** `test_mediapipe_native_code_has_no_usage_telemetry` scans the installed wheel's
  native libraries and fails if the uploader appears. It runs in CI, so it checks the
  macOS and Linux wheels too.
- **Cost of the fix:** numpy 1.26, OpenCV 4.11, protobuf 4.25 (see F9). MediaPipe 0.10.21 also
  ships OpenCV 3.4.10 (see F10). The tracking API and results are unchanged. One check was
  needed: 0.10.21 rebuilds the pose matrix from column-major data correctly.

### F1. Click positions in the persistent log (Medium, privacy). Fixed

The pipeline logged every click's screen coordinates at INFO, which goes to a log file
that's kept between runs. Over time that becomes a usage trace, which conflicts with CLAUDE.md
§4.1 ("the only persisted data is settings…"). Per-action logging is now DEBUG only (off by
default), and the log keeps start-up information, warnings, and errors (D19). A static test
fails if an INFO or higher log call mentions a click, cursor, or pointer position.

### F5. Stuck mouse button during drag (Medium, safety). Fixed by design

Drag holds the left button down between two dwells. If tracking stopped in between, the
button could stay held. The output layer now tracks held buttons and releases them, even
with the safety gate closed, on: pause, the panic hotkey, face loss, a person taking over
the mouse, quit, and a pipeline crash. The engine also releases on any interruption.
Tests: `test_held_drag_button_released_on_interruption` (pause, face lost, manual mouse),
`test_release_always_goes_through_even_with_gate_closed`, and the fuzz invariant "never
dragging while paused or faceless".

### F6. Non-finite pose values crashed the pipeline (Medium). Fixed

A NaN or infinite yaw, pitch, or roll (from a broken tracker frame or an edited replay file)
flowed through the filters into cursor coordinates. The first `round(nan)` then crashed the
pipeline thread. That failed safe (gate closed) but stopped the app. Such frames now count
as "no face", and non-finite gesture scores are ignored. Found by the engine fuzzer (34 of
40 seeds failed before the fix, 0 after).

### F7. System DLLs copied from the build machine (Medium, supply chain). Fixed

PyInstaller bundled `ucrtbase.dll` and the `api-ms-win-*.dll` files (41 Eclipse-signed DLLs) from
`C:\Program Files\Eclipse…`, a Java runtime that happened to be on the build machine's PATH;
they were Eclipse-signed. Windows 10 and later provide these itself. Taking DLLs from
whatever is on the builder's PATH makes builds non-reproducible, and a planted DLL in any
PATH folder could ship to users. The spec now excludes them, and the build has no
Eclipse-signed files. **Recommendation:** release builds only from CI with a clean PATH
(M6).

### F2. Settings crash on a wrong-type schema version (Low). Fixed

`{"schema_version": {"a": 1}}` raised an uncaught `TypeError` at start-up. Version
checks are now strict, and `TypeError`/`RecursionError` are handled. Files over 1 MB are
refused. Any unusable file is moved to `settings.json.bak` and defaults are used.

### F3. Model check/use gap (Low). Fixed

The model was hashed and then re-opened by path, so it could in principle be swapped in
between. It is now read once, hashed, and those same bytes are handed to MediaPipe.

### F4. Lock file in a shared temp folder (Low, Linux/macOS). Fixed

Another local user could pre-create the lock in a shared `/tmp` and stop Nodwell from
starting. The lock now lives in the per-user cache folder.

### F8. Dev tools in the bundle (Low). Fixed

pydantic's optional mypy plugin pulled `mypy`, `librt`, `ast_serialize`, and `setuptools`
into the app. They're excluded now. Together with F7: 476 → 360 files (343 with MediaPipe
0.10.21).

### F9. protobuf CVE-2026-0994 (Low, not reachable). Accepted

protobuf 4.25.9 (MediaPipe 0.10.21 requires `<5`) has a denial-of-service in
`json_format.ParseDict()` with nested `Any` messages. The fix is in 5.29.6 and 6.33.5.
Nodwell never uses protobuf, MediaPipe's runtime code doesn't use `json_format`, and the
module isn't loaded when the tracker starts.
`test_vulnerable_protobuf_json_parser_is_not_reachable` keeps it that way. Revisit when
MediaPipe allows a fixed protobuf.

### F10. Old OpenCV inside MediaPipe 0.10.21 (Low). Accepted

`mediapipe/python/opencv_world3410.dll` is OpenCV 3.4.10 (2020). In Nodwell it only
processes raw camera frames in memory. It never decodes image or video files, which is
where OpenCV's historical vulnerabilities cluster.

### F11. UI settings skipped validation (Low). Fixed

pydantic's `model_copy()` does not validate. Every settings object the UI produces is now
re-validated before it's applied or saved, and invalid ones are refused.

### F12. Easing thread could die silently (Low). Fixed

An exception from the OS input call would end the cursor-easing thread. It now logs and
continues. Also: `--record` with an unwritable path no longer crashes start-up.

### A1. Click types not keyboard-reachable (Accessibility). Fixed

The toolbar is deliberately unfocusable so it never steals focus from the user's app. The
same choices are now also on the panel's Home tab, which is keyboard-reachable
(CLAUDE.md §4.3).

## Residual risks and notes

- **macOS and Linux runtime behaviour is unverified.** The socket and file probes ran on
  Windows only. CI's static and wheel scans cover the other OSes; repeat the runtime probes
  there when hardware is available.
- **Windows UIPI:** Nodwell can't click into windows running as administrator. This is by
  Windows design and documented in MANUAL_TESTS.
- **Global keyboard hook:** the caregiver hotkeys use a system-wide keyboard listener
  (pynput), so keystrokes pass through the process. Nothing is stored or logged. Some
  antivirus tools flag such hooks.
- **Unsigned binaries:** SmartScreen and Gatekeeper will warn. Code signing is an M6 item.
- **`--record`** writes facial-expression scores (numbers, never images) when explicitly
  started with that flag. Someone able to edit the user's shortcut could enable it, but that
  person can already run anything as the user.
- **Persisted data today:** `settings.json`, the rotating log (start-up, warnings, errors;
  at most 3 × 1 MB), and matplotlib's font cache (font names only). The disk probe found
  nothing else written.
- **Input contention:** any local program that moves the mouse keeps Nodwell in "mouse in
  use" mode. That's intended, so a caregiver can take over; a hostile program could use it
  to stall Nodwell, but it could equally just move the mouse itself.

## How to repeat this audit

- `uv run pytest tests/test_security.py`: static guards, fuzzing, and supply-chain guards.
- Build, then run the exe with `--smoke-test` while polling the OS connection table for its
  process ID (the PowerShell approach in "Method" above). Expect no sockets.
- `uvx pip-audit` over `uv export --no-dev --no-hashes` output.
- List signers of `dist/Nodwell/**/*.dll`: expect only Python Software Foundation, The Qt
  Company, Microsoft, or unsigned (third-party wheels), and nothing taken from the build
  machine's own programs.
