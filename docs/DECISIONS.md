# Decisions

Each entry: context, options, choice, why. Newest last. Dependency additions need a
one-line justification here (CLAUDE.md §13).

---

## D1. Python 3.12 (2026-10-06)

- **Context:** CLAUDE.md §5 said 3.11, "3.12 only if supported everywhere".
- **Options:** 3.11, 3.12.
- **Choice:** 3.12 (`requires-python = ">=3.12,<3.13"`, `.python-version`).
- **Why:** since 0.10.30 MediaPipe ships `py3-none` wheels (a ctypes wrapper around a native
  library), so the Python version no longer gates MediaPipe. PySide6 6.11 (3.10–3.14), pynput,
  and PyInstaller 6.22 all support 3.12. 3.12 is installed on the dev machine; 3.11 gets
  security fixes only until Oct 2027. Confirmed by the owner. S1/S5 verify per OS.

## D2. Drop Intel Mac in v1 (2026-10-06)

- **Context:** CLAUDE.md listed macOS arm64 + x64. PyPI shows the last `macosx_x86_64` MediaPipe
  wheel was 0.10.21 (Feb 2025); 0.10.30 through 1.1.0 ship macOS arm64 only.
- **Options:** drop Intel Mac; pin 0.10.21 everywhere; split pins per platform.
- **Choice:** drop Intel Mac. macOS support means Apple Silicon only.
- **Why:** pinning a 2025 release freezes the whole project on unmaintained tracking code; split
  pins double the test matrix. Confirmed by the owner. README will list it as a limitation.

## D3. Exact pin `mediapipe==1.0.1` (2026-10-06)

- **Context:** tracking behaviour (landmarks, blendshape scores) drives every threshold.
- **Choice:** exact pin; everything else uses compatible ranges and the `uv.lock` lockfile.
- **Why:** an unreviewed MediaPipe upgrade could silently shift gesture thresholds. 1.0.1 had
  ~7 weeks in the wild; 1.1.0 was released on the day of planning. Upgrades are deliberate and
  re-run the gesture benchmark.

## D4. uv for environments and the lockfile (2026-10-06)

- **Justification (dev tooling, not a runtime dependency):** one cross-platform lockfile
  (`uv.lock`) so CI on three OSes installs identical versions; fast cached CI installs.
- **Alternatives:** pip + venv + pip-tools (per-OS requirements files, slower).

## D5. Model asset URL and SHA-256 pin (2026-10-06)

- **URL** (from the official Face Landmarker docs):
  `https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task`
