"""Composition root: builds settings, threads, backends, and UI, and wires them together."""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, QStandardPaths, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QScreen
from PySide6.QtWidgets import QApplication, QMessageBox

from nodwell import paths
from nodwell.core.engine import (
    ApplySettings,
    InteractionEngine,
    Pause,
    PauseReason,
    Recenter,
    Resume,
    SetScreen,
)
from nodwell.core.pointer import ScreenRect
from nodwell.core.recording import Recorder
from nodwell.core.safety import SafetyGate
from nodwell.core.settings import Settings, load_settings, save_settings
from nodwell.i18n import _
from nodwell.pipeline import FrameSource, LiveSource, Pipeline, PipelineStatus, ReplaySource
from nodwell.platform.hotkeys import GlobalHotkeys
from nodwell.platform.input_backend import DryRunBackend, GatedInput, InputBackend

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Options:
    """Command-line options (see __main__.py)."""

    camera: int | None = None
    dry_run: bool = False
    replay: Path | None = None
    record: Path | None = None
    smoke_test: bool = False


def os_pointer_scale(screen: QScreen) -> float:
    """Factor from Qt's logical pixels to the coordinates pynput uses (DECISIONS.md D12).

    Windows and X11 inject input in physical pixels (Qt makes the process DPI-aware), so
    the factor is the screen's device pixel ratio. macOS uses points, like Qt, so it's 1.
    """
    return 1.0 if sys.platform == "darwin" else screen.devicePixelRatio()


def primary_screen_rect() -> tuple[ScreenRect, float]:
    """The primary screen in OS input coordinates, plus the scale factor (M1: primary only)."""
    screen = QGuiApplication.primaryScreen()
    scale = os_pointer_scale(screen)
    g = screen.geometry()
    rect = ScreenRect(g.x() * scale, g.y() * scale, g.width() * scale, g.height() * scale)
    return rect, scale


class Bridge(QObject):
    """Carries events from worker threads to the Qt main thread (queued signals)."""

    status = Signal(object)
    quit_requested = Signal()


class Controller:
    """User intents (from panel, tray, hotkeys) -> engine commands and settings changes.

    `pause`, `toggle_pause`, and `recenter` are called from the hotkey thread too; they
    only touch the thread-safe gate and command queue. Settings changes happen on the
    main thread only.
    """

    def __init__(self, settings: Settings, pipeline: Pipeline, gate: SafetyGate) -> None:
        self.settings = settings
        self.pipeline = pipeline
        self.gate = gate

    def pause(self) -> None:
        self.gate.block()  # stop output now; the engine catches up on its next frame
        self.pipeline.send(Pause(PauseReason.USER))

    def resume(self) -> None:
        self.pipeline.send(Resume())

    def toggle_pause(self) -> None:
        """Hotkey: the panic stop when running, resume when stopped."""
        if self.gate.allows():
            self.pause()
        else:
            self.resume()

    def recenter(self) -> None:
        self.pipeline.send(Recenter())

    def update_settings(self, settings: Settings) -> None:
        self.settings = settings
        self.pipeline.send(ApplySettings(settings))
        try:
            save_settings(paths.settings_path(), settings)
        except OSError:
            log.exception("could not save settings")

    def set_pointer_mode(self, mode: str) -> None:
        s = self.settings
        self.update_settings(
            s.model_copy(update={"pointer": s.pointer.model_copy(update={"mode": mode})})
        )

    def set_dwell(self, enabled: bool) -> None:
        s = self.settings
        self.update_settings(
            s.model_copy(update={"dwell": s.dwell.model_copy(update={"enabled": enabled})})
        )


def _single_instance_lock() -> QLockFile | None:
    """Two copies fighting over the cursor would be dangerous; allow only one."""
    folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.TempLocation)
    lock = QLockFile(str(Path(folder) / "nodwell.lock"))
    lock.setStaleLockTime(0)
    return lock if lock.tryLock(100) else None


