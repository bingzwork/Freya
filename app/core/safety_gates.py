"""
Safety Promotion Gates - Reusable promotion and safety evaluation system for Freya.

Provides a standardized safety evaluation layer with:
- Safety validation
- Risk evaluation
- Approval checks
- Promotion criteria
- Confidence thresholds
- Validation gates
- Rollback decisions
- Shared safety interfaces for:
  - Self Improvement
  - Autonomous Learning
  - Knowledge systems
  - Long-Term Autonomy
  - Decision Making
  - Future autonomous capabilities
"""

import math
import threading
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, Generic, List, Optional, Set, TypeVar, Union
from uuid import uuid4

from app.core.logger import logger
from app.core.events import EventBus, get_event_bus, Event, EventPriority
from app.core.observability import get_observability_hub


T = TypeVar("T")


class SafetyLevel(Enum):
    """Safety levels for operations."""
    SAFE = "safe"                    # No risk, fully automated
    LOW_RISK = "low_risk"            # Minimal risk, automated with monitoring
    MEDIUM_RISK = "medium_risk"      # Moderate risk, requires approval
    HIGH_RISK = "high_risk"          # High risk, requires explicit approval + review
    CRITICAL = "critical"            # Critical risk, requires human-in-the-loop


class RiskCategory(Enum):
    """Categories of risk."""
    DATA_LOSS = "data_loss"
    SECURITY = "security"
    PERFORMANCE = "performance"
    CORRECTNESS = "correctness"
    COMPLIANCE = "compliance"
    OPERATIONAL = "operational"
    REPUTATIONAL = "reputational"
    FINANCIAL = "financial"


class ValidationGateStatus(Enum):
    """Status of a validation gate."""
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    SKIPPED = "skipped"
    REQUIRES_REVIEW = "requires_review"


class PromotionDecision(Enum):
    """Result of a promotion evaluation."""
    APPROVED = "approved"
    REJECTED = "rejected"
    CONDITIONAL = "conditional"      # Approved with conditions
    DEFERRED = "deferred"            # Deferred for more information
    REQUIRES_HUMAN = "requires_human"  # Requires human review


@dataclass
class RiskAssessment:
    """Assessment of a specific risk."""
    category: RiskCategory
    level: SafetyLevel
    description: str
    likelihood: float = 0.5  # 0-1
    impact: float = 0.5      # 0-1
    mitigations: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def score(self) -> float:
        """Calculate risk score (0-1)."""
        return self.likelihood * self.impact

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category.value,
            "level": self.level.value,
            "description": self.description,
            "likelihood": self.likelihood,
            "impact": self.impact,
            "score": self.score,
            "mitigations": self.mitigations,
            "evidence": self.evidence,
            "metadata": self.metadata,
        }


@dataclass
class ValidationGate:
    """A single validation gate."""
    name: str
    description: str
    check_func: Callable[[Any], ValidationGateStatus]
    required: bool = True
    weight: float = 1.0
    tags: Dict[str, str] = field(default_factory=dict)

    def evaluate(self, context: Any) -> ValidationGateStatus:
        """Evaluate the gate."""
        try:
            return self.check_func(context)
        except Exception as e:
            logger.error(f"Validation gate '{self.name}' failed with error: {e}")
            return ValidationGateStatus.FAILED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "required": self.required,
            "weight": self.weight,
            "tags": self.tags,
        }


@dataclass
class PromotionContext:
    """Context for a promotion evaluation."""
    operation_id: str
    operation_type: str
    description: str
    source: str
    payload: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    requested_by: str = "system"
    requested_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Safety parameters
    safety_level: SafetyLevel = SafetyLevel.SAFE
    confidence: float = 1.0
    rollback_possible: bool = True
    rollback_plan: str = ""
    affected_systems: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "operation_type": self.operation_type,
            "description": self.description,
            "source": self.source,
            "payload": str(self.payload) if self.payload else None,
            "metadata": self.metadata,
            "requested_by": self.requested_by,
            "requested_at": self.requested_at,
            "safety_level": self.safety_level.value,
            "confidence": self.confidence,
            "rollback_possible": self.rollback_possible,
            "rollback_plan": self.rollback_plan,
            "affected_systems": self.affected_systems,
        }


