# M0 spike notes

Each spike answers one question. Raw results are pasted unedited from the spike's
`SPIKE RESULT` block. Numbers here are **spike observations**, not `bench/` measurements, so
they are not copied into `METRICS.md` or the README (CLAUDE.md §9).

## Status matrix

| Spike | Windows x64 | macOS arm64 | Linux x64 (X11) |
|---|---|---|---|
| S1 Landmarker live | Not run (awaiting owner) | Not run (no hardware) | Not run (no hardware) |
| S2 pynput injection | Not run (awaiting owner) | Not run (no hardware) | Not run (no hardware) |
| S3 Click-through overlay | Not run (awaiting owner) | Not run (no hardware) | Not run (no hardware) |
| S4 No-focus keyboard | Not run (awaiting owner) | Not run (no hardware) | Not run (no hardware) |
| S5 PyInstaller bundle | **Pass (local, Python hidden from PATH)** 2026-10-07; true clean machine: not run | CI-only (pending first push) | CI-only (pending first push) |

Legend: Not run / Pass / Partial / Fail / CI-only (built and headless-tested in GitHub Actions,
no human check).

---

## Environment: Windows dev machine

| | |
|---|---|
| Machine | High-end 14-inch laptop |
| OS | Windows 11 Home 10.0.26200 |
| CPU | AMD Ryzen 9 8945HS (8C/16T) |
| RAM | 15.3 GB |
| GPU | NVIDIA GeForce RTX 4060 Laptop + AMD Radeon 780M (MediaPipe runs on CPU via XNNPACK) |
| Display | 2880x1800 (scaling: owner to confirm in S2) |
| Cameras | "USB2.0 FHD UVC WebCam" and "USB2.0 IR UVC WebCam" (index of each: S1 to confirm) |
| Python | 3.12.5 |
| Packages | mediapipe 1.0.1, opencv-contrib-python 5.0.0.93, numpy 2.5.3, PySide6 6.11.2, pynput 1.8.2, PyInstaller 6.22.3 (contrib hooks 2026.8) |

**Caveat:** this is a high-end laptop, not the "mid-range laptop" of CLAUDE.md §4.5. A pass
here does not show the fps target on modest hardware. We still need a run on a mid-range
machine before claiming it.

---

## Findings before any manual run (from package inspection and headless runs)

> **Update 2026-10-09:** findings 1 to 3 describe MediaPipe 1.0.1. The project now pins
> 0.10.21 (DECISIONS.md D20) because 1.0.1 uploads usage telemetry from native code, which
> the Python-level check in finding 5 could not see (SECURITY_AUDIT.md F0).

1. **MediaPipe 1.x has no `mp.solutions`.** The top-level module exposes only `Image`,
   `ImageFormat`, and `tasks`. The working API is
   `mediapipe.tasks.python.vision.FaceLandmarker` with `FaceLandmarkerOptions`
   (`running_mode`, `num_faces`, `output_face_blendshapes`,
   `output_facial_transformation_matrixes`, `result_callback`) and
   `BaseOptions(model_asset_path=...)`. Methods: `detect`, `detect_for_video`, `detect_async`.
   *Implication:* the landmark overlay in the live view must be drawn by us (Qt), not by
   MediaPipe's old drawing utils.
2. **MediaPipe 1.x is a ctypes wrapper** around `mediapipe/tasks/c/libmediapipe.{dll,so,dylib}`
   (52.7 MB on Windows), located via `importlib.resources`. PyInstaller must keep it at that
   package-relative path (`collect_dynamic_libs("mediapipe")` does).
3. **matplotlib is imported eagerly** by `mediapipe.tasks.python.vision` (via `drawing_utils`), so
   it can't be excluded from bundles. We set `MPLBACKEND=Agg` before importing.
4. **Wheels:** MediaPipe ≥ 0.10.30 has no macOS Intel wheel (DECISIONS.md D2).
5. **No network at runtime (Python level):** with a socket tripwire installed before import,
   creating the landmarker and running inference made zero connection attempts (unfrozen and
   frozen). Limitation: the tripwire patches Python's `socket` module only; native code that
   opened sockets directly would bypass it. A firewall-level check is a candidate for M6.
6. **Blank-frame inference cost:** about 1.4 to 2.6 ms per 640x480 frame with no face (detector
   only). This is not a tracking number; S1 measures real tracking.

---

## S1. MediaPipe Face Landmarker live

**Question:** Does Face Landmarker run live on the webcam at ≥ 25 fps, and what exactly does it output?

### Windows: not run yet
- **Procedure:** docs/MANUAL_TESTS.md › S1.
- **Raw result:** _pending_
- **Answer:** _pending_
- **Workarounds needed:** _pending_
- **Implications for M1+:** _pending_

