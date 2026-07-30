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
    IMPROVEMENT_LOOP = "improvement_loop"


class RegressionType(Enum):
    """Type of regression detected."""
    TEST_FAILURE = "test_failure"
    BUILD_FAILURE = "build_failure"
    LINT_REGRESSION = "lint_regression"
    PERFORMANCE_REGRESSION = "performance_regression"
    BEHAVIORAL_CHANGE = "behavioral_change"
    API_BREAKING = "api_breaking"


class QualityDimension(Enum):
    """Code quality dimensions to evaluate."""
    SIMPLICITY = "simplicity"
    READABILITY = "readability"
    MAINTAINABILITY = "maintainability"
    CONSISTENCY = "consistency"
    ARCHITECTURE_COMPLIANCE = "architecture_compliance"
    COMPLEXITY = "complexity"
    DUPLICATION = "duplication"
    DOCUMENTATION = "documentation"
    TESTING = "testing"
    ERROR_HANDLING = "error_handling"


class DocumentationCheck(Enum):
    """Types of documentation verification checks."""
    README_EXISTS = "readme_exists"
    DOCS_MATCH_IMPLEMENTATION = "docs_match_implementation"
    EXAMPLES_WORK = "examples_work"
    API_DOCS_CURRENT = "api_docs_current"
    CHANGELOG_CURRENT = "changelog_current"
    ROADMAP_CURRENT = "roadmap_current"
    IMPLEMENTATION_STATUS_CURRENT = "implementation_status_current"
    ARCHITECTURE_DOCS_CURRENT = "architecture_docs_current"
    INLINE_DOCS_PRESENT = "inline_docs_present"
    TYPE_HINTS_PRESENT = "type_hints_present"


class ImprovementAction(Enum):
    """Types of improvement actions."""
    REFACTOR = "refactor"
    ADD_TESTS = "add_tests"
    ADD_DOCS = "add_docs"
    FIX_COMPLEXITY = "fix_complexity"
    FIX_DUPLICATION = "fix_duplication"
    FIX_STYLE = "fix_style"
    UPDATE_DOCS = "update_docs"
    FIX_REQUIREMENTS = "fix_requirements"


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


# ============================================================================
# HIGH PRIORITY: Regression Detection Models
# ============================================================================

@dataclass
class RegressionCheck:
    """A single regression check comparing pre/post state."""
    id: str = field(default_factory=lambda: f"reg_{uuid.uuid4().hex[:8]}")
    name: str = ""
    type: str = "test"  # test, build, lint, execution, file_hash
    pre_state: Dict[str, Any] = field(default_factory=dict)
    post_state: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RegressionResult:
    """Result of a regression check."""
    check_id: str
    check_name: str
    check_type: str
    has_regression: bool = False
    regression_details: List[str] = field(default_factory=list)
    pre_value: Any = None
    post_value: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_id": self.check_id,
            "check_name": self.check_name,
            "check_type": self.check_type,
            "has_regression": self.has_regression,
            "regression_details": self.regression_details,
            "pre_value": self.pre_value,
            "post_value": self.post_value,
            "metadata": self.metadata,
        }


# ============================================================================
# HIGH PRIORITY: Code Quality Review Models
# ============================================================================

@dataclass
class QualityIssue:
    """A code quality issue found during review."""
    id: str = field(default_factory=lambda: f"qual_{uuid.uuid4().hex[:8]}")
    file_path: str = ""
    line_number: Optional[int] = None
    category: str = "style"  # style, complexity, architecture, security, performance, maintainability
    severity: str = "warning"  # info, warning, error, critical
    title: str = ""
    description: str = ""
    suggestion: str = ""
    rule_id: str = ""
    confidence: float = 0.8


