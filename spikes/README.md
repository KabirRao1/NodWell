# M0 spikes

Throwaway experiments that each answer one question before M1 builds on it. Not part of the
`nodwell` package; anything worth keeping is rewritten properly later (DECISIONS.md D7).

| Script | Question |
|---|---|
| `s1_landmarker_live.py` | Does Face Landmarker run live at ≥ 25 fps, and what does it output (blendshape names, landmarks, matrix)? |
| `s2_pynput_inject.py` | Can pynput move/click/type/scroll in another app? Do its coordinates match Qt's under display scaling? |
| `s3_overlay_clickthrough.py` | Can a Qt overlay be transparent, click-through, and always on top? |
| `s4_nofocus_keyboard.py` | Can a Qt keyboard take dwell presses and type into another app without stealing focus? |
| `s5_pyinstaller/` | Does a PyInstaller bundle with MediaPipe, Qt, pynput, and the model launch on a clean machine? |

Step-by-step instructions: `docs/MANUAL_TESTS.md`. Findings: `docs/SPIKE_NOTES.md`.

Ground rules every spike follows:
- Camera frames stay in memory. Nothing is written to disk, and the preview is an in-memory window.
- S1 and S5 block all Python-level network connections and report any attempts.
- Scripts that move the real cursor or type start with a countdown; `Esc` (S2) or Ctrl+C aborts.
- Each prints one JSON block between `===== SPIKE RESULT` markers to paste back.
