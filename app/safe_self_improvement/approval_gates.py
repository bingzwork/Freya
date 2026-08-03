"""
Approval Gates with DecisionManager Integration.

Manages human approval gates for safe self-improvement operations.
Integrates with DecisionManager for structured approval workflows.
"""

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Callable
from enum import Enum
import uuid

from app.safe_self_improvement.models import (
    ImprovementCandidate,
    FileModification,
    ApprovalRequest,
    ApprovalStatus,
    RiskLevel,
)
from app.decision.manager import DecisionManager
from app.decision.models import DecisionContext, DecisionType, DecisionCategory
from app.core.logger import logger


class ApprovalDecision(Enum):
    """Outcome of an approval decision."""

    APPROVED = "approved"
    REJECTED = "rejected"
    PENDING = "pending"
    TIMED_OUT = "timed_out"
    AUTO_APPROVED = "auto_approved"
    OVERRIDDEN = "overridden"


@dataclass
class ApprovalRule:
    """Rule for determining approval requirements."""

    name: str
    description: str
    condition: Callable[[ImprovementCandidate], bool]
    required_approvers: int = 1
    timeout_seconds: float = 300.0
    auto_approve: bool = False
    escalation_seconds: Optional[float] = None
    escalation_approvers: List[str] = field(default_factory=list)


