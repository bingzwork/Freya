"""Failure Recovery Integration for Central Orchestrator.

This module bridges the orchestrator's task execution with the
Failure Recovery system (FailureDetector, RootCauseAnalyzer, RecoveryOrchestrator)
for automatic failure detection, analysis, and recovery.
"""

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from app.core.events import get_event_bus, Event, EventPriority
from app.failure_recovery.detector import FailureDetector, FailureEvent
from app.failure_recovery.analyzer import RootCauseAnalyzer
from app.failure_recovery.orchestrator import RecoveryOrchestrator, RecoveryStrategy

logger = logging.getLogger(__name__)


class FailureSeverity(Enum):
    """Severity levels for failures."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class FailureContext:
    """Context information for a failure."""
    workflow_id: str
    task_id: str
    capability_name: str
    error: str
    error_type: str
    attempt: int
    max_retries: int
    step_inputs: Dict[str, Any] = field(default_factory=dict)
    step_outputs: Dict[str, Any] = field(default_factory=dict)
    stack_trace: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class RecoveryAction:
    """A recovery action to take."""
    strategy: RecoveryStrategy
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    auto_execute: bool = False


class FailureRecoveryIntegration:
    """
    Integrates the orchestrator with the Failure Recovery system.

    Provides:
    - Automatic failure detection from task execution errors
    - Root cause analysis
    - Recovery strategy selection and execution
    - Integration with task executor's retry logic
    - Event publishing for monitoring
    """

    def __init__(
        self,
        failure_detector: FailureDetector,
        root_cause_analyzer: RootCauseAnalyzer,
        recovery_orchestrator: RecoveryOrchestrator,
        task_executor: Any = None,
        workflow_composer: Any = None,
        capability_registry: Any = None,
    ):
        self._failure_detector = failure_detector
        self._root_cause_analyzer = root_cause_analyzer
        self._recovery_orchestrator = recovery_orchestrator
        self._task_executor = task_executor
        self._workflow_composer = workflow_composer
        self._capability_registry = capability_registry
        self._event_bus = get_event_bus()

        self._lock = threading.RLock()
        self._failure_history: List[FailureContext] = []
        self._max_history = 1000

        # Configuration
        self._auto_recovery_enabled = True
        self._max_auto_recovery_attempts = 3
        self._recovery_cooldown_seconds = 5.0

        # Track recovery attempts per workflow
        self._recovery_attempts: Dict[str, int] = {}

    # =========================================================================
    # Configuration
    # =========================================================================

    def set_auto_recovery(self, enabled: bool):
        """Enable or disable automatic recovery."""
        self._auto_recovery_enabled = enabled

    def set_max_auto_recovery_attempts(self, max_attempts: int):
        """Set maximum automatic recovery attempts per workflow."""
        self._max_auto_recovery_attempts = max_attempts

    def set_recovery_cooldown(self, seconds: float):
        """Set cooldown between recovery attempts."""
        self._recovery_cooldown_seconds = seconds

    # =========================================================================
    # Main Entry Points
    # =========================================================================

    def handle_task_failure(
        self,
        workflow_id: str,
        task_id: str,
        capability_name: str,
        error: Exception,
        attempt: int,
        max_retries: int,
        step_inputs: Dict[str, Any],
        step_outputs: Dict[str, Any],
    ) -> Optional[RecoveryAction]:
        """
        Handle a task failure - detect, analyze, and potentially recover.

        This is called by the TaskExecutor when a task fails.
        Returns a RecoveryAction if recovery should be attempted,
        None if the failure should be handled normally (retry or fail).
        """
        # Create failure context
        context = FailureContext(
            workflow_id=workflow_id,
            task_id=task_id,
            capability_name=capability_name,
            error=str(error),
            error_type=type(error).__name__,
            attempt=attempt,
            max_retries=max_retries,
            step_inputs=step_inputs,
            step_outputs=step_outputs,
            stack_trace=self._get_stack_trace(error),
        )

        # Store in history
        with self._lock:
            self._failure_history.append(context)
            if len(self._failure_history) > self._max_history:
                self._failure_history = self._failure_history[-self._max_history:]

        # Publish failure detected event
        self._publish_event("failure.detected", {
            "workflow_id": workflow_id,
            "task_id": task_id,
            "capability": capability_name,
            "error": str(error),
            "attempt": attempt,
        })

        # Check if we should attempt auto-recovery
        if not self._should_attempt_recovery(workflow_id, attempt, max_retries):
            return None

        # Detect failure using FailureDetector
        failure_event = self._detect_failure(context)
        if not failure_event:
            return None

        # Analyze root cause
        root_causes = self._root_cause_analyzer.analyze(failure_event)

        # Get recovery strategy
        recovery_result = self._recovery_orchestrator.recover(
            failure_event=failure_event,
            root_causes=root_causes,
            context={
                "workflow_id": workflow_id,
                "task_id": task_id,
                "capability_name": capability_name,
                "attempt": attempt,
            }
        )

        if recovery_result.success:
            # Determine recovery action
            action = self._create_recovery_action(
                recovery_result.strategy_used,
                recovery_result,
                context
            )

            # Track recovery attempt
            with self._lock:
                self._recovery_attempts[workflow_id] = self._recovery_attempts.get(workflow_id, 0) + 1

            # Publish recovery event
            self._publish_event("failure.recovery_initiated", {
                "workflow_id": workflow_id,
                "task_id": task_id,
                "strategy": action.strategy.value,
                "description": action.description,
            })

            return action

        # Recovery failed
        self._publish_event("failure.recovery_failed", {
            "workflow_id": workflow_id,
            "task_id": task_id,
            "error": recovery_result.final_failure,
        })

        return None

    def handle_workflow_stalled(
        self,
        workflow_id: str,
        stalled_task_id: str,
        stall_duration_seconds: float,
    ) -> Optional[RecoveryAction]:
        """Handle a stalled workflow (no progress for extended period)."""
        context = FailureContext(
            workflow_id=workflow_id,
            task_id=stalled_task_id,
            capability_name="workflow_monitor",
            error=f"Workflow stalled for {stall_duration_seconds:.0f} seconds",
            error_type="WorkflowStalled",
            attempt=1,
            max_retries=1,
        )

        failure_event = self._failure_detector.detect_from_result(
            result=None,
            component="workflow_executor",
            operation="execute_workflow",
            task_description=f"Workflow {workflow_id} stalled at task {stalled_task_id}",
            attempt_number=1,
            max_attempts=1,
            metadata={
                "workflow_id": workflow_id,
                "stalled_task_id": stalled_task_id,
                "stall_duration_seconds": stall_duration_seconds,
            }
        )

        root_causes = self._root_cause_analyzer.analyze(failure_event)

        recovery_result = self._recovery_orchestrator.recover(
            failure_event=failure_event,
            root_causes=root_causes,
            context={"workflow_id": workflow_id, "stalled_task_id": stalled_task_id}
        )

        if recovery_result.success:
            action = self._create_recovery_action(
                recovery_result.strategy_used,
                recovery_result,
                context
            )
            return action

        return None

    def handle_capability_failure(
        self,
        capability_name: str,
        error: Exception,
        context: Dict[str, Any],
    ) -> bool:
        """Handle a capability-level failure (e.g., health check failed)."""
        failure_event = self._failure_detector.detect_from_result(
            result=None,
            component="capability_registry",
            operation=f"capability_{capability_name}",
            task_description=f"Capability {capability_name} failed: {error}",
            attempt_number=1,
            max_attempts=3,
            metadata={
                "capability_name": capability_name,
                "error": str(error),
                "error_type": type(error).__name__,
                **context,
            }
        )

        root_causes = self._root_cause_analyzer.analyze(failure_event)

        recovery_result = self._recovery_orchestrator.recover(
            failure_event=failure_event,
            root_causes=root_causes,
            context={"capability_name": capability_name}
        )

        if recovery_result.success:
            self._publish_event("capability.recovery_initiated", {
                "capability": capability_name,
                "strategy": recovery_result.strategy_used.value,
            })
            return True

        return False

    # =========================================================================
    # Internal Methods
    # =========================================================================

    def _should_attempt_recovery(
        self,
        workflow_id: str,
        attempt: int,
        max_retries: int
    ) -> bool:
        """Determine if we should attempt automatic recovery."""
        if not self._auto_recovery_enabled:
            return False

        # Don't recover on last retry - let normal failure handling take over
        if attempt >= max_retries:
            return False

        # Check max auto-recovery attempts per workflow
        with self._lock:
            attempts = self._recovery_attempts.get(workflow_id, 0)
            if attempts >= self._max_auto_recovery_attempts:
                return False

        return True

    def _detect_failure(self, context: FailureContext) -> Optional[FailureEvent]:
        """Create a FailureEvent from the context."""
        try:
            # Use the failure detector
            return self._failure_detector.detect_from_result(
                result=None,  # No verification result for task failures
                component=f"capability_{context.capability_name}",
                operation="execute_task",
                task_description=f"Task {context.task_id} in workflow {context.workflow_id}",
                attempt_number=context.attempt,
                max_attempts=context.max_retries,
                metadata={
                    "workflow_id": context.workflow_id,
                    "task_id": context.task_id,
                    "capability_name": context.capability_name,
                    "error": context.error,
                    "error_type": context.error_type,
                    "stack_trace": context.stack_trace,
                    "step_inputs": context.step_inputs,
                    "step_outputs": context.step_outputs,
                }
            )
        except Exception as e:
            logger.error(f"Failed to detect failure: {e}")
            return None

    def _create_recovery_action(
        self,
        strategy: RecoveryStrategy,
        recovery_result: Any,
        context: FailureContext
    ) -> RecoveryAction:
        """Create a RecoveryAction from the recovery result."""
        strategy_descriptions = {
            RecoveryStrategy.RETRY_WITH_BACKOFF: "Retry the task with exponential backoff",
            RecoveryStrategy.RETRY_WITH_DIFFERENT_INPUTS: "Retry with modified inputs based on error",
            RecoveryStrategy.FALLBACK_CAPABILITY: "Switch to a fallback capability",
            RecoveryStrategy.REPLAN_TASK: "Replan the task with a different approach",
            RecoveryStrategy.SKIP_TASK: "Skip this task and continue with workflow",
            RecoveryStrategy.ROLLBACK: "Rollback to previous checkpoint",
            RecoveryStrategy.HUMAN_INTERVENTION: "Request human intervention",
            RecoveryStrategy.ABORT_WORKFLOW: "Abort the entire workflow",
        }

        return RecoveryAction(
            strategy=strategy,
            description=strategy_descriptions.get(strategy, f"Apply {strategy.value} strategy"),
            parameters={
                "workflow_id": context.workflow_id,
                "task_id": context.task_id,
                "capability_name": context.capability_name,
                "recovery_details": recovery_result.details if hasattr(recovery_result, 'details') else {},
            },
            auto_execute=strategy in (
                RecoveryStrategy.RETRY_WITH_BACKOFF,
                RecoveryStrategy.RETRY_WITH_DIFFERENT_INPUTS,
                RecoveryStrategy.FALLBACK_CAPABILITY,
            ),
        )

    def _get_stack_trace(self, error: Exception) -> Optional[str]:
        """Get stack trace from exception."""
        import traceback
        return ''.join(traceback.format_exception(type(error), error, error.__traceback__))

    def _publish_event(self, event_name: str, data: Dict[str, Any]):
        """Publish an event to the event bus."""
        try:
            self._event_bus.publish(Event(
                name=event_name,
                data=data,
                source="failure_recovery_integration",
                priority=EventPriority.HIGH if "failed" in event_name else EventPriority.NORMAL
            ))
        except Exception as e:
            logger.warning(f"Failed to publish event {event_name}: {e}")

    # =========================================================================
    # Recovery Execution Helpers
    # =========================================================================

    def execute_recovery_action(
        self,
        action: RecoveryAction,
        task_executor: Any,
    ) -> bool:
        """
        Execute a recovery action.

        This modifies the task executor's state to implement the recovery.
        Returns True if recovery was initiated successfully.
        """
        try:
            params = action.parameters
            workflow_id = params.get("workflow_id")
            task_id = params.get("task_id")
            capability_name = params.get("capability_name")

            if not workflow_id or not task_executor:
                return False

            context = task_executor.get_context(workflow_id)
            if not context:
                return False

            if action.strategy == RecoveryStrategy.RETRY_WITH_BACKOFF:
                # Reset retry count for this task to allow retry
                if task_id in context.retries:
                    context.retries[task_id] = 0
                # Clear error so it can retry
                if task_id in context.step_errors:
                    del context.step_errors[task_id]
                return True

            elif action.strategy == RecoveryStrategy.RETRY_WITH_DIFFERENT_INPUTS:
                # Modify inputs based on error
                recovery_details = params.get("recovery_details", {})
                modified_inputs = recovery_details.get("modified_inputs", {})
                if modified_inputs:
                    # Store modified inputs for next execution
                    context.global_inputs.update(modified_inputs)
                if task_id in context.retries:
                    context.retries[task_id] = 0
                return True

            elif action.strategy == RecoveryStrategy.FALLBACK_CAPABILITY:
                # Switch to fallback capability
                recovery_details = params.get("recovery_details", {})
                fallback = recovery_details.get("fallback_capability")
                if fallback and self._capability_registry:
                    fallback_cap = self._capability_registry.get_capability(fallback)
                    if fallback_cap:
                        context.capabilities[capability_name] = fallback_cap
                        return True
                return False

            elif action.strategy == RecoveryStrategy.REPLAN_TASK:
                # Trigger workflow recomposition
                if self._workflow_composer:
                    # This would require workflow recomposition
                    # For now, just reset the task for retry
                    if task_id in context.retries:
                        context.retries[task_id] = 0
                    return True
                return False

            elif action.strategy == RecoveryStrategy.SKIP_TASK:
                # Mark task as completed (skipped) and continue
                context.completed_steps.add(task_id)
                context.step_outputs[task_id] = {"skipped": True, "reason": action.description}
                return True

            elif action.strategy == RecoveryStrategy.ROLLBACK:
                # Trigger checkpoint recovery
                if task_executor._recover_from_checkpoint(context):
                    return True
                return False

            elif action.strategy in (RecoveryStrategy.HUMAN_INTERVENTION, RecoveryStrategy.ABORT_WORKFLOW):
                # These require external handling
                return False

            return False

        except Exception as e:
            logger.error(f"Failed to execute recovery action: {e}")
            return False

    # =========================================================================
    # Query Methods
    # =========================================================================

    def get_failure_history(
        self,
        workflow_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[FailureContext]:
        """Get failure history with optional filtering."""
        with self._lock:
            history = list(self._failure_history)

        if workflow_id:
            history = [f for f in history if f.workflow_id == workflow_id]

        return history[-limit:]

    def get_recovery_stats(self) -> Dict[str, Any]:
        """Get recovery statistics."""
        with self._lock:
            total_failures = len(self._failure_history)
            total_recoveries = sum(self._recovery_attempts.values())

            by_type = {}
            for f in self._failure_history:
                by_type[f.error_type] = by_type.get(f.error_type, 0) + 1

            by_capability = {}
            for f in self._failure_history:
                by_capability[f.capability_name] = by_capability.get(f.capability_name, 0) + 1

        return {
            "total_failures": total_failures,
            "total_recovery_attempts": total_recoveries,
            "auto_recovery_enabled": self._auto_recovery_enabled,
            "max_auto_recovery_attempts": self._max_auto_recovery_attempts,
            "failures_by_type": by_type,
            "failures_by_capability": by_capability,
            "recovery_attempts_by_workflow": dict(self._recovery_attempts),
        }

    def clear_recovery_attempts(self, workflow_id: Optional[str] = None):
        """Clear recovery attempt counters."""
        with self._lock:
            if workflow_id:
                self._recovery_attempts.pop(workflow_id, None)
            else:
                self._recovery_attempts.clear()


# =========================================================================
# Factory function
# =========================================================================

def create_failure_recovery_integration(
    agent=None,
    task_executor=None,
    workflow_composer=None,
    capability_registry=None,
) -> FailureRecoveryIntegration:
    """Create a FailureRecoveryIntegration with all components."""
    # Get components from agent if provided
    if agent:
        failure_detector = getattr(agent, 'failure_detector', None)
        root_cause_analyzer = getattr(agent, 'root_cause_analyzer', None)
        recovery_orchestrator = getattr(agent, 'recovery_orchestrator', None)
    else:
        failure_detector = FailureDetector()
        root_cause_analyzer = RootCauseAnalyzer()
        recovery_orchestrator = RecoveryOrchestrator(
            failure_detector=failure_detector,
            root_cause_analyzer=root_cause_analyzer,
        )

    return FailureRecoveryIntegration(
        failure_detector=failure_detector,
        root_cause_analyzer=root_cause_analyzer,
        recovery_orchestrator=recovery_orchestrator,
        task_executor=task_executor,
        workflow_composer=workflow_composer,
        capability_registry=capability_registry,
    )