@dataclass
class QualityReview:
    """Result of a code quality review."""
    review_id: str = field(default_factory=lambda: f"qr_{uuid.uuid4().hex[:8]}")
    issues: List[QualityIssue] = field(default_factory=list)
    overall_score: float = 1.0  # 0.0 - 1.0, lower is worse
    category_scores: Dict[str, float] = field(default_factory=dict)
    summary: str = ""

    @property
    def issue_count(self) -> int:
        return len(self.issues)

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "critical")

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    @property
    def info_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "info")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "review_id": self.review_id,
            "issues": [i.__dict__ for i in self.issues],
            "overall_score": self.overall_score,
            "category_scores": self.category_scores,
            "summary": self.summary,
            "issue_count": self.issue_count,
            "critical_count": self.critical_count,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
        }


# ============================================================================
# HIGH PRIORITY: Documentation Verification Models
# ============================================================================

@dataclass
class DocCheck:
    """A documentation check to perform."""
    id: str = field(default_factory=lambda: f"doc_{uuid.uuid4().hex[:8]}")
    name: str = ""
    type: str = "consistency"  # consistency, examples, roadmap, api_docs, readme
    target_files: List[str] = field(default_factory=list)
    expected_content: str = ""
    check_function: str = ""  # Name of check function to run
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DocCheckResult:
    """Result of a documentation check."""
    check_id: str
    check_name: str
    check_type: str
    passed: bool = False
    issues: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    details: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_id": self.check_id,
            "check_name": self.check_name,
            "check_type": self.check_type,
            "passed": self.passed,
            "issues": self.issues,
            "suggestions": self.suggestions,
            "details": self.details,
            "metadata": self.metadata,
        }


# ============================================================================
# HIGH PRIORITY: Improvement Loop Models
# ============================================================================

@dataclass
class ImprovementIteration:
    """A single iteration in the improvement loop."""
    iteration: int
    evaluation_id: str
    overall_confidence: float
    issues_found: int
    issues_fixed: int
    improvements_made: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    met_threshold: bool = False


@dataclass
class ImprovementLoopResult:
    """Result of running the improvement loop."""
    loop_id: str = field(default_factory=lambda: f"il_{uuid.uuid4().hex[:8]}")
    iterations: List[ImprovementIteration] = field(default_factory=list)
    initial_confidence: float = 0.0
    final_confidence: float = 0.0
    total_issues_fixed: int = 0
    total_improvements: int = 0
    stopped_reason: str = ""  # threshold_met, max_iterations, error, no_improvement
    total_duration_seconds: float = 0.0
    success: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "loop_id": self.loop_id,
            "iterations": [i.__dict__ for i in self.iterations],
            "initial_confidence": self.initial_confidence,
            "final_confidence": self.final_confidence,
            "total_issues_fixed": self.total_issues_fixed,
            "total_improvements": self.total_improvements,
            "stopped_reason": self.stopped_reason,
            "total_duration_seconds": self.total_duration_seconds,
            "success": self.success,
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

    # High Priority capabilities
    run_regression_detection: bool = True
    run_code_quality_review: bool = True
    run_documentation_verification: bool = True

    # Confidence scoring settings
    confidence_thresholds: Dict[str, float] = field(default_factory=lambda: {
        "requirement_verification": 0.6,
        "functional_validation": 0.7,
        "regression_detection": 0.8,
        "code_quality": 0.6,
        "documentation": 0.7,
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

    # High Priority results
    regression_results: List[RegressionResult] = field(default_factory=list)
    quality_review: Optional[QualityReview] = None
    doc_check_results: List[DocCheckResult] = field(default_factory=list)

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
            "regression_results": [r.to_dict() for r in self.regression_results],
            "quality_review": self.quality_review.to_dict() if self.quality_review else None,
            "doc_check_results": [r.to_dict() for r in self.doc_check_results],
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
            regression_results=[RegressionResult(**r) for r in data.get("regression_results", [])],
            quality_review=QualityReview(**data["quality_review"]) if data.get("quality_review") else None,
            doc_check_results=[DocCheckResult(**r) for r in data.get("doc_check_results", [])],
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
        "run_regression_detection": self.run_regression_detection,
        "run_code_quality_review": self.run_code_quality_review,
        "run_documentation_verification": self.run_documentation_verification,
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