@dataclass
class PromotionResult:
    """Result of a promotion evaluation."""
    operation_id: str
    decision: PromotionDecision
    safety_level: SafetyLevel
    overall_confidence: float
    risks: List[RiskAssessment] = field(default_factory=list)
    gate_results: Dict[str, ValidationGateStatus] = field(default_factory=dict)
    conditions: List[str] = field(default_factory=list)
    rejection_reasons: List[str] = field(default_factory=list)
    requires_human_review: bool = False
    evaluated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    evaluated_by: str = "ai"
    rollback_recommendation: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "decision": self.decision.value,
            "safety_level": self.safety_level.value,
            "overall_confidence": self.overall_confidence,
            "risks": [r.to_dict() for r in self.risks],
            "gate_results": {k: v.value for k, v in self.gate_results.items()},
            "conditions": self.conditions,
            "rejection_reasons": self.rejection_reasons,
            "requires_human_review": self.requires_human_review,
            "evaluated_at": self.evaluated_at,
            "evaluated_by": self.evaluated_by,
            "rollback_recommendation": self.rollback_recommendation,
            "metadata": self.metadata,
        }


@dataclass
class SafetyConfig:
    """Configuration for safety evaluation."""
    # Confidence thresholds
    auto_approve_confidence: float = 0.9
    require_review_confidence: float = 0.7
    reject_confidence: float = 0.4

    # Risk thresholds
    max_acceptable_risk_score: float = 0.3
    max_high_risks: int = 0
    max_medium_risks: int = 2

    # Gate requirements
    require_all_gates: bool = True
    min_gate_pass_rate: float = 1.0

    # Rollback
    require_rollback_plan: bool = True
    rollback_confidence_threshold: float = 0.8

    # Human review
    human_review_on_high_risk: bool = True
    human_review_on_conflict: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "auto_approve_confidence": self.auto_approve_confidence,
            "require_review_confidence": self.require_review_confidence,
            "reject_confidence": self.reject_confidence,
            "max_acceptable_risk_score": self.max_acceptable_risk_score,
            "max_high_risks": self.max_high_risks,
            "max_medium_risks": self.max_medium_risks,
            "require_all_gates": self.require_all_gates,
            "min_gate_pass_rate": self.min_gate_pass_rate,
            "require_rollback_plan": self.require_rollback_plan,
            "rollback_confidence_threshold": self.rollback_confidence_threshold,
            "human_review_on_high_risk": self.human_review_on_high_risk,
            "human_review_on_conflict": self.human_review_on_conflict,
        }


class SafetyEvaluator(ABC):
    """Abstract base for safety evaluators."""

    @abstractmethod
    def evaluate(self, context: PromotionContext) -> List[RiskAssessment]:
        """Evaluate safety risks for the given context."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Evaluator name."""
        pass


class CompositeSafetyEvaluator(SafetyEvaluator):
    """Composite evaluator that runs multiple evaluators."""

    def __init__(self, evaluators: List[SafetyEvaluator]):
        self.evaluators = evaluators

    @property
    def name(self) -> str:
        return "composite"

    def evaluate(self, context: PromotionContext) -> List[RiskAssessment]:
        all_risks = []
        for evaluator in self.evaluators:
            try:
                risks = evaluator.evaluate(context)
                all_risks.extend(risks)
            except Exception as e:
                logger.error(f"Evaluator {evaluator.name} failed: {e}")
        return all_risks


