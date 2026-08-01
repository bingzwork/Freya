"""Human Oversight Enhancement - Interactive approval UI integration and review/override APIs.

This module implements the Human Oversight Enhancement capability (Phase 2+ enhancement):
- Interactive approval UI (terminal-based with arrow keys)
- Review history and decision override APIs
- Approval delegation and escalation
- Audit trail for human interventions
- Integration with existing approval gates
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set
import json
import uuid

from app.decision.history import DecisionHistory, DecisionRecord
from app.decision.models import DecisionContext, DecisionOption, DecisionResult, DecisionType, DecisionCategory

logger = logging.getLogger(__name__)


class ApprovalStatus(str, Enum):
    """Status of an approval request."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    OVERRIDDEN = "overridden"
    ESCALATED = "escalated"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class ApprovalPriority(str, Enum):
    """Priority of an approval request."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


@dataclass
class ApprovalRequest:
    """A request for human approval."""
    request_id: str
    decision_id: str
    decision_type: DecisionType
    risk_level: str
    confidence: float
    title: str
    description: str
    options: List[DecisionOption]
    recommended_option: Optional[DecisionOption]
    context: Dict[str, Any]
    status: ApprovalStatus = ApprovalStatus.PENDING
    priority: ApprovalPriority = ApprovalPriority.NORMAL
    requested_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    responded_at: Optional[str] = None
    responded_by: Optional[str] = None
    response: Optional[str] = None
    response_reason: str = ""
    override_reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_resolved(self) -> bool:
        return self.status in (ApprovalStatus.APPROVED, ApprovalStatus.REJECTED,
                               ApprovalStatus.OVERRIDDEN, ApprovalStatus.TIMED_OUT,
                               ApprovalStatus.CANCELLED)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "decision_id": self.decision_id,
            "decision_type": self.decision_type.value,
            "risk_level": self.risk_level,
            "confidence": self.confidence,
            "title": self.title,
            "description": self.description,
            "options": [{"name": o.name, "action": o.action, "description": o.description} for o in self.options],
            "recommended_option": self.recommended_option.name if self.recommended_option else None,
            "context": self.context,
            "status": self.status.value,
            "priority": self.priority.value,
            "requested_at": self.requested_at,
            "responded_at": self.responded_at,
            "responded_by": self.responded_by,
            "response": self.response,
            "response_reason": self.response_reason,
            "override_reason": self.override_reason,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ApprovalRequest":
        options = [DecisionOption(**o) for o in data.get("options", [])]
        recommended = None
        if data.get("recommended_option"):
            for o in options:
                if o.name == data["recommended_option"]:
                    recommended = o
                    break
        return cls(
            request_id=data["request_id"],
            decision_id=data["decision_id"],
            decision_type=DecisionType(data["decision_type"]),
            risk_level=data["risk_level"],
            confidence=data["confidence"],
            title=data["title"],
            description=data["description"],
            options=options,
            recommended_option=recommended,
            context=data["context"],
            status=ApprovalStatus(data["status"]),
            priority=ApprovalPriority(data["priority"]),
            requested_at=data["requested_at"],
            responded_at=data.get("responded_at"),
            responded_by=data.get("responded_by"),
            response=data.get("response"),
            response_reason=data.get("response_reason", ""),
            override_reason=data.get("override_reason", ""),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ApprovalRule:
    """A rule for automatic approval/routing."""
    rule_id: str
    name: str
    description: str
    conditions: Dict[str, Any]  # Conditions that trigger this rule
    action: str  # "auto_approve", "auto_reject", "require_approval", "escalate"
    priority: int = 100  # Lower = higher priority
    enabled: bool = True
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def matches(self, context: Dict[str, Any]) -> bool:
        """Check if rule matches context."""
        for key, expected in self.conditions.items():
            actual = context.get(key)
            if actual != expected:
                if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
                    if expected == 0 or abs(actual - expected) / abs(expected) > 0.1:
                        return False
                else:
                    return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "description": self.description,
            "conditions": self.conditions,
            "action": self.action,
            "priority": self.priority,
            "enabled": self.enabled,
            "created_at": self.created_at,
        }


class HumanOversightManager:
    """Manages human oversight and approval workflows.

    This class provides the Human Oversight Enhancement capability:
    1. Interactive terminal-based approval UI
    2. Approval request queue with priority handling
    3. Rule-based auto-approval/routing
    4. Decision override and review APIs
    5. Audit trail for all human interventions
    """

    def __init__(
        self,
        decision_history: DecisionHistory,
        workspace: str = ".",
        default_timeout_seconds: float = 300.0,
        enable_ui: bool = True,
    ):
        """Initialize the human oversight manager.

        Args:
            decision_history: DecisionHistory for context
            workspace: Workspace path for persistence
            default_timeout_seconds: Default timeout for approval requests
            enable_ui: Whether to enable interactive UI
        """
        self.decision_history = decision_history
        self.workspace = Path(workspace).resolve()
        self.default_timeout = default_timeout_seconds
        self.enable_ui = enable_ui

        self._lock = threading.RLock()
        self._requests: Dict[str, ApprovalRequest] = {}
        self._request_queue: List[str] = []  # request_ids in priority order
        self._rules: Dict[str, ApprovalRule] = {}
        self._audit_log: List[Dict[str, Any]] = []
        self._callbacks: List[Callable[[ApprovalRequest], None]] = []
        self._storage_path = self.workspace / "data" / "human_oversight.json"

        # UI state
        self._ui_active = False
        self._selected_index = 0

        # Default rules
        self._register_default_rules()

        self._load()

    def _register_default_rules(self) -> None:
        """Register default approval rules."""
        default_rules = [
            ApprovalRule(
                rule_id="rule_auto_approve_low_risk",
                name="Auto-approve low risk high confidence",
                description="Auto-approve low risk decisions with high confidence",
                conditions={"risk_level": "low", "confidence_min": 0.8},
                action="auto_approve",
                priority=10,
            ),
            ApprovalRule(
                rule_id="rule_auto_approve_info_risk",
                name="Auto-approve info risk",
                description="Auto-approve informational risk decisions",
                conditions={"risk_level": "info"},
                action="auto_approve",
                priority=20,
            ),
            ApprovalRule(
                rule_id="rule_require_approval_critical",
                name="Require approval for critical risk",
                description="Always require human approval for critical risk decisions",
                conditions={"risk_level": "critical"},
                action="require_approval",
                priority=30,
            ),
            ApprovalRule(
                rule_id="rule_require_approval_low_conf",
                name="Require approval for low confidence",
                description="Require approval when confidence is below threshold",
                conditions={"confidence_max": 0.5},
                action="require_approval",
                priority=40,
            ),
            ApprovalRule(
                rule_id="rule_escalate_high_risk_low_conf",
                name="Escalate high risk low confidence",
                description="Escalate high risk decisions with low confidence",
                conditions={"risk_level": "high", "confidence_max": 0.6},
                action="escalate",
                priority=5,
            ),
        ]

        for rule in default_rules:
            self._rules[rule.rule_id] = rule

    def _load(self) -> None:
        """Load oversight data from disk."""
        if not self._storage_path.exists():
            return
        try:
            with open(self._storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for r in data.get("requests", []):
                req = ApprovalRequest.from_dict(r)
                self._requests[req.request_id] = req
                if req.status == ApprovalStatus.PENDING:
                    self._request_queue.append(req.request_id)

            for rule in data.get("rules", []):
                self._rules[rule["rule_id"]] = ApprovalRule(**rule)

            self._audit_log = data.get("audit_log", [])

            logger.info(f"[HumanOversight] Loaded {len(self._requests)} requests, {len(self._rules)} rules")
        except Exception as e:
            logger.warning(f"[HumanOversight] Failed to load oversight data: {e}")

    def _save(self) -> None:
        """Save oversight data to disk."""
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._storage_path.with_suffix(".tmp")
        try:
            data = {
                "requests": [r.to_dict() for r in self._requests.values()],
                "rules": [r.to_dict() for r in self._rules.values()],
                "audit_log": self._audit_log,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            temp_path.replace(self._storage_path)
        except Exception as e:
            logger.error(f"[HumanOversight] Failed to save oversight data: {e}")

    # -------------------------------------------------------------------------
    # Public API - Approval Requests
    # -------------------------------------------------------------------------

    def request_approval(
        self,
        decision_id: str,
        decision_type: DecisionType,
        risk_level: str,
        confidence: float,
        title: str,
        description: str,
        options: List[DecisionOption],
        recommended_option: Optional[DecisionOption] = None,
        context: Optional[Dict[str, Any]] = None,
        timeout_seconds: Optional[float] = None,
        priority: ApprovalPriority = ApprovalPriority.NORMAL,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ApprovalRequest:
        """Create and queue an approval request.

        Args:
            decision_id: ID of the decision requiring approval
            decision_type: Type of decision
            risk_level: Risk level of the decision
            confidence: Confidence in the recommended option
            title: Short title for the request
            description: Detailed description
            options: Available options
            recommended_option: Recommended option (if any)
            context: Additional context
            timeout_seconds: Custom timeout
            priority: Request priority
            metadata: Additional metadata

        Returns:
            The created ApprovalRequest
        """
        with self._lock:
            request = ApprovalRequest(
                request_id=f"appr_{uuid.uuid4().hex[:12]}",
                decision_id=decision_id,
                decision_type=decision_type,
                risk_level=risk_level,
                confidence=confidence,
                title=title,
                description=description,
                options=options,
                recommended_option=recommended_option,
                context=context or {},
                priority=priority,
                metadata=metadata or {},
            )

            # Check rules for auto-action
            rule_action = self._evaluate_rules(request)
            if rule_action == "auto_approve":
                request.status = ApprovalStatus.APPROVED
                request.responded_at = datetime.now(timezone.utc).isoformat()
                request.responded_by = "system"
                request.response = "auto_approved"
                request.response_reason = "Matched auto-approval rule"
                self._log_audit("auto_approve", request)
            elif rule_action == "auto_reject":
                request.status = ApprovalStatus.REJECTED
                request.responded_at = datetime.now(timezone.utc).isoformat()
                request.responded_by = "system"
                request.response = "auto_rejected"
                request.response_reason = "Matched auto-rejection rule"
                self._log_audit("auto_reject", request)
            elif rule_action == "escalate":
                request.priority = ApprovalPriority.URGENT
                request.metadata["escalated"] = True

            # Add to queue if pending
            if request.status == ApprovalStatus.PENDING:
                self._insert_into_queue(request)
                self._notify_callbacks(request)

            self._requests[request.request_id] = request
            self._save()

            logger.info(f"[HumanOversight] Created approval request {request.request_id} for decision {decision_id} "
                       f"(status: {request.status.value})")

            return request

    def _evaluate_rules(self, request: ApprovalRequest) -> Optional[str]:
        """Evaluate approval rules against request."""
        matching_rules = [
            rule for rule in self._rules.values()
            if rule.enabled and rule.matches({
                "risk_level": request.risk_level,
                "confidence": request.confidence,
                "decision_type": request.decision_type.value,
                **request.context,
            })
        ]

        if not matching_rules:
            return None

        # Sort by priority
        matching_rules.sort(key=lambda r: r.priority)

        # Return action of highest priority rule
        return matching_rules[0].action

    def _insert_into_queue(self, request: ApprovalRequest) -> None:
        """Insert request into priority queue."""
        priority_order = {
            ApprovalPriority.URGENT: 0,
            ApprovalPriority.HIGH: 1,
            ApprovalPriority.NORMAL: 2,
            ApprovalPriority.LOW: 3,
        }

        insert_idx = 0
        for i, req_id in enumerate(self._request_queue):
            existing = self._requests.get(req_id)
            if existing and priority_order[request.priority] < priority_order[existing.priority]:
                insert_idx = i
                break
            insert_idx = i + 1

        self._request_queue.insert(insert_idx, request.request_id)

    def get_pending_requests(self) -> List[ApprovalRequest]:
        """Get all pending approval requests."""
        with self._lock:
            return [self._requests[rid] for rid in self._request_queue if self._requests[rid].status == ApprovalStatus.PENDING]

    def get_request(self, request_id: str) -> Optional[ApprovalRequest]:
        """Get an approval request by ID."""
        with self._lock:
            return self._requests.get(request_id)

    def respond_to_request(
        self,
        request_id: str,
        response: str,
        reason: str = "",
        responded_by: str = "user",
        override: bool = False,
    ) -> bool:
        """Respond to an approval request.

        Args:
            request_id: ID of the request
            response: Response ("approve", "reject", "override")
            reason: Reason for response
            responded_by: Who responded
            override: Whether this is an override (bypasses normal flow)

        Returns:
            True if request was found and updated
        """
        with self._lock:
            request = self._requests.get(request_id)
            if not request:
                return False

            if request.status != ApprovalStatus.PENDING and not override:
                return False

            old_status = request.status
            request.responded_at = datetime.now(timezone.utc).isoformat()
            request.responded_by = responded_by
            request.response_reason = reason

            if response == "approve":
                request.status = ApprovalStatus.APPROVED
                request.response = "approved"
            elif response == "reject":
                request.status = ApprovalStatus.REJECTED
                request.response = "rejected"
            elif response == "override":
                request.status = ApprovalStatus.OVERRIDDEN
                request.response = "overridden"
                request.override_reason = reason
            else:
                return False

            # Remove from queue
            if request_id in self._request_queue:
                self._request_queue.remove(request_id)

            self._log_audit(f"respond_{response}", request, {"old_status": old_status.value})
            self._save()

            logger.info(f"[HumanOversight] Request {request_id} {response}d by {responded_by}")
            return True

    def cancel_request(self, request_id: str, reason: str = "") -> bool:
        """Cancel a pending approval request."""
        with self._lock:
            request = self._requests.get(request_id)
            if not request or request.status != ApprovalStatus.PENDING:
                return False

            request.status = ApprovalStatus.CANCELLED
            request.responded_at = datetime.now(timezone.utc).isoformat()
            request.responded_by = "system"
            request.response = "cancelled"
            request.response_reason = reason

            if request_id in self._request_queue:
                self._request_queue.remove(request_id)

            self._log_audit("cancel", request, {"reason": reason})
            self._save()
            return True

    def escalate_request(self, request_id: str, reason: str = "") -> bool:
        """Escalate a request to urgent priority."""
        with self._lock:
            request = self._requests.get(request_id)
            if not request or request.status != ApprovalStatus.PENDING:
                return False

            request.priority = ApprovalPriority.URGENT
            request.metadata["escalated"] = True
            request.metadata["escalation_reason"] = reason

            # Re-queue at front
            if request_id in self._request_queue:
                self._request_queue.remove(request_id)
            self._request_queue.insert(0, request_id)

            self._log_audit("escalate", request, {"reason": reason})
            self._save()
            return True

    # -------------------------------------------------------------------------
    # Public API - Rules
    # -------------------------------------------------------------------------

    def add_rule(self, rule: ApprovalRule) -> None:
        """Add an approval rule."""
        with self._lock:
            self._rules[rule.rule_id] = rule
            self._save()

    def remove_rule(self, rule_id: str) -> bool:
        """Remove an approval rule."""
        with self._lock:
            if rule_id in self._rules:
                del self._rules[rule_id]
                self._save()
                return True
            return False

    def get_rules(self) -> List[ApprovalRule]:
        """Get all approval rules."""
        with self._lock:
            return sorted(self._rules.values(), key=lambda r: r.priority)

    def update_rule(self, rule_id: str, **updates) -> bool:
        """Update a rule's properties."""
        with self._lock:
            rule = self._rules.get(rule_id)
            if not rule:
                return False

            for key, value in updates.items():
                if hasattr(rule, key):
                    setattr(rule, key, value)

            self._save()
            return True

    # -------------------------------------------------------------------------
    # Public API - Review & Override
    # -------------------------------------------------------------------------

    def review_decision(self, decision_id: str) -> Optional[Dict[str, Any]]:
        """Review a decision and its approval history."""
        with self._lock:
            record = self.decision_history._records.get(decision_id)
            if not record:
                return None

            # Find related approval requests
            related_requests = [
                r for r in self._requests.values()
                if r.decision_id == decision_id
            ]

            return {
                "decision": {
                    "decision_id": record.decision_id,
                    "decision_type": record.decision_type.value,
                    "category": record.category.value,
                    "risk_level": record.risk_level,
                    "confidence": record.confidence,
                    "chosen_option": record.chosen_option_name,
                    "rationale": record.rationale,
                    "executed": record.executed,
                    "actual_success": record.actual_success,
                    "timestamp": record.timestamp,
                },
                "approval_requests": [r.to_dict() for r in related_requests],
                "audit_entries": [
                    entry for entry in self._audit_log
                    if entry.get("decision_id") == decision_id
                ],
            }

    def override_decision(
        self,
        decision_id: str,
        new_option: DecisionOption,
        reason: str,
        overridden_by: str = "user",
    ) -> bool:
        """Override a decision's chosen option (post-execution correction)."""
        with self._lock:
            record = self.decision_history._records.get(decision_id)
            if not record:
                return False

            old_option = record.chosen_option_name
            record.chosen_option_name = new_option.name
            record.chosen_option_action = new_option.action
            record.metadata = record.metadata or {}
            record.metadata["overridden"] = True
            record.metadata["override_reason"] = reason
            record.metadata["overridden_by"] = overridden_by
            record.metadata["override_at"] = datetime.now(timezone.utc).isoformat()
            record.metadata["original_option"] = old_option

            self._log_audit("override_decision", {
                "decision_id": decision_id,
                "old_option": old_option,
                "new_option": new_option.name,
                "reason": reason,
                "overridden_by": overridden_by,
            })

            self.decision_history._save()
            return True

    def get_audit_log(
        self,
        decision_id: Optional[str] = None,
        action_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get audit log entries."""
        with self._lock:
            entries = self._audit_log

            if decision_id:
                entries = [e for e in entries if e.get("decision_id") == decision_id]
            if action_type:
                entries = [e for e in entries if e.get("action") == action_type]

            return entries[-limit:]

    # -------------------------------------------------------------------------
    # Public API - Interactive UI
    # -------------------------------------------------------------------------

    def run_approval_ui(self) -> None:
        """Run the interactive terminal approval UI."""
        if not self.enable_ui:
            logger.warning("[HumanOversight] UI not enabled")
            return

        try:
            import sys
            import termios
            import tty
        except ImportError:
            logger.warning("[HumanOversight] Terminal UI not available (requires termios/tty)")
            return

        self._ui_active = True
        self._selected_index = 0

        try:
            self._run_ui_loop()
        finally:
            self._ui_active = False

    def _run_ui_loop(self) -> None:
        """Main UI loop."""
        import sys

        old_settings = termios.tcgetattr(sys.stdin)
        try:
            tty.setcbreak(sys.stdin.fileno())

            while self._ui_active:
                self._render_ui()

                # Check for input with timeout
                if self._check_input():
                    key = sys.stdin.read(1)
                    if key == '\x1b':  # Escape sequence
                        key += sys.stdin.read(2)
                        self._handle_arrow_key(key)
                    elif key in ('q', 'Q'):
                        break
                    elif key in ('\r', '\n'):
                        self._handle_enter()
                    elif key.isdigit():
                        self._handle_number_key(int(key))

                time.sleep(0.1)
        finally:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)

    def _check_input(self) -> bool:
        """Check if input is available (non-blocking)."""
        import select
        import sys
        return select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], [])

    def _render_ui(self) -> None:
        """Render the UI."""
        import sys

        # Clear screen
        sys.stdout.write('\033[2J\033[H')

        pending = self.get_pending_requests()

        sys.stdout.write("=" * 80 + "\n")
        sys.stdout.write("  HUMAN OVERSIGHT - APPROVAL QUEUE\n")
        sys.stdout.write("=" * 80 + "\n")
        sys.stdout.write(f"  Pending: {len(pending)}  |  Press Q to quit\n\n")

        if not pending:
            sys.stdout.write("  No pending approval requests.\n")
        else:
            for i, req in enumerate(pending):
                prefix = "▶ " if i == self._selected_index else "  "
                status_symbol = {"pending": "⏳", "high": "🔥", "urgent": "🚨"}.get(req.priority.value, "⏳")
                sys.stdout.write(f"{prefix}{status_symbol} [{req.priority.value.upper()}] {req.title}\n")
                sys.stdout.write(f"    ID: {req.request_id}  |  Decision: {req.decision_id}\n")
                sys.stdout.write(f"    Risk: {req.risk_level}  |  Confidence: {req.confidence:.0%}\n")
                sys.stdout.write(f"    {req.description[:70]}...\n\n")

        sys.stdout.write("-" * 80 + "\n")
        sys.stdout.write("  Controls: ↑/↓ Navigate  |  1=Approve  2=Reject  3=Override  Enter=Details\n")
        sys.stdout.flush()

    def _handle_arrow_key(self, key: str) -> None:
        """Handle arrow key navigation."""
        pending = self.get_pending_requests()
        if not pending:
            return

        if key == '\x1b[A':  # Up
            self._selected_index = max(0, self._selected_index - 1)
        elif key == '\x1b[B':  # Down
            self._selected_index = min(len(pending) - 1, self._selected_index + 1)

    def _handle_number_key(self, num: int) -> None:
        """Handle number key for quick actions."""
        pending = self.get_pending_requests()
        if 0 <= self._selected_index < len(pending):
            req = pending[self._selected_index]
            if num == 1:
                self.respond_to_request(req.request_id, "approve", "Approved via UI")
            elif num == 2:
                self.respond_to_request(req.request_id, "reject", "Rejected via UI")
            elif num == 3:
                self.respond_to_request(req.request_id, "override", "Overridden via UI", override=True)

    def _handle_enter(self) -> None:
        """Handle Enter key - show details."""
        pending = self.get_pending_requests()
        if 0 <= self._selected_index < len(pending):
            self._show_request_details(pending[self._selected_index])

    def _show_request_details(self, request: ApprovalRequest) -> None:
        """Show detailed view of a request."""
        import sys

        old_settings = termios.tcgetattr(sys.stdin)
        try:
            tty.setcbreak(sys.stdin.fileno())

            while True:
                sys.stdout.write('\033[2J\033[H')
                sys.stdout.write(f"  APPROVAL REQUEST DETAILS: {request.request_id}\n")
                sys.stdout.write("=" * 80 + "\n\n")

                sys.stdout.write(f"  Title:       {request.title}\n")
                sys.stdout.write(f"  Decision:    {request.decision_id} ({request.decision_type.value})\n")
                sys.stdout.write(f"  Risk Level:  {request.risk_level}\n")
                sys.stdout.write(f"  Confidence:  {request.confidence:.0%}\n")
                sys.stdout.write(f"  Priority:    {request.priority.value}\n")
                sys.stdout.write(f"  Status:      {request.status.value}\n")
                sys.stdout.write(f"  Requested:   {request.requested_at}\n\n")

                sys.stdout.write(f"  Description:\n    {request.description}\n\n")

                sys.stdout.write("  Options:\n")
                for i, opt in enumerate(request.options):
                    rec = " ★ RECOMMENDED" if request.recommended_option and opt.name == request.recommended_option.name else ""
                    sys.stdout.write(f"    {i+1}. {opt.name}{rec}\n")
                    sys.stdout.write(f"       Action: {opt.action}\n")
                    sys.stdout.write(f"       {opt.description}\n\n")

                sys.stdout.write("-" * 80 + "\n")
                sys.stdout.write("  [A]pprove  [R]eject  [O]verride  [E]scalate  [B]ack\n")

                key = sys.stdin.read(1).lower()
                if key == 'a':
                    self.respond_to_request(request.request_id, "approve", "Approved from details view")
                    break
                elif key == 'r':
                    self.respond_to_request(request.request_id, "reject", "Rejected from details view")
                    break
                elif key == 'o':
                    reason = input("Override reason: ")
                    self.respond_to_request(request.request_id, "override", reason, override=True)
                    break
                elif key == 'e':
                    reason = input("Escalation reason: ")
                    self.escalate_request(request.request_id, reason)
                elif key == 'b' or key == '\x1b':  # Escape or B
                    break
        finally:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)

    # -------------------------------------------------------------------------
    # Callbacks
    # -------------------------------------------------------------------------

    def register_callback(self, callback: Callable[[ApprovalRequest], None]) -> None:
        """Register a callback for new approval requests."""
        with self._lock:
            self._callbacks.append(callback)

    def unregister_callback(self, callback: Callable[[ApprovalRequest], None]) -> bool:
        """Unregister a callback."""
        with self._lock:
            if callback in self._callbacks:
                self._callbacks.remove(callback)
                return True
            return False

    def _notify_callbacks(self, request: ApprovalRequest) -> None:
        """Notify all callbacks of new request."""
        for callback in self._callbacks:
            try:
                callback(request)
            except Exception as e:
                logger.warning(f"[HumanOversight] Callback error: {e}")

    # -------------------------------------------------------------------------
    # Audit Logging
    # -------------------------------------------------------------------------

    def _log_audit(self, action: str, request: ApprovalRequest, extra: Optional[Dict] = None) -> None:
        """Log an audit entry."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "request_id": request.request_id,
            "decision_id": request.decision_id,
            "user": request.responded_by,
            "extra": extra or {},
        }
        self._audit_log.append(entry)
        # Keep last 10000 entries
        if len(self._audit_log) > 10000:
            self._audit_log = self._audit_log[-10000:]


# Convenience function
def create_human_oversight_manager(
    decision_history: DecisionHistory,
    workspace: str = ".",
    default_timeout_seconds: float = 300.0,
    enable_ui: bool = True,
) -> HumanOversightManager:
    """Create a HumanOversightManager instance with standard configuration."""
    return HumanOversightManager(
        decision_history=decision_history,
        workspace=workspace,
        default_timeout_seconds=default_timeout_seconds,
        enable_ui=enable_ui,
    )