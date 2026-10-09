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

## M1 pointer MVP: Windows (about 15 minutes)

These steps check the M1 acceptance criteria: move and dwell-click in any app with head
movement alone, losing your face freezes the cursor, and the latency report runs. They also
cover what spikes S1 to S3 were meant to check (camera fps, DPI coordinates, overlay).

**Know the safety keys first.** `Ctrl+Alt+P` stops everything instantly; press it again to
resume. `Ctrl+Alt+Q` quits. You can also grab the real mouse at any time: Nodwell backs off.

**Start it** (either way):
- Packaged: double-click `dist\Nodwell\Nodwell.exe`. To pass options, run it from a
  terminal, e.g. `.\dist\Nodwell\Nodwell.exe --camera 1`.
- From source: `uv run python -m nodwell` (shows the log in the terminal).

Settings live in `%LOCALAPPDATA%\Nodwell\settings.json` (written the first time you change
something in the panel). Logs are in `%LOCALAPPDATA%\Nodwell\Logs\nodwell.log`: events and
numbers only, never images.

Sit about an arm's length from the screen, in normal room light. For each step, note
**pass / fail / partly** plus anything odd.

1. **Start.** The panel appears top-right with a "Starting" pill. Look at the screen and hold
   still: within a few seconds the pill turns "Active" and the cursor jumps to the screen
   centre. If it stays "Starting" with "Face not found", you may be on the IR camera: quit
   with `Ctrl+Alt+Q`, then run with `--camera 1`.
2. **Direction.** Turn your head right: does the cursor go right? Look up: does it go up?
   If an axis is backwards, say which one.
3. **Four corners (display-scaling check).** Can you reach all four screen corners with a
   comfortable head turn? Does the cursor stop short of any edge, or overshoot onto a second
   screen? Also tell me your display resolution and scale (Settings > System > Display).
   The app saw the primary screen as 1920x1080 at 100%.
4. **Steadiness.** Hold the cursor on one word for 5 seconds. Rate the shake from 1 (rock
   steady) to 5 (unusable).
5. **Dwell click.** Open Notepad. Hover the cursor over the *File* menu and hold still: an
   orange ring fills around the cursor for 1 second, then it clicks. Then dwell on a link in
   a browser. Does the click land where the ring was? Is the ring see-through, and does it
   stay on top?
6. **No repeat clicks.** After a dwell click, keep still for 5 more seconds: no second click
   should happen until you move away and back.
7. **Face lost.** Cover the camera with your hand. The cursor must freeze **immediately** and
   the pill must say "Face not found". After 5 seconds it says "Paused". Uncover: it must
   **stay** paused.
8. **Resume gesture.** Raise your eyebrows and hold. Watch the meter in the panel: the bar
   must pass the black line, and the text counts "Holding... %". After 2 seconds it resumes,
   and the cursor recentres. Tell me roughly how far past the line your eyebrows get (e.g.
   "barely" or "easily").
9. **Pause gesture.** While active, do the same: it pauses.
10. **False pauses.** Use the computer normally for 2 minutes: talk, blink, smile, look
    around. Did it ever pause or resume by itself?
11. **Panic key.** While active, press `Ctrl+Alt+P`: everything stops instantly. Press again:
    it resumes.
12. **Recenter.** Lean or turn so the cursor sits off-centre, then press `Ctrl+Alt+R` and
    check that your current pose becomes the new centre. Also dwell on the panel's
    *Recenter* button.
13. **Pause by dwell.** Dwell on the panel's *Pause* button. It pauses. (Resume with the
    gesture or `Ctrl+Alt+P`.)
14. **Relative mode.** Dwell on *Relative*. Tilting your head now pushes the cursor like a
    joystick; facing the screen stops it. Is it usable? Too fast or too slow?
15. **Mouse override.** While active, move the real mouse. The panel says "Mouse in use",
    Nodwell stops moving the cursor, and head control comes back about 1.5 seconds after you
    let go.
16. **Admin windows (expected limitation).** Open Task Manager and try to dwell-click in it.
    Windows blocks input from normal apps to admin windows, so this is expected to fail.
    Confirm.
17. **Latency report.** Quit Nodwell, then sit in front of the camera and run
    `uv run python bench/latency.py --seconds 60`. Move your head now and then (dwell
    clicking is off; the cursor will move). Paste the whole result block, and tell me the
    lighting conditions.

Paste back: your pass/fail notes for each step, the latency result, and the last 50 lines
of `nodwell.log` if anything failed.

---

## Click types, gestures, and smoothing: Windows (about 15 minutes)

Added after M1: the click-type toolbar (left screen edge), head-tilt gestures, and cursor
gliding. Same start-up and safety keys as above. While a dwell builds, the ring shows what
it will do: nothing for a left click, **R** for right, **2×** for double, a drag symbol, or
scroll arrows.

1. **Toolbar keeps your focus.** Open Notepad, click into it, and type a word. Dwell on
   **Right** on the toolbar. Notepad must stay the active window (title bar still active,
   caret still blinking). Then dwell on the text in Notepad: its right-click menu opens.
2. **Double click.** Dwell on **Double**, then dwell on a word in Notepad. The word is selected.
3. **Drag.** Dwell on **Drag**, dwell on a window's title bar (it grabs), turn your head to
   move it, and dwell again (it drops). Also try selecting text in Notepad by dragging.
4. **Scroll.** Open a long web page. Dwell on **Scroll**, then dwell on the page. Look slightly
   up or down: does it scroll smoothly at a readable speed? Turn your head well to the side:
   does scrolling stop? Start again, then hold still for 3 s: does it stop by itself?
5. **Tilt right gives a right click.** Hover over the Notepad text, then tilt your head toward
   your right shoulder and hold about half a second. The right-click menu should open where
   the cursor was before you tilted. **If you get a double click instead, the directions are
   swapped:** on the panel's Gestures tab, press "Left and right tilt" so it says swapped, and
   tell me.
6. **Tilt left gives a double click** (e.g. select a word in Notepad).
7. **No false clicks.** Use the computer normally for 2 minutes: talk, nod, look around, lean.
   Any accidental right or double clicks? Roughly how many?
8. **Gestures tab.** Each gesture's bar moves as you do it, and passes the black line when you
   do it fully. "Action ▸" cycles what a gesture does; turning one Off stops it. Is the 12°
   tilt comfortable, too much, or too little?
9. **Glide.** Pointer tab: turn "Glide between frames" Off, move around, then turn it On. Does
   the cursor look smoother with it On? Does it feel laggy?
10. **Live tuning.** Pointer tab: change Smoothness, Head turn to reach the edge, and Dwell time
    with − and +. Do the changes take effect immediately?
11. **Panic during a drag.** Start a drag on a desktop icon (button held), then press
    `Ctrl+Alt+P`. The icon must drop immediately (button released) and everything stop.
12. **Keyboard.** With a real keyboard, Tab through the panel. Can you reach the "Next click"
    buttons on the Home tab and choose one with Space?

Paste back pass/fail per step, which tilt direction worked, and your answers to 7 to 9.

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