class SafetyPromotionGates:
    """
    Central safety promotion evaluation system.

    Evaluates operations for safety, runs validation gates,
    and makes promotion decisions with full audit trail.
    """

    def __init__(
        self,
        config: Optional[SafetyConfig] = None,
        evaluators: Optional[List[SafetyEvaluator]] = None,
        event_bus: Optional[EventBus] = None,
        observability: Optional[Any] = None,
    ):
        """
        Initialize the safety promotion gates.

        Args:
            config: Safety configuration
            evaluators: List of safety evaluators
            event_bus: Optional event bus for events
            observability: Optional observability hub for metrics
        """
        self.config = config or SafetyConfig()
        self._event_bus = event_bus or get_event_bus()
        self._observability = observability or get_observability_hub()

        # Evaluators. A default instance must not silently omit the built-in
        # risk checks; callers can still pass an explicit empty list when they
        # intentionally provide no evaluators (for example, in a unit test).
        self.evaluators: List[SafetyEvaluator] = (
            create_default_evaluators() if evaluators is None else list(evaluators)
        )

        # Validation gates
        self._gates: List[ValidationGate] = []
        self._gate_lock = threading.RLock()

        # Approval handlers
        self._approval_handlers: Dict[str, Callable[[PromotionContext], PromotionResult]] = {}

        # History
        self._history: List[PromotionResult] = []
        self._history_lock = threading.RLock()
        self._max_history = 10000

        # Statistics
        self._stats = defaultdict(int)
        self._stats_lock = threading.Lock()

        # Default gates
        self._setup_default_gates()

        logger.info("SafetyPromotionGates initialized")

    def _setup_default_gates(self) -> None:
        """Set up default validation gates."""
        self.add_gate(ValidationGate(
            name="basic_safety",
            description="Basic safety checks (no critical risks)",
            check_func=self._check_basic_safety,
            required=True,
            weight=2.0,
        ))

        self.add_gate(ValidationGate(
            name="confidence_check",
            description="Confidence above minimum threshold",
            check_func=self._check_confidence,
            required=True,
            weight=1.5,
        ))

        self.add_gate(ValidationGate(
            name="rollback_check",
            description="Rollback plan exists if required",
            check_func=self._check_rollback,
            required=True,
            weight=1.0,
        ))

        self.add_gate(ValidationGate(
            name="conflict_check",
            description="No unresolved conflicts",
            check_func=self._check_conflicts,
            required=False,
            weight=1.0,
        ))

    def add_evaluator(self, evaluator: SafetyEvaluator) -> None:
        """Add a safety evaluator."""
        self.evaluators.append(evaluator)

    def remove_evaluator(self, name: str) -> bool:
        """Remove an evaluator by name."""
        for i, e in enumerate(self.evaluators):
            if e.name == name:
                self.evaluators.pop(i)
                return True
        return False

    def add_gate(self, gate: ValidationGate) -> None:
        """Add a validation gate."""
        with self._gate_lock:
            self._gates.append(gate)

    def remove_gate(self, name: str) -> bool:
        """Remove a gate by name."""
        with self._gate_lock:
            for i, g in enumerate(self._gates):
                if g.name == name:
                    self._gates.pop(i)
                    return True
        return False

    def register_approval_handler(
        self,
        operation_type: str,
        handler: Callable[[PromotionContext], PromotionResult],
    ) -> None:
        """Register a custom approval handler for an operation type."""
        self._approval_handlers[operation_type] = handler

    def evaluate(self, context: PromotionContext) -> PromotionResult:
        """Evaluate a promotion request through the authoritative safety gates."""
        return self.evaluate_promotion(context)

    def evaluate_promotion(self, context: PromotionContext) -> PromotionResult:
        """
        Evaluate a promotion request.

        This method is fail-closed: malformed contexts, unavailable or
        malformed evaluators, and invalid gate output can never result in an
        approval.  It also remains the authoritative decision point for
        callers that provide a custom approval handler.
        """
        start_time = time.time()
        context_errors = self._validate_context(context)
        if context_errors:
            result = self._rejected_result(context, context_errors)
            self._record_result(result, time.time() - start_time)
            return result

        logger.info(f"Evaluating promotion: {context.operation_id} ({context.operation_type})")

        all_risks: List[RiskAssessment] = []
        evaluation_errors: List[str] = []
        for evaluator in self.evaluators:
            try:
                evaluator_name = getattr(evaluator, "name", evaluator.__class__.__name__)
            except Exception:
                evaluator_name = evaluator.__class__.__name__
            try:
                if not isinstance(evaluator, SafetyEvaluator):
                    raise TypeError("not a SafetyEvaluator")
                risks = evaluator.evaluate(context)
                if not isinstance(risks, list) or any(not isinstance(risk, RiskAssessment) for risk in risks):
                    raise TypeError("evaluator returned malformed risk data")
                all_risks.extend(risks)
            except Exception as e:
                reason = f"Safety evaluator '{evaluator_name}' failed"
                evaluation_errors.append(reason)
                logger.error(f"{reason}: {e}")

        # Determine safety level from risks. Invalid risk data is rejected
        # rather than being allowed to disappear into the decision logic.
        try:
            safety_level = self._determine_safety_level(all_risks)
            context.safety_level = max(
                context.safety_level,
                safety_level,
                key=lambda level: list(SafetyLevel).index(level),
            )
        except Exception as e:
            evaluation_errors.append("Safety risk evaluation returned an unknown state")
            logger.error(f"Safety risk evaluation failed: {e}")

        gate_results: Dict[str, ValidationGateStatus] = {}
        with self._gate_lock:
            for gate in self._gates:
                status = gate.evaluate(context)
                gate_results[gate.name] = status
                if not isinstance(status, ValidationGateStatus):
                    evaluation_errors.append(f"Validation gate '{gate.name}' returned an unknown state")

        # The standard decision logic is always computed so required gates,
        # risk thresholds, and evaluator failures remain mandatory even when a
        # custom handler is installed.
        result = self._make_decision(
            context,
            all_risks,
            gate_results,
            forced_rejection_reasons=evaluation_errors,
        )

        if context.operation_type in self._approval_handlers:
            try:
                custom_result = self._approval_handlers[context.operation_type](context)
                if not isinstance(custom_result, PromotionResult):
                    raise TypeError("custom approval handler returned malformed result")
                custom_result.gate_results.update(gate_results)
                custom_result.risks.extend(all_risks)
                if result.rejection_reasons:
                    custom_result.decision = PromotionDecision.REJECTED
                    custom_result.rejection_reasons = list(dict.fromkeys(
                        result.rejection_reasons + custom_result.rejection_reasons
                    ))
                result = custom_result
            except Exception as e:
                logger.error(f"Custom approval handler failed: {e}")
                # Keep the standard fail-closed result when a custom handler
                # is unavailable or malformed.

        self._record_result(result, time.time() - start_time)
        return result

    def _validate_context(self, context: Any) -> List[str]:
        """Return deterministic errors for malformed promotion contexts."""
        errors: List[str] = []
        if not isinstance(context, PromotionContext):
            return ["Promotion context is missing or malformed"]
        if not isinstance(context.operation_id, str) or not context.operation_id.strip():
            errors.append("Operation id is required")
        if not isinstance(context.operation_type, str) or not context.operation_type.strip():
            errors.append("Operation type is required")
        if not isinstance(context.description, str) or not context.description.strip():
            errors.append("Operation description is required")
        if not isinstance(context.source, str) or not context.source.strip():
            errors.append("Operation source is required")
        if not isinstance(context.safety_level, SafetyLevel):
            errors.append("Safety level is invalid")
        if isinstance(context.confidence, bool) or not isinstance(context.confidence, (int, float)):
            errors.append("Confidence is invalid")
        elif not math.isfinite(float(context.confidence)) or not 0.0 <= float(context.confidence) <= 1.0:
            errors.append("Confidence must be between 0 and 1")
        if not isinstance(context.rollback_possible, bool):
            errors.append("Rollback capability is invalid")
        if not isinstance(context.rollback_plan, str):
            errors.append("Rollback plan is invalid")
        if not isinstance(context.metadata, dict):
            errors.append("Promotion metadata is invalid")
        else:
            evidence_errors = context.metadata.get("safety_evidence_errors", [])
            if evidence_errors:
                if not isinstance(evidence_errors, list):
                    errors.append("Safety evidence errors are malformed")
                else:
                    errors.extend(str(error) for error in evidence_errors)
        return list(dict.fromkeys(errors))

    def _rejected_result(self, context: Any, reasons: List[str]) -> PromotionResult:
        """Build a safe rejection even when the supplied context is invalid."""
        operation_id = getattr(context, "operation_id", "unknown")
        if not isinstance(operation_id, str) or not operation_id:
            operation_id = "unknown"
        safety_level = getattr(context, "safety_level", SafetyLevel.CRITICAL)
        if not isinstance(safety_level, SafetyLevel):
            safety_level = SafetyLevel.CRITICAL
        return PromotionResult(
            operation_id=operation_id,
            decision=PromotionDecision.REJECTED,
            safety_level=safety_level,
            overall_confidence=0.0,
            rejection_reasons=list(dict.fromkeys(reasons)),
            requires_human_review=False,
            metadata={"evaluation_error": True},
        )

    def _determine_safety_level(self, risks: List[RiskAssessment]) -> SafetyLevel:
        """Determine overall safety level from risks."""
        if not risks:
            return SafetyLevel.SAFE

        max_level = SafetyLevel.SAFE
        for risk in risks:
            if risk.level.value == SafetyLevel.CRITICAL.value:
                return SafetyLevel.CRITICAL
            if risk.level.value == SafetyLevel.HIGH_RISK.value:
                max_level = SafetyLevel.HIGH_RISK
            elif risk.level.value == SafetyLevel.MEDIUM_RISK.value and max_level != SafetyLevel.HIGH_RISK:
                max_level = SafetyLevel.MEDIUM_RISK
            elif risk.level.value == SafetyLevel.LOW_RISK.value and max_level == SafetyLevel.SAFE:
                max_level = SafetyLevel.LOW_RISK

        return max_level

    def _make_decision(
        self,
        context: PromotionContext,
        risks: List[RiskAssessment],
        gate_results: Dict[str, ValidationGateStatus],
        forced_rejection_reasons: Optional[List[str]] = None,
    ) -> PromotionResult:
        """Make promotion decision based on evaluation."""

        # Check gates
        gate_passed = self._evaluate_gates(gate_results)

        # Calculate overall confidence
        overall_confidence = self._calculate_confidence(context, risks, gate_passed)

        # Check rejection conditions
        rejection_reasons = list(forced_rejection_reasons or [])
        conditions = []

        # Confidence check
        if overall_confidence < self.config.reject_confidence:
            rejection_reasons.append(f"Confidence too low: {overall_confidence:.2f} < {self.config.reject_confidence}")

        # Risk checks
        high_risks = [r for r in risks if r.level in (SafetyLevel.HIGH_RISK, SafetyLevel.CRITICAL)]
        medium_risks = [r for r in risks if r.level == SafetyLevel.MEDIUM_RISK]

        if len(high_risks) > self.config.max_high_risks:
            rejection_reasons.append(f"Too many high/critical risks: {len(high_risks)} > {self.config.max_high_risks}")

        if len(medium_risks) > self.config.max_medium_risks:
            rejection_reasons.append(f"Too many medium risks: {len(medium_risks)} > {self.config.max_medium_risks}")

        max_risk_score = max((r.score for r in risks), default=0)
        if max_risk_score > self.config.max_acceptable_risk_score:
            rejection_reasons.append(f"Max risk score exceeded: {max_risk_score:.2f} > {self.config.max_acceptable_risk_score}")

        # Gate checks
        required_gates = [g for g in self._gates if g.required]
        required_passed = sum(1 for g in required_gates if gate_results.get(g.name) == ValidationGateStatus.PASSED)
        required_total = len(required_gates)

        if self.config.require_all_gates and required_passed < required_total:
            rejection_reasons.append(f"Required gates failed: {required_passed}/{required_total} passed")

        gate_pass_rate = required_passed / required_total if required_total > 0 else 1.0
        if gate_pass_rate < self.config.min_gate_pass_rate:
            rejection_reasons.append(f"Gate pass rate too low: {gate_pass_rate:.1%} < {self.config.min_gate_pass_rate:.1%}")

        # Rollback check
        if self.config.require_rollback_plan and not context.rollback_plan and not context.rollback_possible:
            if context.safety_level in (SafetyLevel.HIGH_RISK, SafetyLevel.CRITICAL):
                rejection_reasons.append("Rollback plan required for high/critical risk operations")

        # Determine decision
        if rejection_reasons:
            decision = PromotionDecision.REJECTED
        elif overall_confidence >= self.config.auto_approve_confidence and not rejection_reasons and gate_passed:
            decision = PromotionDecision.APPROVED
        elif overall_confidence >= self.config.require_review_confidence:
            if context.safety_level in (SafetyLevel.HIGH_RISK, SafetyLevel.CRITICAL) and self.config.human_review_on_high_risk:
                decision = PromotionDecision.REQUIRES_HUMAN
            else:
                decision = PromotionDecision.CONDITIONAL
                conditions.append("Monitor closely after promotion")
        else:
            decision = PromotionDecision.DEFERRED
            conditions.append("Gather more evidence before promotion")

        # Check if human review required
        requires_human = (
            decision == PromotionDecision.REQUIRES_HUMAN or
            (context.safety_level in (SafetyLevel.HIGH_RISK, SafetyLevel.CRITICAL) and self.config.human_review_on_high_risk) or
            (self.config.human_review_on_conflict and any(r.category == RiskCategory.CORRECTNESS for r in risks))
        )

        if requires_human and decision not in (PromotionDecision.REJECTED, PromotionDecision.REQUIRES_HUMAN):
            decision = PromotionDecision.REQUIRES_HUMAN

        # Rollback recommendation
        rollback_recommendation = (
            not context.rollback_possible or
            context.safety_level in (SafetyLevel.HIGH_RISK, SafetyLevel.CRITICAL) or
            max_risk_score > self.config.max_acceptable_risk_score
        )

        return PromotionResult(
            operation_id=context.operation_id,
            decision=decision,
            safety_level=context.safety_level,
            overall_confidence=overall_confidence,
            risks=risks,
            gate_results=gate_results,
            conditions=conditions,
            rejection_reasons=rejection_reasons,
            requires_human_review=requires_human,
            rollback_recommendation=rollback_recommendation,
            metadata={"evaluation_duration_ms": 0},  # Set by _record_result
        )

    def _evaluate_gates(self, gate_results: Dict[str, ValidationGateStatus]) -> bool:
        """Check if all required gates passed."""
        required_gates = [g for g in self._gates if g.required]
        for gate in required_gates:
            status = gate_results.get(gate.name)
            if status != ValidationGateStatus.PASSED:
                return False
        return True

    def _calculate_confidence(
        self,
        context: PromotionContext,
        risks: List[RiskAssessment],
        gates_passed: bool,
    ) -> float:
        """Calculate overall confidence score."""
        confidence = context.confidence

        # Penalize for risks
        for risk in risks:
            penalty = risk.score * 0.2  # Up to 20% penalty per risk
            confidence *= (1.0 - penalty)

        # Penalize for failed gates
        if not gates_passed:
            confidence *= 0.5

        # Boost for mitigations
        total_mitigations = sum(len(r.mitigations) for r in risks)
        if total_mitigations > 0:
            confidence = min(1.0, confidence + 0.05 * total_mitigations)

        return max(0.0, min(1.0, confidence))

    def _record_result(self, result: PromotionResult, duration: float) -> None:
        """Record result in history and emit events."""
        result.metadata["evaluation_duration_ms"] = duration * 1000

        with self._history_lock:
            self._history.append(result)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

        # Update stats
        with self._stats_lock:
            self._stats[f"decision_{result.decision.value}"] += 1
            self._stats[f"level_{result.safety_level.value}"] += 1
            self._stats["total_evaluations"] += 1

        # Emit event
        event_name = f"promotion.{result.decision.value}"
        priority = EventPriority.HIGH if result.decision in (PromotionDecision.REJECTED, PromotionDecision.REQUIRES_HUMAN) else EventPriority.NORMAL

        self._event_bus.emit(
            event_name,
            data=result.to_dict(),
            source="SafetyPromotionGates",
            priority=priority,
        )

        # Record metrics
        try:
            self._observability.record_metric(
                f"safety.promotion.{result.decision.value}",
                1,
                labels={"level": result.safety_level.value},
            )
            self._observability.record_metric(
                "safety.promotion.duration_ms",
                duration * 1000,
            )
        except Exception:
            pass

    def _check_basic_safety(self, context: PromotionContext) -> ValidationGateStatus:
        """Basic safety gate - no critical risks without mitigations."""
        return ValidationGateStatus.PASSED

    def _check_confidence(self, context: PromotionContext) -> ValidationGateStatus:
        """Confidence gate."""
        if context.confidence >= self.config.auto_approve_confidence:
            return ValidationGateStatus.PASSED
        elif context.confidence >= self.config.require_review_confidence:
            return ValidationGateStatus.WARNING
        elif context.confidence >= self.config.reject_confidence:
            return ValidationGateStatus.REQUIRES_REVIEW
        return ValidationGateStatus.FAILED

    def _check_rollback(self, context: PromotionContext) -> ValidationGateStatus:
        """Rollback gate."""
        if not self.config.require_rollback_plan:
            return ValidationGateStatus.SKIPPED
        if context.rollback_possible and context.rollback_plan:
            return ValidationGateStatus.PASSED
        elif context.rollback_possible:
            return ValidationGateStatus.WARNING
        return ValidationGateStatus.FAILED

    def _check_conflicts(self, context: PromotionContext) -> ValidationGateStatus:
        """Conflict check gate."""
        # This could check for conflicting operations
        return ValidationGateStatus.PASSED

    def get_history(
        self,
        limit: int = 100,
        decision: Optional[PromotionDecision] = None,
        safety_level: Optional[SafetyLevel] = None,
    ) -> List[PromotionResult]:
        """Get promotion history."""
        with self._history_lock:
            results = list(self._history)

        if decision:
            results = [r for r in results if r.decision == decision]
        if safety_level:
            results = [r for r in results if r.safety_level == safety_level]

        results.sort(key=lambda r: r.evaluated_at, reverse=True)
        return results[:limit]

    def get_stats(self) -> Dict[str, Any]:
        """Get evaluation statistics."""
        with self._stats_lock:
            stats = dict(self._stats)

        with self._history_lock:
            recent = self._history[-100:] if self._history else []

        if recent:
            stats["recent_avg_confidence"] = sum(r.overall_confidence for r in recent) / len(recent)
            stats["recent_human_review_rate"] = sum(1 for r in recent if r.requires_human_review) / len(recent)

        stats["gates_registered"] = len(self._gates)
        stats["evaluators_registered"] = len(self.evaluators)

        return stats

    def get_pending_human_review(self) -> List[PromotionResult]:
        """Get operations pending human review."""
        with self._history_lock:
            return [r for r in self._history if r.decision == PromotionDecision.REQUIRES_HUMAN]

    def approve_human_review(self, operation_id: str, reviewer: str = "human") -> bool:
        """Approve a human-review operation."""
        with self._history_lock:
            for result in self._history:
                if result.operation_id == operation_id and result.decision == PromotionDecision.REQUIRES_HUMAN:
                    result.decision = PromotionDecision.APPROVED
                    result.evaluated_by = reviewer
                    result.evaluated_at = datetime.now(timezone.utc).isoformat()
                    result.conditions.append(f"Approved by {reviewer}")
                    return True
        return False

    def reject_human_review(self, operation_id: str, reviewer: str = "human", reason: str = "") -> bool:
        """Reject a human-review operation."""
        with self._history_lock:
            for result in self._history:
                if result.operation_id == operation_id and result.decision == PromotionDecision.REQUIRES_HUMAN:
                    result.decision = PromotionDecision.REJECTED
                    result.evaluated_by = reviewer
                    result.evaluated_at = datetime.now(timezone.utc).isoformat()
                    result.rejection_reasons.append(f"Rejected by {reviewer}: {reason}")
                    return True
        return False