def run(options: Options) -> int:
    """Start the app; returns the process exit code."""
    app = QApplication(sys.argv)  # first: sets per-monitor DPI awareness (D12)
    app.setApplicationName("Nodwell")
    app.setQuitOnLastWindowClosed(False)

    lock = _single_instance_lock()
    if lock is None:
        if not options.smoke_test:
            QMessageBox.information(None, "Nodwell", _("Nodwell is already running."))
        return 1

    settings = load_settings(paths.settings_path())
    if options.camera is not None:
        settings = settings.model_copy(
            update={"camera": settings.camera.model_copy(update={"index": options.camera})}
        )

    source: FrameSource
    try:
        if options.replay is not None:
            source = ReplaySource(options.replay)
        elif options.smoke_test:
            from nodwell.pipeline import SyntheticSource

            source = SyntheticSource(paths.verify_model())
        else:
            source = LiveSource(settings.camera, paths.verify_model())
    except paths.ModelError as exc:
        log.error("%s", exc)
        if not options.smoke_test:
            QMessageBox.critical(None, "Nodwell", str(exc))
        return 1

    screen, scale = primary_screen_rect()
    log.info("primary screen %s (scale %.2f)", screen, scale)

    gate = SafetyGate()
    backend: InputBackend
    if options.dry_run or options.smoke_test or options.replay is not None:
        backend = DryRunBackend()
    else:
        from nodwell.platform.input_backend import PynputBackend

        backend = PynputBackend()  # after QApplication, see D12
    output = GatedInput(backend, gate, settings.safety.min_click_interval_s)
    engine = InteractionEngine(settings, screen, scale)

    recorder = None
    if options.record is not None:
        log.warning("recording FeatureFrames (numbers only, no images) to %s", options.record)
        recorder = Recorder(options.record)

    bridge = Bridge()
    pipeline = Pipeline(
        source,
        engine,
        output,
        gate,
        on_status=bridge.status.emit,
        paused_fps=settings.camera.paused_fps,
        recorder=recorder,
    )
    controller = Controller(settings, pipeline, gate)

    # UI (imported here so `--help` and tests don't pay for Qt widgets).
    from nodwell.ui.overlays.dwell_ring import DwellRing
    from nodwell.ui.panel import StatusPanel
    from nodwell.ui.tray import Tray

    panel = StatusPanel(settings)
    ring = DwellRing()
    tray = Tray()

    def on_status(ps: PipelineStatus) -> None:
        panel.update_status(ps)
        tray.set_mode(ps.engine.mode)
        ring.set_progress(ps.engine.dwell_progress, controller.settings.dwell.dwell_s)

    def quit_app() -> None:
        panel.allow_close()
        app.quit()

    def show_panel() -> None:
        panel.showNormal()
        panel.raise_()
        panel.activateWindow()

    bridge.status.connect(on_status)
    bridge.quit_requested.connect(quit_app)
    panel.pause_clicked.connect(controller.pause)
    panel.resume_clicked.connect(controller.resume)
    panel.recenter_clicked.connect(controller.recenter)
    panel.mode_selected.connect(controller.set_pointer_mode)
    panel.dwell_toggled.connect(controller.set_dwell)
    panel.quit_clicked.connect(quit_app)
    tray.toggle_pause.connect(controller.toggle_pause)
    tray.recenter.connect(controller.recenter)
    tray.show_panel.connect(show_panel)
    tray.quit.connect(quit_app)

    def on_screen_changed() -> None:
        rect, s = primary_screen_rect()
        pipeline.send(SetScreen(rect, s))

    primary = QGuiApplication.primaryScreen()
    primary.geometryChanged.connect(on_screen_changed)
    app.primaryScreenChanged.connect(on_screen_changed)

    hk = settings.hotkeys
    hotkeys = GlobalHotkeys(
        {
            hk.pause: controller.toggle_pause,
            hk.recenter: controller.recenter,
            hk.quit: bridge.quit_requested.emit,
        }
    )

    # Errors raised on worker threads before any status arrives (e.g. camera won't open).
    def poll_errors() -> None:
        message = pipeline.error or source.error or hotkeys.error
        if message:
            panel.show_error(message)

    error_timer = QTimer()
    error_timer.timeout.connect(poll_errors)
    error_timer.start(500)

    # Top-right corner: easy to reach with a head pointer, out of the way of most apps.
    panel.adjustSize()
    avail = primary.availableGeometry()
    panel.move(avail.right() - panel.width() - 24, avail.top() + 24)
    panel.show()
    tray.show()
    if not options.smoke_test:
        hotkeys.start()
    pipeline.start()  # MediaPipe loads on the pipeline thread, after the panel is up

    if options.smoke_test:
        # Quit once 30 frames went through the whole pipeline (or after 30 s: fail).
        def check_smoke() -> None:
            if pipeline.frames >= 30 or pipeline.error or not pipeline.is_alive():
                quit_app()

        smoke_timer = QTimer()
        smoke_timer.timeout.connect(check_smoke)
        smoke_timer.start(200)
        QTimer.singleShot(30_000, quit_app)

    code = app.exec()

    hotkeys.stop()
    pipeline.stop()
    pipeline.join(timeout=3.0)
    gate.block()
    tray.hide()
    lock.unlock()

    if options.smoke_test:
        ok = pipeline.frames > 0 and pipeline.error is None
        log.info(
            "smoke test: %s (%d frames, error=%s, stages=%s)",
            "PASS" if ok else "FAIL",
            pipeline.frames,
            pipeline.error,
            {k: v["p50"] for k, v in pipeline.stats.summary().items()},
        )
        return 0 if ok else 1
    if isinstance(backend, DryRunBackend):
        log.info("dry run: %d moves, %d clicks", backend.moves, len(backend.clicks))
    return code
