"""The interaction engine: turns FeatureFrames into pointer moves and clicks.

A pure state machine. It is fed one FeatureFrame per camera frame (plus the real cursor
position, read back from the OS) and returns what should happen: where the cursor goes,
whether to click, and a status snapshot for the UI. It never touches the OS itself.

Modes:
    STARTING  waiting for a face that stays tracked for `startup_stable_s`, then recenters
              and goes ACTIVE. Launching the app is the deliberate act that starts control.
    ACTIVE    pointer follows the head; dwell clicks fire.
    PAUSED    nothing moves or clicks. Left by Resume (button, hotkey) or the pause gesture.

Fail-safes (CLAUDE.md §4.4): no face -> no moves and no clicks, and auto-pause after
`face_lost_pause_s`; a short grace period after the face comes back; clicks rate limited;
if someone else moves the mouse, the engine yields for `manual_override_s`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from .dwell import DwellDetector
from .features import Quality, quality
from .filters import OneEuroFilter, smoothness_to_min_cutoff
from .frame import FeatureFrame
from .gestures import HoldGesture
from .pointer import AxisConfig, ScreenRect, absolute_position, relative_step
from .safety import ClickRateLimiter
from .settings import Settings

Point = tuple[float, float]

# The real cursor counts as "moved by someone else" beyond this distance from where we put
# it, in physical pixels. Small enough to notice a hand on the mouse, large enough to
# ignore rounding.
OVERRIDE_DISTANCE_PX = 12.0
# Relative mode integrates speed over time; cap the step so a stalled frame can't teleport.
MAX_DT_S = 0.1


class Mode(StrEnum):
    STARTING = "starting"
    ACTIVE = "active"
    PAUSED = "paused"


class PauseReason(StrEnum):
    NONE = "none"
    USER = "user"  # button, tray, or hotkey
    GESTURE = "gesture"
    FACE_LOST = "face_lost"


# ---------------------------------------------------------------- commands (UI -> engine)


@dataclass(frozen=True, slots=True)
class Pause:
    reason: PauseReason = PauseReason.USER


@dataclass(frozen=True, slots=True)
class Resume:
    """Go ACTIVE and recenter on the current head pose."""


@dataclass(frozen=True, slots=True)
class Recenter:
    """Make the current head pose the neutral pose."""


@dataclass(frozen=True, slots=True)
class ApplySettings:
    settings: Settings


@dataclass(frozen=True, slots=True)
class SetScreen:
    screen: ScreenRect
    device_pixel_ratio: float = 1.0


Command = Pause | Resume | Recenter | ApplySettings | SetScreen


# ---------------------------------------------------------------- outputs (engine -> world)


@dataclass(frozen=True, slots=True)
class Status:
    """Snapshot for the UI. Everything a status pill, meter, or ring needs."""

    mode: Mode
    pause_reason: PauseReason
    face: bool
    quality: Quality
    pointer: Point
    dwell_progress: float
    gesture_name: str
    gesture_value: float | None  # None: no face, or the model lacks this blendshape
    gesture_available: bool | None  # None: not known yet (no face seen)
    gesture_progress: float
    drift_suggested: bool
    manual_override: bool


@dataclass(frozen=True, slots=True)
class EngineOutput:
    move_to: Point | None
    click_at: Point | None
    status: Status


@dataclass(slots=True)
class _Neutral:
    yaw: float = 0.0
    pitch: float = 0.0
    pending: bool = True  # recenter at the next frame with a face


@dataclass(slots=True)
class _Drift:
    """Exponential moving average of the head offset from neutral."""

    yaw: float = 0.0
    pitch: float = 0.0
    last_t: float | None = None
    suggested: bool = False


class InteractionEngine:
    """Pure state machine from FeatureFrames to pointer actions. Single-threaded."""

    def __init__(
        self, settings: Settings, screen: ScreenRect, device_pixel_ratio: float = 1.0
    ) -> None:
        self._filter_params: tuple[float, float, float] | None = None
        self._clicks: ClickRateLimiter | None = None
        self._screen = screen
        self._dpr = device_pixel_ratio
        self.mode = Mode.STARTING
        self.pause_reason = PauseReason.NONE
        self._neutral = _Neutral()
        self._drift = _Drift()
        self._pos: Point = screen.center
        self._last_commanded: Point | None = None
        self._last_t: float | None = None
        self._face_lost_since: float | None = None
        self._face_since: float | None = None
        self._grace_until = 0.0
        self._override_until = 0.0
        self._gesture_available: bool | None = None
        self.apply_settings(settings)

    # ------------------------------------------------------------ configuration

    def apply_settings(self, settings: Settings) -> None:
        """Adopt new settings. Filter history is kept unless the filter params changed."""
        self.settings = settings
        p = settings.pointer
        params = (smoothness_to_min_cutoff(p.smoothness), p.beta, p.d_cutoff_hz)
        if self._filter_params != params:
            self._filter_params = params
            self._yaw_filter = OneEuroFilter(*params)
            self._pitch_filter = OneEuroFilter(*params)
        self._x_axis = AxisConfig(p.yaw_range_deg, p.invert_x, p.dead_zone_deg)
        self._y_axis = AxisConfig(p.pitch_range_deg, p.invert_y, p.dead_zone_deg)
        d = settings.dwell
        self._dwell = DwellDetector(d.dwell_s, d.radius_px * self._dpr)
        g = settings.pause_gesture
        self._gesture = HoldGesture(g.on_threshold, g.off_threshold, g.hold_s, g.cooldown_s)
        interval = settings.safety.min_click_interval_s
        if self._clicks is None or self._clicks.min_interval_s != interval:
            self._clicks = ClickRateLimiter(interval)

    def handle(self, command: Command) -> None:
        """Apply one command from the UI, a hotkey, or the tray."""
        match command:
            case Pause(reason):
                self._pause(reason)
            case Resume():
                self._activate()
            case Recenter():
                self._neutral.pending = True
            case ApplySettings(settings):
                self.apply_settings(settings)
            case SetScreen(screen, dpr):
                self._screen, self._dpr = screen, dpr
                self._pos = screen.clamp(*self._pos)
                self.apply_settings(self.settings)

    def _pause(self, reason: PauseReason) -> None:
        self.mode, self.pause_reason = Mode.PAUSED, reason
        self._dwell.reset()

    def _activate(self) -> None:
        self.mode, self.pause_reason = Mode.ACTIVE, PauseReason.NONE
        self._neutral.pending = True
        self._dwell.reset()
        self._last_commanded = None  # we didn't move the cursor while paused

    # ------------------------------------------------------------ per-frame update

    def update(self, frame: FeatureFrame, cursor: Point | None = None) -> EngineOutput:
        """Process one frame. `cursor` is the real OS cursor position, if known."""
        t = frame.t
        dt = 0.0 if self._last_t is None else min(max(t - self._last_t, 0.0), MAX_DT_S)
        self._last_t = t

        self._detect_manual_override(cursor, t)

        if not frame.face:
            return self._no_face(frame, t)
        if self._face_lost_since is not None:  # face just came back
            self._face_lost_since = None
            self._grace_until = t + self.settings.safety.reacquire_grace_s
            self._yaw_filter.reset()
            self._pitch_filter.reset()
        if self._face_since is None:
            self._face_since = t

        # Filters run in every mode so they are warm when control resumes.
        yaw = self._yaw_filter(frame.yaw, t)
        pitch = self._pitch_filter(frame.pitch, t)

        gesture_value, gesture_progress = self._update_gesture(frame, t)

        stable_for = t - self._face_since
        if self.mode is Mode.STARTING and stable_for >= self.settings.safety.startup_stable_s:
            self._activate()
        if self._neutral.pending:
            self._neutral = _Neutral(yaw, pitch, pending=False)
            self._drift = _Drift()

        dyaw, dpitch = yaw - self._neutral.yaw, pitch - self._neutral.pitch
        self._update_drift(dyaw, dpitch, t)

        move_to: Point | None = None
        click_at: Point | None = None
        dwell_progress = 0.0
        overriding = t < self._override_until
        if self.mode is Mode.ACTIVE and t >= self._grace_until and not overriding:
            p = self.settings.pointer
            x_axis, y_axis = self._x_axis, self._y_axis
            if p.mode == "absolute":
                self._pos = absolute_position(dyaw, dpitch, x_axis, y_axis, self._screen)
            else:
                max_speed = p.max_speed_screens_per_s * self._screen.width
                self._pos = relative_step(
                    self._pos,
                    dyaw,
                    dpitch,
                    dt,
                    x_axis,
                    y_axis,
                    max_speed,
                    p.acceleration,
                    self._screen,
                )
            move_to = self._pos
            self._last_commanded = self._pos
            if gesture_progress > 0.0:
                self._dwell.reset()  # a gesture in progress must not also click
            elif self.settings.dwell.enabled:
                d = self._dwell.update(*self._pos, t)
                dwell_progress = d.progress
                if d.fired and self._clicks is not None and self._clicks.try_acquire(t):
                    click_at = self._pos
        else:
            self._dwell.reset()

        return EngineOutput(
            move_to,
            click_at,
            self._status(frame, gesture_value, gesture_progress, dwell_progress),
        )

    def _no_face(self, frame: FeatureFrame, t: float) -> EngineOutput:
        """Face lost: freeze everything; auto-pause after a while."""
        if self._face_lost_since is None:
            self._face_lost_since = t
        self._face_since = None
        self._dwell.reset()
        self._gesture.reset()
        lost_for = t - self._face_lost_since
        if self.mode is Mode.ACTIVE and lost_for >= self.settings.safety.face_lost_pause_s:
            self._pause(PauseReason.FACE_LOST)
        return EngineOutput(None, None, self._status(frame, None, 0.0, 0.0))

    def _update_gesture(self, frame: FeatureFrame, t: float) -> tuple[float | None, float]:
        """Run the pause/resume hold gesture. Returns (score, hold progress)."""
        g = self.settings.pause_gesture
        value = frame.blendshapes.get(g.blendshape)
        if frame.blendshapes:
            self._gesture_available = value is not None
        if not g.enabled or value is None:
            return value, 0.0
        update = self._gesture.update(value, t)
        if update.fired:
            if self.mode is Mode.ACTIVE:
                self._pause(PauseReason.GESTURE)
            else:
                self._activate()
        return value, update.progress

    def _detect_manual_override(self, cursor: Point | None, t: float) -> None:
        """If the real cursor isn't where we put it, a person moved the mouse: yield."""
        if cursor is None or self._last_commanded is None:
            return
        if math.dist(cursor, self._last_commanded) > OVERRIDE_DISTANCE_PX:
            self._override_until = t + self.settings.safety.manual_override_s
            self._pos = self._screen.clamp(*cursor)
            self._last_commanded = None
            self._dwell.reset()

    def _update_drift(self, dyaw: float, dpitch: float, t: float) -> None:
        """Suggest recentering when the average head offset stays far from neutral.

        Exponential moving average with time constant tau: each frame moves the average a
        fraction (1 - e^(-dt/tau)) of the way toward the current offset.
        """
        cfg = self.settings.drift
        d = self._drift
        if d.last_t is not None and cfg.enabled:
            k = 1.0 - math.exp(-(t - d.last_t) / cfg.time_constant_s)
            d.yaw += k * (dyaw - d.yaw)
            d.pitch += k * (dpitch - d.pitch)
            d.suggested = math.hypot(d.yaw, d.pitch) > cfg.threshold_deg
        d.last_t = t

    def _status(
        self,
        frame: FeatureFrame,
        gesture_value: float | None,
        gesture_progress: float,
        dwell_progress: float,
    ) -> Status:
        return Status(
            mode=self.mode,
            pause_reason=self.pause_reason,
            face=frame.face,
            quality=quality(frame),
            pointer=self._pos,
            dwell_progress=dwell_progress,
            gesture_name=self.settings.pause_gesture.blendshape,
            gesture_value=gesture_value,
            gesture_available=self._gesture_available,
            gesture_progress=gesture_progress,
            drift_suggested=self._drift.suggested,
            manual_override=frame.t < self._override_until,
        )
