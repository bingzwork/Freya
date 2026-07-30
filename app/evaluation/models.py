"""Core data models for the Self-Evaluation system.

This module defines the fundamental data structures used by the evaluation framework
to represent evaluation runs, results, requirements, and confidence scores.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


class EvaluationType(Enum):
    """Type of evaluation being performed."""
    REQUIREMENT_VERIFICATION = "requirement_verification"
    FUNCTIONAL_VALIDATION = "functional_validation"
    REGRESSION_DETECTION = "regression_detection"
    CODE_QUALITY_REVIEW = "code_quality_review"
    DOCUMENTATION_VERIFICATION = "documentation_verification"
    COMPREHENSIVE = "comprehensive"


class EvaluationStatus(Enum):
    """Status of an evaluation run."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class VerificationStatus(Enum):
    """Result of a requirement verification check."""
    SATISFIED = "satisfied"
    PARTIALLY_SATISFIED = "partially_satisfied"
    NOT_SATISFIED = "not_satisfied"
    CANNOT_VERIFY = "cannot_verify"


class ValidationStatus(Enum):
    """Result of a functional validation check."""
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


class ConfidenceLevel(Enum):
    """Confidence level for evaluation results."""
    CRITICAL = "critical"      # 0.0 - 0.2: Very low confidence, do not deliver
    LOW = "low"                # 0.2 - 0.4: Low confidence, needs review
    MEDIUM = "medium"          # 0.4 - 0.6: Moderate confidence
    HIGH = "high"              # 0.6 - 0.8: High confidence
    VERY_HIGH = "very_high"    # 0.8 - 1.0: Very high confidence, ready to deliver

    @classmethod
    def from_score(cls, score: float) -> "ConfidenceLevel":
        if score >= 0.8:
            return cls.VERY_HIGH
        elif score >= 0.6:
            return cls.HIGH
        elif score >= 0.4:
            return cls.MEDIUM
        elif score >= 0.2:
            return cls.LOW
        return cls.CRITICAL

    @property
    def min_score(self) -> float:
        return {
            ConfidenceLevel.CRITICAL: 0.0,
            ConfidenceLevel.LOW: 0.2,
            ConfidenceLevel.MEDIUM: 0.4,
            ConfidenceLevel.HIGH: 0.6,
            ConfidenceLevel.VERY_HIGH: 0.8,
        }[self]

    @property
    def max_score(self) -> float:
        return {
            ConfidenceLevel.CRITICAL: 0.2,
            ConfidenceLevel.LOW: 0.4,
            ConfidenceLevel.MEDIUM: 0.6,
            ConfidenceLevel.HIGH: 0.8,
            ConfidenceLevel.VERY_HIGH: 1.0,
        }[self]


class EvaluationTrigger(Enum):
    """What triggered this evaluation."""
    TASK_COMPLETION = "task_completion"
    GOAL_COMPLETION = "goal_completion"
    REPAIR_COMPLETION = "repair_completion"
    MANUAL = "manual"
    SCHEDULED = "scheduled"


@dataclass
class Requirement:
    """A single requirement to verify against completed work."""
    id: str = field(default_factory=lambda: f"req_{uuid.uuid4().hex[:8]}")
    description: str = ""
    source: str = "user_request"  # user_request, goal, plan, acceptance_criteria
    category: str = "functional"  # functional, non_functional, quality, security
    priority: str = "high"        # critical, high, medium, low
    acceptance_criteria: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "source": self.source,
            "category": self.category,
            "priority": self.priority,
            "acceptance_criteria": self.acceptance_criteria,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Requirement":
        return cls(
            id=data.get("id", f"req_{uuid.uuid4().hex[:8]}"),
            description=data.get("description", ""),
            source=data.get("source", "user_request"),
            category=data.get("category", "functional"),
            priority=data.get("priority", "high"),
            acceptance_criteria=data.get("acceptance_criteria", []),
            metadata=data.get("metadata", {}),
        )