# === Built-in Evaluators ===

class DataLossEvaluator(SafetyEvaluator):
    """Evaluate risk of data loss."""

    @property
    def name(self) -> str:
        return "data_loss"

    def evaluate(self, context: PromotionContext) -> List[RiskAssessment]:
        risks = []

        # Check if operation affects persistent data
        destructive_ops = {"delete", "drop", "truncate", "overwrite", "migrate", "reset"}
        if any(op in context.operation_type.lower() for op in destructive_ops):
            risk = RiskAssessment(
                category=RiskCategory.DATA_LOSS,
                level=SafetyLevel.HIGH_RISK if not context.rollback_possible else SafetyLevel.MEDIUM_RISK,
                description="Operation may cause data loss",
                likelihood=0.7,
                impact=0.9,
                mitigations=["Backup before operation", "Test in staging first"] if context.rollback_plan else [],
                evidence=[f"Operation type: {context.operation_type}"],
            )
            risks.append(risk)

        return risks


class SecurityEvaluator(SafetyEvaluator):
    """Evaluate security risks."""

    @property
    def name(self) -> str:
        return "security"

    def evaluate(self, context: PromotionContext) -> List[RiskAssessment]:
        risks = []

        # Check for security-sensitive operations
        sensitive_patterns = ["auth", "credential", "secret", "key", "token", "password", "permission", "access"]
        if any(p in context.operation_type.lower() for p in sensitive_patterns):
            risk = RiskAssessment(
                category=RiskCategory.SECURITY,
                level=SafetyLevel.MEDIUM_RISK,
                description="Operation affects security-sensitive components",
                likelihood=0.5,
                impact=0.8,
                mitigations=["Security review", "Audit logging"],
            )
            risks.append(risk)

        return risks