### Blendshape names (read from the model at runtime)
_Pending S1._ The list is checked against the CLAUDE.md §8 P1.1 candidates (`jawOpen`,
`browInnerUp`, `browOuterUpLeft/Right`, `mouthSmileLeft/Right`, `mouthPucker`, `cheekPuff`,
`eyeBlinkLeft/Right`) and marked ✓/✗.

---

## S2. pynput input injection

**Question:** Can pynput move, click, type, and scroll in another app, and do its coordinates
agree with Qt's under display scaling?

### Windows: not run yet
- **Raw result (normal Notepad):** _pending_
- **Raw result (elevated Notepad):** _pending_
- **Answer:** _pending_
- **DPI finding:** _pending_ (compare `dpi_awareness_before_qt` / `after_qt` and `coordinates_agree`)

---

## S3. Transparent, click-through, always-on-top overlay

**Question:** Can a Qt window be transparent, click-through, and always on top, without taking focus?

### Windows: not run yet
- **Raw results (small / full / --win32):** _pending_
- **Ex-styles Qt sets by itself:** _pending_ (`exstyle_set_by_qt`)
- **Answer:** _pending_

---

## S4. Non-focus-stealing dwell keyboard

**Question:** Can a Qt window receive dwell presses (and real clicks) and send keystrokes to
another app without taking focus?

### Windows: not run yet
- **Raw results (Qt only / --win32-noactivate):** _pending_
- **Answer:** _pending_

**Design tension for M3 (known in advance):** a window that never takes focus can't also be
Tab-navigable for caregivers (CLAUDE.md §4.3). Likely fix: a caregiver mode, entered via the
Control Center, that temporarily lets the keyboard take focus.

---

## S5. PyInstaller bundle with MediaPipe and the model

**Question:** Does a PyInstaller build including MediaPipe, Qt, pynput, and the model launch on
a clean machine?

### Windows: Pass locally; true clean machine not run
- **Procedure:**
  `uv run pyinstaller --noconfirm --clean spikes/s5_pyinstaller/selftest.spec`, then ran
  `dist\nodwell-selftest\nodwell-selftest.exe` from `%TEMP%` with every Python, uv, and
  WindowsApps entry removed from `PATH` (`python` not resolvable) and
  `PYTHONHOME`/`PYTHONPATH`/`VIRTUAL_ENV` unset.
- **Build:** 92 s; onedir bundle **374 MB, 537 files**.
- **Raw result (2nd run, abbreviated):**
  ```
  "frozen": true, "mediapipe": "1.0.1", "opencv-contrib-python": "5.0.0.93",
  "PySide6": "6.11.2", "pynput": "1.8.2",
  checks: model ok (sha256 match), landmarker ok (create 0.03 s, blank-frame p50 1.38 ms),
          qt ok (platform "windows"), pynput ok (read cursor position)
  "network_attempts": [], "seconds_since_python_start": 1.48, "all_ok": true
  ```
- **Launch wall time:** 5.94 s on the first run (cold disk cache, Defender scan), 1.75 s on the second.
- **Answer:** Yes on this machine. It isn't proven on a machine that has never had Python
  installed: Windows 11 Home has no Windows Sandbox, so that check waits for a second PC or VM.
- **What the spec needed:** `collect_dynamic_libs("mediapipe")` for `libmediapipe.dll`;
  `collect_submodules("pynput")` because pynput picks its backend by name at runtime;
  `copy_metadata(...)` only so the self-test can report versions. No custom hooks were needed.
- **Largest files (trim candidates for M6):** `cv2.pyd` 107.7 MB, `libmediapipe.dll` 52.7 MB,
  `opencv_videoio_ffmpeg500_64.dll` 29.4 MB (we never decode video files, so it's likely removable),
  `PySide6/opengl32sw.dll` 19.7 MB (software OpenGL fallback), numpy OpenBLAS 19.6 MB.
- **Not yet checked:** SmartScreen behaviour on a downloaded, unsigned build; `--camera` in the frozen app.

### macOS arm64 / Linux x64: CI-only once the repo is pushed
`.github/workflows/build-spike.yml` builds and runs the headless self-test (Linux under Xvfb) and
uploads a `.tar.gz`. Results are recorded here after the first run.

---

## Known limitations found so far

- **Intel Mac unsupported** (no MediaPipe wheels since 0.10.21).
- **Windows UIPI:** expected that injected input can't reach elevated windows. Confirm in S2.
- **Wayland:** expected unsupported for global injection (CLAUDE.md §12). Confirm on Linux later.
- **Bundle size:** about 375 MB unpacked on Windows before any trimming.
