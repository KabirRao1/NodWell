# How Nodwell works (as of M0)

This is a guided tour of the repository: what each part does, how it works inside, and how to
run it. It describes the project as it is **today, at Milestone 0**. M0 builds no application
yet; it sets up the tooling and runs five experiments ("spikes") that check the riskiest
assumptions before any real features are built on them.

For the full product spec, see `CLAUDE.md`. For results, see `docs/SPIKE_NOTES.md`.

---

## 1. The big picture

**Nodwell** will be a desktop app that lets someone control their computer and communicate
using only head movement, facial gestures, and coarse eye gaze, seen through an ordinary
webcam. Everything runs on the user's machine; video never leaves it or touches the disk.

The finished app will be a pipeline like this (CLAUDE.md §6):

```
webcam ──> CameraThread ──> TrackerThread (MediaPipe) ──> FeatureExtractor ──> Filters
                                                                                 │
           mouse / keyboard / speech  <── ActionDispatcher <── InteractionEngine ┘
```

1. **Camera**: OpenCV grabs frames from the webcam.
2. **Tracker**: Google's MediaPipe *Face Landmarker* finds the face in each frame. It returns
   478 3D points ("landmarks"), 52 expression scores ("blendshapes", e.g. how open the jaw
   is, from 0 to 1), and a 4x4 matrix describing where the head is pointing.
3. **Features**: turn that raw output into a few useful numbers: head yaw/pitch/roll, nose
   position, gaze direction, and tracking quality.
4. **Filters**: smooth out jitter (a "One Euro" filter, which smooths heavily when you're
   still and lightly when you move fast).
5. **Interaction engine**: decides what the numbers mean. Head offset becomes cursor
   motion, hovering still for a moment ("dwell") becomes a click, and a held eyebrow raise
   becomes an action.
6. **Dispatcher**: actually moves the mouse, presses keys, or speaks.

None of that pipeline exists yet. M0 checks that each risky building block works first.

---

## 2. Quick start

From a PowerShell window:

```powershell
cd C:\dev\nodwell
uv sync                                   # create .venv and install exact locked versions
uv run python scripts/fetch_model.py      # download + verify the face model (once)

uv run ruff check .                       # lint
uv run ruff format --check .              # formatting
uv run mypy                               # type check
uv run pytest                             # unit tests

uv run python spikes/s1_landmarker_live.py --preview   # run a spike
```

`uv run <command>` means "run this inside the project's virtual environment". You never need to
activate the environment by hand.

---

## 3. What's in the repository

```
nodwell/
├── CLAUDE.md                 product spec and working rules
├── pyproject.toml            project metadata, dependencies, tool settings
├── uv.lock                   exact version of every package, for all three OSes
├── .python-version           "3.12": tells uv which Python to use
├── .gitignore                keeps the venv, builds, model file, and any images out of git
├── .gitattributes            same (LF) line endings on every OS
│
├── nodwell/                  the application package (empty placeholders in M0)
│   └── core/                 future pure-Python logic: filters, gestures, dwell, engine
│
├── scripts/fetch_model.py    downloads the MediaPipe model and checks its fingerprint
├── models/
│   ├── face_landmarker.sha256   the pinned fingerprint (committed)
│   └── face_landmarker.task     the model itself (downloaded, NOT committed)
│
├── spikes/                   the five M0 experiments (throwaway code)
│   ├── _common.py            shared helpers: network tripwire, result printing, timing
│   ├── _win32.py             small Windows-only helpers (window styles, focus)
│   ├── s1_landmarker_live.py
│   ├── s2_pynput_inject.py
│   ├── s3_overlay_clickthrough.py
│   ├── s4_nofocus_keyboard.py
│   └── s5_pyinstaller/       self-test program + recipe for building it into an .exe
│
├── tests/                    automated tests (run by pytest and CI)
├── .github/workflows/        CI: checks on every push; .exe builds on 3 OSes
└── docs/                     decisions, status, spike results, manual test steps
```

---

## 4. Dependencies and the environment

**`pyproject.toml`** lists what the project needs:

| Package | What it's for |
|---|---|
| `mediapipe` | face tracking (pinned to exactly `1.0.1`) |
| `opencv-contrib-python` | webcam capture (`cv2`) |
| `PySide6` | the user interface (Qt 6) and the on-screen overlays |
| `pynput` | moving the mouse and pressing keys in other apps |
| `pyttsx3` | text-to-speech (used from M3) |
| `pydantic`, `platformdirs` | settings files and where to store them (from M1) |
| dev: `pytest`, `ruff`, `mypy`, `pyinstaller` | tests, lint/format, type check, building the .exe |

**`uv.lock`** records the exact version of every package, including the packages those
packages depend on, for Windows, macOS, and Linux at once. `uv sync --locked` installs exactly
those versions, so your machine and every CI machine run identical code.

Why some choices look the way they do (the full reasoning is in `docs/DECISIONS.md`):

- **MediaPipe is pinned exactly** because gesture thresholds depend on its output. An upgrade
  must be deliberate and re-tested, never accidental.
- **`opencv-contrib-python`, not `opencv-python`**: MediaPipe already depends on the contrib
  build, and installing both gives you two conflicting copies of `cv2`.
- **Python 3.12, Apple Silicon only on Mac**: current MediaPipe wheels work on any Python 3
  version, but no longer exist for Intel Macs.

---

## 5. Code-quality checks

| Tool | What it checks | Settings live in |
|---|---|---|
| **ruff** | common bugs, unused imports, import order, style, and formatting | `[tool.ruff]` in `pyproject.toml` |
| **mypy** | type errors. **Strict** on `nodwell/core/`: every function there must be fully typed | `[tool.mypy]` |
| **pytest** | runs everything in `tests/` | `[tool.pytest.ini_options]` |

### The import-boundary test (`tests/test_import_boundaries.py`)

The spec requires `nodwell/core/` to stay *pure Python*: no Qt, OpenCV, MediaPipe, or OS input
libraries. That way the engine can be tested by replaying recorded numbers, with no camera
or screen.

The test enforces this without running the code. It reads every `.py` file under `core/`,
parses it into a syntax tree with Python's `ast` module, finds every `import` statement
(including ones hidden inside functions), and fails if any of them names a forbidden package.
Two extra tests feed the checker deliberately bad and deliberately good snippets, to prove the
checker itself works.

### The model test (`tests/test_fetch_model.py`)

This tests the download script with a **fake downloader**, so no network is used. It checks
that a good file passes, a tampered or missing file fails, and a bad download leaves nothing
behind.

---

## 6. The face model and its fingerprint

MediaPipe needs a model file, `face_landmarker.task` (about 3.7 MB). We don't commit it to git;
`scripts/fetch_model.py` downloads it from the URL in Google's official docs.

To make sure we always get *exactly* the file we tested with, we store its **SHA-256 hash**
(a fingerprint that changes completely if even one byte changes) in
`models/face_landmarker.sha256`. The script works like this:

1. Read the pinned fingerprint.
2. If the model already exists, re-check its fingerprint and stop.
3. Otherwise download it to a **temporary file** in the same folder.
4. Check the temporary file's fingerprint. If it doesn't match, delete it and fail loudly.
5. Only if it matches, rename it to `face_landmarker.task`.

Because of step 5, a half-finished, corrupted, or tampered download can never be mistaken for
the real model. Run `python scripts/fetch_model.py --verify` to check an existing file without
touching the network.

The app itself never downloads anything. The download happens only at setup or build time.

---

## 7. Continuous integration (GitHub Actions)

After the repo is pushed to GitHub, two workflows run automatically:

**`ci.yml`** runs on every push, on Windows, macOS (Apple Silicon), and Ubuntu:

1. check out the code
2. install uv, then `uv sync --locked` (fails if `uv.lock` is out of date)
3. ruff lint, then ruff format check, then mypy, then pytest

A red ❌ on any OS means something broke there.

**`build-spike.yml`** runs on pushes to `main` that touch the spikes or dependencies, or when
started by hand. On each OS it:

1. installs the dependencies (on Linux, also the system libraries Qt needs and a virtual
   screen, `xvfb`)
2. downloads and verifies the model (cached between runs)
3. builds the self-test `.exe` (or the Mac/Linux equivalent) with PyInstaller
4. **runs it**, so the build fails if the bundled program can't start
5. packs it into a `.tar.gz` you can download from the run's page and try on another machine

---

## 8. The five spikes

Each spike is a small standalone script that answers one yes/no question. They share some
rules:

- **Results block.** At the end, each prints a JSON summary between `===== SPIKE RESULT`
  lines. Paste that block into `docs/SPIKE_NOTES.md` (or into the chat).
- **Countdown and abort.** Scripts that move the real mouse or type wait 5 seconds first so
  you can get ready, and can be stopped (`Esc` in S2, Ctrl+C in S3/S4).
- **No images saved.** Camera frames only ever exist in memory.

### Shared helpers (`spikes/_common.py`)

- **Network tripwire.** Python opens network connections through its `socket` module. The
  tripwire replaces `socket.connect` and friends with versions that *record* the attempt and
  then *refuse* it. S1 and S5 install it **before** importing MediaPipe. So if anything tried
  to phone home, the result's `network_attempts` list would show it, and the connection would
  fail. (Limitation: code written in C that opens sockets directly would bypass it.)
- **`env_info()`** records OS, CPU, Python, and exact package versions, so every result
  says what it was measured on.
- **`percentiles()`** summarises timings as p50 (the typical value), p95 (the slow case:
  95% of measurements were faster than this), and max.
- It also sets `MPLBACKEND=Agg`. MediaPipe imports the plotting library matplotlib as it
  loads; this setting stops matplotlib from ever trying to open a window.

### Windows helpers (`spikes/_win32.py`)

These call the Windows API directly through `ctypes`:

- **Reading and setting extended window styles.** These are flags Windows keeps on every
  window, such as `TOPMOST` (always on top), `TRANSPARENT` (clicks pass through),
  `NOACTIVATE` (clicking it doesn't take focus), and `TOOLWINDOW` (hidden from the taskbar
  and Alt+Tab). The spikes print which flags Qt set by itself, so we learn what Qt handles and
  what we must add.
- **`foreground_window()`** reports which window currently has keyboard focus. S4 uses it as
  hard evidence of whether focus was stolen.

On macOS and Linux these helpers do nothing.

### S1: face tracking live (`s1_landmarker_live.py`)

**Question:** does Face Landmarker run fast enough (≥ 25 frames/second), and what exactly does it
output?

How it works:

1. Creates a `FaceLandmarker` with blendshapes and the head-pose matrix switched on.
2. Opens the webcam (`--camera`, `--backend`) and asks for 640x480 at 30 fps.
3. For each frame: read it, convert the colour order (OpenCV uses BGR, MediaPipe wants RGB),
   then run the tracker. It times each stage separately.
4. It supports MediaPipe's two video modes:
   - **VIDEO** (default): call and wait for the answer. Simple, and timing is easy to measure.
   - **LIVE_STREAM** (`--live`): hand the frame over and get the answer later through a
     callback, on MediaPipe's own thread. Busy frames get dropped instead of queuing up,
     which keeps latency low. The script records how long each answer took to come back.
5. The first time it sees a face, it records the landmark count, the matrix shape, and the
   **full list of blendshape names straight from the model**. The spec says not to trust
   hard-coded names, so the script compares the real list with the names the spec expects
   and reports any that are missing.
6. `--preview` shows the camera with dots drawn on your face, in an in-memory window.

### S2: controlling the mouse and keyboard (`s2_pynput_inject.py`)

**Question:** can `pynput` move, click, type, and scroll in *another* app?

How it works:

1. Records where you left the mouse, then moves it around an 80-pixel square twice. After
   each move it reads the position back to check it landed where intended.
2. Clicks (which focuses Notepad), types a test sentence, presses Enter, and scrolls down and up.
3. Times every call.
4. **Display-scaling check.** On a high-resolution laptop, Windows scales everything (e.g.
   200%). A program can see coordinates either in real pixels or in scaled pixels, depending on
   its "DPI awareness". Qt changes this setting when it starts. So the script records the
   setting, starts Qt in the same process, moves the mouse to (300, 300) with pynput, and asks
   Qt where the cursor is. If the two disagree, the real app must convert between them.
5. **Admin check** (`--label "notepad elevated"`): Windows blocks normal programs from sending
   input to programs running as administrator (this is called UIPI). We expect this to fail,
   and confirm it so we can document it.

### S3: the see-through overlay (`s3_overlay_clickthrough.py`)

**Question:** can we draw something on top of everything (the dwell progress ring) that is
see-through, doesn't block clicks, and never takes focus?

How it works:

1. Creates a Qt window with flags for: no border, always on top, a tool window (no taskbar
   button), transparent to input, never takes focus, and a translucent background.
2. A timer runs about 60 times a second. Each tick it advances the ring's progress and moves
   the ring to the mouse position.
   - `--mode small` moves a small 96x96 window around.
   - `--mode full` uses one invisible window covering the whole screen and draws the ring at
     the cursor. We want to know which is smoother and cheaper.
3. `--win32` additionally forces the Windows style flags in case Qt's flags aren't enough.
4. Reports which style flags Qt set by itself, paint rate, timer jitter, and CPU use. Then it
   asks you what you saw, e.g. whether clicks went through and whether it stayed on top.

### S4: a keyboard that doesn't steal focus (`s4_nofocus_keyboard.py`)

**Question:** can an on-screen keyboard type into Notepad *without* Notepad losing focus?

This is the hardest problem of the five. Normally, clicking a window makes it the active
window, so keystrokes would go to our keyboard instead of Notepad.

How it works:

1. Shows a small always-on-top keyboard (H, I, !, Space, Enter, Backspace) with big keys and
   wide gaps.
2. **Dwell path.** Hovering over a key starts a 1-second timer, shown as an orange fill. When
   it completes, the key fires, with no click at all. Moving away cancels it. This is how a
   head-pointer user would type.
3. **Click path.** A real mouse click also fires the key, which tests the harder case.
4. Firing a key sends it through pynput, so it goes to whichever window has focus.
5. **Evidence.** For every press it records which window had focus. It also counts how often
   our own app became the active app. If our keyboard ever "stole" focus, the result shows it.
6. `--win32-noactivate` adds Windows' "don't activate on click" flag, in case Qt's flag isn't
   enough.

A known design conflict, flagged for M3: a keyboard that can never take focus can't be
navigated with the Tab key either, and the spec also wants that for caregivers. The likely
solution is a caregiver mode that temporarily allows focus.

### S5: building an .exe (`s5_pyinstaller/`)

**Question:** can everything (MediaPipe, Qt, pynput, and the model) be packed into a program that
runs on a computer without Python?

**`selftest.py`** is the program being packed. When run, it checks, in order:

1. the bundled model is present and its fingerprint matches
2. MediaPipe's native library loads and the tracker runs on a synthetic grey image (no camera
   needed)
3. Qt starts and shows a window for a moment
4. pynput can read the cursor position (it never moves it)
5. with `--camera`: the webcam delivers frames for 5 seconds

It exits with code 0 only if every check passed *and* nothing tried to use the network.

**`selftest.spec`** is the PyInstaller recipe. PyInstaller follows the program's imports to
find what to include, but a few things are invisible to it, so the recipe adds them by hand:

- **The model and its fingerprint file**, placed in `models/` inside the bundle.
- **MediaPipe's native library.** MediaPipe 1.x is a thin Python layer over one big compiled
  library (`libmediapipe.dll` on Windows), which it finds by its location inside the package.
  `collect_dynamic_libs("mediapipe")` copies it to the same relative spot.
- **pynput's OS backends.** pynput picks its Windows, Mac, or Linux backend by name when it
  starts, which PyInstaller can't follow. `collect_submodules("pynput")` includes them all.
- **Package metadata**, so the self-test can report exact versions.

Inside the bundle, the program finds its files through `sys._MEIPASS`, which PyInstaller sets
to the bundle's `_internal` folder.

Build it and run it:

```powershell
uv run python scripts/fetch_model.py
uv run pyinstaller --noconfirm --clean spikes/s5_pyinstaller/selftest.spec
.\dist\nodwell-selftest\nodwell-selftest.exe
.\dist\nodwell-selftest\nodwell-selftest.exe --camera
```

It's a **"onedir" build**: an `.exe` plus an `_internal` folder next to it. **Copy the whole
`nodwell-selftest` folder** to move it to another PC. We chose onedir over a single-file `.exe`
because a single file has to unpack itself to a temp folder on every launch. That is slow,
antivirus tools flag it more often, and it makes it harder to swap out the Qt libraries, which
Qt's licence (LGPL) requires.

---

## 9. Privacy guards in M0

