# Manual tests

Checks that need a real camera, screen, or OS permission, so they can't run in CI.
Each step says exactly what to do and what to send back. **Nothing here writes camera frames
anywhere**: spikes keep frames in memory only and block network access while they run.

All commands run from the repo root (`C:\dev\nodwell` on the dev machine) in a terminal.
After each spike, copy everything between the `===== SPIKE RESULT` lines and paste it back,
together with your answers to the questions the script prints.

One-time setup:

```
uv sync
uv run python scripts/fetch_model.py
```

---

## M0 spikes: Windows

### S1. Face Landmarker live (about 3 minutes)

1. Sit in your usual position, about an arm's length from the screen, in normal room light.
2. Run `uv run python spikes/s1_landmarker_live.py --preview`.
   - A preview window appears with orange dots on your face. **If the image is grey or
     ghostly, that's the IR camera:** press `q`, then rerun with `--camera 1`.
3. For 30 seconds, look around, turn your head left/right/up/down, smile, raise your
   eyebrows, open your mouth, and blink a few times.
4. Paste the result block.
5. Repeat **without** `--preview` (preview drawing costs time):
   `uv run python spikes/s1_landmarker_live.py` (add `--camera 1` if you needed it). Paste.
6. Repeat with `--live` (LIVE_STREAM mode). Paste.
7. Optional: repeat step 5 with `--backend dshow`. Paste, and say if the camera opened faster.

**Pass:** `end_to_end_fps` ≥ 25 at 640x480, `landmark_count` 478, a 4x4 matrix,
`network_attempts` empty, and a full blendshape list.

### S2. pynput injection (about 3 minutes)

1. Open Notepad and put it in the middle of the screen.
2. Run `uv run python spikes/s2_pynput_inject.py`.
3. During the 5-second countdown, **hover the mouse over Notepad's text area** and let go of it.
4. Watch: the cursor traces a small square twice, clicks, types a line, and scrolls.
   Press `Esc` to abort at any time.
5. Paste the result and answer the four printed questions (including your display scale %).
6. **Admin check:** close Notepad, right-click Notepad, choose *Run as administrator*, then repeat
   steps 2 to 4 with `--label "notepad elevated"`. We expect the movement to work but the
   click and typing *not* to reach the elevated window. Say what happened.

### S3. Overlay (about 3 minutes per run)

1. Run `uv run python spikes/s3_overlay_clickthrough.py`.
2. For 60 seconds, with the orange ring following your mouse:
   - Click and type in Notepad *through* the ring.
   - Click the taskbar, open Start, and press Alt+Tab. Does the ring stay on top? Is it listed in Alt+Tab?
   - Maximise a browser window; play a video in borderless fullscreen (YouTube `f` key) and
     check whether the ring stays on top.
3. Paste the result and answer the six printed questions.
4. Repeat with `--mode full`, then with `--win32`. Paste each, and note any differences.

### S4. No-focus keyboard (about 3 minutes per run)

1. Open Notepad and click into it so it has a blinking caret.
2. Run `uv run python spikes/s4_nofocus_keyboard.py`. A dark keyboard appears at the bottom of the screen.
3. **Dwell:** hover over `H`, then `I`, then `!` for about 1 second each without clicking. Each
   key should fill orange and then type into Notepad.
4. **Click:** click `Space`, then `H`, then `I` with the mouse.
5. Watch Notepad's title bar and caret: does Notepad stay the active window?
6. Wait for the 90 s timer (or Ctrl+C in the terminal). Paste the result and answers.
7. Repeat with `--win32-noactivate`. Paste the result and answers.

### S5. PyInstaller build (Claude ran this already; this step is for a clean machine later)

1. On a Windows PC that has **never had Python installed**, download the
   `nodwell-selftest-Windows-X64` artifact from the *Build spike 5* GitHub Actions run, or
   copy `dist/nodwell-selftest` across.
2. Extract it and run `nodwell-selftest.exe` from a terminal. Expect a SmartScreen or
   antivirus prompt; record exactly what it says.
3. Run `nodwell-selftest.exe --camera`.
4. Paste both results.

---

## M0 spikes: macOS (Apple Silicon) — not yet run (no hardware)

Same scripts. Use TextEdit instead of Notepad. Differences to record:
- First run: macOS asks for **Camera** permission for the terminal app. Record the exact
  dialog text and where to grant it (System Settings > Privacy & Security > Camera).
- S2/S4 need **Accessibility** permission for the terminal (Privacy & Security >
  Accessibility). S2 reports `mac_accessibility_trusted`.
- S4 is expected to fail with Qt flags alone (a non-activating `NSPanel` may be needed).
  Record the behaviour; adding PyObjC needs owner approval first.
- S5: the artifact is a `.tar.gz`; extract with `tar -xzf`. Gatekeeper will block the unsigned
  binary. Record the exact prompt and the workaround (right-click > Open, or
  `xattr -dr com.apple.quarantine nodwell-selftest`).

## M0 spikes: Linux (Ubuntu 24.04, X11) — not yet run (no hardware)

Same scripts. Use gedit or Text Editor instead of Notepad.
- Log in with **"Ubuntu on Xorg"** (gear icon on the login screen). `echo $XDG_SESSION_TYPE`
  must print `x11`.
- Also run S2 once in a Wayland session and record the failure mode (expected: injection only
  reaches XWayland windows, or nothing).
- S5: extract the `.tar.gz` and run `./nodwell-selftest/nodwell-selftest`.
