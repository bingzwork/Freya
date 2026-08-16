"""Model-independent avatar behavior controller.

This module intentionally contains presentation commands only.  It observes
state supplied by the runtime bridge; it does not reason, route, execute tools,
or make decisions for Freya.
"""

from __future__ import annotations

import threading
from dataclasses import replace
from typing import Any, Callable, Optional
from uuid import uuid4

from .adapters import AvatarAdapter, NoopAvatarAdapter
from .models import (
    AvatarExpression,
    AvatarGesture,
    AvatarSnapshot,
    AvatarState,
    GazePoint,
    GazeTarget,
)


_EXPRESSION_FALLBACKS: dict[AvatarExpression, tuple[AvatarExpression, ...]] = {
    AvatarExpression.EXCITED: (AvatarExpression.HAPPY, AvatarExpression.SURPRISED, AvatarExpression.NEUTRAL),
    AvatarExpression.CONCERNED: (AvatarExpression.CONFUSED, AvatarExpression.NEUTRAL),
    AvatarExpression.CONFUSED: (AvatarExpression.CONCERNED, AvatarExpression.NEUTRAL),
    AvatarExpression.FOCUSED: (AvatarExpression.NEUTRAL,),
    AvatarExpression.SURPRISED: (AvatarExpression.HAPPY, AvatarExpression.NEUTRAL),
    AvatarExpression.HAPPY: (AvatarExpression.NEUTRAL,),
    AvatarExpression.NEUTRAL: (AvatarExpression.NEUTRAL,),
}

_STATE_EXPRESSIONS: dict[AvatarState, AvatarExpression] = {
    AvatarState.IDLE: AvatarExpression.NEUTRAL,
    AvatarState.LISTENING: AvatarExpression.NEUTRAL,
    AvatarState.THINKING: AvatarExpression.FOCUSED,
    AvatarState.WORKING: AvatarExpression.FOCUSED,
    AvatarState.SPEAKING: AvatarExpression.NEUTRAL,
    AvatarState.SUCCESS: AvatarExpression.HAPPY,
    AvatarState.WARNING: AvatarExpression.CONCERNED,
    AvatarState.ERROR: AvatarExpression.CONCERNED,
    AvatarState.SEARCHING: AvatarExpression.FOCUSED,
    AvatarState.READING: AvatarExpression.FOCUSED,
    AvatarState.MEMORY_RECALL: AvatarExpression.FOCUSED,
    AvatarState.CODING: AvatarExpression.FOCUSED,
    AvatarState.RUNNING_TESTS: AvatarExpression.FOCUSED,
    AvatarState.BROWSING: AvatarExpression.FOCUSED,
    AvatarState.WAITING: AvatarExpression.NEUTRAL,
    AvatarState.CONFUSED: AvatarExpression.CONFUSED,
    AvatarState.EXCITED: AvatarExpression.EXCITED,
    AvatarState.GESTURING: AvatarExpression.HAPPY,
}