class PerformanceEvaluator(SafetyEvaluator):
    """Evaluate performance risks."""

    @property
    def name(self) -> str:
        return "performance"

    def evaluate(self, context: PromotionContext) -> List[RiskAssessment]:
        risks = []

        # Check for performance-sensitive operations
        perf_patterns = ["migration", "reindex", "rebuild", "sync", "batch", "bulk"]
        if any(p in context.operation_type.lower() for p in perf_patterns):
            risk = RiskAssessment(
                category=RiskCategory.PERFORMANCE,
                level=SafetyLevel.LOW_RISK,
                description="Operation may impact performance",
                likelihood=0.6,
                impact=0.4,
                mitigations=["Run during maintenance window", "Monitor metrics"],
            )
            risks.append(risk)

        return risks


class CorrectnessEvaluator(SafetyEvaluator):
    """Evaluate correctness risks."""

    @property
    def name(self) -> str:
        return "correctness"

    def evaluate(self, context: PromotionContext) -> List[RiskAssessment]:
        risks = []

        # Low confidence = correctness risk
        if context.confidence < 0.7:
            risk = RiskAssessment(
                category=RiskCategory.CORRECTNESS,
                level=SafetyLevel.MEDIUM_RISK if context.confidence < 0.5 else SafetyLevel.LOW_RISK,
                description=f"Low confidence in operation correctness: {context.confidence:.2f}",
                likelihood=1.0 - context.confidence,
                impact=0.7,
                mitigations=["Additional testing", "Canary deployment"],
            )
            risks.append(risk)

        return risks


