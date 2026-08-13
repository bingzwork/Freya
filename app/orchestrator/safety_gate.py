"""Safety Gate for the Central Autonomous Orchestrator.

Integrates RiskAnalyzer, DecisionManager, and HumanOversight to provide
comprehensive safety controls for all autonomous operations.
"""

import logging
import threading
import time
from collections import defaultdict
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
from uuid import uuid4

from app.risk.risk_analyzer import RiskAnalyzer, RiskCategory
from app.risk.risk_item import RiskSeverity as RiskLevel, RiskProbability, RiskItem as RiskFinding
from app.decision.manager import DecisionManager, DecisionContext, DecisionType, DecisionCategory, DecisionResult, DecisionOption
from app.core.events import get_event_bus, Event, EventPriority
from app.core.observability import get_observability_hub, ComponentInfo, ComponentType
from app.orchestrator.capability_registry import Capability, CapabilityRegistry, CapabilityState, get_capability_registry


logger = logging.getLogger(__name__)


class SafetyAction(Enum):
    """Actions the safety gate can take."""
    ALLOW = "allow"                    # Allow the operation
    ALLOW_WITH_MONITORING = "allow_with_monitoring"  # Allow but monitor closely
    REQUIRE_APPROVAL = "require_approval"  # Require human approval
    MODIFY_AND_ALLOW = "modify_and_allow"  # Modify parameters then allow
    BLOCK = "block"                    # Block the operation
    ESCALATE = "escalate"              # Escalate to higher authority


class SafetyGateMode(Enum):
    """Operating modes for the safety gate."""
    PERMISSIVE = "permissive"    # Allow most operations, log warnings
    BALANCED = "balanced"        # Balanced safety (default)
    STRICT = "strict"            # Require approval for medium+ risk
    PARANOID = "paranoid"        # Require approval for low+ risk, block high+


@dataclass
class SafetyPolicy:
    """Policy configuration for the safety gate."""
    mode: SafetyGateMode = SafetyGateMode.BALANCED

    # Risk thresholds per mode
    risk_thresholds: Dict[SafetyGateMode, Dict[str, Any]] = field(default_factory=lambda: {
        SafetyGateMode.PERMISSIVE: {
            "auto_allow_below": RiskLevel.LOW,
            "require_approval_at": RiskLevel.CRITICAL,
            "block_at": RiskLevel.CRITICAL,
        },
        SafetyGateMode.BALANCED: {
            "auto_allow_below": RiskLevel.LOW,
            "require_approval_at": RiskLevel.HIGH,
            "block_at": RiskLevel.CRITICAL,
        },
        SafetyGateMode.STRICT: {
            "auto_allow_below": RiskLevel.INFO,
            "require_approval_at": RiskLevel.MEDIUM,
            "block_at": RiskLevel.HIGH,
        },
        SafetyGateMode.PARANOID: {
            "auto_allow_below": RiskLevel.INFO,
            "require_approval_at": RiskLevel.LOW,
            "block_at": RiskLevel.MEDIUM,
        },
    })

    # Operation categories that always require approval
    always_require_approval: Set[str] = field(default_factory=lambda: {
        "file_deletion",
        "system_modification",
        "network_access",
        "credential_access",
        "code_execution",
        "database_mutation",
        "external_api_call",
    })

    # Operation categories that are always blocked
    always_block: Set[str] = field(default_factory=lambda: {
        "system_destruction",
        "data_exfiltration",
        "privilege_escalation",
    })

    # Confidence thresholds
    min_confidence_for_auto: float = 0.7
    min_confidence_for_approval: float = 0.5

    # Rate limiting
    max_operations_per_minute: int = 100
    max_high_risk_per_hour: int = 10

    # Human oversight
    require_human_for: List[str] = field(default_factory=list)
    approval_timeout_seconds: float = 300.0


