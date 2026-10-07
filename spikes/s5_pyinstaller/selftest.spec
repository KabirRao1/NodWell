# PyInstaller spec for the spike 5 self-test (onedir build; see DECISIONS.md D6).
#
#   uv run python scripts/fetch_model.py
#   uv run pyinstaller --noconfirm --clean spikes/s5_pyinstaller/selftest.spec
#   dist/nodwell-selftest/nodwell-selftest(.exe)
#
# Findings this spec encodes are written up in docs/SPIKE_NOTES.md (S5).
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules, copy_metadata

HERE = Path(SPECPATH).resolve()  # noqa: F821  (SPECPATH is injected by PyInstaller)
ROOT = HERE.parents[1]

datas = [
    (str(ROOT / "models" / "face_landmarker.task"), "models"),
    (str(ROOT / "models" / "face_landmarker.sha256"), "models"),
]
# Package metadata, so the self-test can report exact versions from inside the bundle.
for dist in ("mediapipe", "opencv-contrib-python", "PySide6", "pynput"):
    datas += copy_metadata(dist)

# mediapipe 1.x is a ctypes wrapper: it loads mediapipe/tasks/c/libmediapipe.{dll,so,dylib}
# via importlib.resources, so the library must sit at that package-relative path.
binaries = collect_dynamic_libs("mediapipe")

# pynput chooses its OS backend (pynput.mouse._win32 / _darwin / _xorg) at import time
# by name, which PyInstaller's static analysis cannot see.
hiddenimports = collect_submodules("pynput")

a = Analysis(  # noqa: F821
    [str(HERE / "selftest.py")],
    pathex=[str(HERE.parent)],  # spikes/ for _common.py
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    # matplotlib cannot be excluded: mediapipe.tasks.python.vision imports it eagerly.
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="nodwell-selftest",
    console=True,
    upx=False,
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    name="nodwell-selftest",
    upx=False,
)
