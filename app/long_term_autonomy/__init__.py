"""Long-Term Autonomy package for Freya AI.

This package implements the long-term autonomy capabilities, including:
- Background scheduler for recurring tasks
- Autonomous decision loop (observe-analyze-decide-act-verify-learn)
- Self-initiated work generation
- Autonomous recovery and watchdog system
- Autonomous project maintenance
- Continuous operation support
"""

from app.long_term_autonomy.manager import AutonomyManager
from app.long_term_autonomy.models import (
    AutonomyConfig,
    AutonomyStateData,
    ObservationData,
    DecisionOutput,
    LearningUpdate,
    AutonomousTask
)
from app.long_term_autonomy.scheduler import BackgroundScheduler, ScheduledJob, JobStatus
from app.long_term_autonomy.storage import AutonomyStorage
from app.long_term_autonomy.watchdog import Watchdog, WatchdogConfig, WatchdogAction, TaskHealth
from app.long_term_autonomy.self_initiated import (
    SelfInitiatedWorkManager,
    OpportunityDetector,
    Opportunity,
    OpportunityType,
    OpportunityPriority,
    DetectorConfig,
    CodeQualityDetector,
    SecurityDetector,
    DependencyDetector,
    TestCoverageDetector
)
from app.long_term_autonomy.maintenance import (
    MaintenanceManager,
    MaintenanceRunner,
    MaintenanceTask,
    MaintenanceTaskType,
    MaintenanceStatus,
    MaintenanceConfig
)
from app.long_term_autonomy.continuous_operation import (
    ContinuousOperationManager,
    StatePersister,
    ContinuousOperationConfig,
    Checkpoint,
    CheckpointType,
    ShutdownReason
)

__all__ = [
    "AutonomyManager",
    "AutonomyConfig",
    "AutonomyStateData",
    "ObservationData",
    "DecisionOutput",
    "LearningUpdate",
    "AutonomousTask",
    "BackgroundScheduler",
    "ScheduledJob",
    "JobStatus",
    "AutonomyStorage",
    "Watchdog",
    "WatchdogConfig",
    "WatchdogAction",
    "TaskHealth",
    "SelfInitiatedWorkManager",
    "OpportunityDetector",
    "Opportunity",
    "OpportunityType",
    "OpportunityPriority",
    "DetectorConfig",
    "CodeQualityDetector",
    "SecurityDetector",
    "DependencyDetector",
    "TestCoverageDetector",
    "MaintenanceManager",
    "MaintenanceRunner",
    "MaintenanceTask",
    "MaintenanceTaskType",
    "MaintenanceStatus",
    "MaintenanceConfig",
    "ContinuousOperationManager",
    "StatePersister",
    "ContinuousOperationConfig",
    "Checkpoint",
    "CheckpointType",
    "ShutdownReason"
]