@dataclass
class SafetyAssessment:
    """Result of a safety assessment."""
    assessment_id: str = field(default_factory=lambda: f"sa_{uuid4().hex[:8]}")
    operation: str = ""
    operation_type: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Risk analysis
    risk_level: RiskLevel = RiskLevel.INFO
    risk_findings: List[RiskFinding] = field(default_factory=list)
    risk_summary: str = ""

    # Decision
    decision_result: Optional[DecisionResult] = None
    confidence: float = 0.0

    # Safety action
    action: SafetyAction = SafetyAction.ALLOW
    reason: str = ""
    conditions: List[str] = field(default_factory=list)  # Conditions for ALLOW_WITH_MONITORING
    modifications: Dict[str, Any] = field(default_factory=dict)  # For MODIFY_AND_ALLOW

    # Approval
    requires_approval: bool = False
    approval_request_id: Optional[str] = None
    approved: Optional[bool] = None
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)


class HumanOversightInterface(ABC):
    """Interface for human oversight/approval."""

    @abstractmethod
    def request_approval(self, assessment: SafetyAssessment) -> str:
        """Request human approval. Returns approval request ID."""
        pass

    @abstractmethod
    def check_approval(self, request_id: str) -> Optional[bool]:
        """Check approval status. Returns True/False/None (pending)."""
        pass

    @abstractmethod
    def wait_for_approval(self, request_id: str, timeout: float) -> Optional[bool]:
        """Wait for approval with timeout. Returns True/False/None (timeout)."""
        pass


class DefaultHumanOversight(HumanOversightInterface):
    """Default implementation using event bus for approval requests."""

    def __init__(self):
        self._event_bus = get_event_bus()
        self._pending_approvals: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def request_approval(self, assessment: SafetyAssessment) -> str:
        request_id = f"approval_{uuid4().hex[:8]}"
        with self._lock:
            self._pending_approvals[request_id] = {
                "assessment": assessment,
                "status": "pending",
                "requested_at": datetime.now(timezone.utc).isoformat(),
                "result": None,
            }

        # Publish approval request event
        self._event_bus.publish(Event(
            name="safety.approval_requested",
            data={
                "request_id": request_id,
                "operation": assessment.operation,
                "risk_level": assessment.risk_level.value,
                "reason": assessment.reason,
                "details": assessment.metadata,
            },
            source="safety_gate",
            priority=EventPriority.HIGH
        ))

        return request_id

    def check_approval(self, request_id: str) -> Optional[bool]:
        with self._lock:
            approval = self._pending_approvals.get(request_id)
            if not approval:
                return None
            return approval["result"]

    def wait_for_approval(self, request_id: str, timeout: float) -> Optional[bool]:
        start = time.time()
        while time.time() - start < timeout:
            result = self.check_approval(request_id)
            if result is not None:
                return result
            time.sleep(0.5)
        return None  # Timeout

    def submit_approval(self, request_id: str, approved: bool, approved_by: str = "human") -> bool:
        """Submit approval decision (called by human or approval system)."""
        with self._lock:
            if request_id not in self._pending_approvals:
                return False
            self._pending_approvals[request_id]["status"] = "completed"
            self._pending_approvals[request_id]["result"] = approved
            self._pending_approvals[request_id]["approved_by"] = approved_by
            self._pending_approvals[request_id]["approved_at"] = datetime.now(timezone.utc).isoformat()

        # Publish result
        self._event_bus.publish(Event(
            name="safety.approval_result",
            data={
                "request_id": request_id,
                "approved": approved,
                "approved_by": approved_by,
            },
            source="safety_gate",
            priority=EventPriority.HIGH
        ))
        return True


