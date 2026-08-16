"""Typed contracts shared by Freya's avatar controller and adapters.

The avatar is a presentation layer only.  These types deliberately contain no
reasoning, routing, memory, capability, or execution responsibilities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional


class AvatarState(str, Enum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    WORKING = "WORKING"
    SPEAKING = "SPEAKING"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    ERROR = "ERROR"
    SEARCHING = "SEARCHING"
    READING = "READING"
    MEMORY_RECALL = "MEMORY_RECALL"
    CODING = "CODING"
    RUNNING_TESTS = "RUNNING_TESTS"
    BROWSING = "BROWSING"
    WAITING = "WAITING"
    CONFUSED = "CONFUSED"
    EXCITED = "EXCITED"
    GESTURING = "GESTURING"


class AvatarExpression(str, Enum):
    NEUTRAL = "neutral"
    HAPPY = "happy"
    CONCERNED = "concerned"
    CONFUSED = "confused"
    FOCUSED = "focused"
    SURPRISED = "surprised"
    EXCITED = "excited"


class GazeTarget(str, Enum):
    USER = "USER"
    CHAT_PANEL = "CHAT_PANEL"
    RESULTS_PANEL = "RESULTS_PANEL"
    CODE_PANEL = "CODE_PANEL"
    BROWSER_PANEL = "BROWSER_PANEL"
    NOTIFICATION = "NOTIFICATION"
    CUSTOM_POINT = "CUSTOM_POINT"


class AvatarGesture(str, Enum):
    NOD = "NOD"
    SMALL_WAVE = "SMALL_WAVE"
    ACKNOWLEDGE = "ACKNOWLEDGE"
    POINT_OR_PRESENT = "POINT_OR_PRESENT"
    CELEBRATE_SUBTLE = "CELEBRATE_SUBTLE"


@dataclass(frozen=True)
class GazePoint:
    """A normalized or world-space point used by adapters that support it."""

    x: float
    y: float
    z: float


@dataclass(frozen=True)
class AvatarSnapshot:
    """Read-only UI-safe representation of current avatar behavior."""

    state: AvatarState = AvatarState.IDLE
    expression: AvatarExpression = AvatarExpression.NEUTRAL
    expression_intensity: float = 1.0
    gaze_target: GazeTarget = GazeTarget.USER
    gaze_point: Optional[GazePoint] = None
    speaking: bool = False
    mouth_open: float = 0.0
    visible: bool = True
    model_status: str = "not_loaded"
    last_event: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "expression": self.expression.value,
            "expression_intensity": self.expression_intensity,
            "gaze_target": self.gaze_target.value,
            "gaze_point": self.gaze_point.__dict__ if self.gaze_point else None,
            "speaking": self.speaking,
            "mouth_open": self.mouth_open,
            "visible": self.visible,
            "model_status": self.model_status,
            "last_event": self.last_event,
            "metadata": dict(self.metadata),
        }
