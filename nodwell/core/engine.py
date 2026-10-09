"""The interaction engine: turns FeatureFrames into pointer moves, clicks, and scrolls.

A pure state machine. It is fed one FeatureFrame per camera frame and returns what should
happen: where the cursor goes, which mouse actions to perform, how much to scroll, and a
status snapshot for the UI. It never touches the OS itself.

Modes:
    STARTING  waiting for a face that stays tracked for `startup_stable_s`, then recenters
              and goes ACTIVE. Launching the app is the deliberate act that starts control.
    ACTIVE    pointer follows the head; dwell and gesture clicks fire.
    PAUSED    nothing moves or clicks. Left by Resume (button, hotkey) or the pause gesture.

Inside ACTIVE, the click type chosen on the toolbar decides what the next dwell does
(left, right, double, middle, drag, or scroll), and gesture bindings act directly.

Fail-safes (CLAUDE.md §4.4): no face -> no moves and no clicks, any held button released,
and auto-pause after `face_lost_pause_s`; a short grace period after the face comes back;
clicks rate limited; if a person moves the mouse, the engine yields for
`manual_override_s`; pausing releases a held drag button and stops scrolling.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from enum import StrEnum

from .actions import (
    GESTURE_CLICKS,
    LEFT_CLICK,
    PRESS_LEFT,
    RELEASE_LEFT,
    SIMPLE_CLICKS,
    ClickAction,
    ClickType,
    GestureAction,
    scroll_speed,
)
from .dwell import DwellDetector
from .features import Quality, quality
from .filters import OneEuroFilter, smoothness_to_min_cutoff
from .frame import FeatureFrame
from .gestures import DERIVED_SOURCES, HoldGesture, gesture_score
from .pointer import AxisConfig, ScreenRect, absolute_position, relative_step
from .safety import ClickRateLimiter
from .settings import GestureBinding, Settings

Point = tuple[float, float]
Rect = tuple[float, float, float, float]  # left, top, width, height (OS input coordinates)

# Relative mode integrates speed over time; cap the step so a stalled frame can't teleport.
MAX_DT_S = 0.1
# Facial and tilt gestures nudge the head. The click lands where the pointer was this long
# before the hold began, and the pointer stays there briefly after the gesture fires.
ANCHOR_LOOKBACK_S = 0.15
ANCHOR_AFTER_FIRE_S = 0.5


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


@dataclass(frozen=True, slots=True)
class SetClickType:
    """Toolbar choice: what the next dwell does."""

    click_type: ClickType


@dataclass(frozen=True, slots=True)
class SetOwnUi:
    """Rectangles of our own windows (panel, toolbar): clicks there are always plain left."""

    rects: tuple[Rect, ...]


Command = Pause | Resume | Recenter | ApplySettings | SetScreen | SetClickType | SetOwnUi


# ---------------------------------------------------------------- outputs (engine -> world)


@dataclass(frozen=True, slots=True)
class GestureReading:
    """Live state of one gesture binding, for its meter in the UI."""

    id: str
    label: str
    action: GestureAction
    value: float | None  # None: no face, or the model lacks this source
    threshold: float
    progress: float  # 0..1 of the hold time
    enabled: bool
    available: bool | None  # None: not known yet (no face seen)


@dataclass(frozen=True, slots=True)
class Status:
    """Snapshot for the UI. Everything a status pill, meter, toolbar, or ring needs."""

    mode: Mode
    pause_reason: PauseReason
    face: bool
    quality: Quality
    pointer: Point
    dwell_progress: float
    click_type: ClickType
    dragging: bool
    scrolling: bool
    scroll_direction: int  # -1 down, 0 still, +1 up
    gestures: tuple[GestureReading, ...]
    drift_suggested: bool
    manual_override: bool


@dataclass(frozen=True, slots=True)
class EngineOutput:
    move_to: Point | None
    clicks: tuple[ClickAction, ...]  # performed in order at `click_at`
    click_at: Point | None
    scroll: Point | None  # (dx, dy) wheel notches this frame, fractional; +dy = up
    release_all: bool  # release any held mouse button now (bypasses the gate)
    status: Status


@dataclass(slots=True)
class _Neutral:
    yaw: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0
    pending: bool = True  # recenter at the next frame with a face


@dataclass(slots=True)
class _Drift:
    """Exponential moving average of the head offset from neutral."""

    yaw: float = 0.0
    pitch: float = 0.0
    last_t: float | None = None
    suggested: bool = False


@dataclass(slots=True)
class _Scroll:
    """Head-controlled scrolling anchored at a point."""

    anchor: Point
    yaw0: float
    pitch0: float
    idle_since: float | None = None
    away_since: float | None = None
    direction: int = 0


class InteractionEngine:
    """Pure state machine from FeatureFrames to pointer actions. Single-threaded."""

    def __init__(
        self, settings: Settings, screen: ScreenRect, device_pixel_ratio: float = 1.0
    ) -> None:
        self._filter_params: tuple[float, float, float] | None = None
        self._clicks: ClickRateLimiter | None = None
        self._gestures: dict[str, tuple[GestureBinding, HoldGesture]] = {}
        self._screen = screen
        self._dpr = device_pixel_ratio
        self.mode = Mode.STARTING
        self.pause_reason = PauseReason.NONE
        self.click_type = ClickType.LEFT
        self.dragging = False
        self._neutral = _Neutral()
        self._drift = _Drift()
        self._pos: Point = screen.center
        self._history: deque[tuple[float, Point]] = deque(maxlen=32)
        self._anchor: Point | None = None
        self._anchor_until = 0.0
        self._scroll: _Scroll | None = None
        self._own_ui: tuple[Rect, ...] = ()
        self._release_pending = False
        self._last_t: float | None = None
        self._face_lost_since: float | None = None
        self._face_since: float | None = None
        self._grace_until = 0.0
        self._override_until = 0.0
        self._available: dict[str, bool] = {}
        self.apply_settings(settings)

    # ------------------------------------------------------------ configuration

    def apply_settings(self, settings: Settings) -> None:
        """Adopt new settings, keeping filter and gesture state where nothing changed."""
        self.settings = settings
        p = settings.pointer
        params = (smoothness_to_min_cutoff(p.smoothness), p.beta, p.d_cutoff_hz)
        if self._filter_params != params:
            self._filter_params = params
            self._yaw_filter = OneEuroFilter(*params)
            self._pitch_filter = OneEuroFilter(*params)
            self._roll_filter = OneEuroFilter(*params)
        self._x_axis = AxisConfig(p.yaw_range_deg, p.invert_x, p.dead_zone_deg)
        self._y_axis = AxisConfig(p.pitch_range_deg, p.invert_y, p.dead_zone_deg)
        d = settings.dwell
        self._dwell = DwellDetector(d.dwell_s, d.radius_px * self._dpr)
        gestures: dict[str, tuple[GestureBinding, HoldGesture]] = {}
        for b in settings.gestures.bindings:
            old = self._gestures.get(b.id)
            if old is not None and old[0] == b:
                gestures[b.id] = old  # unchanged: keep its hold and cooldown state
            else:
                detector = HoldGesture(b.on_threshold, b.off_threshold, b.hold_s, b.cooldown_s)
                gestures[b.id] = (b, detector)
        self._gestures = gestures
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
            case SetClickType(click_type):
                self._select_click_type(click_type)
            case SetOwnUi(rects):
                self._own_ui = rects

    def _select_click_type(self, click_type: ClickType) -> None:
        if click_type is not ClickType.DRAG:
            self._end_drag()
        if click_type is not ClickType.SCROLL:
            self._scroll = None
        self.click_type = click_type

    def _pause(self, reason: PauseReason) -> None:
        self.mode, self.pause_reason = Mode.PAUSED, reason
        self._dwell.reset()
        self._end_drag()
        self._stop_scroll()
        self._anchor = None

    def _activate(self) -> None:
        self.mode, self.pause_reason = Mode.ACTIVE, PauseReason.NONE
        self._neutral.pending = True
        self._dwell.reset()

    def _end_drag(self) -> None:
        if self.dragging:
            self.dragging = False
            self._release_pending = True

    def _stop_scroll(self) -> None:
        if self._scroll is not None:
            self._scroll = None
            self._used_click_type()

    def _used_click_type(self) -> None:
        """A one-shot toolbar choice has been used: go back to left click."""
        if not self.settings.dwell.sticky_click_type:
            self.click_type = ClickType.LEFT

    # ------------------------------------------------------------ per-frame update

    def update(self, frame: FeatureFrame, manual_cursor: Point | None = None) -> EngineOutput:
        """Process one frame.

        `manual_cursor` is the real cursor position when a person has just moved the mouse
        (the output layer detects that); None otherwise.
        """
        t = frame.t
        dt = 0.0 if self._last_t is None else min(max(t - self._last_t, 0.0), MAX_DT_S)
        self._last_t = t

        if manual_cursor is not None:
            self._override_until = t + self.settings.safety.manual_override_s
            self._pos = self._screen.clamp(*manual_cursor)
            self._dwell.reset()
            self._anchor = None
            self._end_drag()
            self._stop_scroll()

        if not frame.face:
            return self._no_face(frame, t)
        if self._face_lost_since is not None:  # face just came back
            self._face_lost_since = None
            self._grace_until = t + self.settings.safety.reacquire_grace_s
            for f in (self._yaw_filter, self._pitch_filter, self._roll_filter):
                f.reset()
        if self._face_since is None:
            self._face_since = t

        # Filters run in every mode so they are warm when control resumes.
        yaw = self._yaw_filter(frame.yaw, t)
        pitch = self._pitch_filter(frame.pitch, t)
        roll = self._roll_filter(frame.roll, t)

        stable_for = t - self._face_since
        if self.mode is Mode.STARTING and stable_for >= self.settings.safety.startup_stable_s:
            self._activate()
        if self._neutral.pending:
            self._neutral = _Neutral(yaw, pitch, roll, pending=False)
            self._drift = _Drift()
        dyaw = yaw - self._neutral.yaw
        dpitch = pitch - self._neutral.pitch
        droll = roll - self._neutral.roll
        self._update_drift(dyaw, dpitch, t)

        readings, fired = self._update_gestures(frame, droll, t)
        holding = any(r.progress > 0.0 for r in readings)

        clicks: list[ClickAction] = []
        click_at: Point | None = None
        for binding in fired:
            action = binding.action
            if action is GestureAction.PAUSE_TOGGLE:
                if self.mode is Mode.ACTIVE:
                    self._pause(PauseReason.GESTURE)
                else:
                    self._activate()
            elif action is GestureAction.RECENTER:
                self._neutral.pending = True
            elif self._can_act(t):
                point = self._anchor or self._pos
                done = self._gesture_action(action, point, dyaw, dpitch, t)
                if done:
                    clicks += done
                    click_at = point
                self._anchor_until = t + ANCHOR_AFTER_FIRE_S

        move_to: Point | None = None
        scroll: Point | None = None
        dwell_progress = 0.0
        if self._can_act(t):
            if self._scroll is not None:
                scroll = self._update_scroll(dyaw, dpitch, dt, t)
                self._dwell.reset()
            else:
                self._update_pointer(dyaw, dpitch, dt, t, holding)
                move_to = self._pos
                if holding:
                    self._dwell.reset()  # a gesture in progress must not also dwell-click
                elif self.settings.dwell.enabled and not clicks:
                    d = self._dwell.update(*self._pos, t)
                    dwell_progress = d.progress
                    if d.fired:
                        done = self._dwell_click(self._pos, dyaw, dpitch, t)
                        if done:
                            clicks += done
                            click_at = self._pos
        else:
            self._dwell.reset()
            self._anchor = None

        return self._output(
            frame, move_to, tuple(clicks), click_at, scroll, readings, dwell_progress
        )

    def _can_act(self, t: float) -> bool:
        return self.mode is Mode.ACTIVE and t >= self._grace_until and t >= self._override_until

    def _update_pointer(
        self, dyaw: float, dpitch: float, dt: float, t: float, holding: bool
    ) -> None:
        """Move the pointer from the head pose, or hold it at the gesture anchor."""
        freeze = self.settings.gestures.freeze_pointer and (holding or t < self._anchor_until)
        if freeze:
            if self._anchor is None:
                self._anchor = self._lookback(t)
            self._pos = self._anchor
            return
        self._anchor = None
        p = self.settings.pointer
        if p.mode == "absolute":
            self._pos = absolute_position(dyaw, dpitch, self._x_axis, self._y_axis, self._screen)
        else:
            self._pos = relative_step(
                self._pos,
                dyaw,
                dpitch,
                dt,
                self._x_axis,
                self._y_axis,
                p.max_speed_screens_per_s * self._screen.width,
                p.acceleration,
                self._screen,
            )
        self._history.append((t, self._pos))

    def _lookback(self, t: float) -> Point:
        """Where the pointer was ANCHOR_LOOKBACK_S ago (or as far back as we know)."""
        target = t - ANCHOR_LOOKBACK_S
        for when, pos in reversed(self._history):
            if when <= target:
                return pos
        return self._history[0][1] if self._history else self._pos

    # ------------------------------------------------------------ clicks and scrolling

    def _in_own_ui(self, point: Point) -> bool:
        x, y = point
        return any(rx <= x < rx + w and ry <= y < ry + h for rx, ry, w, h in self._own_ui)

    def _rate_ok(self, t: float) -> bool:
        return self._clicks is not None and self._clicks.try_acquire(t)

    def _own_ui_click(self, t: float) -> list[ClickAction]:
        """Our own windows always get a plain left click; a held drag is released first."""
        out: list[ClickAction] = []
        if self.dragging:
            self.dragging = False
            out.append(RELEASE_LEFT)
        if self._rate_ok(t):
            out.append(LEFT_CLICK)
        return out

    def _toggle_drag(self, t: float) -> list[ClickAction]:
        if self.dragging:
            self.dragging = False
            return [RELEASE_LEFT]
        if self._rate_ok(t):
            self.dragging = True
            return [PRESS_LEFT]
        return []

    def _start_scroll(self, point: Point, dyaw: float, dpitch: float) -> None:
        self._scroll = _Scroll(point, dyaw, dpitch)
        self._pos = point

    def _dwell_click(self, point: Point, dyaw: float, dpitch: float, t: float) -> list[ClickAction]:
        """What a completed dwell does, given the selected click type."""
        if self._in_own_ui(point):
            return self._own_ui_click(t)
        ct = self.click_type
        if ct is ClickType.SCROLL:
            self._start_scroll(point, dyaw, dpitch)
            return []
        if ct is ClickType.DRAG:
            was_dragging = self.dragging
            out = self._toggle_drag(t)
            if was_dragging:
                self._used_click_type()
            return out
        if self._rate_ok(t):
            self._used_click_type()
            return [SIMPLE_CLICKS[ct]]
        return []

    def _gesture_action(
        self, action: GestureAction, point: Point, dyaw: float, dpitch: float, t: float
    ) -> list[ClickAction]:
        """Perform a gesture's action at `point`. Leaves the toolbar choice untouched."""
        if action in GESTURE_CLICKS:
            if self._in_own_ui(point):
                return self._own_ui_click(t)
            return [SIMPLE_CLICKS[GESTURE_CLICKS[action]]] if self._rate_ok(t) else []
        if action is GestureAction.DRAG_TOGGLE:
            return self._toggle_drag(t)
        if action is GestureAction.SCROLL_TOGGLE:
            if self._scroll is not None:
                self._scroll = None
            else:
                self._start_scroll(point, dyaw, dpitch)
        return []

    def _update_scroll(self, dyaw: float, dpitch: float, dt: float, t: float) -> Point | None:
        """Head pitch relative to the scroll anchor sets the scroll speed.

        Scrolling ends when the head turns well away sideways (held briefly), or when the
        head rests inside the dead zone for `idle_exit_s`.
        """
        s = self._scroll
        assert s is not None
        cfg = self.settings.scroll
        if abs(dyaw - s.yaw0) > cfg.exit_yaw_deg:
            s.away_since = t if s.away_since is None else s.away_since
            if t - s.away_since >= cfg.exit_yaw_hold_s:
                self._stop_scroll()
            return None
        s.away_since = None
        speed = scroll_speed(
            dpitch - s.pitch0, cfg.dead_zone_deg, cfg.full_speed_deg, cfg.max_notches_per_s
        )
        if speed == 0.0:
            s.direction = 0
            s.idle_since = t if s.idle_since is None else s.idle_since
            if t - s.idle_since >= cfg.idle_exit_s:
                self._stop_scroll()
            return None
        s.idle_since = None
        s.direction = 1 if speed > 0 else -1
        return (0.0, speed * dt)

    # ------------------------------------------------------------ gestures

    def _update_gestures(
        self, frame: FeatureFrame, droll: float, t: float
    ) -> tuple[tuple[GestureReading, ...], list[GestureBinding]]:
        """Score every binding; return the readings and the bindings that fired now."""
        g = self.settings.gestures
        readings: list[GestureReading] = []
        fired: list[GestureBinding] = []
        for binding, detector in self._gestures.values():
            score = gesture_score(
                binding.source, frame.blendshapes, droll, g.tilt_full_deg, g.swap_tilt
            )
            if frame.blendshapes or binding.source in DERIVED_SOURCES:
                self._available[binding.id] = score is not None
            progress = 0.0
            if binding.enabled and binding.action is not GestureAction.NONE and score is not None:
                u = detector.update(score, t)
                progress = u.progress
                if u.fired:
                    fired.append(binding)
            readings.append(self._reading(binding, score, progress))
        return tuple(readings), fired

    def _reading(self, b: GestureBinding, value: float | None, progress: float) -> GestureReading:
        return GestureReading(
            id=b.id,
            label=b.label,
            action=b.action,
            value=value,
            threshold=b.on_threshold,
            progress=progress,
            enabled=b.enabled,
            available=self._available.get(b.id),
        )

    # ------------------------------------------------------------ no face, drift, output

    def _no_face(self, frame: FeatureFrame, t: float) -> EngineOutput:
        """Face lost: freeze everything, release held buttons; auto-pause after a while."""
        if self._face_lost_since is None:
            self._face_lost_since = t
        self._face_since = None
        self._dwell.reset()
        self._anchor = None
        self._end_drag()
        self._stop_scroll()
        for _, detector in self._gestures.values():
            detector.reset()
        lost_for = t - self._face_lost_since
        if self.mode is Mode.ACTIVE and lost_for >= self.settings.safety.face_lost_pause_s:
            self._pause(PauseReason.FACE_LOST)
        readings = tuple(self._reading(b, None, 0.0) for b, _ in self._gestures.values())
        return self._output(frame, None, (), None, None, readings, 0.0)

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

    def _output(
        self,
        frame: FeatureFrame,
        move_to: Point | None,
        clicks: tuple[ClickAction, ...],
        click_at: Point | None,
        scroll: Point | None,
        readings: tuple[GestureReading, ...],
        dwell_progress: float,
    ) -> EngineOutput:
        release, self._release_pending = self._release_pending, False
        status = Status(
            mode=self.mode,
            pause_reason=self.pause_reason,
            face=frame.face,
            quality=quality(frame),
            pointer=self._pos,
            dwell_progress=dwell_progress,
            click_type=self.click_type,
            dragging=self.dragging,
            scrolling=self._scroll is not None,
            scroll_direction=self._scroll.direction if self._scroll is not None else 0,
            gestures=readings,
            drift_suggested=self._drift.suggested,
            manual_override=frame.t < self._override_until,
        )
        return EngineOutput(move_to, clicks, click_at, scroll, release, status)
