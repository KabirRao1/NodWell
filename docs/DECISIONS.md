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