class ApprovalGateManager:
    """
    Manages approval gates for self-improvement operations.

    Determines when approval is required, routes requests to approvers,
    and integrates with DecisionManager for structured decision making.
    """

    def __init__(
        self,
        decision_manager: Optional[DecisionManager] = None,
        default_timeout_seconds: float = 300.0,
        auto_approve_low_risk: bool = True,
        max_pending_requests: int = 50,
    ):
        self.decision_manager = decision_manager or DecisionManager()
        self.default_timeout_seconds = default_timeout_seconds
        self.auto_approve_low_risk = auto_approve_low_risk
        self.max_pending_requests = max_pending_requests

        self._lock = threading.RLock()
        self._pending_requests: Dict[str, ApprovalRequest] = {}
        self._approval_history: List[ApprovalRequest] = []
        self._rules: List[ApprovalRule] = []
        self._approvers: Dict[str, Dict[str, Any]] = {}  # approver_id -> info
        self._callbacks: Dict[str, List[Callable]] = {
            "on_request": [],
            "on_approved": [],
            "on_rejected": [],
            "on_timeout": [],
            "on_auto_approved": [],
        }
        self._stats = {
            "total_requests": 0,
            "approved": 0,
            "rejected": 0,
            "auto_approved": 0,
            "timed_out": 0,
            "overridden": 0,
        }

        self._setup_default_rules()

    def _setup_default_rules(self) -> None:
        """Set up default approval rules."""
        self._rules = [
            ApprovalRule(
                name="high_risk",
                description="High risk improvements require approval",
                condition=lambda c: c.estimated_risk >= RiskLevel.HIGH,
                required_approvers=2,
                timeout_seconds=600.0,
            ),
            ApprovalRule(
                name="critical_risk",
                description="Critical risk improvements require senior approval",
                condition=lambda c: c.estimated_risk >= RiskLevel.CRITICAL,
                required_approvers=2,
                timeout_seconds=1200.0,
                escalation_seconds=300.0,
                escalation_approvers=["senior_reviewer", "architect"],
            ),
            ApprovalRule(
                name="many_files",
                description="Changes to many files require approval",
                condition=lambda c: len(c.modifications) > 5,
                required_approvers=1,
                timeout_seconds=300.0,
            ),
            ApprovalRule(
                name="security_changes",
                description="Security-related changes require approval",
                condition=lambda c: c.category.value == "security",
                required_approvers=1,
                timeout_seconds=300.0,
            ),
            ApprovalRule(
                name="architecture_changes",
                description="Architecture changes require approval",
                condition=lambda c: c.category.value == "architecture",
                required_approvers=2,
                timeout_seconds=600.0,
            ),
            ApprovalRule(
                name="low_confidence",
                description="Low confidence changes require approval",
                condition=lambda c: c.confidence < 0.7,
                required_approvers=1,
                timeout_seconds=300.0,
            ),
            ApprovalRule(
                name="delete_operations",
                description="Delete operations require approval",
                condition=lambda c: any(
                    m.modification_type.value == "delete" for m in c.modifications
                ),
                required_approvers=1,
                timeout_seconds=300.0,
            ),
        ]

    def check_approval_required(
        self, candidate: ImprovementCandidate
    ) -> tuple[bool, List[ApprovalRule], Optional[ApprovalRule]]:
        """
        Check if approval is required for a candidate.

        Returns:
            tuple: (requires_approval, matching_rules, auto_approve_rule)
        """
        matching_rules = []
        auto_approve_rule = None

        for rule in self._rules:
            try:
                if rule.condition(candidate):
                    matching_rules.append(rule)
                    if rule.auto_approve and auto_approve_rule is None:
                        auto_approve_rule = rule
            except Exception as e:
                logger.error(f"[ApprovalGateManager] Rule {rule.name} error: {e}")

        # Check auto-approval for low risk
        if self.auto_approve_low_risk and candidate.estimated_risk <= RiskLevel.LOW:
            # Create implicit auto-approve rule
            auto_approve_rule = ApprovalRule(
                name="auto_approve_low_risk",
                description="Auto-approve low risk improvements",
                condition=lambda c: c.estimated_risk <= RiskLevel.LOW,
                auto_approve=True,
            )

        requires_approval = len(matching_rules) > 0 and auto_approve_rule is None
        return requires_approval, matching_rules, auto_approve_rule

    def request_approval(
        self,
        candidate: ImprovementCandidate,
        requested_by: str = "system",
        risk_assessment: Optional[Dict[str, Any]] = None,
    ) -> ApprovalRequest:
        """
        Request approval for an improvement candidate.

        If auto-approval applies, returns immediately with AUTO_APPROVED status.
        """
        with self._lock:
            if len(self._pending_requests) >= self.max_pending_requests:
                raise RuntimeError("Max pending approval requests reached")

            # Check approval requirements
            requires_approval, matching_rules, auto_approve_rule = self.check_approval_required(candidate)

            # Create approval request
            request = ApprovalRequest(
                id=f"appr_{uuid.uuid4().hex[:8]}",
                candidate_id=candidate.id,
                candidate_title=candidate.title,
                modifications=candidate.modifications,
                risk_assessment=risk_assessment or {},
                requested_by=requested_by,
                auto_approval_eligible=auto_approve_rule is not None,
            )

            if not requires_approval or auto_approve_rule:
                request.status = ApprovalStatus.AUTO_APPROVED
                request.responded_at = datetime.now(timezone.utc).isoformat()
                request.responded_by = "auto_approver"
                request.response_reason = "Auto-approved based on risk level"
                self._trigger_callbacks("on_auto_approved", request)
                self._stats["auto_approved"] += 1
            else:
                request.status = ApprovalStatus.PENDING
                self._pending_requests[request.id] = request
                self._stats["total_requests"] += 1
                self._trigger_callbacks("on_request", request)

            return request

    def approve(
        self,
        request_id: str,
        approved_by: str,
        reason: str = "",
    ) -> tuple[bool, str]:
        """Approve a pending request."""
        with self._lock:
            request = self._pending_requests.get(request_id)
            if not request:
                return False, "Request not found"

            if request.status != ApprovalStatus.PENDING:
                return False, f"Request not pending: {request.status.value}"

            # Check if we have enough approvers
            required = self._get_required_approvers(request)
            # For simplicity, single approval for now
            # In production, track multiple approvals

            request.status = ApprovalStatus.APPROVED
            request.responded_at = datetime.now(timezone.utc).isoformat()
            request.responded_by = approved_by
            request.response_reason = reason

            self._complete_request(request_id)
            self._trigger_callbacks("on_approved", request)
            self._stats["approved"] += 1

            return True, "Approved"

    def reject(
        self,
        request_id: str,
        rejected_by: str,
        reason: str = "",
    ) -> tuple[bool, str]:
        """Reject a pending request."""
        with self._lock:
            request = self._pending_requests.get(request_id)
            if not request:
                return False, "Request not found"

            if request.status != ApprovalStatus.PENDING:
                return False, f"Request not pending: {request.status.value}"

            request.status = ApprovalStatus.REJECTED
            request.responded_at = datetime.now(timezone.utc).isoformat()
            request.responded_by = rejected_by
            request.response_reason = reason

            self._complete_request(request_id)
            self._trigger_callbacks("on_rejected", request)
            self._stats["rejected"] += 1

            return True, "Rejected"

    def override(
        self,
        request_id: str,
        overridden_by: str,
        reason: str = "",
    ) -> tuple[bool, str]:
        """Override a request (emergency approval)."""
        with self._lock:
            request = self._pending_requests.get(request_id)
            if not request:
                return False, "Request not found"

            request.status = ApprovalStatus.OVERRIDDEN
            request.responded_at = datetime.now(timezone.utc).isoformat()
            request.responded_by = overridden_by
            request.response_reason = f"OVERRIDE: {reason}"

            self._complete_request(request_id)
            self._stats["overridden"] += 1

            return True, "Overridden"

    def check_timeout(self, request_id: str) -> bool:
        """Check if a request has timed out."""
        with self._lock:
            request = self._pending_requests.get(request_id)
            if not request or request.status != ApprovalStatus.PENDING:
                return False

            requested_at = datetime.fromisoformat(request.requested_at)
            elapsed = (datetime.now(timezone.utc) - requested_at).total_seconds()

            # Find matching rule for timeout
            timeout = self.default_timeout_seconds
            for rule in self._rules:
                try:
                    if rule.condition(ImprovementCandidate(id=request.candidate_id, modifications=request.modifications)):
                        timeout = rule.timeout_seconds
                        break
                except Exception:
                    pass

            if elapsed >= timeout:
                request.status = ApprovalStatus.TIMED_OUT
                request.responded_at = datetime.now(timezone.utc).isoformat()
                request.responded_by = "system"
                request.response_reason = f"Timed out after {timeout}s"

                self._complete_request(request_id)
                self._trigger_callbacks("on_timeout", request)
                self._stats["timed_out"] += 1
                return True

            return False

    def process_timeouts(self) -> int:
        """Process all timed out requests. Returns count of timed out requests."""
        with self._lock:
            timed_out = 0
            for request_id in list(self._pending_requests.keys()):
                if self.check_timeout(request_id):
                    timed_out += 1
            return timed_out

    def _get_required_approvers(self, request: ApprovalRequest) -> int:
        """Get required approvers for a request."""
        candidate = ImprovementCandidate(
            id=request.candidate_id,
            modifications=request.modifications,
        )
        _, matching_rules, _ = self.check_approval_required(candidate)
        return max((r.required_approvers for r in matching_rules), default=1)

    def _complete_request(self, request_id: str) -> None:
        """Move request from pending to history."""
        if request_id in self._pending_requests:
            request = self._pending_requests.pop(request_id)
            self._approval_history.append(request)
            # Keep last 1000
            if len(self._approval_history) > 1000:
                self._approval_history = self._approval_history[-1000:]

    def get_request(self, request_id: str) -> Optional[ApprovalRequest]:
        """Get an approval request by ID."""
        with self._lock:
            if request_id in self._pending_requests:
                return self._pending_requests[request_id]
            for req in self._approval_history:
                if req.id == request_id:
                    return req
            return None

    def get_pending_requests(self) -> List[ApprovalRequest]:
        """Get all pending approval requests."""
        with self._lock:
            return list(self._pending_requests.values())

    def get_history(self, limit: int = 100) -> List[ApprovalRequest]:
        """Get approval history."""
        with self._lock:
            return self._approval_history[-limit:]

    def register_approver(
        self,
        approver_id: str,
        name: str,
        roles: List[str] = None,
        contact: str = "",
    ) -> None:
        """Register an approver."""
        with self._lock:
            self._approvers[approver_id] = {
                "id": approver_id,
                "name": name,
                "roles": roles or [],
                "contact": contact,
                "registered_at": datetime.now(timezone.utc).isoformat(),
            }

    def get_approvers(self) -> List[Dict[str, Any]]:
        """Get all registered approvers."""
        with self._lock:
            return list(self._approvers.values())

    def register_callback(self, event: str, callback: Callable) -> None:
        """Register a callback for approval events."""
        with self._lock:
            if event in self._callbacks:
                self._callbacks[event].append(callback)

    def _trigger_callbacks(self, event: str, request: ApprovalRequest) -> None:
        """Trigger callbacks for an event."""
        for callback in self._callbacks.get(event, []):
            try:
                callback(request)
            except Exception as e:
                logger.error(f"[ApprovalGateManager] Callback error: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get approval statistics."""
        with self._lock:
            return {
                **self._stats,
                "pending_count": len(self._pending_requests),
                "history_count": len(self._approval_history),
            }

    def add_rule(self, rule: ApprovalRule) -> None:
        """Add a custom approval rule."""
        with self._lock:
            self._rules.append(rule)

    def remove_rule(self, name: str) -> bool:
        """Remove an approval rule by name."""
        with self._lock:
            for i, rule in enumerate(self._rules):
                if rule.name == name:
                    self._rules.pop(i)
                    return True
            return False


def create_default_approval_gate_manager(
    decision_manager: Optional[DecisionManager] = None,
) -> ApprovalGateManager:
    """Create an ApprovalGateManager with sensible defaults."""
    return ApprovalGateManager(decision_manager=decision_manager)