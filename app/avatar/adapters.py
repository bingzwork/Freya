"""Replaceable avatar adapter contracts.

The controller speaks only this interface.  A browser-side VRM adapter, a
native adapter, or a test double can implement it without changing Freya's
runtime or state-mapping logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Protocol

from .models import AvatarExpression, AvatarGesture, AvatarState, GazePoint, GazeTarget


class AvatarAdapter(Protocol):
    """Model-independent operations required by :class:`AvatarController`."""

    def set_state(self, state: AvatarState) -> None: ...

    def set_expression(self, expression: AvatarExpression, intensity: float) -> None: ...

    def set_gaze_target(self, target: GazeTarget, point: Optional[GazePoint] = None) -> None: ...

    def set_speaking(self, speaking: bool) -> None: ...

    def update_lip_sync(self, openness: float) -> None: ...

    def play_gesture(self, gesture: AvatarGesture) -> bool: ...

    def reset_pose(self) -> None: ...

    def update(self, delta_seconds: float) -> None: ...

    def dispose(self) -> None: ...


@dataclass
class NoopAvatarAdapter:
    """A safe adapter used when a renderer/model is not available.

    It records the latest commands so the controller remains observable in
    headless mode and never becomes a startup dependency for Freya.
    """

    model_status: str = "unavailable"
    available_expressions: set[AvatarExpression] = field(default_factory=lambda: set(AvatarExpression))
    available_gestures: set[AvatarGesture] = field(default_factory=set)
    state: AvatarState = AvatarState.IDLE
    expression: AvatarExpression = AvatarExpression.NEUTRAL
    expression_intensity: float = 1.0
    gaze_target: GazeTarget = GazeTarget.USER
    gaze_point: Optional[GazePoint] = None
    speaking: bool = False
    mouth_open: float = 0.0
    disposed: bool = False
    commands: list[tuple[str, Any]] = field(default_factory=list)

    def set_state(self, state: AvatarState) -> None:
        self.state = state
        self.commands.append(("set_state", state))

    def set_expression(self, expression: AvatarExpression, intensity: float) -> None:
        if expression not in self.available_expressions:
            expression = AvatarExpression.NEUTRAL
        self.expression = expression
        self.expression_intensity = max(0.0, min(1.0, float(intensity)))
        self.commands.append(("set_expression", (expression, self.expression_intensity)))

    def set_gaze_target(self, target: GazeTarget, point: Optional[GazePoint] = None) -> None:
        self.gaze_target = target
        self.gaze_point = point
        self.commands.append(("set_gaze_target", (target, point)))

    def set_speaking(self, speaking: bool) -> None:
        self.speaking = bool(speaking)
        if not self.speaking:
            self.mouth_open = 0.0
        self.commands.append(("set_speaking", self.speaking))

    def update_lip_sync(self, openness: float) -> None:
        self.mouth_open = max(0.0, min(1.0, float(openness))) if self.speaking else 0.0
        self.commands.append(("update_lip_sync", self.mouth_open))

    def play_gesture(self, gesture: AvatarGesture) -> bool:
        supported = gesture in self.available_gestures
        self.commands.append(("play_gesture", (gesture, supported)))
        return supported

    def reset_pose(self) -> None:
        self.commands.append(("reset_pose", None))

    def update(self, delta_seconds: float) -> None:
        if not self.disposed:
            self.commands.append(("update", max(0.0, float(delta_seconds))))

    def dispose(self) -> None:
        self.disposed = True
        self.commands.append(("dispose", None))

    def supports_expression(self, expression: AvatarExpression) -> bool:
        return expression in self.available_expressions

    def supported_expressions(self) -> Iterable[AvatarExpression]:
        return tuple(self.available_expressions)