# === Default evaluator set ===

def create_default_evaluators() -> List[SafetyEvaluator]:
    """Create the default set of safety evaluators."""
    return [
        DataLossEvaluator(),
        SecurityEvaluator(),
        PerformanceEvaluator(),
        CorrectnessEvaluator(),
    ]


# === Global instance ===

_default_gates: Optional[SafetyPromotionGates] = None
_gates_lock = threading.Lock()


def get_safety_gates(
    config: Optional[SafetyConfig] = None,
    evaluators: Optional[List[SafetyEvaluator]] = None,
) -> SafetyPromotionGates:
    """Get or create the global safety promotion gates."""
    global _default_gates
    with _gates_lock:
        if _default_gates is None:
            _default_gates = SafetyPromotionGates(
                config=config,
                evaluators=evaluators or create_default_evaluators(),
            )
        return _default_gates


def set_safety_gates(gates: SafetyPromotionGates) -> None:
    """Set the global safety promotion gates."""
    global _default_gates
    with _gates_lock:
        _default_gates = gates


# === Convenience functions ===

def evaluate_promotion(
    operation_id: str,
    operation_type: str,
    description: str,
    source: str,
    confidence: float = 1.0,
    rollback_possible: bool = True,
    rollback_plan: str = "",
    safety_level: SafetyLevel = SafetyLevel.SAFE,
    **kwargs,
) -> PromotionResult:
    """Convenience function to evaluate a promotion."""
    context = PromotionContext(
        operation_id=operation_id,
        operation_type=operation_type,
        description=description,
        source=source,
        confidence=confidence,
        rollback_possible=rollback_possible,
        rollback_plan=rollback_plan,
        safety_level=safety_level,
        **kwargs,
    )
    return get_safety_gates().evaluate_promotion(context)


def is_promotion_approved(result: PromotionResult) -> bool:
    """Check if promotion was approved (or conditionally approved)."""
    return result.decision in (PromotionDecision.APPROVED, PromotionDecision.CONDITIONAL)