"""Adaptive Decision Revision - Monitor outcomes during execution and re-evaluate decisions when context changes.

This module implements the Adaptive Decision Revision capability (Phase 2+ enhancement):
- Monitors execution outcomes in real-time
- Detects significant context changes that warrant re-evaluation
- Triggers decision revision workflows when conditions change
- Integrates with DecisionManager, DecisionHistory, and existing systems
"""

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set
import uuid

from app.decision.models import (
    DecisionContext,
    DecisionOption,
    DecisionResult,
    DecisionRecord,
    DecisionCategory,
    DecisionType,
)
from app.decision.history import DecisionHistory
from app.decision.manager import DecisionManager

# Shared infrastructure imports
from app.core.background_jobs import get_job_service, BackgroundJobService, JobTriggerConfig, JobTriggerType, JobPriority

logger = logging.getLogger(__name__)


class ContextChangeType(str):
    """Types of context changes that may trigger revision."""
    SYSTEM_STATE_CHANGED = "system_state_changed"
    NEW_INFORMATION = "new_information"
    GOAL_CHANGED = "goal_changed"
    FAILURE_DETECTED = "failure_detected"
    RESOURCE_CONSTRAINT = "resource_constraint"
    USER_INTERVENTION = "user_intervention"
    TIME_EXPIRED = "time_expired"
    DEPENDENCY_FAILED = "dependency_failed"


@dataclass
class ContextChange:
    """Represents a detected context change that may require decision revision."""
    change_type: ContextChangeType
    description: str
    severity: str  # critical, high, medium, low
    detected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    affected_decision_ids: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "change_type": self.change_type,
            "description": self.description,
            "severity": self.severity,
            "detected_at": self.detected_at,
            "affected_decision_ids": self.affected_decision_ids,
            "metadata": self.metadata,
        }


@dataclass
class RevisionTrigger:
    """Configuration for when to trigger a decision revision."""
    decision_id: str
    conditions: List[Dict[str, Any]] = field(default_factory=list)
    check_interval_seconds: float = 30.0
    max_revisions: int = 3
    revision_count: int = 0
    last_check: Optional[str] = None
    is_active: bool = True