class SafetyGate:
    """
    Central safety gate for all autonomous operations.

    Integrates:
    - RiskAnalyzer for pattern-based risk detection
    - DecisionManager for confidence-scored decisions
    - HumanOversight for approval workflows
    """

    def __init__(
        self,
        risk_analyzer: Optional[RiskAnalyzer] = None,
        decision_manager: Optional[DecisionManager] = None,
        human_oversight: Optional[HumanOversightInterface] = None,
        policy: Optional[SafetyPolicy] = None,
        registry: Optional[CapabilityRegistry] = None,
    ):
        self.risk_analyzer = risk_analyzer or RiskAnalyzer()
        self.decision_manager = decision_manager
        self.human_oversight = human_oversight or DefaultHumanOversight()
        self.policy = policy or SafetyPolicy()
        self.registry = registry or get_capability_registry()

        self._event_bus = get_event_bus()
        self._observability = get_observability_hub()
        self._lock = threading.RLock()

        # Rate limiting
        self._operation_counts: Dict[str, List[float]] = defaultdict(list)
        self._high_risk_counts: List[float] = []

        # Assessment history
        self._assessment_history: List[SafetyAssessment] = []
        self._max_history = 1000

        # Register with observability
        self._observability.register_component(ComponentInfo(
            name="SafetyGate",
            component_type=ComponentType.SERVICE,
            version="1.0.0",
            description="Central safety gate integrating risk analysis, decision making, and human oversight",
            metadata={}
        ))

        # Add default risk patterns
        self._initialize_risk_patterns()

    def _initialize_risk_patterns(self):
        """Initialize default risk patterns for autonomous operations."""
        # File operations
        self.risk_analyzer.register_pattern(
            name="file_deletion",
            patterns=[r"(delete|remove|rm\s+|unlink)"],
            severity=RiskLevel.HIGH,
            probability=RiskProbability.LIKELY,
            category=RiskCategory.SECURITY,
        )

        self.risk_analyzer.register_pattern(
            name="system_modification",
            patterns=[r"(chmod|chown|sudo|mount|systemctl|service\s+)"],
            severity=RiskLevel.HIGH,
            probability=RiskProbability.POSSIBLE,
            category=RiskCategory.OPERATIONAL,
        )

        self.risk_analyzer.register_pattern(
            name="network_access",
            patterns=[r"(curl|wget|nc\s+|netcat|ssh|scp|rsync)"],
            severity=RiskLevel.MEDIUM,
            probability=RiskProbability.POSSIBLE,
            category=RiskCategory.SECURITY,
        )

        self.risk_analyzer.register_pattern(
            name="credential_access",
            patterns=[r"(password|secret|token|key|credential|auth)"],
            severity=RiskLevel.HIGH,
            probability=RiskProbability.POSSIBLE,
            category=RiskCategory.SECURITY,
        )

        self.risk_analyzer.register_pattern(
            name="code_execution",
            patterns=[r"(\beval\b|\bexec\b|subprocess|os\.system|shell=True)"],
            severity=RiskLevel.HIGH,
            probability=RiskProbability.POSSIBLE,
            category=RiskCategory.SECURITY,
        )

        self.risk_analyzer.register_pattern(
            name="database_mutation",
            patterns=[r"(DELETE\s+FROM|DROP\s+TABLE|TRUNCATE|ALTER\s+TABLE)"],
            severity=RiskLevel.HIGH,
            probability=RiskProbability.POSSIBLE,
            category=RiskCategory.SECURITY,
        )

        self.risk_analyzer.register_pattern(
            name="external_api_call",
            patterns=[r"(requests\.|httpx\.|aiohttp\.|api\.)"],
            severity=RiskLevel.MEDIUM,
            probability=RiskProbability.POSSIBLE,
            category=RiskCategory.SECURITY,
        )

        # Critical patterns
        self.risk_analyzer.register_pattern(
            name="system_destruction",
            patterns=[r"(rm\s+-rf\s+/|format\s+|mkfs|dd\s+if=)"],
            severity=RiskLevel.CRITICAL,
            probability=RiskProbability.RARE,
            category=RiskCategory.OPERATIONAL,
        )

        self.risk_analyzer.register_pattern(
            name="data_exfiltration",
            patterns=[r"(tar\s+.*\s+\|\s*(nc|ssh)|exfil|steal)"],
            severity=RiskLevel.CRITICAL,
            probability=RiskProbability.RARE,
            category=RiskCategory.SECURITY,
        )

        self.risk_analyzer.register_pattern(
            name="privilege_escalation",
            patterns=[r"(sudo\s+su|setuid|setgid|capset|capsh)"],
            severity=RiskLevel.CRITICAL,
            probability=RiskProbability.RARE,
            category=RiskCategory.SECURITY,
        )

    def assess(self, operation: str, operation_type: str, context: Dict[str, Any] = None) -> SafetyAssessment:
        """
        Perform a comprehensive safety assessment of an operation.

        Args:
            operation: Description of the operation
            operation_type: Type/category of operation
            context: Additional context (capability, task, workflow, etc.)

        Returns:
            SafetyAssessment with action and details
        """
        context = context or {}
        assessment = SafetyAssessment(
            operation=operation,
            operation_type=operation_type,
            metadata=context
        )

        # Step 1: Check always-block list
        if self._is_always_blocked(operation_type):
            assessment.action = SafetyAction.BLOCK
            assessment.risk_level = RiskLevel.CRITICAL
            assessment.reason = f"Operation type '{operation_type}' is always blocked"
            self._record_assessment(assessment)
            return assessment

        # Step 2: Risk analysis
        risk_findings = self.risk_analyzer._analyze_content(operation)

        # Determine overall risk level from findings
        if risk_findings:
            max_severity = max(f.severity for f in risk_findings)
            assessment.risk_level = max_severity
        else:
            assessment.risk_level = RiskLevel.INFO

        assessment.risk_findings = risk_findings
        assessment.risk_summary = f"Found {len(risk_findings)} risk findings" if risk_findings else "No risks detected"

        # Step 3: Decision manager evaluation (if available)
        if self.decision_manager:
            decision_context = DecisionContext(
                task_description=operation,
                current_phase="safety_assessment",
                component="safety_gate",
                available_context=str(context),
                project_state=context,
                risk_tolerance=self._get_risk_tolerance(),
            )
            # Use decide_simple which doesn't require explicit options
            decision = self.decision_manager.decide_simple(
                decision_type=DecisionType.FILE_MODIFICATION if "file" in operation_type.lower() else DecisionType.TOOL_SELECTION,
                task_description=operation,
                options=[
                    DecisionOption(
                        id="allow",
                        name="Allow",
                        description="Allow the operation",
                        action="allow",
                        category=DecisionCategory.EXECUTION,
                        decision_type=DecisionType.FILE_MODIFICATION if "file" in operation_type.lower() else DecisionType.TOOL_SELECTION,
                        estimated_success=0.8,
                        estimated_effort=0.1,
                        estimated_impact=0.5,
                        risk_level="low",
                    ),
                    DecisionOption(
                        id="block",
                        name="Block",
                        description="Block the operation",
                        action="block",
                        category=DecisionCategory.EXECUTION,
                        decision_type=DecisionType.FILE_MODIFICATION if "file" in operation_type.lower() else DecisionType.TOOL_SELECTION,
                        estimated_success=1.0,
                        estimated_effort=0.1,
                        estimated_impact=0.0,
                        risk_level="none",
                    ),
                    DecisionOption(
                        id="require_approval",
                        name="Require Approval",
                        description="Require human approval",
                        action="require_approval",
                        category=DecisionCategory.EXECUTION,
                        decision_type=DecisionType.FILE_MODIFICATION if "file" in operation_type.lower() else DecisionType.TOOL_SELECTION,
                        estimated_success=0.9,
                        estimated_effort=0.5,
                        estimated_impact=0.3,
                        risk_level="low",
                    ),
                ],
                component="safety_gate",
                metadata=context,
            )
            assessment.decision_result = decision
            assessment.confidence = decision.confidence if decision else 0.0

        # Step 4: Rate limiting check
        if self._is_rate_limited(operation_type):
            assessment.action = SafetyAction.BLOCK
            assessment.reason = "Rate limit exceeded for this operation type"
            self._record_assessment(assessment)
            return assessment

        # Step 5: Determine action based on policy
        assessment.action = self._determine_action(assessment)

        # Step 6: Handle approval requirement
        if assessment.action == SafetyAction.REQUIRE_APPROVAL:
            assessment.requires_approval = True
            assessment.approval_request_id = self.human_oversight.request_approval(assessment)
            assessment.reason += f" (approval request: {assessment.approval_request_id})"

        self._record_assessment(assessment)
        self._update_rate_limits(operation_type, assessment.risk_level)

        # Publish event
        self._publish_event("safety.assessment", {
            "assessment_id": assessment.assessment_id,
            "operation": operation,
            "operation_type": operation_type,
            "risk_level": assessment.risk_level.value,
            "action": assessment.action.value,
            "requires_approval": assessment.requires_approval,
        })

        return assessment

    def wait_for_approval(self, assessment: SafetyAssessment, timeout: Optional[float] = None) -> SafetyAssessment:
        """Wait for human approval if required."""
        if not assessment.requires_approval or not assessment.approval_request_id:
            return assessment

        timeout = timeout or self.policy.approval_timeout_seconds
        result = self.human_oversight.wait_for_approval(assessment.approval_request_id, timeout)

        if result is True:
            assessment.approved = True
            assessment.action = SafetyAction.ALLOW
            assessment.reason = "Approved by human oversight"
        elif result is False:
            assessment.approved = False
            assessment.action = SafetyAction.BLOCK
            assessment.reason = "Rejected by human oversight"
        else:
            assessment.action = SafetyAction.BLOCK
            assessment.reason = "Approval timeout"
            assessment.approved = False

        assessment.approved_at = datetime.now(timezone.utc).isoformat()
        self._record_assessment(assessment)
        return assessment

    def check_and_enforce(self, operation: str, operation_type: str, context: Dict[str, Any] = None) -> SafetyAssessment:
        """
        Perform assessment and enforce the decision.

        This is the main entry point for capabilities to check safety.
        """
        assessment = self.assess(operation, operation_type, context)

        if assessment.action == SafetyAction.REQUIRE_APPROVAL:
            assessment = self.wait_for_approval(assessment)

        # Final enforcement
        if assessment.action == SafetyAction.BLOCK:
            raise SafetyViolationError(f"Operation blocked by safety gate: {assessment.reason}")

        return assessment

    def _is_always_blocked(self, operation_type: str) -> bool:
        return operation_type in self.policy.always_block

    def _is_always_approval_required(self, operation_type: str) -> bool:
        return operation_type in self.policy.always_require_approval

    def _get_risk_tolerance(self) -> str:
        mode = self.policy.mode
        if mode == SafetyGateMode.PERMISSIVE:
            return "high"
        elif mode == SafetyGateMode.BALANCED:
            return "medium"
        elif mode == SafetyGateMode.STRICT:
            return "low"
        else:
            return "very_low"

    def _determine_action(self, assessment: SafetyAssessment) -> SafetyAction:
        """Determine safety action based on policy and assessment."""
        mode = self.policy.mode
        thresholds = self.policy.risk_thresholds[mode]

        risk_level = assessment.risk_level

        # Always require approval for certain operation types
        if self._is_always_approval_required(assessment.operation_type):
            return SafetyAction.REQUIRE_APPROVAL

        # A DecisionManager confidence is meaningful only when a decision was
        # actually produced.  The production initializer intentionally keeps
        # this collaborator optional; without one, policy risk rules remain
        # authoritative instead of silently blocking every operation.
        if assessment.decision_result is not None and assessment.confidence < self.policy.min_confidence_for_auto:
            if assessment.confidence >= self.policy.min_confidence_for_approval:
                return SafetyAction.REQUIRE_APPROVAL
            return SafetyAction.BLOCK

        # Map risk level to ordinal for comparison
        risk_order = {
            RiskLevel.INFO: 0,
            RiskLevel.LOW: 1,
            RiskLevel.MEDIUM: 2,
            RiskLevel.HIGH: 3,
            RiskLevel.CRITICAL: 4,
        }

        risk_value = risk_order.get(risk_level, 0)
        allow_threshold = risk_order.get(thresholds["auto_allow_below"], 0)
        approval_threshold = risk_order.get(thresholds["require_approval_at"], 0)
        block_threshold = risk_order.get(thresholds["block_at"], 0)

        if risk_value <= allow_threshold:
            return SafetyAction.ALLOW
        elif risk_value < approval_threshold:
            return SafetyAction.ALLOW_WITH_MONITORING
        elif risk_value < block_threshold:
            return SafetyAction.REQUIRE_APPROVAL
        else:
            return SafetyAction.BLOCK

    def _is_rate_limited(self, operation_type: str) -> bool:
        """Check if operation is rate limited."""
        now = time.time()

        # Clean old entries
        for key in list(self._operation_counts.keys()):
            self._operation_counts[key] = [t for t in self._operation_counts[key] if now - t < 60]

        self._high_risk_counts = [t for t in self._high_risk_counts if now - t < 3600]

        # Check general rate limit
        if len(self._operation_counts[operation_type]) >= self.policy.max_operations_per_minute:
            return True

        return False

    def _update_rate_limits(self, operation_type: str, risk_level: RiskLevel):
        """Update rate limit counters."""
        now = time.time()
        self._operation_counts[operation_type].append(now)

        if risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            self._high_risk_counts.append(now)

    def _record_assessment(self, assessment: SafetyAssessment):
        """Record assessment in history."""
        with self._lock:
            self._assessment_history.append(assessment)
            if len(self._assessment_history) > self._max_history:
                self._assessment_history.pop(0)

    def _publish_event(self, event_type: str, payload: Dict[str, Any]):
        """Publish an event to the event bus."""
        try:
            event = Event(
                name=event_type,
                data=payload,
                source="safety_gate",
                priority=EventPriority.HIGH if "block" in event_type or "violation" in event_type else EventPriority.NORMAL
            )
            self._event_bus.publish(event)
        except Exception as e:
            logger.warning(f"Failed to publish event {event_type}: {e}")

    def get_assessment_history(self, limit: int = 100) -> List[SafetyAssessment]:
        """Get recent assessment history."""
        with self._lock:
            return self._assessment_history[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        """Get safety gate statistics."""
        with self._lock:
            total = len(self._assessment_history)
            if total == 0:
                return {"total_assessments": 0}

            actions = defaultdict(int)
            risk_levels = defaultdict(int)
            approvals = 0
            rejections = 0

            for a in self._assessment_history:
                actions[a.action.value] += 1
                risk_levels[a.risk_level.value] += 1
                if a.approved is True:
                    approvals += 1
                elif a.approved is False:
                    rejections += 1

            return {
                "total_assessments": total,
                "actions": dict(actions),
                "risk_levels": dict(risk_levels),
                "approvals": approvals,
                "rejections": rejections,
                "pending_approvals": len([
                    a for a in self._assessment_history
                    if a.requires_approval and a.approved is None
                ]),
                "policy_mode": self.policy.mode.value,
            }

    def set_mode(self, mode: SafetyGateMode):
        """Change the safety gate mode."""
        with self._lock:
            old_mode = self.policy.mode
            self.policy.mode = mode
            logger.info(f"Safety gate mode changed: {old_mode.value} -> {mode.value}")

        self._publish_event("safety.mode_changed", {
            "old_mode": old_mode.value,
            "new_mode": mode.value
        })


class SafetyViolationError(Exception):
    """Raised when an operation is blocked by the safety gate."""
    pass


# Convenience function for capabilities
def check_safety(
    operation: str,
    operation_type: str,
    context: Dict[str, Any] = None,
    safety_gate: Optional[SafetyGate] = None
) -> SafetyAssessment:
    """Convenience function to check safety."""
    gate = safety_gate or SafetyGate()
    return gate.check_and_enforce(operation, operation_type, context)