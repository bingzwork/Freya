"""
Safe Self-Improvement Policies.

Defines and enforces policies for autonomous self-improvement operations.
Policies control what improvements are allowed, under what conditions, and how they are handled.
"""

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable, Set
from enum import Enum
import json

from app.safe_self_improvement.models import (
    ImprovementCandidate,
    FileModification,
    ImprovementCategory,
    RiskLevel,
)
from app.core.logger import logger


class PolicyAction(Enum):
    """Actions to take when a policy matches."""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"
    REQUIRE_VERIFICATION = "require_verification"
    LIMIT_SCOPE = "limit_scope"
    REDUCE_RISK = "reduce_risk"
    LOG_ONLY = "log_only"


class PolicyScope(Enum):
    """Scope of policy application."""

    GLOBAL = "global"
    CATEGORY = "category"
    FILE_PATTERN = "file_pattern"
    SOURCE = "source"
    CUSTOM = "custom"


@dataclass
class PolicyCondition:
    """Condition for policy matching."""

    field: str  # e.g., "estimated_risk", "category", "source", "file_path"
    operator: str  # eq, ne, gt, lt, gte, lte, in, not_in, contains, matches
    value: Any

    def evaluate(self, candidate: ImprovementCandidate) -> bool:
        """Evaluate condition against a candidate."""
        # Get field value
        if self.field == "estimated_risk":
            field_value = candidate.estimated_risk
        elif self.field == "category":
            field_value = candidate.category
        elif self.field == "source":
            field_value = candidate.source
        elif self.field == "confidence":
            field_value = candidate.confidence
        elif self.field == "estimated_impact":
            field_value = candidate.estimated_impact
        elif self.field == "estimated_effort":
            field_value = candidate.estimated_effort
        elif self.field == "file_count":
            field_value = len(candidate.modifications)
        elif self.field == "total_lines":
            field_value = sum(len((m.new_content or "").splitlines()) for m in candidate.modifications)
        elif self.field == "has_delete":
            field_value = any(m.modification_type.value == "delete" for m in candidate.modifications)
        elif self.field == "affected_files":
            field_value = candidate.affected_files
        else:
            # Try to get from metadata
            field_value = candidate.metadata.get(self.field)

        # Apply operator
        return self._compare(field_value, self.operator, self.value)

    def _compare(self, field_value: Any, operator: str, target_value: Any) -> bool:
        """Compare field value with target using operator."""
        # Handle enum values
        if hasattr(field_value, 'value'):
            field_value = field_value.value
        if hasattr(target_value, 'value'):
            target_value = target_value.value

        if operator == "eq":
            return field_value == target_value
        elif operator == "ne":
            return field_value != target_value
        elif operator == "gt":
            return field_value > target_value
        elif operator == "lt":
            return field_value < target_value
        elif operator == "gte":
            return field_value >= target_value
        elif operator == "lte":
            return field_value <= target_value
        elif operator == "in":
            return field_value in target_value if isinstance(target_value, (list, set)) else False
        elif operator == "not_in":
            return field_value not in target_value if isinstance(target_value, (list, set)) else True
        elif operator == "contains":
            return target_value in field_value if isinstance(field_value, (str, list, set)) else False
        elif operator == "matches":
            import fnmatch
            return fnmatch.fnmatch(str(field_value), str(target_value))
        return False


@dataclass
class SelfImprovementPolicy:
    """A single self-improvement policy."""

    id: str
    name: str
    description: str
    scope: PolicyScope
    conditions: List[PolicyCondition]
    action: PolicyAction
    priority: int = 0  # Higher priority = evaluated first
    enabled: bool = True
    tags: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    created_by: str = "system"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def matches(self, candidate: ImprovementCandidate) -> bool:
        """Check if policy matches a candidate."""
        if not self.enabled:
            return False
        return all(cond.evaluate(candidate) for cond in self.conditions)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "scope": self.scope.value,
            "conditions": [
                {"field": c.field, "operator": c.operator, "value": c.value}
                for c in self.conditions
            ],
            "action": self.action.value,
            "priority": self.priority,
            "enabled": self.enabled,
            "tags": self.tags,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SelfImprovementPolicy":
        conditions = [
            PolicyCondition(field=c["field"], operator=c["operator"], value=c["value"])
            for c in data.get("conditions", [])
        ]
        return cls(
            id=data["id"],
            name=data["name"],
            description=data["description"],
            scope=PolicyScope(data["scope"]),
            conditions=conditions,
            action=PolicyAction(data["action"]),
            priority=data.get("priority", 0),
            enabled=data.get("enabled", True),
            tags=data.get("tags", []),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            created_by=data.get("created_by", "system"),
            metadata=data.get("metadata", {}),
        )


