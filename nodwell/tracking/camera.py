"""Camera capture thread: reads frames and puts the newest one in a LatestSlot.

Frames live only in memory. Nothing here (or anywhere) writes them to disk or sends them
anywhere (CLAUDE.md §4.1).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

import cv2

from nodwell.core.latest import LatestSlot
from nodwell.core.settings import CameraSettings

log = logging.getLogger(__name__)

BACKENDS = {
    "any": cv2.CAP_ANY,
    "msmf": cv2.CAP_MSMF,
    "dshow": cv2.CAP_DSHOW,
    "avfoundation": cv2.CAP_AVFOUNDATION,
    "v4l2": cv2.CAP_V4L2,
}


@dataclass(slots=True)
class CapturedFrame:
    """One BGR frame (numpy array) and when the camera read returned it."""

    image: Any
    t: float  # time.perf_counter() when cap.read() returned
    read_ms: float


class CameraThread(threading.Thread):
    """Reads frames continuously; consumers take the newest from `slot`."""

    def __init__(self, settings: CameraSettings) -> None:
        super().__init__(name="camera", daemon=True)
        self.settings = settings
        self.slot: LatestSlot[CapturedFrame] = LatestSlot()
        self.error: str | None = None
        self.description = ""
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()
        self.slot.close()

    def run(self) -> None:
        s = self.settings
        cap = cv2.VideoCapture(s.index, BACKENDS[s.backend])
        try:
            if not cap.isOpened():
                self.error = f"Camera {s.index} could not be opened"
                log.error(self.error)
                return
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, s.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, s.height)
            cap.set(cv2.CAP_PROP_FPS, s.fps)
            self.description = (
                f"camera {s.index} via {cap.getBackendName()} at "
                f"{int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x"
                f"{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))} "
                f"@ {cap.get(cv2.CAP_PROP_FPS):.0f} fps"
            )
            log.info("opened %s", self.description)
            failures = 0
            while not self._stop_event.is_set():
                start = time.perf_counter()
                ok, image = cap.read()
                end = time.perf_counter()
                if not ok:
                    failures += 1
                    if failures in (1, 30):
                        log.warning("camera read failed (%d in a row)", failures)
                    time.sleep(0.05)
                    continue
                failures = 0
                self.slot.put(CapturedFrame(image, end, (end - start) * 1000))
        except Exception as exc:  # report to the UI instead of dying silently
            self.error = f"Camera error: {exc}"
            log.exception("camera thread crashed")
        finally:
            cap.release()
