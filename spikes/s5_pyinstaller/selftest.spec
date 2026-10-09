# PyInstaller spec for the spike 5 self-test (onedir build; see DECISIONS.md D6).
#
#   uv run python scripts/fetch_model.py
#   uv run pyinstaller --noconfirm --clean spikes/s5_pyinstaller/selftest.spec
#   dist/nodwell-selftest/nodwell-selftest(.exe)
#
# Findings this spec encodes are written up in docs/SPIKE_NOTES.md (S5).
from importlib.util import find_spec
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs, copy_metadata

HERE = Path(SPECPATH).resolve()  # noqa: F821  (SPECPATH is injected by PyInstaller)
ROOT = HERE.parents[1]

datas = [
    (str(ROOT / "models" / "face_landmarker.task"), "models"),
    (str(ROOT / "models" / "face_landmarker.sha256"), "models"),
]
# Package metadata, so the self-test can report exact versions from inside the bundle.
for dist in ("mediapipe", "opencv-contrib-python", "PySide6", "pynput"):
    datas += copy_metadata(dist)

# MediaPipe's native libraries (0.10.21: the framework bindings and the OpenCV library they
# ship) must keep their package-relative paths.
binaries = collect_dynamic_libs("mediapipe")

# pynput chooses its OS backend (pynput.mouse._win32 / _darwin / _xorg) at import time by
# name, which static analysis can't see. List every module from pynput's files instead of
# collect_submodules(): that imports each one at build time, and on a build machine with no
# display the Linux (_xorg) backend fails to import and is silently left out.
_pynput_dir = Path(find_spec("pynput").submodule_search_locations[0])
hiddenimports = sorted(
    {
        ("pynput." + ".".join(p.relative_to(_pynput_dir).with_suffix("").parts)).removesuffix(
            ".__init__"
        )
        for p in _pynput_dir.rglob("*.py")
    }
)

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
