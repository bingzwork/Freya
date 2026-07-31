"""Failure Recovery System - Unified failure detection, root cause analysis, and recovery orchestration.

This module provides the centralized failure recovery pipeline for Freya:
- Unified Failure Detection: Single entry point for all failure types
- Root Cause Analyzer: Structured error parsing and cause identification
- Recovery Orchestrator: Complete recovery lifecycle coordination
"""

from app.failure_recovery.detector import (
    FailureDetector,
    FailureEvent,
    FailureType,
    FailureSeverity,
    Recoverability,
)
from app.failure_recovery.analyzer import (
    RootCauseAnalyzer,
    RootCause,
    RootCauseEvidence,
    CauseCategory,
)
from app.failure_recovery.orchestrator import (
    RecoveryOrchestrator,
    RecoveryEvent,
    RecoveryStage,
    RecoveryStrategy,
    RecoveryResult,
)

__all__ = [
    # Detector
    "FailureDetector",
    "FailureEvent",
    "FailureType",
    "FailureSeverity",
    "Recoverability",
    # Analyzer
    "RootCauseAnalyzer",
    "RootCause",
    "RootCauseEvidence",
    # Orchestrator
    "RecoveryOrchestrator",
    "RecoveryEvent",
    "RecoveryStage",
    "RecoveryStrategy",
    "RecoveryResult",
]