# PyInstaller spec for the Nodwell app (onedir, windowed; DECISIONS.md D6).
#
#   uv run python scripts/fetch_model.py
#   uv run pyinstaller --noconfirm --clean packaging/nodwell.spec
#   dist/Nodwell/Nodwell(.exe)            (add --smoke-test for a headless self-check)
#
# Recipe proven by spike 5 (spikes/s5_pyinstaller/selftest.spec), plus trimming of files
# the app never loads, to keep the download small.
import re
from importlib.util import find_spec
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs

HERE = Path(SPECPATH).resolve()  # noqa: F821  (SPECPATH is injected by PyInstaller)
ROOT = HERE.parent

datas = [
    (str(ROOT / "models" / "face_landmarker.task"), "models"),
    (str(ROOT / "models" / "face_landmarker.sha256"), "models"),
]
# MediaPipe's native libraries (0.10.21: the framework bindings and the OpenCV library they
# ship) must keep their package-relative paths.
binaries = collect_dynamic_libs("mediapipe")
# pynput picks its OS backend by name at runtime, invisible to static analysis. List every
# module from pynput's files rather than collect_submodules(), which imports them at build
# time and silently drops the Linux backend on a build machine with no display.
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
    [str(HERE / "entry.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    # matplotlib can't be excluded: mediapipe.tasks.python.vision imports it eagerly (D10).
    # pydantic.mypy (a type-checker plugin) drags in mypy and its native helpers; none of
    # it runs in the app (docs/SECURITY_AUDIT.md F8).
    excludes=[
        "tkinter",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtNetwork",
        "pydantic.mypy",
        "mypy",
        "mypy_extensions",
        "ast_serialize",
        "librt",
        "setuptools",
    ],
    noarchive=False,
)

# Files we never load. Each pattern matches the bundle-relative destination path.
TRIM = [
    r"opencv_videoio_ffmpeg.*\.dll$",  # video-file decoding; we only read cameras (29 MB)
    r"opengl32sw\.dll$",  # software OpenGL fallback; our widgets paint with the CPU (20 MB)
    r"Qt6(Quick|Qml|VirtualKeyboard|Pdf)[^/\\]*\.dll$",  # QML stack, virtual keyboard, PDF
    r"plugins[/\\]platforminputcontexts[/\\]",  # virtual keyboard plugin (needs QtQuick)
    r"plugins[/\\]imageformats[/\\]qpdf",  # PDF image plugin (needs Qt6Pdf)
    r"PySide6[/\\]translations[/\\]",  # Qt's own UI translations; we use _() (i18n.py)
    # Windows 10+ provides the Universal CRT and API-set DLLs itself. PyInstaller otherwise
    # copies them from whatever program is on the build machine's PATH (here a Java
    # install): not reproducible, and a planted DLL could ride along (SECURITY_AUDIT F7).
    r"(^|[/\\])api-ms-win-[^/\\]*\.dll$",
    r"(^|[/\\])ucrtbase\.dll$",
]
_trim = re.compile("|".join(TRIM), re.IGNORECASE)
a.binaries = [b for b in a.binaries if not _trim.search(b[0])]
a.datas = [d for d in a.datas if not _trim.search(d[0])]

pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Nodwell",
    console=False,  # windowed app; logs go to the user log folder (see __main__.py)
    upx=False,
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    name="Nodwell",
    upx=False,
)
