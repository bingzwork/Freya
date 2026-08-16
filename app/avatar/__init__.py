"""Freya's non-critical, presentation-only avatar subsystem."""

from .adapters import AvatarAdapter, NoopAvatarAdapter
from .controller import AvatarController
from .mapping import AvatarStateMapper
from .models import AvatarExpression, AvatarGesture, AvatarSnapshot, AvatarState, GazePoint, GazeTarget
from .runtime import AvatarRuntime

__all__ = [
    "AvatarAdapter",
    "AvatarController",
    "AvatarExpression",
    "AvatarGesture",
    "AvatarRuntime",
    "AvatarSnapshot",
    "AvatarState",
    "AvatarStateMapper",
    "GazePoint",
    "GazeTarget",
    "NoopAvatarAdapter",
]
