"""The pipeline thread: frames in, cursor moves and clicks out (DECISIONS.md D11).

Each loop iteration: apply pending commands, take the newest frame, run tracking and
feature extraction, run the engine, open or close the safety gate, send OS input, and
publish a status snapshot for the UI. Everything after the camera runs on this one thread,
so there are no thread hops between seeing a face and moving the cursor.

Frame sources:
    LiveSource       the webcam plus MediaPipe (normal use)
    SyntheticSource  blank grey frames through the real tracker (smoke tests, no camera)
    ReplaySource     recorded FeatureFrames from JSONL (deterministic runs, no camera)
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from nodwell.core.engine import (
    ApplySettings,
    Command,
    EngineOutput,
    InteractionEngine,
    Mode,
    Status,
)
from nodwell.core.features import extract
from nodwell.core.frame import FeatureFrame
from nodwell.core.recording import read_frames
from nodwell.core.safety import SafetyGate
from nodwell.core.settings import CameraSettings
from nodwell.core.timing import StageStats
from nodwell.platform.input_backend import GatedInput
from nodwell.platform.pointer_animator import PointerAnimator

if TYPE_CHECKING:
    from nodwell.tracking.camera import CameraThread
    from nodwell.tracking.landmarker import FaceTracker

log = logging.getLogger(__name__)

Timings = dict[str, float]


class FrameSource(Protocol):
    live: bool  # True if FeatureFrame.t is a perf_counter capture time (enables end-to-end)
    error: str | None

    @property
    def description(self) -> str:
        """Human-readable name of the source, for the UI and logs."""

    def prepare(self) -> None:
        """Heavy setup, run on the pipeline thread (e.g. loading MediaPipe)."""

    def next(self, min_interval_s: float, timings: Timings) -> FeatureFrame | None:
        """Block until the next frame; None means the source is finished."""

    def close(self) -> None: ...


class LiveSource:
    """Webcam frames tracked by MediaPipe."""

    live = True

    def __init__(self, camera_settings: CameraSettings, model: bytes) -> None:
        from nodwell.tracking.camera import CameraThread

        self._camera: CameraThread = CameraThread(camera_settings)
        self._model = model
        self._tracker: FaceTracker | None = None
        self._last_processed = -float("inf")
        self.error: str | None = None
        self.blendshape_names: list[str] = []

    @property
    def description(self) -> str:
        return self._camera.description

    @property
    def dropped_frames(self) -> int:
        """Frames the camera delivered that were overwritten before being processed."""
        return self._camera.slot.dropped

    def prepare(self) -> None:
        from nodwell.tracking.landmarker import FaceTracker

        self._camera.start()
        self._tracker = FaceTracker(self._model)

    def next(self, min_interval_s: float, timings: Timings) -> FeatureFrame | None:
        assert self._tracker is not None, "prepare() first"
        while True:
            item = self._camera.slot.get(timeout=0.5)
            if item is None:
                if not self._camera.is_alive():
                    self.error = self._camera.error or "Camera stopped"
                # No frame for 0.5 s: report "no face" so the engine freezes and,
                # if it lasts, auto-pauses.
                return FeatureFrame(t=time.perf_counter(), face=False)
            if item.t - self._last_processed >= min_interval_s:
                break  # otherwise skip it: paused mode runs at a lower rate
        self._last_processed = item.t
        timings["capture"] = item.read_ms
        timings["queue"] = (time.perf_counter() - item.t) * 1000
        result = self._tracker.process(item.image, item.t)
        timings["convert"] = result.convert_ms
        timings["inference"] = result.inference_ms
        a = time.perf_counter()
        frame = extract(result.face, item.t, result.brightness)
        timings["features"] = (time.perf_counter() - a) * 1000
        if not self.blendshape_names and self._tracker.blendshape_names:
            self.blendshape_names = self._tracker.blendshape_names
            log.info("model blendshapes: %s", ", ".join(self.blendshape_names))
        return frame

    def close(self) -> None:
        self._camera.stop()
        self._camera.join(timeout=2.0)
        if self._tracker is not None:
            self._tracker.close()


class SyntheticSource:
    """Blank grey frames at a fixed rate, through the real tracker. No camera needed."""

    live = True
    error: str | None = None
    description = "synthetic frames (no camera)"

    def __init__(self, model: bytes, fps: float = 30.0) -> None:
        self._model = model
        self._period = 1.0 / fps
        self._tracker: FaceTracker | None = None
        self._next_t = 0.0

    def prepare(self) -> None:
        import numpy as np

        from nodwell.tracking.landmarker import FaceTracker

        self._tracker = FaceTracker(self._model)
        self._image = np.full((480, 640, 3), 128, dtype=np.uint8)
        self._next_t = time.perf_counter()

    def next(self, min_interval_s: float, timings: Timings) -> FeatureFrame | None:
        assert self._tracker is not None, "prepare() first"
        self._next_t += max(self._period, min_interval_s)
        time.sleep(max(0.0, self._next_t - time.perf_counter()))
        t = time.perf_counter()
        result = self._tracker.process(self._image, t)
        timings["convert"] = result.convert_ms
        timings["inference"] = result.inference_ms
        return extract(result.face, t, result.brightness)

    def close(self) -> None:
        if self._tracker is not None:
            self._tracker.close()


class ReplaySource:
    """Recorded FeatureFrames, optionally paced in real time."""

    live = False
    error: str | None = None

    def __init__(self, path: Path, realtime: bool = True) -> None:
        self.description = f"replay of {path.name}"
        self._frames: Iterator[FeatureFrame] = read_frames(path)
        self._realtime = realtime
        self._offset: float | None = None

    def prepare(self) -> None:
        pass

    def next(self, min_interval_s: float, timings: Timings) -> FeatureFrame | None:
        frame = next(self._frames, None)
        if frame is not None and self._realtime:
            now = time.perf_counter()
            if self._offset is None:
                self._offset = now - frame.t
            time.sleep(max(0.0, frame.t + self._offset - now))
        return frame

    def close(self) -> None:
        pass


class FrameSink(Protocol):
    """Receives every FeatureFrame (e.g. the opt-in Recorder, or a benchmark counter)."""

    def write(self, frame: FeatureFrame) -> None: ...
    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class PipelineStatus:
    """What the UI shows: the engine's status plus pipeline health."""

    engine: Status
    fps: float
    source: str
    error: str | None


