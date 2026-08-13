"""
Core data models for Safe Self-Improvement.

Defines the fundamental types used throughout the safe self-improvement system.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from functools import total_ordering
import uuid


class ModificationType(Enum):
    """Types of file modifications."""

    CREATE = "create"
    MODIFY = "modify"
    DELETE = "delete"
    RENAME = "rename"
    MOVE = "move"


class ApprovalStatus(Enum):
    """Status of approval request."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    OVERRIDDEN = "overridden"
    TIMED_OUT = "timed_out"
    AUTO_APPROVED = "auto_approved"
    NOT_REQUIRED = "not_required"


@total_ordering
class RiskLevel(Enum):
    """Risk levels for operations."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @classmethod
    def from_score(cls, score: float) -> "RiskLevel":
        """Convert numeric score to risk level."""
        if score >= 0.8:
            return cls.CRITICAL
        elif score >= 0.6:
            return cls.HIGH
        elif score >= 0.4:
            return cls.MEDIUM
        elif score >= 0.2:
            return cls.LOW
        return cls.NONE

    def __lt__(self, other: "RiskLevel") -> bool:
        if not isinstance(other, RiskLevel):
            return NotImplemented
        order = {
            RiskLevel.NONE: 0,
            RiskLevel.LOW: 1,
            RiskLevel.MEDIUM: 2,
            RiskLevel.HIGH: 3,
            RiskLevel.CRITICAL: 4,
        }
        return order[self] < order[other]


class ImprovementCategory(Enum):
    """Categories of improvements."""

    COMPLEXITY = "complexity"
    STYLE = "style"
    DOCUMENTATION = "documentation"
    TESTS = "tests"
    SECURITY = "security"
    PERFORMANCE = "performance"
    CORRECTNESS = "correctness"
    ARCHITECTURE = "architecture"
    DEPENDENCY = "dependency"
    DEPRECATION = "deprecation"


class RollbackReason(Enum):
    """Reasons for rollback."""

    VERIFICATION_FAILED = "verification_failed"
    TESTS_FAILED = "tests_failed"
    LINT_FAILED = "lint_failed"
    REGRESSION_DETECTED = "regression_detected"
    HUMAN_REJECTED = "human_rejected"
    RISK_EXCEEDED = "risk_exceeded"
    POLICY_VIOLATION = "policy_violation"
    SYSTEM_ERROR = "system_error"
    TIMEOUT = "timeout"


@dataclass
class FileModification:
    """Represents a single file modification."""

    id: str = field(default_factory=lambda: f"mod_{uuid.uuid4().hex[:8]}")
    modification_type: ModificationType = ModificationType.MODIFY
    file_path: str = ""
    old_content: Optional[str] = None
    new_content: Optional[str] = None
    line_range: Optional[tuple[int, int]] = None
    description: str = ""
    category: ImprovementCategory = ImprovementCategory.CORRECTNESS
    risk_level: RiskLevel = RiskLevel.NONE
    confidence: float = 1.0
    affects_allowlist: bool = False
    affects_denylist: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "modification_type": self.modification_type.value,
            "file_path": self.file_path,
            "old_content": self.old_content,
            "new_content": self.new_content,
            "line_range": self.line_range,
            "description": self.description,
            "category": self.category.value,
            "risk_level": self.risk_level.value,
            "confidence": self.confidence,
            "affects_allowlist": self.affects_allowlist,
            "affects_denylist": self.affects_denylist,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FileModification":
        line_range = data.get("line_range")
        if line_range and isinstance(line_range, list):
            line_range = tuple(line_range)
        return cls(
            id=data.get("id", f"mod_{uuid.uuid4().hex[:8]}"),
            modification_type=ModificationType(data.get("modification_type", "modify")),
            file_path=data.get("file_path", ""),
            old_content=data.get("old_content"),
            new_content=data.get("new_content"),
            line_range=line_range,
            description=data.get("description", ""),
            category=ImprovementCategory(data.get("category", "correctness")),
            risk_level=RiskLevel(data.get("risk_level", "none")),
            confidence=data.get("confidence", 1.0),
            affects_allowlist=data.get("affects_allowlist", False),
            affects_denylist=data.get("affects_denylist", False),
        )


@dataclass
class ImprovementCandidate:
    """Represents a candidate improvement to be evaluated."""

    id: str = field(default_factory=lambda: f"imp_{uuid.uuid4().hex[:8]}")
    title: str = ""
    description: str = ""
    category: ImprovementCategory = ImprovementCategory.CORRECTNESS
    source: str = "diagnostics"  # diagnostics, evaluation, manual, autonomous
    modifications: List[FileModification] = field(default_factory=list)
    affected_files: List[str] = field(default_factory=list)
    estimated_risk: RiskLevel = RiskLevel.NONE
    estimated_impact: float = 0.5  # 0-1
    estimated_effort: float = 0.5  # 0-1
    confidence: float = 0.5
    priority_score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "category": self.category.value,
            "source": self.source,
            "modifications": [m.to_dict() for m in self.modifications],
            "affected_files": self.affected_files,
            "estimated_risk": self.estimated_risk.value,
            "estimated_impact": self.estimated_impact,
            "estimated_effort": self.estimated_effort,
            "confidence": self.confidence,
            "priority_score": self.priority_score,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


@dataclass
class ApprovalRequest:
    """Request for human approval of an improvement."""

    id: str = field(default_factory=lambda: f"appr_{uuid.uuid4().hex[:8]}")
    candidate_id: str = ""
    candidate_title: str = ""
    modifications: List[FileModification] = field(default_factory=list)
    risk_assessment: Dict[str, Any] = field(default_factory=dict)
    status: ApprovalStatus = ApprovalStatus.PENDING
    requested_by: str = "system"
    requested_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    responded_at: Optional[str] = None
    responded_by: Optional[str] = None
    response_reason: str = ""
    auto_approval_eligible: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "candidate_id": self.candidate_id,
            "candidate_title": self.candidate_title,
            "modifications": [m.to_dict() for m in self.modifications],
            "risk_assessment": self.risk_assessment,
            "status": self.status.value,
            "requested_by": self.requested_by,
            "requested_at": self.requested_at,
            "responded_at": self.responded_at,
            "responded_by": self.responded_by,
            "response_reason": self.response_reason,
            "auto_approval_eligible": self.auto_approval_eligible,
        }


@dataclass
class ExecutionResult:
    """Result of executing an improvement."""

    candidate_id: str = ""
    success: bool = False
    applied_modifications: List[FileModification] = field(default_factory=list)
    failed_modifications: List[FileModification] = field(default_factory=list)
    verification_results: Dict[str, Any] = field(default_factory=dict)
    rollback_performed: bool = False
    rollback_reason: Optional[RollbackReason] = None
    error: Optional[str] = None
    duration_ms: float = 0.0
    executed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "success": self.success,
            "applied_modifications": [m.to_dict() for m in self.applied_modifications],
            "failed_modifications": [m.to_dict() for m in self.failed_modifications],
            "verification_results": self.verification_results,
            "rollback_performed": self.rollback_performed,
            "rollback_reason": self.rollback_reason.value if self.rollback_reason else None,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "executed_at": self.executed_at,
            "metadata": self.metadata,
        }


@dataclass
class RollbackCheckpoint:
    """Snapshot of files before modification for rollback capability."""

    id: str = field(default_factory=lambda: f"rb_{uuid.uuid4().hex[:8]}")
    candidate_id: str = ""
    file_snapshots: Dict[str, Optional[str]] = field(default_factory=dict)  # path -> content (None = didn't exist)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "candidate_id": self.candidate_id,
            "file_snapshots": self.file_snapshots,
            "created_at": self.created_at,
            "description": self.description,
        }


@dataclass
class SafeSelfImprovementConfig:
    """Configuration for safe self-improvement engine."""

    # Allowlist/Denylist
    enable_allowlist: bool = True
    enable_denylist: bool = True
    default_allowlist_paths: List[str] = field(default_factory=list)
    default_denylist_paths: List[str] = field(default_factory=lambda: [
        "**/__pycache__/**",
        "**/.git/**",
        "**/.venv/**",
        "**/venv/**",
        "**/node_modules/**",
        "**/*.pyc",
        "**/*.pyo",
        "**/*.pyd",
        "**/.pytest_cache/**",
        "**/.mypy_cache/**",
        "**/data/memory/**",
        "**/data/vector_db/**",
        "*.key",
        "*.pem",
        "*.crt",
        "*.csr",
        "**/secrets/**",
        "**/credentials/**",
        "**/.env*",
    ])

    # Boundaries
    max_files_per_improvement: int = 10
    max_lines_per_modification: int = 500
    max_total_modifications_per_session: int = 50

    # Risk thresholds
    auto_approve_max_risk: RiskLevel = RiskLevel.LOW
    require_human_approval_risk: RiskLevel = RiskLevel.HIGH
    max_concurrent_improvements: int = 1

    # Confidence thresholds
    min_confidence_for_auto_execute: float = 0.8
    min_confidence_for_approval_request: float = 0.5
    reject_below_confidence: float = 0.3

    # Prioritization weights
    impact_weight: float = 0.4
    effort_weight: float = 0.2  # Lower effort = higher priority
    risk_weight: float = 0.2    # Lower risk = higher priority
    confidence_weight: float = 0.2

    # Rollback
    require_rollback_checkpoint: bool = True
    auto_rollback_on_verification_failure: bool = True
    auto_rollback_on_test_failure: bool = True
    auto_rollback_on_regression: bool = True
    checkpoint_retention_hours: int = 24

    # Promotion
    promotion_require_tests: bool = True
    promotion_require_lint: bool = True
    promotion_require_no_regression: bool = True
    promotion_min_confidence: float = 0.75

    # Policy
    enforce_policies: bool = True
    policy_evaluation_on_submit: bool = True
    policy_evaluation_on_execute: bool = True

    # Timeouts
    approval_timeout_seconds: float = 300.0
    execution_timeout_seconds: float = 600.0
    verification_timeout_seconds: float = 300.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enable_allowlist": self.enable_allowlist,
            "enable_denylist": self.enable_denylist,
            "default_allowlist_paths": self.default_allowlist_paths,
            "default_denylist_paths": self.default_denylist_paths,
            "max_files_per_improvement": self.max_files_per_improvement,
            "max_lines_per_modification": self.max_lines_per_modification,
            "max_total_modifications_per_session": self.max_total_modifications_per_session,
            "auto_approve_max_risk": self.auto_approve_max_risk.value,
            "require_human_approval_risk": self.require_human_approval_risk.value,
            "max_concurrent_improvements": self.max_concurrent_improvements,
            "min_confidence_for_auto_execute": self.min_confidence_for_auto_execute,
            "min_confidence_for_approval_request": self.min_confidence_for_approval_request,
            "reject_below_confidence": self.reject_below_confidence,
            "impact_weight": self.impact_weight,
            "effort_weight": self.effort_weight,
            "risk_weight": self.risk_weight,
            "confidence_weight": self.confidence_weight,
            "require_rollback_checkpoint": self.require_rollback_checkpoint,
            "auto_rollback_on_verification_failure": self.auto_rollback_on_verification_failure,
            "auto_rollback_on_test_failure": self.auto_rollback_on_test_failure,
            "auto_rollback_on_regression": self.auto_rollback_on_regression,
            "checkpoint_retention_hours": self.checkpoint_retention_hours,
            "promotion_require_tests": self.promotion_require_tests,
            "promotion_require_lint": self.promotion_require_lint,
            "promotion_require_no_regression": self.promotion_require_no_regression,
            "promotion_min_confidence": self.promotion_min_confidence,
            "enforce_policies": self.enforce_policies,
            "policy_evaluation_on_submit": self.policy_evaluation_on_submit,
            "policy_evaluation_on_execute": self.policy_evaluation_on_execute,
            "approval_timeout_seconds": self.approval_timeout_seconds,
            "execution_timeout_seconds": self.execution_timeout_seconds,
            "verification_timeout_seconds": self.verification_timeout_seconds,
        }