@dataclass
class RequirementVerification:
    """Result of verifying a single requirement."""
    requirement_id: str
    requirement_description: str
    status: VerificationStatus
    evidence: List[str] = field(default_factory=list)
    gaps: List[str] = field(default_factory=list)
    confidence: float = 0.5
    notes: str = ""

    @property
    def is_satisfied(self) -> bool:
        return self.status in (VerificationStatus.SATISFIED, VerificationStatus.PARTIALLY_SATISFIED)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "requirement_description": self.requirement_description,
            "status": self.status.value,
            "evidence": self.evidence,
            "gaps": self.gaps,
            "confidence": self.confidence,
            "notes": self.notes,
            "is_satisfied": self.is_satisfied,
        }


@dataclass
class ValidationCheck:
    """A single functional validation check (test, build, lint, etc.)."""
    id: str = field(default_factory=lambda: f"val_{uuid.uuid4().hex[:8]}")
    name: str = ""
    type: str = "test"          # test, build, lint, execution, static_analysis
    command: List[str] = field(default_factory=list)
    expected_outcome: str = "success"
    working_directory: str = "."
    timeout_seconds: int = 120
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    """Result of a single validation check."""
    check_id: str
    check_name: str
    check_type: str
    status: ValidationStatus
    stdout: str = ""
    stderr: str = ""
    return_code: int = 0
    duration_seconds: float = 0.0
    passed: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_id": self.check_id,
            "check_name": self.check_name,
            "check_type": self.check_type,
            "status": self.status.value,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "return_code": self.return_code,
            "duration_seconds": self.duration_seconds,
            "passed": self.passed,
            "metadata": self.metadata,
        }


@dataclass
class EvaluationConfig:
    """Configuration for an evaluation run."""
    evaluation_type: EvaluationType = EvaluationType.COMPREHENSIVE
    trigger: EvaluationTrigger = EvaluationTrigger.TASK_COMPLETION
    task_id: Optional[str] = None
    task_description: str = ""
    original_request: str = ""
    goal_id: Optional[str] = None
    plan_id: Optional[str] = None

    # Requirement verification settings
    verify_requirements: bool = True
    requirement_confidence_threshold: float = 0.6

    # Functional validation settings
    run_tests: bool = True
    run_lint: bool = True
    run_build: bool = True
    run_execution: bool = False
    custom_validations: List[ValidationCheck] = field(default_factory=list)

    # Confidence scoring settings
    confidence_thresholds: Dict[str, float] = field(default_factory=lambda: {
        "requirement_verification": 0.6,
        "functional_validation": 0.7,
        "overall": 0.65,
    })

    # Behavior settings
    fail_fast: bool = False
    require_approval_below_confidence: float = 0.5
    store_results: bool = True