class AvatarController:
    """Drive a replaceable avatar adapter from presentation commands."""

    def __init__(self, adapter: Optional[AvatarAdapter] = None) -> None:
        self._adapter: AvatarAdapter = adapter or NoopAvatarAdapter()
        self._lock = threading.RLock()
        self._snapshot = AvatarSnapshot(model_status=self._adapter_status())
        self._last_error: Optional[str] = None
        self._listeners: dict[str, Callable[[AvatarSnapshot], None]] = {}
        self._disposed = False

    @property
    def adapter(self) -> AvatarAdapter:
        return self._adapter

    @property
    def last_error(self) -> Optional[str]:
        with self._lock:
            return self._last_error

    def snapshot(self) -> AvatarSnapshot:
        with self._lock:
            return replace(self._snapshot, metadata=dict(self._snapshot.metadata))

    def subscribe(self, listener: Callable[[AvatarSnapshot], None]) -> str:
        with self._lock:
            subscription_id = str(uuid4())
            self._listeners[subscription_id] = listener
            return subscription_id

    def unsubscribe(self, subscription_id: str) -> bool:
        with self._lock:
            return self._listeners.pop(subscription_id, None) is not None

    def set_state(self, state: AvatarState, *, event_name: Optional[str] = None, metadata: Optional[dict[str, Any]] = None) -> None:
        state = AvatarState(state)
        with self._lock:
            if self._disposed:
                return
            try:
                self._safe_call("set_state", self._adapter.set_state, state)
                self._snapshot = replace(
                    self._snapshot,
                    state=state,
                    last_event=event_name or self._snapshot.last_event,
                    metadata={**self._snapshot.metadata, **(metadata or {})},
                )
                self.set_expression(_STATE_EXPRESSIONS[state])
                self._notify()
            except Exception as exc:  # defensive isolation at the non-critical UI boundary
                self._record_error(exc)

    def set_expression(self, expression: AvatarExpression, intensity: float = 1.0) -> None:
        expression = AvatarExpression(expression)
        with self._lock:
            if self._disposed:
                return
            try:
                resolved = self._resolve_expression(expression)
                self._safe_call("set_expression", self._adapter.set_expression, resolved, intensity)
                self._snapshot = replace(
                    self._snapshot,
                    expression=resolved,
                    expression_intensity=max(0.0, min(1.0, float(intensity))),
                )
                self._notify()
            except Exception as exc:
                self._record_error(exc)

    def set_expression_intensity(self, intensity: float) -> None:
        self.set_expression(self.snapshot().expression, intensity)

    def look_at(self, target: GazeTarget, point: Optional[GazePoint] = None) -> None:
        self.set_gaze_target(target, point)

    def set_gaze_target(self, target: GazeTarget, point: Optional[GazePoint] = None) -> None:
        target = GazeTarget(target)
        with self._lock:
            if self._disposed:
                return
            try:
                self._safe_call("set_gaze_target", self._adapter.set_gaze_target, target, point)
                self._snapshot = replace(self._snapshot, gaze_target=target, gaze_point=point)
                self._notify()
            except Exception as exc:
                self._record_error(exc)

    def start_speaking(self, *, event_name: Optional[str] = None) -> None:
        with self._lock:
            if self._disposed:
                return
            try:
                self._safe_call("set_speaking", self._adapter.set_speaking, True)
                self._snapshot = replace(self._snapshot, speaking=True, state=AvatarState.SPEAKING, last_event=event_name or self._snapshot.last_event)
                self._notify()
            except Exception as exc:
                self._record_error(exc)

    def update_lip_sync(self, openness: float) -> None:
        with self._lock:
            if self._disposed:
                return
            try:
                value = max(0.0, min(1.0, float(openness))) if self._snapshot.speaking else 0.0
                self._safe_call("update_lip_sync", self._adapter.update_lip_sync, value)
                self._snapshot = replace(self._snapshot, mouth_open=value)
            except Exception as exc:
                self._record_error(exc)

    def stop_speaking(self, *, event_name: Optional[str] = None) -> None:
        with self._lock:
            if self._disposed:
                return
            try:
                self._safe_call("set_speaking", self._adapter.set_speaking, False)
                self._safe_call("update_lip_sync", self._adapter.update_lip_sync, 0.0)
                self._snapshot = replace(self._snapshot, speaking=False, mouth_open=0.0, last_event=event_name or self._snapshot.last_event)
                self._notify()
            except Exception as exc:
                self._record_error(exc)

    def play_gesture(self, gesture: AvatarGesture, *, event_name: Optional[str] = None) -> bool:
        gesture = AvatarGesture(gesture)
        with self._lock:
            if self._disposed:
                return False
            try:
                supported = bool(self._adapter.play_gesture(gesture))
                if not supported:
                    # The adapter may not have an animation for this rig.  A state
                    # change plus the adapter's idle motion is the safe fallback.
                    self._safe_call("set_state", self._adapter.set_state, AvatarState.GESTURING)
                self._snapshot = replace(self._snapshot, state=AvatarState.GESTURING, last_event=event_name or self._snapshot.last_event)
                self._notify()
                return supported
            except Exception as exc:
                self._record_error(exc)
                return False

    def reset_pose(self) -> None:
        with self._lock:
            if self._disposed:
                return
            try:
                self._safe_call("reset_pose", self._adapter.reset_pose)
            except Exception as exc:
                self._record_error(exc)

    def set_visible(self, visible: bool) -> None:
        with self._lock:
            if self._disposed:
                return
            self._snapshot = replace(self._snapshot, visible=bool(visible))
            self._notify()

    def update(self, delta_seconds: float) -> None:
        with self._lock:
            if self._disposed or not self._snapshot.visible:
                return
            try:
                self._safe_call("update", self._adapter.update, max(0.0, float(delta_seconds)))
            except Exception as exc:
                self._record_error(exc)

    def dispose(self) -> None:
        with self._lock:
            if self._disposed:
                return
            try:
                self._adapter.dispose()
            except Exception as exc:
                self._record_error(exc)
            finally:
                self._disposed = True
                self._listeners.clear()

    def _notify(self) -> None:
        snapshot = self.snapshot()
        for listener in tuple(self._listeners.values()):
            try:
                listener(snapshot)
            except Exception as exc:
                self._record_error(exc, "listener")

    def _resolve_expression(self, requested: AvatarExpression) -> AvatarExpression:
        supports = getattr(self._adapter, "supports_expression", None)
        if callable(supports):
            for candidate in (requested, *_EXPRESSION_FALLBACKS[requested]):
                try:
                    if supports(candidate):
                        return candidate
                except Exception:
                    continue
        return requested

    def _adapter_status(self) -> str:
        return str(getattr(self._adapter, "model_status", "ready"))

    def _safe_call(self, operation: str, callback: Any, *args: Any) -> Any:
        try:
            return callback(*args)
        except Exception as exc:
            self._record_error(exc, operation)
            raise

    def _record_error(self, exc: Exception, operation: str = "avatar") -> None:
        self._last_error = f"{operation}: {exc}"
