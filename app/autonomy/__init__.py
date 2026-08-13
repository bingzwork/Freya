"""Autonomy + Observation Package for Freya.

This package implements the Autonomy + Observation group from TARGET_ARCHITECTURE.md:

- AutonomyManager: Main coordinator
- Watchdog: Observes system events and metrics, feeds LearningPipeline
- SelfInitiatedWorkManager: Reads goals, creates autonomous work via WorkflowOrchestrator
- MaintenanceManager: Creates maintenance work via WorkflowOrchestrator

Cross-group wiring:
- SelfInitiatedWorkManager -> Read Goals -> GoalManager
- SelfInitiatedWorkManager -> Autonomous Work -> WorkflowOrchestrator
- MaintenanceManager -> Maintenance Work -> WorkflowOrchestrator
- Watchdog -> Observations -> LearningPipeline
- Watchdog -> System Events -> EventBus
- Watchdog -> Metrics/Health -> ObservabilityHub
- AutonomyManager -> BackgroundJobService (shared, not own scheduler)
"""

from .models import (
    WatchdogObservation,
    WatchdogEventType,
    WatchdogSeverity,
    AutonomyConfig,
    AutonomousWorkItem,
    GoalContext,
)
from .watchdog import Watchdog
from .self_initiated import SelfInitiatedWorkManager
from .maintenance import MaintenanceManager
from .manager import AutonomyManager

__all__ = [
    "WatchdogObservation",
    "WatchdogEventType",
    "WatchdogSeverity",
    "AutonomyConfig",
    "AutonomousWorkItem",
    "GoalContext",
    "Watchdog",
    "SelfInitiatedWorkManager",
    "MaintenanceManager",
    "AutonomyManager",
]

__version__ = "1.0.0"