- **Pinned SHA-256:** `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff`
  (3,758,596 bytes; Last-Modified 2023-05-03; MD5 matches the bucket's `x-goog-hash`).
  The versioned `/float16/1/` path serves identical bytes.
- **Why `latest` + checksum:** it is the URL the docs give; if Google replaces the file, the
  build fails loudly instead of silently changing tracking behaviour.
- `scripts/fetch_model.py` downloads to a temp file and only moves it into place after the
  checksum matches. The model file is not committed (`.gitignore`).

## D6. PyInstaller onedir, not onefile (2026-10-06)

- **Why:** onefile unpacks ~370 MB to a temp dir on every launch (slow start), triggers more
  antivirus false positives, and makes PySide6's LGPL libraries harder to replace.

## D7. Spikes live in `spikes/`, outside the package (2026-10-06)

- **Why:** M0 must not produce application code. Spikes are experiments: excluded from mypy
  and from the wheel, linted by ruff only. Anything worth keeping is rewritten properly in the
  milestone that needs it.

## D8. `opencv-contrib-python` instead of `opencv-python` (2026-10-06)

- **Context:** CLAUDE.md §5 says "OpenCV". MediaPipe 1.0.1 declares a dependency on
  `opencv-contrib-python`. Installing `opencv-python` as well puts two packages that both
  provide the `cv2` module into one environment, which breaks unpredictably.
- **Choice:** depend on `opencv-contrib-python` directly (we import `cv2` ourselves).
- **Cost:** `cv2.pyd` is ~108 MB on Windows. Revisit at M6 (bundle trimming).

## D9. Repository moved out of OneDrive (2026-10-07)

- **Context:** the venv (~1 GB) and build output (~375 MB per build) were inside a OneDrive
  folder, which would sync them and lock files during builds.
- **Choice:** the working repo is `C:\dev\nodwell`. The old OneDrive folder is a stale copy.

## D10. Packaged-app dependencies pulled in by MediaPipe (2026-10-06, observation)

- MediaPipe 1.0.1 also requires `matplotlib`, `sounddevice`, `absl-py`, `flatbuffers`, and
  `certifi`. `mediapipe.tasks.python.vision` imports `matplotlib.pyplot` eagerly (via
  `drawing_utils`), so matplotlib cannot be excluded from bundles. We set `MPLBACKEND=Agg`
  before importing MediaPipe so it never selects a GUI backend.
- No new dependencies were added beyond CLAUDE.md §5; these are transitive.

## D11. M1 threading: camera thread + one pipeline thread, latest-frame slot (2026-10-09)

- **Context:** the owner asked for an architecture that is "super light and fast".
- **Options:** (a) one thread per stage with queues; (b) camera thread + one pipeline thread;
  (c) multiprocessing.
- **Choice:** (b). The camera thread puts frames into a one-item `LatestSlot` that overwrites
  instead of queuing; the pipeline thread runs MediaPipe, features, filters, the engine, and OS
  input back to back. UI and hotkeys send commands through a `queue.SimpleQueue`, drained once
  per frame. The UI gets status snapshots through a queued Qt signal at 15 Hz.
- **Why:** capture overlaps inference (both release the GIL), lag can never build up, and there
  is no thread hop between tracking and moving the cursor. Processes would add copying and
  start-up cost for no gain: the per-frame Python work is far below a millisecond.
- **Safety:** a `SafetyGate` (`threading.Event`) is checked before every OS action. The panic
  hotkey closes it from the hotkey thread, so output stops even if the pipeline is busy. The
  gate reopens only when the engine *enters* Active.

## D12. Pointer coordinates are OS input coordinates of the primary screen (2026-10-09)

- **Context:** S2 (the DPI check) has not been run yet. On Windows, Qt 6 makes the process
  per-monitor DPI-aware, so pynput works in physical pixels while Qt geometry is logical.
- **Choice:** the engine works in OS input coordinates: Qt geometry × device pixel ratio on
  Windows and X11, × 1 on macOS (Quartz events use points, like Qt). `QApplication` is created
  before pynput. The dwell radius is scaled by the same factor. M1 covers the primary screen only.
- **Defence:** each frame the real cursor is read back. If it isn't where the engine put it, a
  person moved the mouse: the engine yields for 1.5 s and adopts that position.
- **To verify:** M1 manual test step "four corners".

## D13. Pause gesture: hold eyebrows up 2 s, which toggles; resume also recenters (2026-10-09)

- **Context:** P0.6 needs a hands-free pause, and resume must be deliberate. The gesture engine
  is M4, and calibration is M2.
- **Choice:** one `HoldGesture` on `browInnerUp` (on 0.5, off 0.35, hold 2 s, cooldown 1 s).
  It must be released before it can fire again. Resume recenters, so a user can rest with
  their head turned and come back cleanly. The name is checked against the model's runtime
  blendshape list; if it's missing, the gesture is disabled and the panel says so.
- **Why eyebrows, not jaw:** yawning and talking open the jaw for seconds; a sustained
  eyebrow raise is rarer and is a common reliable gesture for persona C.
- **Risk:** thresholds are uncalibrated until M2. The panel shows a live meter with the
  threshold marked, and the values are in the settings file.

## D14. MediaPipe VIDEO mode (synchronous) for M1 (2026-10-09)

- **Choice:** `detect_for_video` on the pipeline thread rather than LIVE_STREAM callbacks.
- **Why:** simpler control flow, directly timeable, and the latest-frame slot already drops
  stale frames. Revisit only if `bench/latency.py` shows inference is the bottleneck.

## D15. App bundle trimming (2026-10-09)

- `packaging/nodwell.spec` drops files the app never loads: `opencv_videoio_ffmpeg*.dll`
  (video-file decoding; we only open cameras), `opengl32sw.dll` (software OpenGL; widgets paint
  with the CPU), the Qt Quick/QML stack, virtual keyboard, PDF plugin, and Qt's translations.
  Measured on Windows: 376 MB → 303 MB. The trimmed build passes `--smoke-test`.
- In frozen builds matplotlib's font cache goes to the user cache folder instead of PyInstaller's
  per-launch temp folder, so it isn't rebuilt on every start (font metadata only).

## D16. Cursor easing between camera frames (2026-10-09)

- **Context:** the owner asked to "smooth things out". At 20–30 camera frames/s the cursor
  moved in visible jumps.
- **Choice:** a `PointerAnimator` thread (~125 Hz) eases the real cursor toward the engine's
  target, with pos += (target − pos)·(1 − e^(−dt/τ)) and τ = 16 ms by default (setting
  `pointer.motion_smoothing_ms`; "Glide between frames" in the panel, 0 = off). Clicks first
  snap exactly to the target. Writes happen under the animator's lock (lock order: animator,
  then output) so a stale in-between position can never follow a snap.