| Rule (CLAUDE.md §4) | How M0 enforces it |
|---|---|
| Camera frames never touch disk | No spike calls any image-saving function. Previews are in-memory windows. `.gitignore` blocks image and video files from git as a safety net. |
| No network at runtime | Network tripwire in S1 and S5, with results reported. The model is downloaded only by the setup script. |
| Core logic stays testable without a camera | Import-boundary test |

---

## 10. The docs folder

| File | What's in it |
|---|---|
| `DECISIONS.md` | every significant choice: context, options, decision, and why |
| `STATUS.md` | what's done, waiting, blocked, and next |
| `SPIKE_NOTES.md` | spike results per OS, findings, and known limitations |
| `MANUAL_TESTS.md` | exact step-by-step instructions for tests that need a human, camera, or screen |
| `METRICS.md` | measured performance numbers. Empty until the `bench/` tools exist (M1+). Only measured numbers go here. |
| `HOW_IT_WORKS.md` | this file |

---

## 11. What happens next

1. Run spikes S1 to S4 on Windows (`docs/MANUAL_TESTS.md`) and record the results in
   `SPIKE_NOTES.md`.
2. Push to GitHub so CI and the multi-OS builds run.
3. Report M0. After approval, start **M1: the pointer MVP**: the real tracking pipeline, a
   smooth head-controlled cursor, dwell clicking with the progress ring, recenter, pause, and
   freezing the cursor when the face is lost.

---

## Glossary

- **Blendshape**: a score from 0 to 1 for one facial movement (e.g. `jawOpen`,
  `browInnerUp`). MediaPipe outputs 52 of them.
- **Dwell**: clicking by holding the pointer still over a target for a set time.
- **Landmarks**: 3D points on the face (478 in MediaPipe, including the irises).
- **Transformation matrix**: a 4x4 grid of numbers describing the head's rotation and
  position; head yaw, pitch, and roll come from it.
- **One Euro filter**: a smoothing filter that adapts to speed. It removes jitter when you're
  still without adding lag when you move.
- **p50 / p95**: the median, and the value that 95% of measurements beat. p95 shows the slow cases.
- **DPI awareness**: whether a Windows program sees real pixels or scaled pixels on a
  scaled display.
- **UIPI**: Windows blocks input from normal programs to admin programs.
- **Extended window styles**: Windows flags such as always-on-top, click-through, and don't-activate.
- **Onedir build**: a PyInstaller output folder with an `.exe` plus its supporting files.
- **Lockfile** (`uv.lock`): exact versions of every package, so all machines match.
- **SHA-256**: a file fingerprint; any change to the file changes it completely.

---

## 12. M1 update: the pointer app

M1 adds the first real application. A quick map; DECISIONS D11 to D15 explain the choices.

```
nodwell/
  __main__.py      entry point: python -m nodwell [--camera N] [--dry-run] [--replay F] [--record F] [--smoke-test]
  app.py           builds everything and wires it together
  pipeline.py      the per-frame loop on its own thread
  core/            pure Python: frame, features, filters, pointer, dwell, gestures, engine, safety, settings, ...
  tracking/        camera thread and the MediaPipe wrapper
  platform/        pynput mouse output, global hotkeys, Windows window styles
  ui/              status panel, dwell ring overlay, tray icon, theme
bench/latency.py   per-stage timing report
packaging/         PyInstaller spec for dist/Nodwell/Nodwell.exe
```

**One frame's journey:** the camera thread reads a frame and drops it into a one-item slot,
overwriting any frame nobody took. The pipeline thread takes it, MediaPipe finds the face,
`features.py` turns the 4x4 matrix into yaw/pitch/roll, the One Euro filters smooth them, and
the engine decides where the cursor goes and whether a dwell click fires. The safety gate is
checked, then pynput moves the cursor. About 15 times a second a status snapshot goes to the UI.

**Run it:** `uv run python -m nodwell`, or build `uv run pyinstaller --noconfirm --clean
packaging/nodwell.spec` and run `dist\Nodwell\Nodwell.exe`. Caregiver keys: Ctrl+Alt+P
pause/resume (instant stop), Ctrl+Alt+R recenter, Ctrl+Alt+Q quit.

**Test without a camera:** `uv run python -m nodwell --replay tests/fixtures/dwell_then_face_lost.jsonl`
plays recorded numbers through the real app without touching the mouse, and `--smoke-test`
runs the whole app on blank frames and exits 0 if everything worked.
