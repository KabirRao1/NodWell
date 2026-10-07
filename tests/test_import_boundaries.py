"""Enforce CLAUDE.md §6: `nodwell/core/` stays free of Qt, OpenCV, MediaPipe, and OS backends.

Keeping core pure lets it be tested from recorded FeatureFrame data with no camera,
screen, or GPU. The check is static (AST), so a forbidden import fails even if it sits
inside a function that the tests never call.
"""

from __future__ import annotations

import ast
from pathlib import Path

CORE_DIR = Path(__file__).resolve().parents[1] / "nodwell" / "core"

FORBIDDEN_TOP_LEVEL = frozenset(
    {
        "PySide6",
        "PyQt5",
        "PyQt6",
        "shiboken6",
        "cv2",
        "mediapipe",
        "pynput",
        "pyttsx3",
    }
)


def forbidden_imports(source: str) -> list[str]:
    """Return the forbidden top-level module names imported anywhere in `source`."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        else:
            continue
        found.extend(n for n in names if n.split(".")[0] in FORBIDDEN_TOP_LEVEL)
    return found


def test_checker_catches_violations() -> None:
    src = (
        "import os\n"
        "import cv2\n"
        "from PySide6.QtCore import QObject\n"
        "\n"
        "def f():\n"
        "    import mediapipe as mp\n"
    )
    assert forbidden_imports(src) == ["cv2", "PySide6.QtCore", "mediapipe"]


def test_checker_allows_relative_and_stdlib() -> None:
    src = "import math\nfrom . import filters\nfrom .filters import OneEuro\nimport numpy\n"
    assert forbidden_imports(src) == []


def test_core_has_no_forbidden_imports() -> None:
    assert CORE_DIR.is_dir(), f"missing {CORE_DIR}"
    violations = {
        str(path.relative_to(CORE_DIR)): bad
        for path in sorted(CORE_DIR.rglob("*.py"))
        if (bad := forbidden_imports(path.read_text(encoding="utf-8")))
    }
    assert violations == {}, f"core/ must stay pure Python: {violations}"