- **Consequence:** "did a person move the mouse?" now compares the real cursor with what we
  last *wrote*, not with the engine's target (`GatedInput.external_move`).

## D17. Click types, toolbar, drag and scroll (2026-10-09)

- **Context:** the owner asked for right and double click. This pulls P0.4 (click-type
  toolbar) and P0.5 (scroll) forward from M4.
- **Choice:**
  - A docked, never-focused toolbar offers Left, Right, Double, Drag, and Scroll. A choice
    applies to the next dwell, then reverts to Left (`dwell.sticky_click_type`).
  - Drag: dwell to grab, dwell again to drop.
  - Scroll: dwell to anchor, then head pitch relative to the anchor scrolls, with fractional
    wheel steps on Windows. Turn away or rest 2.5 s to stop.
  - Dwells and gestures landing on our own windows are always plain left clicks (`SetOwnUi`),
    so choosing "Right" on the toolbar doesn't itself become a right click.
  - The same choices sit on the panel's Home tab for keyboard users (SECURITY_AUDIT A1).
- **Edge scroll zones** (optional in P0.5) are not done yet.

## D18. Gesture bindings and defaults (2026-10-09)

- **Choice:** settings schema v2 replaces the single pause gesture with a list of bindings
  (source, action, on/off thresholds, hold, cooldown, enabled). It is migrated from v1.
  - Sources: any blendshape name read from the model at runtime, plus derived `smile`,
    `head_tilt_left`, and `head_tilt_right` (roll relative to neutral, 30° = 1.0).
  - Defaults: eyebrows held 2 s = pause/resume; tilt right 12° for 0.4 s = right click; tilt
    left = double click; mouth (left click) and smile (drag) are off by default.
- **Gesture anchor:** while a gesture builds, the cursor freezes where it was 150 ms before
  the hold began, and stays there 0.5 s after it fires, so the head movement of the gesture
  doesn't move the click.
- **Why tilts:** they're deliberate, rarely held by accident, and need no facial expression.
  The tilt direction is derived from the transform maths, not yet measured; the
  `gestures.swap_tilt` setting fixes it in one step if wrong.

## D19. Logging policy (2026-10-09)

- **Choice:** the persistent log keeps start-up information, warnings, and errors only.
  Per-action details (clicks, positions) are DEBUG, off by default. A static test enforces
  this (SECURITY_AUDIT F1).
- **Why:** CLAUDE.md §4.1 lists what may persist; a usage trace is not on it.

## D20. MediaPipe pinned to 0.10.21; supersedes the version in D3 (2026-10-09)

- **Context:** the VAPT found MediaPipe 1.0.1 uploading usage telemetry to
  `play.googleapis.com` from native code, with no documented opt-out (SECURITY_AUDIT F0).
  That breaks CLAUDE.md §4.2.
- **Options:** switch to 0.10.21 (reported clean); keep 1.0.1 behind an installer firewall
  rule; keep it and disclose it; defer.
- **Choice (owner):** 0.10.21. The exact-pin rule of D3 still applies.
- **Verified:** no Clearcut client or endpoint in its native code; zero sockets in 3 of 3
  probed runs of the packaged app; all tests pass.
- **Costs:** numpy 1.26.4, OpenCV 4.11, protobuf 4.25.9 (CVE-2026-0994 is not reachable; F9).
  MediaPipe ships OpenCV 3.4.10 (F10). jax, jaxlib, scipy, and sentencepiece are installed as
  dependencies but not imported, so they aren't bundled.
- **Guard:** a test fails if a future wheel contains the uploader.
- **Note for the owner:** 0.10.21 has a `universal2` macOS wheel, so Intel Macs could be
  supported again. D2 is unchanged until the owner decides.

## D21. Release-bundle hygiene (2026-10-09)

- The spec excludes the type-checker plugin chain (`pydantic.mypy` → mypy and its helpers)
  and Windows' own UCRT/API-set DLLs. PyInstaller had copied those from a Java install on
  the build machine's PATH (SECURITY_AUDIT F7, F8). Release builds should come from CI with a
  clean PATH (M6).