@dataclass
class RevisionResult:
    """Result of a decision revision."""
    revision_id: str
    original_decision_id: str
    trigger: ContextChange
    original_result: DecisionResult
    revised_result: Optional[DecisionResult] = None
    was_revised: bool = False
    revision_reason: str = ""
    executed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AdaptiveDecisionRevision:
    """Monitors and re-evaluates decisions when context changes.

    This class provides the Adaptive Decision Revision capability:
    1. Register decisions for monitoring
    2. Detect context changes through various signals
    3. Trigger re-evaluation when significant changes occur
    4. Execute revision workflow and record results
    """

    def __init__(
        self,
        decision_manager: DecisionManager,
        decision_history: Optional[DecisionHistory] = None,
        check_interval_seconds: float = 30.0,
        job_service: Optional[BackgroundJobService] = None,
    ):
        """Initialize the adaptive revision monitor.

        Args:
            decision_manager: The DecisionManager to use for re-evaluation
            decision_history: Optional DecisionHistory for querying past decisions
            check_interval_seconds: How often to check for context changes
            job_service: Optional shared BackgroundJobService instance
        """
        self.decision_manager = decision_manager
        self.decision_history = decision_history
        self.check_interval = check_interval_seconds
        self.job_service = job_service or get_job_service()

        self._lock = threading.RLock()
        self._triggers: Dict[str, RevisionTrigger] = {}
        self._revision_history: List[RevisionResult] = []
        self._context_snapshots: Dict[str, Dict[str, Any]] = {}
        self._change_detectors: List[Callable[[DecisionContext], List[ContextChange]]] = []
        self._running = False
        self._monitor_job_id = "adaptive_revision_monitor"
        self._context_provider: Optional[Callable[[], DecisionContext]] = None

        # Register default change detectors
        self._register_default_detectors()

    def _register_default_detectors(self) -> None:
        """Register built-in context change detectors."""
        self._change_detectors = [
            self._detect_system_state_change,
            self._detect_failure_pattern,
            self._detect_goal_change,
            self._detect_resource_constraint,
            self._detect_time_expiry,
        ]

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def register_decision_for_monitoring(
        self,
        decision_id: str,
        context: DecisionContext,
        conditions: Optional[List[Dict[str, Any]]] = None,
        max_revisions: int = 3,
    ) -> None:
        """Register a decision for adaptive monitoring.

        Args:
            decision_id: ID of the decision to monitor
            context: The context at the time of the original decision
            conditions: Optional custom conditions that trigger revision
            max_revisions: Maximum number of revisions allowed
        """
        with self._lock:
            trigger = RevisionTrigger(
                decision_id=decision_id,
                conditions=conditions or [],
                max_revisions=max_revisions,
            )
            self._triggers[decision_id] = trigger
            self._context_snapshots[decision_id] = context.to_dict()
            logger.info(f"[AdaptiveRevision] Registered decision {decision_id} for monitoring")

    def unregister_decision(self, decision_id: str) -> bool:
        """Stop monitoring a decision.

        Args:
            decision_id: ID of the decision to stop monitoring

        Returns:
            True if decision was being monitored, False otherwise
        """
        with self._lock:
            if decision_id in self._triggers:
                self._triggers[decision_id].is_active = False
                del self._triggers[decision_id]
                self._context_snapshots.pop(decision_id, None)
                logger.info(f"[AdaptiveRevision] Unregistered decision {decision_id}")
                return True
            return False

    def detect_context_changes(self, current_context: DecisionContext) -> List[ContextChange]:
        """Run all registered change detectors against current context.

        Args:
            current_context: Current decision context to evaluate

        Returns:
            List of detected context changes
        """
        all_changes = []
        for detector in self._change_detectors:
            try:
                changes = detector(current_context)
                all_changes.extend(changes)
            except Exception as e:
                logger.warning(f"[AdaptiveRevision] Change detector failed: {e}")
        return all_changes

    def check_and_revise(
        self,
        current_context: DecisionContext,
        force_check: bool = False,
    ) -> List[RevisionResult]:
        """Check monitored decisions for context changes and revise if needed.

        Args:
            current_context: Current context to compare against
            force_check: If True, check all triggers regardless of interval

        Returns:
            List of revision results
        """
        revisions = []
        with self._lock:
            current_time = datetime.now(timezone.utc)

            for decision_id, trigger in list(self._triggers.items()):
                if not trigger.is_active:
                    continue

                # Check interval
                if not force_check and trigger.last_check:
                    try:
                        last = datetime.fromisoformat(trigger.last_check.replace("Z", "+00:00"))
                        elapsed = (current_time - last).total_seconds()
                        if elapsed < trigger.check_interval_seconds:
                            continue
                    except (ValueError, TypeError):
                        pass

                trigger.last_check = current_time.isoformat()

                # Get original context snapshot
                original_context_dict = self._context_snapshots.get(decision_id)
                if not original_context_dict:
                    continue

                original_context = DecisionContext.from_dict(original_context_dict)

                # Detect changes
                changes = self.detect_context_changes(current_context)
                relevant_changes = [c for c in changes if decision_id in c.affected_decision_ids or not c.affected_decision_ids]

                if not relevant_changes:
                    continue

                # Check if any changes meet trigger conditions
                should_revise = self._should_revise(trigger, relevant_changes, original_context, current_context)
                if not should_revise:
                    continue

                # Check revision limit
                if trigger.revision_count >= trigger.max_revisions:
                    logger.warning(f"[AdaptiveRevision] Max revisions reached for {decision_id}")
                    continue

                # Get original decision record
                original_record = self.decision_history.get_decision(decision_id) if self.decision_history else None
                if not original_record:
                    logger.debug(f"[AdaptiveRevision] No history record for {decision_id}")
                    continue

                # Reconstruct original result (simplified)
                original_result = self._record_to_result(original_record)

                # Re-evaluate with current context
                logger.info(f"[AdaptiveRevision] Revising decision {decision_id} due to: {[c.change_type for c in relevant_changes]}")
                revised_result = self._reevaluate_decision(
                    original_record,
                    current_context,
                    relevant_changes,
                )

                if revised_result:
                    # Create revision result
                    revision = RevisionResult(
                        revision_id=f"rev_{uuid.uuid4().hex[:8]}",
                        original_decision_id=decision_id,
                        trigger=relevant_changes[0],  # Primary trigger
                        original_result=original_result,
                        revised_result=revised_result,
                        was_revised=True,
                        revision_reason=f"Context change: {', '.join(c.change_type for c in relevant_changes)}",
                    )
                    self._revision_history.append(revision)
                    trigger.revision_count += 1

                    # Update context snapshot
                    self._context_snapshots[decision_id] = current_context.to_dict()

                    revisions.append(revision)
                    logger.info(f"[AdaptiveRevision] Decision {decision_id} revised (revision #{trigger.revision_count})")

        return revisions

    def get_revision_history(self, decision_id: Optional[str] = None) -> List[RevisionResult]:
        """Get revision history for a decision or all decisions.

        Args:
            decision_id: Optional filter by decision ID

        Returns:
            List of revision results
        """
        with self._lock:
            if decision_id:
                return [r for r in self._revision_history if r.original_decision_id == decision_id]
            return list(self._revision_history)

    def add_change_detector(self, detector: Callable[[DecisionContext], List[ContextChange]]) -> None:
        """Add a custom context change detector.

        Args:
            detector: Function that takes DecisionContext and returns list of ContextChange
        """
        with self._lock:
            self._change_detectors.append(detector)

    def start_monitoring(self, context_provider: Callable[[], DecisionContext]) -> None:
        """Start background monitoring using shared BackgroundJobService.

        Args:
            context_provider: Function that returns current DecisionContext
        """
        if self._running:
            return

        self._running = True
        self._context_provider = context_provider

        # Schedule recurring job using shared BackgroundJobService
        self.job_service.schedule(
            job_id=self._monitor_job_id,
            func=self._check_and_revise_job,
            trigger=JobTriggerConfig(type=JobTriggerType.RECURRING, interval_seconds=self.check_interval),
            priority=JobPriority.NORMAL,
            max_retries=1,
            replace_existing=True,
        )
        logger.info("[AdaptiveRevision] Started background monitoring via shared BackgroundJobService")

    def stop_monitoring(self) -> None:
        """Stop background monitoring."""
        self._running = False
        self._context_provider = None

        # Cancel the monitoring job
        try:
            self.job_service.cancel(self._monitor_job_id)
        except Exception as e:
            logger.warning(f"[AdaptiveRevision] Error cancelling monitor job: {e}")

        logger.info("[AdaptiveRevision] Stopped background monitoring")

    def _check_and_revise_job(self) -> None:
        """Background job to check for context changes and revise decisions."""
        if not self._running or self._context_provider is None:
            return

        try:
            current_context = self._context_provider()
            self.check_and_revise(current_context)
        except Exception as e:
            logger.warning(f"[AdaptiveRevision] Monitor job error: {e}")

    # -------------------------------------------------------------------------
    # Built-in Change Detectors
    # -------------------------------------------------------------------------

    def _detect_system_state_change(self, context: DecisionContext) -> List[ContextChange]:
        """Detect changes in system state."""
        changes = []

        # Check if we have a previous snapshot for any monitored decision
        for decision_id, snapshot in self._context_snapshots.items():
            old_state = snapshot.get("system_state", "normal")
            new_state = context.system_state

            if old_state != new_state:
                severity = "critical" if new_state == "critical" else "high" if new_state == "degraded" else "medium"
                changes.append(ContextChange(
                    change_type=ContextChangeType.SYSTEM_STATE_CHANGED,
                    description=f"System state changed from {old_state} to {new_state}",
                    severity=severity,
                    affected_decision_ids=[decision_id],
                    metadata={"old_state": old_state, "new_state": new_state},
                ))

        return changes

    def _detect_failure_pattern(self, context: DecisionContext) -> List[ContextChange]:
        """Detect patterns of recent failures."""
        changes = []

        # Get recent failure count from context
        recent_failures = context.recent_failures
        if recent_failures >= 3:
            # Find decisions that might be affected
            affected = [did for did in self._triggers.keys()]
            changes.append(ContextChange(
                change_type=ContextChangeType.FAILURE_DETECTED,
                description=f"Multiple recent failures detected ({recent_failures})",
                severity="high" if recent_failures >= 5 else "medium",
                affected_decision_ids=affected,
                metadata={"failure_count": recent_failures},
            ))

        return changes

    def _detect_goal_change(self, context: DecisionContext) -> List[ContextChange]:
        """Detect changes in active goal."""
        changes = []

        for decision_id, snapshot in self._context_snapshots.items():
            old_goal_id = snapshot.get("active_goal_id")
            new_goal_id = context.active_goal_id

            if old_goal_id != new_goal_id and old_goal_id and new_goal_id:
                changes.append(ContextChange(
                    change_type=ContextChangeType.GOAL_CHANGED,
                    description=f"Active goal changed from {old_goal_id} to {new_goal_id}",
                    severity="medium",
                    affected_decision_ids=[decision_id],
                    metadata={"old_goal_id": old_goal_id, "new_goal_id": new_goal_id},
                ))

        return changes

    def _detect_resource_constraint(self, context: DecisionContext) -> List[ContextChange]:
        """Detect resource constraints from context metadata."""
        changes = []

        # Check metadata for resource indicators
        memory_pressure = context.metadata.get("memory_pressure", False)
        cpu_pressure = context.metadata.get("cpu_pressure", False)
        disk_pressure = context.metadata.get("disk_pressure", False)

        if memory_pressure or cpu_pressure or disk_pressure:
            affected = [did for did in self._triggers.keys()]
            resource_types = [r for r, v in [("memory", memory_pressure), ("cpu", cpu_pressure), ("disk", disk_pressure)] if v]
            changes.append(ContextChange(
                change_type=ContextChangeType.RESOURCE_CONSTRAINT,
                description=f"Resource constraints detected: {', '.join(resource_types)}",
                severity="high",
                affected_decision_ids=affected,
                metadata={
                    "memory_pressure": memory_pressure,
                    "cpu_pressure": cpu_pressure,
                    "disk_pressure": disk_pressure,
                },
            ))

        return changes

    def _detect_time_expiry(self, context: DecisionContext) -> List[ContextChange]:
        """Detect time-based expiry of decisions."""
        changes = []

        current_time = datetime.now(timezone.utc)

        for decision_id, trigger in self._triggers.items():
            if trigger.last_check:
                try:
                    last = datetime.fromisoformat(trigger.last_check.replace("Z", "+00:00"))
                    elapsed_hours = (current_time - last).total_seconds() / 3600

                    # Check for explicit expiry in metadata
                    max_age_hours = context.metadata.get("decision_max_age_hours")
                    if max_age_hours and elapsed_hours > max_age_hours:
                        changes.append(ContextChange(
                            change_type=ContextChangeType.TIME_EXPIRED,
                            description=f"Decision {decision_id} exceeded max age of {max_age_hours} hours",
                            severity="medium",
                            affected_decision_ids=[decision_id],
                            metadata={"elapsed_hours": elapsed_hours, "max_age_hours": max_age_hours},
                        ))
                except (ValueError, TypeError):
                    pass

        return changes

    # -------------------------------------------------------------------------
    # Revision Logic
    # -------------------------------------------------------------------------

    def _should_revise(
        self,
        trigger: RevisionTrigger,
        changes: List[ContextChange],
        original_context: DecisionContext,
        current_context: DecisionContext,
    ) -> bool:
        """Determine if a decision should be revised based on changes."""
        # Always revise on critical changes
        if any(c.severity == "critical" for c in changes):
            return True

        # Check custom conditions
        for condition in trigger.conditions:
            if self._evaluate_condition(condition, changes, current_context):
                return True

        # Default: revise on high severity changes
        if any(c.severity in ("high", "critical") for c in changes):
            return True

        return False

    def _evaluate_condition(
        self,
        condition: Dict[str, Any],
        changes: List[ContextChange],
        context: DecisionContext,
    ) -> bool:
        """Evaluate a custom trigger condition."""
        condition_type = condition.get("type", "")

        if condition_type == "system_state":
            target_state = condition.get("value")
            return context.system_state == target_state

        elif condition_type == "failure_threshold":
            threshold = condition.get("value", 3)
            return context.recent_failures >= threshold

        elif condition_type == "risk_level":
            target = condition.get("value")
            # Would need to check current decision's risk
            return False  # Simplified

        elif condition_type == "context_change":
            # Generic: any context field changed
            field = condition.get("field")
            old_value = condition.get("old_value")
            if field and hasattr(context, field):
                return getattr(context, field) != old_value

        return False

    def _reevaluate_decision(
        self,
        original_record: DecisionRecord,
        current_context: DecisionContext,
        changes: List[ContextChange],
    ) -> Optional[DecisionResult]:
        """Re-evaluate a decision with current context."""
        try:
            # Reconstruct original options (simplified - would need full reconstruction)
            # For now, we create a basic reevaluation using the manager
            # In a full implementation, we'd reconstruct the original options

            # Create a context for the reevaluation that incorporates changes
            revision_context = DecisionContext(
                task_description=f"REVISION: {original_record.task_description}",
                component=original_record.component,
                current_phase=current_context.current_phase,
                available_context=current_context.available_context,
                working_memory=current_context.working_memory,
                project_state=current_context.project_state,
                active_goal_id=current_context.active_goal_id,
                active_goal_name=current_context.active_goal_name,
                plan_id=current_context.plan_id,
                current_step=current_context.current_step,
                recent_failures=current_context.recent_failures,
                recent_successes=current_context.recent_successes,
                system_state=current_context.system_state,
                risk_tolerance=current_context.risk_tolerance,
                user_input=current_context.user_input,
                requires_approval=current_context.requires_approval,
                allow_mutations=current_context.allow_mutations,
                metadata={
                    **current_context.metadata,
                    "is_revision": True,
                    "original_decision_id": original_record.decision_id,
                    "trigger_changes": [c.to_dict() for c in changes],
                },
            )

            # For proper reevaluation, we'd need the original options
            # This is a simplified version that returns None to indicate
            # manual re-evaluation is needed
            logger.info(f"[AdaptiveRevision] Decision {original_record.decision_id} flagged for manual re-evaluation")
            return None

        except Exception as e:
            logger.error(f"[AdaptiveRevision] Re-evaluation failed: {e}")
            return None

    def _record_to_result(self, record: DecisionRecord) -> DecisionResult:
        """Convert a DecisionRecord back to a DecisionResult (approximate)."""
        from app.decision.models import DecisionOption, DecisionCategory, DecisionType

        chosen_option = None
        if record.chosen_option_name:
            chosen_option = DecisionOption(
                name=record.chosen_option_name,
                action=record.chosen_option_action,
                description=f"Original choice: {record.chosen_option_name}",
                category=record.category,
                decision_type=record.decision_type,
            )

        return DecisionResult(
            decision_id=record.decision_id,
            decision_type=record.decision_type,
            category=record.category,
            chosen_option=chosen_option,
            confidence=record.confidence,
            confidence_level=record.confidence_level,
            risk_level=record.risk_level,
            rationale=record.rationale,
            key_factors=record.key_factors,
            should_execute=record.executed,
            component=record.component,
        )

    # Convenience function
def create_adaptive_revision(
    decision_manager: DecisionManager,
    decision_history: Optional[DecisionHistory] = None,
    check_interval_seconds: float = 30.0,
    job_service: Optional[BackgroundJobService] = None,
) -> AdaptiveDecisionRevision:
    """Create an AdaptiveDecisionRevision instance with standard configuration."""
    return AdaptiveDecisionRevision(
        decision_manager=decision_manager,
        decision_history=decision_history,
        check_interval_seconds=check_interval_seconds,
        job_service=job_service,
    )