class Pipeline(threading.Thread):
    """Runs the per-frame loop on its own thread until `stop()`."""

    # A person moved the mouse if the real cursor is this far (OS pixels) from where we
    # last put it. Small enough to notice a hand on the mouse, large enough to ignore rounding.
    OVERRIDE_DISTANCE_PX = 12.0

    def __init__(
        self,
        source: FrameSource,
        engine: InteractionEngine,
        output: GatedInput,
        gate: SafetyGate,
        on_status: Callable[[PipelineStatus], None],
        paused_fps: float = 10.0,
        status_hz: float = 15.0,
        recorder: FrameSink | None = None,
    ) -> None:
        super().__init__(name="pipeline", daemon=True)
        self.source = source
        self.engine = engine
        self.output = output
        self.gate = gate
        self.on_status = on_status
        self.paused_fps = paused_fps
        self.recorder = recorder
        self.animator = PointerAnimator(output, engine.settings.pointer.motion_smoothing_ms / 1000)
        self.commands: queue.SimpleQueue[Command] = queue.SimpleQueue()
        self.stats = StageStats()
        self.frames = 0
        self.error: str | None = None
        self._status_period = 1.0 / status_hz
        self._stop_event = threading.Event()
        self._frame_times: deque[float] = deque(maxlen=60)

    def send(self, command: Command) -> None:
        """Queue a command; applied at the start of the next frame. Thread-safe."""
        self.commands.put(command)

    def stop(self) -> None:
        self._stop_event.set()

    def fps(self) -> float:
        times = self._frame_times
        if len(times) < 2 or times[-1] == times[0]:
            return 0.0
        return (len(times) - 1) / (times[-1] - times[0])

    def run(self) -> None:
        try:
            self.source.prepare()
        except Exception as exc:
            self.error = f"Tracking could not start: {exc}"
            log.exception("pipeline prepare failed")
            self.gate.block()
            return
        self.animator.start()
        last_status = 0.0
        last_mode = self.engine.mode
        try:
            while not self._stop_event.is_set():
                self._apply_commands()
                min_interval = 0.0 if self.engine.mode is Mode.ACTIVE else 1.0 / self.paused_fps
                timings: Timings = {}
                frame = self.source.next(min_interval, timings)
                if frame is None:
                    break
                e0 = time.perf_counter()
                manual = None
                if self.engine.mode is Mode.ACTIVE:
                    manual = self.output.external_move(self.OVERRIDE_DISTANCE_PX)
                    if manual is not None:
                        self.animator.clear()
                out = self.engine.update(frame, manual)
                e1 = time.perf_counter()
                mode = self.engine.mode
                self._sync_gate(mode, last_mode)
                self._dispatch(out)
                e2 = time.perf_counter()
                self._record(frame, timings, e1 - e0, e2 - e1, e2)
                if self.recorder is not None:
                    self.recorder.write(frame)
                if e2 - last_status >= self._status_period or mode is not last_mode:
                    self._publish(out.status)
                    last_status = e2
                last_mode = mode
        except Exception as exc:
            self.error = f"Tracking stopped: {exc}"
            log.exception("pipeline crashed")
        finally:
            self.gate.block()
            self.output.release_all()  # never leave a mouse button held down
            self.animator.stop()
            self.source.close()
            if self.recorder is not None:
                self.recorder.close()

    def _apply_commands(self) -> None:
        while not self.commands.empty():
            command = self.commands.get_nowait()
            self.engine.handle(command)
            if isinstance(command, ApplySettings):
                self.animator.tau_s = command.settings.pointer.motion_smoothing_ms / 1000

    def _sync_gate(self, mode: Mode, last_mode: Mode) -> None:
        """Open the gate only on *entering* ACTIVE, never "because we're still ACTIVE".

        A panic block from the hotkey thread must stick until the engine has processed
        the matching Pause.
        """
        if mode is not Mode.ACTIVE:
            self.gate.block()
            self.animator.clear()
        elif last_mode is not Mode.ACTIVE:
            self.output.forget_written()
            self.gate.allow()

    def _dispatch(self, out: EngineOutput) -> None:
        """Send the engine's decisions to the OS, in a safe order."""
        if out.release_all:
            self.output.release_all()
        if out.clicks and out.click_at is not None:
            # Clicks land exactly on target, not wherever the easing has got to.
            self.animator.snap_to(*out.click_at)
            for action in out.clicks:
                self.output.perform(action)
        elif out.move_to is not None:
            self.animator.set_target(*out.move_to)
        if out.scroll is not None:
            self.output.scroll(*out.scroll)

    def _record(
        self, frame: FeatureFrame, timings: Timings, engine_s: float, dispatch_s: float, end: float
    ) -> None:
        self.frames += 1
        self._frame_times.append(end)
        timings["engine"] = engine_s * 1000
        timings["dispatch"] = dispatch_s * 1000
        if self.source.live and "capture" in timings:
            timings["end_to_end"] = (end - frame.t) * 1000
        for stage, ms in timings.items():
            self.stats.add(stage, ms)

    def _publish(self, status: Status) -> None:
        self.on_status(
            PipelineStatus(
                engine=status,
                fps=self.fps(),
                source=self.source.description,
                error=self.error or self.source.error,
            )
        )
