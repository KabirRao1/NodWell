"""Shared helpers for the M0 spikes. Throwaway code: not part of the nodwell package."""

from __future__ import annotations

import json
import os
import platform
import socket
import statistics
import sys
from importlib import metadata
from typing import Any

# mediapipe.tasks.python.vision imports matplotlib.pyplot at import time (via
# drawing_utils). Force the non-GUI backend so it never opens a window or picks Qt.
os.environ.setdefault("MPLBACKEND", "Agg")

RESULT_BEGIN = "===== SPIKE RESULT (paste everything between these lines) ====="
RESULT_END = "===== END SPIKE RESULT ====="

PACKAGES = ("mediapipe", "opencv-contrib-python", "numpy", "PySide6", "pynput", "pyinstaller")


class NetworkTripwire:
    """Block and record every outbound socket connection in this process.

    Used to show that MediaPipe and friends make no network calls at runtime
    (CLAUDE.md §4.2). Only Python-level sockets are covered; native code that
    opens sockets directly would bypass it, which is noted in SPIKE_NOTES.
    """

    def __init__(self) -> None:
        self.attempts: list[str] = []
        self._orig_connect = socket.socket.connect
        self._orig_connect_ex = socket.socket.connect_ex
        self._orig_create_connection = socket.create_connection

    def install(self) -> NetworkTripwire:
        tripwire = self

        def connect(sock: socket.socket, address: Any) -> None:
            tripwire.attempts.append(f"connect {address!r}")
            raise OSError("network blocked by spike tripwire")

        def connect_ex(sock: socket.socket, address: Any) -> int:
            tripwire.attempts.append(f"connect_ex {address!r}")
            return 1

        def create_connection(address: Any, *args: Any, **kwargs: Any) -> socket.socket:
            tripwire.attempts.append(f"create_connection {address!r}")
            raise OSError("network blocked by spike tripwire")

        socket.socket.connect = connect  # type: ignore[method-assign,assignment]
        socket.socket.connect_ex = connect_ex  # type: ignore[method-assign,assignment]
        socket.create_connection = create_connection  # type: ignore[assignment]
        return self


def env_info() -> dict[str, Any]:
    """Describe the machine and package versions, for SPIKE_NOTES 'Environment'."""
    versions: dict[str, str | None] = {}
    for pkg in PACKAGES:
        try:
            versions[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            versions[pkg] = None
    return {
        "os": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "python": sys.version.split()[0],
        "frozen": bool(getattr(sys, "frozen", False)),
        "session_type": os.environ.get("XDG_SESSION_TYPE"),
        "packages": versions,
    }


def percentiles(values_ms: list[float]) -> dict[str, float | None]:
    """p50 / p95 / max of a list of millisecond timings, rounded for reading."""
    if not values_ms:
        return {"n": 0, "p50": None, "p95": None, "max": None}
    ordered = sorted(values_ms)
    p95 = ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]
    return {
        "n": len(ordered),
        "p50": round(statistics.median(ordered), 2),
        "p95": round(p95, 2),
        "max": round(ordered[-1], 2),
    }


def print_result(result: dict[str, Any]) -> None:
    """Print the JSON summary block the user pastes back into the conversation."""
    print()
    print(RESULT_BEGIN)
    print(json.dumps(result, indent=2, default=str))
    print(RESULT_END)


def countdown(seconds: int, message: str) -> None:
    """Give the user time to arrange windows before a spike touches the real cursor."""
    import time

    print(message)
    for remaining in range(seconds, 0, -1):
        print(f"  starting in {remaining}...", flush=True)
        time.sleep(1)