class PolicyEngine:
    """
    Engine for evaluating and enforcing self-improvement policies.

    Policies are evaluated in priority order. First matching policy determines action.
    """

    def __init__(
        self,
        storage_path: Optional[str] = None,
        default_action: PolicyAction = PolicyAction.ALLOW,
    ):
        self.storage_path = Path(storage_path) if storage_path else None
        self.default_action = default_action

        self._lock = threading.RLock()
        self._policies: Dict[str, SelfImprovementPolicy] = {}
        self._evaluation_history: List[Dict[str, Any]] = []
        self._stats = {
            "evaluations": 0,
            "allowed": 0,
            "denied": 0,
            "required_approval": 0,
            "required_verification": 0,
        }

        # Load default policies
        self._setup_default_policies()

        # Load from storage
        if self.storage_path:
            self._load_policies()

    def _setup_default_policies(self) -> None:
        """Set up default safety policies."""
        default_policies = [
            # Deny critical risk without explicit override
            SelfImprovementPolicy(
                id="deny_critical_risk",
                name="Deny Critical Risk",
                description="Deny improvements with critical risk level",
                scope=PolicyScope.GLOBAL,
                conditions=[
                    PolicyCondition("estimated_risk", "eq", RiskLevel.CRITICAL),
                ],
                action=PolicyAction.DENY,
                priority=100,
                tags=["safety", "risk"],
            ),
            # Require approval for high risk
            SelfImprovementPolicy(
                id="require_approval_high_risk",
                name="Require Approval for High Risk",
                description="High risk improvements require human approval",
                scope=PolicyScope.GLOBAL,
                conditions=[
                    PolicyCondition("estimated_risk", "eq", RiskLevel.HIGH),
                ],
                action=PolicyAction.REQUIRE_APPROVAL,
                priority=90,
                tags=["approval", "risk"],
            ),
            # Require verification for medium+ risk
            SelfImprovementPolicy(
                id="require_verification_medium_risk",
                name="Require Verification for Medium Risk",
                description="Medium and higher risk improvements require verification",
                scope=PolicyScope.GLOBAL,
                conditions=[
                    PolicyCondition("estimated_risk", "gte", RiskLevel.MEDIUM),
                ],
                action=PolicyAction.REQUIRE_VERIFICATION,
                priority=80,
                tags=["verification", "risk"],
            ),
            # Deny delete operations by default
            SelfImprovementPolicy(
                id="deny_delete_operations",
                name="Deny Delete Operations",
                description="Deny improvements that delete files",
                scope=PolicyScope.GLOBAL,
                conditions=[
                    PolicyCondition("has_delete", "eq", True),
                ],
                action=PolicyAction.DENY,
                priority=95,
                tags=["safety", "delete"],
            ),
            # Limit scope for large changes
            SelfImprovementPolicy(
                id="limit_large_changes",
                name="Limit Large Changes",
                description="Limit improvements affecting many files",
                scope=PolicyScope.GLOBAL,
                conditions=[
                    PolicyCondition("file_count", "gt", 10),
                ],
                action=PolicyAction.LIMIT_SCOPE,
                priority=70,
                tags=["scope", "size"],
            ),
            # Security changes require approval
            SelfImprovementPolicy(
                id="require_approval_security",
                name="Require Approval for Security Changes",
                description="Security category improvements require approval",
                scope=PolicyScope.CATEGORY,
                conditions=[
                    PolicyCondition("category", "eq", ImprovementCategory.SECURITY),
                ],
                action=PolicyAction.REQUIRE_APPROVAL,
                priority=85,
                tags=["approval", "security"],
            ),
            # Architecture changes require verification
            SelfImprovementPolicy(
                id="require_verification_architecture",
                name="Require Verification for Architecture Changes",
                description="Architecture category improvements require verification",
                scope=PolicyScope.CATEGORY,
                conditions=[
                    PolicyCondition("category", "eq", ImprovementCategory.ARCHITECTURE),
                ],
                action=PolicyAction.REQUIRE_VERIFICATION,
                priority=75,
                tags=["verification", "architecture"],
            ),
            # Low confidence requires approval
            SelfImprovementPolicy(
                id="require_approval_low_confidence",
                name="Require Approval for Low Confidence",
                description="Low confidence improvements require approval",
                scope=PolicyScope.GLOBAL,
                conditions=[
                    PolicyCondition("confidence", "lt", 0.5),
                ],
                action=PolicyAction.REQUIRE_APPROVAL,
                priority=60,
                tags=["approval", "confidence"],
            ),
            # Autonomous source gets extra scrutiny
            SelfImprovementPolicy(
                id="scrutinize_autonomous",
                name="Scrutinize Autonomous Improvements",
                description="Autonomous improvements require verification",
                scope=PolicyScope.SOURCE,
                conditions=[
                    PolicyCondition("source", "eq", "autonomous"),
                ],
                action=PolicyAction.REQUIRE_VERIFICATION,
                priority=50,
                tags=["verification", "autonomous"],
            ),
        ]

        for policy in default_policies:
            self._policies[policy.id] = policy

    def evaluate(self, candidate: ImprovementCandidate) -> Dict[str, Any]:
        """
        Evaluate policies against a candidate.

        Returns:
            Dict with action, matched_policy, and details
        """
        with self._lock:
            self._stats["evaluations"] += 1

            # Sort policies by priority (highest first)
            sorted_policies = sorted(
                self._policies.values(),
                key=lambda p: p.priority,
                reverse=True
            )

            matched_policy = None
            final_action = self.default_action

            for policy in sorted_policies:
                if policy.matches(candidate):
                    matched_policy = policy
                    final_action = policy.action
                    break

            # Update stats
            if final_action == PolicyAction.ALLOW:
                self._stats["allowed"] += 1
            elif final_action == PolicyAction.DENY:
                self._stats["denied"] += 1
            elif final_action == PolicyAction.REQUIRE_APPROVAL:
                self._stats["required_approval"] += 1
            elif final_action == PolicyAction.REQUIRE_VERIFICATION:
                self._stats["required_verification"] += 1

            # Record evaluation
            eval_record = {
                "candidate_id": candidate.id,
                "action": final_action.value,
                "matched_policy": matched_policy.id if matched_policy else None,
                "matched_policy_name": matched_policy.name if matched_policy else None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self._evaluation_history.append(eval_record)
            if len(self._evaluation_history) > 10000:
                self._evaluation_history = self._evaluation_history[-10000:]

            return {
                "action": final_action,
                "matched_policy": matched_policy.to_dict() if matched_policy else None,
                "allowed": final_action == PolicyAction.ALLOW,
                "requires_approval": final_action == PolicyAction.REQUIRE_APPROVAL,
                "requires_verification": final_action == PolicyAction.REQUIRE_VERIFICATION,
                "limited": final_action == PolicyAction.LIMIT_SCOPE,
                "denied": final_action == PolicyAction.DENY,
            }

    def add_policy(self, policy: SelfImprovementPolicy) -> None:
        """Add a policy."""
        with self._lock:
            self._policies[policy.id] = policy
            self._save_policies()

    def remove_policy(self, policy_id: str) -> bool:
        """Remove a policy by ID."""
        with self._lock:
            if policy_id in self._policies:
                del self._policies[policy_id]
                self._save_policies()
                return True
            return False

    def enable_policy(self, policy_id: str) -> bool:
        """Enable a policy."""
        with self._lock:
            if policy_id in self._policies:
                self._policies[policy_id].enabled = True
                self._save_policies()
                return True
            return False

    def disable_policy(self, policy_id: str) -> bool:
        """Disable a policy."""
        with self._lock:
            if policy_id in self._policies:
                self._policies[policy_id].enabled = False
                self._save_policies()
                return True
            return False

    def get_policy(self, policy_id: str) -> Optional[SelfImprovementPolicy]:
        """Get a policy by ID."""
        with self._lock:
            return self._policies.get(policy_id)

    def list_policies(self, enabled_only: bool = False) -> List[SelfImprovementPolicy]:
        """List all policies."""
        with self._lock:
            policies = list(self._policies.values())
            if enabled_only:
                policies = [p for p in policies if p.enabled]
            return sorted(policies, key=lambda p: p.priority, reverse=True)

    def _save_policies(self) -> None:
        """Save policies to storage."""
        if not self.storage_path:
            return

        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "policies": [p.to_dict() for p in self._policies.values()],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            temp_path = self.storage_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            temp_path.replace(self.storage_path)
        except Exception as e:
            logger.error(f"[PolicyEngine] Failed to save policies: {e}")

    def _load_policies(self) -> None:
        """Load policies from storage."""
        if not self.storage_path or not self.storage_path.exists():
            return

        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for policy_data in data.get("policies", []):
                policy = SelfImprovementPolicy.from_dict(policy_data)
                self._policies[policy.id] = policy

            logger.info(f"[PolicyEngine] Loaded {len(self._policies)} policies")
        except Exception as e:
            logger.error(f"[PolicyEngine] Failed to load policies: {e}")

    def get_evaluation_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get policy evaluation history."""
        with self._lock:
            return self._evaluation_history[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        """Get policy engine statistics."""
        with self._lock:
            return {
                **self._stats,
                "total_policies": len(self._policies),
                "enabled_policies": sum(1 for p in self._policies.values() if p.enabled),
            }

    def clear_policies(self, keep_defaults: bool = True) -> int:
        """Clear all policies."""
        with self._lock:
            if keep_defaults:
                # Keep policies with priority >= 50 (defaults)
                to_remove = [
                    pid for pid, p in self._policies.items()
                    if p.priority < 50
                ]
            else:
                to_remove = list(self._policies.keys())

            for pid in to_remove:
                del self._policies[pid]

            self._save_policies()
            return len(to_remove)


def create_policy_engine(storage_path: Optional[str] = None) -> PolicyEngine:
    """Create a PolicyEngine with sensible defaults."""
    return PolicyEngine(storage_path=storage_path)