@dataclass
class EvaluationResult:
    """Complete result of an evaluation run."""
    evaluation_id: str = field(default_factory=lambda: f"eval_{uuid.uuid4().hex[:8]}")
    config: Optional[EvaluationConfig] = None
    status: EvaluationStatus = EvaluationStatus.PENDING
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_seconds: float = 0.0

    # Requirement verification results
    requirements: List[Requirement] = field(default_factory=list)
    requirement_verifications: List[RequirementVerification] = field(default_factory=list)

    # Functional validation results
    validation_checks: List[ValidationCheck] = field(default_factory=list)
    validation_results: List[ValidationResult] = field(default_factory=list)

    # Overall scores
    requirement_score: float = 0.0
    validation_score: float = 0.0
    overall_confidence: float = 0.0
    confidence_level: ConfidenceLevel = ConfidenceLevel.MEDIUM

    # Detailed breakdown
    confidence_breakdown: Dict[str, float] = field(default_factory=dict)

    # Decision
    should_deliver: bool = False
    requires_rework: bool = False
    requires_human_review: bool = False
    rework_reasons: List[str] = field(default_factory=list)

    # Summary
    summary: str = ""

    @property
    def requirements_satisfied_count(self) -> int:
        return sum(1 for v in self.requirement_verifications if v.is_satisfied)

    @property
    def requirements_total_count(self) -> int:
        return len(self.requirement_verifications)

    @property
    def validations_passed_count(self) -> int:
        return sum(1 for r in self.validation_results if r.passed)

    @property
    def validations_total_count(self) -> int:
        return len(self.validation_results)

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "evaluation_id": self.evaluation_id,
            "config": self.config.to_dict() if self.config else None,
            "status": self.status.value,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "requirements": [r.to_dict() for r in self.requirements],
            "requirement_verifications": [v.to_dict() for v in self.requirement_verifications],
            "validation_checks": [c.to_dict() for c in self.validation_checks],
            "validation_results": [r.to_dict() for r in self.validation_results],
            "requirement_score": self.requirement_score,
            "validation_score": self.validation_score,
            "overall_confidence": self.overall_confidence,
            "confidence_level": self.confidence_level.value,
            "confidence_breakdown": self.confidence_breakdown,
            "should_deliver": self.should_deliver,
            "requires_rework": self.requires_rework,
            "requires_human_review": self.requires_human_review,
            "rework_reasons": self.rework_reasons,
            "summary": self.summary,
        }
        if self.config:
            result["config"] = {
                "evaluation_type": self.config.evaluation_type.value,
                "trigger": self.config.trigger.value,
                "task_id": self.config.task_id,
                "task_description": self.config.task_description,
                "original_request": self.config.original_request,
                "goal_id": self.config.goal_id,
                "plan_id": self.config.plan_id,
            }
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvaluationResult":
        config_data = data.get("config", {})
        config = EvaluationConfig(
            evaluation_type=EvaluationType(config_data.get("evaluation_type", "comprehensive")),
            trigger=EvaluationTrigger(config_data.get("trigger", "task_completion")),
            task_id=config_data.get("task_id"),
            task_description=config_data.get("task_description", ""),
            original_request=config_data.get("original_request", ""),
            goal_id=config_data.get("goal_id"),
            plan_id=config_data.get("plan_id"),
        )
        result = cls(
            evaluation_id=data.get("evaluation_id", f"eval_{uuid.uuid4().hex[:8]}"),
            config=config,
            status=EvaluationStatus(data.get("status", "pending")),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            duration_seconds=data.get("duration_seconds", 0.0),
            requirements=[Requirement.from_dict(r) for r in data.get("requirements", [])],
            requirement_verifications=[RequirementVerification(**v) for v in data.get("requirement_verifications", [])],
            validation_checks=[ValidationCheck(**c) for c in data.get("validation_checks", [])],
            validation_results=[ValidationResult(**r) for r in data.get("validation_results", [])],
            requirement_score=data.get("requirement_score", 0.0),
            validation_score=data.get("validation_score", 0.0),
            overall_confidence=data.get("overall_confidence", 0.0),
            confidence_level=ConfidenceLevel(data.get("confidence_level", "medium")),
            confidence_breakdown=data.get("confidence_breakdown", {}),
            should_deliver=data.get("should_deliver", False),
            requires_rework=data.get("requires_rework", False),
            requires_human_review=data.get("requires_human_review", False),
            rework_reasons=data.get("rework_reasons", []),
            summary=data.get("summary", ""),
        )
        return result


# Add to_dict methods for config
def _config_to_dict(self) -> Dict[str, Any]:
    return {
        "evaluation_type": self.evaluation_type.value,
        "trigger": self.trigger.value,
        "task_id": self.task_id,
        "task_description": self.task_description,
        "original_request": self.original_request,
        "goal_id": self.goal_id,
        "plan_id": self.plan_id,
        "verify_requirements": self.verify_requirements,
        "requirement_confidence_threshold": self.requirement_confidence_threshold,
        "run_tests": self.run_tests,
        "run_lint": self.run_lint,
        "run_build": self.run_build,
        "run_execution": self.run_execution,
        "custom_validations": [c.to_dict() for c in self.custom_validations],
        "confidence_thresholds": self.confidence_thresholds,
        "fail_fast": self.fail_fast,
        "require_approval_below_confidence": self.require_approval_below_confidence,
        "store_results": self.store_results,
    }

EvaluationConfig.to_dict = _config_to_dict


def _validation_check_to_dict(self) -> Dict[str, Any]:
    return {
        "id": self.id,
        "name": self.name,
        "type": self.type,
        "command": self.command,
        "expected_outcome": self.expected_outcome,
        "working_directory": self.working_directory,
        "timeout_seconds": self.timeout_seconds,
        "metadata": self.metadata,
    }

ValidationCheck.to_dict = _validation_check_to_dict