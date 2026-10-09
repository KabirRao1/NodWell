"""Composition root: builds settings, threads, backends, and UI, and wires them together."""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError
from PySide6.QtCore import QLockFile, QObject, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QScreen
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from nodwell import paths
from nodwell.core.actions import ClickType
from nodwell.core.engine import (
    ApplySettings,
    InteractionEngine,
    Pause,
    PauseReason,
    Recenter,
    Rect,
    Resume,
    SetClickType,
    SetOwnUi,
    SetScreen,
)
from nodwell.core.pointer import ScreenRect
from nodwell.core.recording import Recorder
from nodwell.core.safety import SafetyGate
from nodwell.core.settings import Settings, load_settings, save_settings
from nodwell.diagnostics import NetworkTripwire
from nodwell.i18n import _
from nodwell.pipeline import (
    FrameSource,
    LiveSource,
    Pipeline,
    PipelineStatus,
    ReplaySource,
    SyntheticSource,
)
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
    # Whole physical pixels: e.g. 1646 logical px x 1.75 = 2880.5, but the screen is 2880.
    rect = ScreenRect(
        round(g.x() * scale), round(g.y() * scale), int(g.width() * scale), int(g.height() * scale)
    )
    return rect, scale


class Bridge(QObject):
    """Carries events from worker threads to the Qt main thread (queued signals)."""

    status = Signal(object)
    quit_requested = Signal()


class Controller:
    """User intents (from panel, toolbar, tray, hotkeys) -> engine commands and settings.

    `pause`, `toggle_pause`, and `recenter` are also called from the hotkey thread; they
    only touch thread-safe objects (the gate, the output lock, the command queue).
    Settings changes happen on the main thread only.
    """

    def __init__(
        self, settings: Settings, pipeline: Pipeline, gate: SafetyGate, output: GatedInput
    ) -> None:
        self.settings = settings
        self.pipeline = pipeline
        self.gate = gate
        self.output = output
        self.on_settings: list[Callable[[Settings], None]] = []

    def pause(self) -> None:
        # Stop output now and let go of any held button; the engine catches up next frame.
        self.gate.block()
        self.output.release_all()
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

    def set_click_type(self, click_type: ClickType) -> None:
        self.pipeline.send(SetClickType(click_type))

    def update_settings(self, settings: Settings) -> None:
        """Validate, apply live, and save. Invalid settings are refused, not applied."""
        try:
            # model_copy() skips validation, so re-validate everything the UI produced.
            settings = Settings.model_validate(settings.model_dump())
        except ValidationError:
            log.exception("refused invalid settings from the UI")
            return
        self.settings = settings
        self.pipeline.send(ApplySettings(settings))
        for callback in self.on_settings:
            callback(settings)
        try:
            save_settings(paths.settings_path(), settings)
        except OSError:
            log.exception("could not save settings")


def _single_instance_lock() -> QLockFile | None:
    """Two copies fighting over the cursor would be dangerous; allow only one."""
    lock = QLockFile(str(paths.lock_path()))
    lock.setStaleLockTime(0)  # stale only if the owning process is gone
    return lock if lock.tryLock(100) else None


def own_ui_rects(widgets: list[QWidget], scale: float) -> tuple[Rect, ...]:
    """Screen rectangles of our visible windows, in OS input coordinates."""
    rects = []
    for w in widgets:
        if w.isVisible():
            g = w.frameGeometry()
            rects.append((g.x() * scale, g.y() * scale, g.width() * scale, g.height() * scale))
    return tuple(rects)


def run(options: Options) -> int:
    """Start the app; returns the process exit code."""
    tripwire = NetworkTripwire().install() if options.smoke_test else None
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
            source = SyntheticSource(paths.load_model())
        else:
            source = LiveSource(settings.camera, paths.load_model())
    except (paths.ModelError, OSError) as exc:
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
    controller = Controller(settings, pipeline, gate, output)

    # UI (imported here so `--help` and tests don't pay for Qt widgets).
    from nodwell.ui.overlays.dwell_ring import DwellRing
    from nodwell.ui.panel import StatusPanel
    from nodwell.ui.toolbar import ClickToolbar
    from nodwell.ui.tray import Tray

    panel = StatusPanel(settings)
    toolbar = ClickToolbar()
    ring = DwellRing()
    tray = Tray()

    def on_status(ps: PipelineStatus) -> None:
        s = ps.engine
        panel.update_status(ps)
        toolbar.update_status(s)
        tray.set_mode(s.mode)
        ring.set_state(
            s.dwell_progress,
            controller.settings.dwell.dwell_s,
            s.click_type,
            s.dragging,
            s.scrolling,
            s.scroll_direction,
        )

    def apply_toolbar(s: Settings) -> None:
        if s.toolbar.visible:
            toolbar.show_docked(s.toolbar.edge)
        else:
            toolbar.hide()

    def quit_app() -> None:
        panel.allow_close()
        app.quit()

    def show_panel() -> None:
        panel.showNormal()
        panel.raise_()
        panel.activateWindow()

    controller.on_settings.append(apply_toolbar)
    bridge.status.connect(on_status)
    bridge.quit_requested.connect(quit_app)
    panel.pause_clicked.connect(controller.pause)
    panel.resume_clicked.connect(controller.resume)
    panel.recenter_clicked.connect(controller.recenter)
    panel.settings_changed.connect(controller.update_settings)
    panel.quit_clicked.connect(quit_app)
    toolbar.click_type_selected.connect(controller.set_click_type)
    tray.toggle_pause.connect(controller.toggle_pause)
    tray.recenter.connect(controller.recenter)
    tray.show_panel.connect(show_panel)
    tray.quit.connect(quit_app)

    def on_screen_changed() -> None:
        rect, s = primary_screen_rect()
        pipeline.send(SetScreen(rect, s))
        apply_toolbar(controller.settings)

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

    # Housekeeping twice a second: errors from worker threads (e.g. the camera won't
    # open) and where our own windows are, so clicks on them stay plain left clicks.
    last_rects: list[tuple[Rect, ...]] = [()]

    def housekeeping() -> None:
        message = pipeline.error or source.error or hotkeys.error
        if message:
            panel.show_error(message)
        rects = own_ui_rects([panel, toolbar], primary_screen_rect()[1])
        if rects != last_rects[0]:
            last_rects[0] = rects
            pipeline.send(SetOwnUi(rects))

    timer = QTimer()
    timer.timeout.connect(housekeeping)
    timer.start(500)

    # Panel top-right, toolbar on its edge: both easy to reach with a head pointer.
    panel.adjustSize()
    avail = primary.availableGeometry()
    panel.move(avail.right() - panel.width() - 24, avail.top() + 24)
    panel.show()
    apply_toolbar(settings)
    tray.show()
    housekeeping()
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
    output.release_all()
    toolbar.hide()
    tray.hide()
    lock.unlock()

    if options.smoke_test:
        attempts = tripwire.attempts if tripwire is not None else []
        ok = pipeline.frames > 0 and pipeline.error is None and not attempts
        log.info(
            "smoke test: %s (%d frames, error=%s, network attempts=%s, stages=%s)",
            "PASS" if ok else "FAIL",
            pipeline.frames,
            pipeline.error,
            attempts,
            {k: v["p50"] for k, v in pipeline.stats.summary().items()},
        )
        return 0 if ok else 1
    if isinstance(backend, DryRunBackend):
        log.info("dry run: %d moves, %d actions", backend.moves, len(backend.actions))
    return code
