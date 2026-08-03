"""Activity Reporter for Central Orchestrator.

Provides plain English execution updates for GUI and conversational feedback.
Integrates with the plain_english module for jargon-free communication.
"""

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from collections import deque

from app.core.events import get_event_bus, Event
from app.capabilities.plain_english import enforce_plain_english, get_plain_english_formatter

logger = logging.getLogger(__name__)


class ActivityLevel(Enum):
    """Activity update severity levels."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"


@dataclass
class ActivityUpdate:
    """An activity update in plain English."""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    level: ActivityLevel = ActivityLevel.INFO
    category: str = ""  # orchestration, workflow, task, capability, safety, learning
    message: str = ""
    workflow_id: Optional[str] = None
    workflow_name: Optional[str] = None
    step_id: Optional[str] = None
    step_name: Optional[str] = None
    capability_name: Optional[str] = None
    progress: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "level": self.level.value,
            "category": self.category,
            "message": self.message,
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "step_id": self.step_id,
            "step_name": self.step_name,
            "capability_name": self.capability_name,
            "progress": self.progress,
            "metadata": self.metadata,
        }


class ActivityReporter:
    """
    Generates and distributes plain English activity updates.

    Subscribes to all orchestrator events and converts them to
    user-friendly messages. Supports multiple output channels:
    - Real-time callbacks (for GUI streaming)
    - Event bus publishing
    - Conversational control handler
    - Log output
    """

    def __init__(
        self,
        enable_plain_english: bool = True,
        debug_mode: bool = False,
        max_history: int = 1000,
    ):
        self._enable_plain_english = enable_plain_english
        self._debug_mode = debug_mode
        self._max_history = max_history
        self._history: deque = deque(maxlen=max_history)
        self._callbacks: List[Callable[[ActivityUpdate], None]] = []
        self._lock = threading.RLock()
        self._event_bus = get_event_bus()
        self._formatter = get_plain_english_formatter(debug_mode)

        # Subscribe to all relevant events
        self._setup_subscriptions()

    def _setup_subscriptions(self):
        """Subscribe to all event types that generate activity updates."""
        # Orchestrator events
        self._event_bus.subscribe("orchestrator.*", self._handle_event)

        # Workflow events
        self._event_bus.subscribe("workflow.*", self._handle_event)

        # Task events
        self._event_bus.subscribe("task.*", self._handle_event)

        # Capability events
        self._event_bus.subscribe("capability.*", self._handle_event)

        # Safety events
        self._event_bus.subscribe("safety.*", self._handle_event)

        # Learning events
        self._event_bus.subscribe("learning.*", self._handle_event)

        # Goal events
        self._event_bus.subscribe("goal.*", self._handle_event)

        # Autonomy events
        self._event_bus.subscribe("autonomy.*", self._handle_event)

        # Recovery events
        self._event_bus.subscribe("recovery.*", self._handle_event)

        # Decision events
        self._event_bus.subscribe("decision.*", self._handle_event)

        # Conversation control events
        self._event_bus.subscribe("conversation.control.*", self._handle_event)

    def _handle_event(self, event: Event):
        """Process an event and generate activity update."""
        try:
            activity = self._event_to_activity(event)
            if activity:
                self._emit_activity(activity)
        except Exception as e:
            logger.warning(f"Failed to process event {event.name}: {e}")

    def _event_to_activity(self, event: Event) -> Optional[ActivityUpdate]:
        """Convert an event to an activity update."""
        data = event.data if hasattr(event, 'data') else {}

        # Map event names to handlers
        handlers = {
            # Orchestrator
            "orchestrator.started": self._handle_orchestrator_started,
            "orchestrator.stopped": self._handle_orchestrator_stopped,
            "orchestrator.paused": self._handle_orchestrator_paused,
            "orchestrator.resumed": self._handle_orchestrator_resumed,
            "orchestrator.health_degraded": self._handle_health_degraded,
            "orchestrator.intent_executed": self._handle_intent_executed,

            # Workflow
            "workflow.started": self._handle_workflow_started,
            "workflow.completed": self._handle_workflow_completed,
            "workflow.failed": self._handle_workflow_failed,
            "workflow.cancelled": self._handle_workflow_cancelled,
            "workflow.paused": self._handle_workflow_paused,
            "workflow.resumed": self._handle_workflow_resumed,
            "workflow.recovered": self._handle_workflow_recovered,
            "workflow.recovering": self._handle_workflow_recovering,

            # Task
            "task.started": self._handle_task_started,
            "task.completed": self._handle_task_completed,
            "task.failed": self._handle_task_failed,
            "task.retrying": self._handle_task_retrying,

            # Capability
            "capability.registered": self._handle_capability_registered,
            "capability.unregistered": self._handle_capability_unregistered,
            "capability.activated": self._handle_capability_activated,
            "capability.deactivated": self._handle_capability_deactivated,
            "capability.health_check_failed": self._handle_capability_health_failed,

            # Safety
            "safety.check.completed": self._handle_safety_check,
            "safety.approval_requested": self._handle_safety_approval_requested,
            "safety.approval_granted": self._handle_safety_approval_granted,
            "safety.approval_denied": self._handle_safety_approval_denied,
            "safety.blocked": self._handle_safety_blocked,

            # Learning
            "learning.reflected": self._handle_learning_reflected,
            "learning.consolidated": self._handle_learning_consolidated,
            "learning.lesson_stored": self._handle_learning_lesson_stored,

            # Goal
            "goal.created": self._handle_goal_created,
            "goal.updated": self._handle_goal_updated,
            "goal.completed": self._handle_goal_completed,
            "goal.failed": self._handle_goal_failed,

            # Recovery
            "recovery.started": self._handle_recovery_started,
            "recovery.completed": self._handle_recovery_completed,
            "recovery.failed": self._handle_recovery_failed,

            # Autonomy
            "autonomy.cycle_started": self._handle_autonomy_cycle_started,
            "autonomy.cycle_completed": self._handle_autonomy_cycle_completed,
            "autonomy.proposal_generated": self._handle_autonomy_proposal,

            # Decision
            "decision.made": self._handle_decision_made,

            # Conversation control
            "conversation.control.stop": self._handle_control_stop,
            "conversation.control.cancel": self._handle_control_cancel,
            "conversation.control.pause": self._handle_control_pause,
            "conversation.control.resume": self._handle_control_resume,
            "conversation.control.undo": self._handle_control_undo,
            "conversation.control.redo": self._handle_control_redo,
        }

        handler = handlers.get(event.name)
        if handler:
            return handler(event, data)

        # Generic fallback
        return ActivityUpdate(
            level=ActivityLevel.INFO,
            category="system",
            message=f"Event: {event.name}",
            metadata={"event": event.name, "data": data},
        )

    # =========================================================================
    # Event Handlers - Orchestrator
    # =========================================================================

    def _handle_orchestrator_started(self, event: Event, data: Dict) -> ActivityUpdate:
        return ActivityUpdate(
            level=ActivityLevel.SUCCESS,
            category="orchestration",
            message="Orchestrator started and ready to process requests",
        )

    def _handle_orchestrator_stopped(self, event: Event, data: Dict) -> ActivityUpdate:
        return ActivityUpdate(
            level=ActivityLevel.INFO,
            category="orchestration",
            message="Orchestrator stopped",
        )

    def _handle_orchestrator_paused(self, event: Event, data: Dict) -> ActivityUpdate:
        return ActivityUpdate(
            level=ActivityLevel.WARNING,
            category="orchestration",
            message="Orchestrator paused - all workflows suspended",
        )

    def _handle_orchestrator_resumed(self, event: Event, data: Dict) -> ActivityUpdate:
        return ActivityUpdate(
            level=ActivityLevel.SUCCESS,
            category="orchestration",
            message="Orchestrator resumed - workflows continuing",
        )

    def _handle_health_degraded(self, event: Event, data: Dict) -> ActivityUpdate:
        return ActivityUpdate(
            level=ActivityLevel.WARNING,
            category="orchestration",
            message="System health degraded - some components may be slow or unavailable",
        )

    def _handle_intent_executed(self, event: Event, data: Dict) -> ActivityUpdate:
        user_input = data.get("user_input", "a request")
        intent = data.get("intent", "unknown")
        return ActivityUpdate(
            level=ActivityLevel.INFO,
            category="orchestration",
            message=f"Processing request: {user_input}",
            metadata={"intent": intent},
        )

    # =========================================================================
    # Event Handlers - Workflow
    # =========================================================================

    def _handle_workflow_started(self, event: Event, data: Dict) -> ActivityUpdate:
        wf_id = data.get("workflow_id", "unknown")
        return ActivityUpdate(
            level=ActivityLevel.INFO,
            category="workflow",
            message=f"Started workflow {wf_id[:8]}",
            workflow_id=wf_id,
            progress=0.0,
        )

    def _handle_workflow_completed(self, event: Event, data: Dict) -> ActivityUpdate:
        wf_id = data.get("workflow_id", "unknown")
        duration = data.get("duration_seconds", 0)
        return ActivityUpdate(
            level=ActivityLevel.SUCCESS,
            category="workflow",
            message=f"Completed workflow {wf_id[:8]} in {duration:.1f} seconds",
            workflow_id=wf_id,
            progress=100.0,
        )

    def _handle_workflow_failed(self, event: Event, data: Dict) -> ActivityUpdate:
        wf_id = data.get("workflow_id", "unknown")
        error = data.get("error", "Unknown error")
        return ActivityUpdate(
            level=ActivityLevel.ERROR,
            category="workflow",
            message=f"Workflow {wf_id[:8]} failed: {error}",
            workflow_id=wf_id,
            metadata={"error": error},
        )

    def _handle_workflow_cancelled(self, event: Event, data: Dict) -> ActivityUpdate:
        wf_id = data.get("workflow_id", "unknown")
        return ActivityUpdate(
            level=ActivityLevel.WARNING,
            category="workflow",
            message=f"Cancelled workflow {wf_id[:8]}",
            workflow_id=wf_id,
        )

    def _handle_workflow_paused(self, event: Event, data: Dict) -> ActivityUpdate:
        wf_id = data.get("workflow_id", "unknown")
        task = data.get("paused_at_task", "a task")
        completed = data.get("completed_so_far", 0)
        return ActivityUpdate(
            level=ActivityLevel.WARNING,
            category="workflow",
            message=f"Paused workflow {wf_id[:8]} at '{task}' ({completed} steps completed)",
            workflow_id=wf_id,
        )

    def _handle_workflow_resumed(self, event: Event, data: Dict) -> ActivityUpdate:
        wf_id = data.get("workflow_id", "unknown")
        task = data.get("resuming_at_task", "next task")
        return ActivityUpdate(
            level=ActivityLevel.INFO,
            category="workflow",
            message=f"Resuming workflow {wf_id[:8]} at '{task}'",
            workflow_id=wf_id,
        )

    def _handle_workflow_recovered(self, event: Event, data: Dict) -> ActivityUpdate:
        wf_id = data.get("workflow_id", "unknown")
        return ActivityUpdate(
            level=ActivityLevel.SUCCESS,
            category="workflow",
            message=f"Recovered workflow {wf_id[:8]} from checkpoint",
            workflow_id=wf_id,
        )

    def _handle_workflow_recovering(self, event: Event, data: Dict) -> ActivityUpdate:
        wf_id = data.get("workflow_id", "unknown")
        return ActivityUpdate(
            level=ActivityLevel.INFO,
            category="workflow",
            message=f"Recovering workflow {wf_id[:8]} from checkpoint...",
            workflow_id=wf_id,
        )

    # =========================================================================
    # Event Handlers - Task
    # =========================================================================

    def _handle_task_started(self, event: Event, data: Dict) -> ActivityUpdate:
        wf_id = data.get("workflow_id", "unknown")
        task_id = data.get("task_id", "unknown")
        cap = data.get("capability", "a capability")
        return ActivityUpdate(
            level=ActivityLevel.INFO,
            category="task",
            message=f"Running {cap} for step {task_id}",
            workflow_id=wf_id,
            step_id=task_id,
            capability_name=cap,
        )

    def _handle_task_completed(self, event: Event, data: Dict) -> ActivityUpdate:
        wf_id = data.get("workflow_id", "unknown")
        task_id = data.get("task_id", "unknown")
        cap = data.get("capability", "a capability")
        duration = data.get("duration_ms", 0)
        return ActivityUpdate(
            level=ActivityLevel.SUCCESS,
            category="task",
            message=f"Finished {cap} for step {task_id} ({duration:.0f}ms)",
            workflow_id=wf_id,
            step_id=task_id,
            capability_name=cap,
            metadata={"duration_ms": duration},
        )

    def _handle_task_failed(self, event: Event, data: Dict) -> ActivityUpdate:
        wf_id = data.get("workflow_id", "unknown")
        task_id = data.get("task_id", "unknown")
        cap = data.get("capability", "a capability")
        error = data.get("error", "Unknown error")
        retries = data.get("retries", 0)
        return ActivityUpdate(
            level=ActivityLevel.ERROR,
            category="task",
            message=f"Failed {cap} for step {task_id} after {retries} retries: {error}",
            workflow_id=wf_id,
            step_id=task_id,
            capability_name=cap,
            metadata={"error": error, "retries": retries},
        )

    def _handle_task_retrying(self, event: Event, data: Dict) -> ActivityUpdate:
        wf_id = data.get("workflow_id", "unknown")
        task_id = data.get("task_id", "unknown")
        attempt = data.get("attempt", 1)
        max_retries = data.get("max_retries", 3)
        error = data.get("error", "Unknown error")
        return ActivityUpdate(
            level=ActivityLevel.WARNING,
            category="task",
            message=f"Retrying step {task_id} (attempt {attempt}/{max_retries}): {error}",
            workflow_id=wf_id,
            step_id=task_id,
            metadata={"attempt": attempt, "max_retries": max_retries, "error": error},
        )

    # =========================================================================
    # Event Handlers - Capability
    # =========================================================================

    def _handle_capability_registered(self, event: Event, data: Dict) -> ActivityUpdate:
        name = data.get("name", "unknown")
        return ActivityUpdate(
            level=ActivityLevel.INFO,
            category="capability",
            message=f"Registered new capability: {name}",
            capability_name=name,
        )

    def _handle_capability_unregistered(self, event: Event, data: Dict) -> ActivityUpdate:
        name = data.get("name", "unknown")
        return ActivityUpdate(
            level=ActivityLevel.INFO,
            category="capability",
            message=f"Unregistered capability: {name}",
            capability_name=name,
        )

    def _handle_capability_activated(self, event: Event, data: Dict) -> ActivityUpdate:
        name = data.get("name", "unknown")
        return ActivityUpdate(
            level=ActivityLevel.SUCCESS,
            category="capability",
            message=f"Activated capability: {name}",
            capability_name=name,
        )

    def _handle_capability_deactivated(self, event: Event, data: Dict) -> ActivityUpdate:
        name = data.get("name", "unknown")
        return ActivityUpdate(
            level=ActivityLevel.WARNING,
            category="capability",
            message=f"Deactivated capability: {name}",
            capability_name=name,
        )

    def _handle_capability_health_failed(self, event: Event, data: Dict) -> ActivityUpdate:
        name = data.get("name", "unknown")
        return ActivityUpdate(
            level=ActivityLevel.ERROR,
            category="capability",
            message=f"Health check failed for capability: {name}",
            capability_name=name,
        )

    # =========================================================================
    # Event Handlers - Safety
    # =========================================================================

    def _handle_safety_check(self, event: Event, data: Dict) -> ActivityUpdate:
        allowed = data.get("allowed", True)
        risk = data.get("risk_level", "unknown")
        return ActivityUpdate(
            level=ActivityLevel.INFO if allowed else ActivityLevel.WARNING,
            category="safety",
            message=f"Safety check: {'allowed' if allowed else 'blocked'} (risk: {risk})",
            metadata={"allowed": allowed, "risk_level": risk},
        )

    def _handle_safety_approval_requested(self, event: Event, data: Dict) -> ActivityUpdate:
        operation = data.get("operation", "an operation")
        return ActivityUpdate(
            level=ActivityLevel.WARNING,
            category="safety",
            message=f"Approval required for: {operation}",
            metadata=data,
        )

    def _handle_safety_approval_granted(self, event: Event, data: Dict) -> ActivityUpdate:
        operation = data.get("operation", "an operation")
        return ActivityUpdate(
            level=ActivityLevel.SUCCESS,
            category="safety",
            message=f"Approved: {operation}",
            metadata=data,
        )

    def _handle_safety_approval_denied(self, event: Event, data: Dict) -> ActivityUpdate:
        operation = data.get("operation", "an operation")
        return ActivityUpdate(
            level=ActivityLevel.ERROR,
            category="safety",
            message=f"Denied: {operation}",
            metadata=data,
        )

    def _handle_safety_blocked(self, event: Event, data: Dict) -> ActivityUpdate:
        operation = data.get("operation", "an operation")
        reason = data.get("reason", "Policy violation")
        return ActivityUpdate(
            level=ActivityLevel.ERROR,
            category="safety",
            message=f"Blocked: {operation} - {reason}",
            metadata=data,
        )

    # =========================================================================
    # Event Handlers - Learning
    # =========================================================================

    def _handle_learning_reflected(self, event: Event, data: Dict) -> ActivityUpdate:
        task = data.get("task", "a task")
        rif_id = data.get("reflection_id", "unknown")
        return ActivityUpdate(
            level=ActivityLevel.INFO,
            category="learning",
            message=f"Generated reflection for: {task}",
            metadata={"reflection_id": rif_id},
        )

    def _handle_learning_consolidated(self, event: Event, data: Dict) -> ActivityUpdate:
        promoted = data.get("promoted_count", 0)
        archived = data.get("archived_count", 0)
        return ActivityUpdate(
            level=ActivityLevel.SUCCESS,
            category="learning",
            message=f"Memory consolidated: {promoted} memories promoted, {archived} archived",
            metadata=data,
        )

    def _handle_learning_lesson_stored(self, event: Event, data: Dict) -> ActivityUpdate:
        title = data.get("title", "a lesson")
        return ActivityUpdate(
            level=ActivityLevel.INFO,
            category="learning",
            message=f"Learned new lesson: {title}",
            metadata=data,
        )

    # =========================================================================
    # Event Handlers - Goal
    # =========================================================================

    def _handle_goal_created(self, event: Event, data: Dict) -> ActivityUpdate:
        name = data.get("name", "a goal")
        return ActivityUpdate(
            level=ActivityLevel.INFO,
            category="goal",
            message=f"Created goal: {name}",
            metadata=data,
        )

    def _handle_goal_updated(self, event: Event, data: Dict) -> ActivityUpdate:
        name = data.get("name", "a goal")
        progress = data.get("progress", 0)
        return ActivityUpdate(
            level=ActivityLevel.INFO,
            category="goal",
            message=f"Updated goal '{name}': {progress:.0f}% complete",
            metadata=data,
            progress=progress,
        )

    def _handle_goal_completed(self, event: Event, data: Dict) -> ActivityUpdate:
        name = data.get("name", "a goal")
        return ActivityUpdate(
            level=ActivityLevel.SUCCESS,
            category="goal",
            message=f"Completed goal: {name}",
            metadata=data,
            progress=100.0,
        )

    def _handle_goal_failed(self, event: Event, data: Dict) -> ActivityUpdate:
        name = data.get("name", "a goal")
        error = data.get("error", "Unknown error")
        return ActivityUpdate(
            level=ActivityLevel.ERROR,
            category="goal",
            message=f"Goal failed: {name} - {error}",
            metadata=data,
        )

    # =========================================================================
    # Event Handlers - Recovery
    # =========================================================================

    def _handle_recovery_started(self, event: Event, data: Dict) -> ActivityUpdate:
        strategy = data.get("strategy", "recovery")
        return ActivityUpdate(
            level=ActivityLevel.INFO,
            category="recovery",
            message=f"Starting recovery using {strategy} strategy",
            metadata=data,
        )

    def _handle_recovery_completed(self, event: Event, data: Dict) -> ActivityUpdate:
        strategy = data.get("strategy_used", "recovery")
        return ActivityUpdate(
            level=ActivityLevel.SUCCESS,
            category="recovery",
            message=f"Recovery completed using {strategy} strategy",
            metadata=data,
        )

    def _handle_recovery_failed(self, event: Event, data: Dict) -> ActivityUpdate:
        error = data.get("final_failure", "Unknown error")
        return ActivityUpdate(
            level=ActivityLevel.ERROR,
            category="recovery",
            message=f"Recovery failed: {error}",
            metadata=data,
        )

    # =========================================================================
    # Event Handlers - Autonomy
    # =========================================================================

    def _handle_autonomy_cycle_started(self, event: Event, data: Dict) -> ActivityUpdate:
        phase = data.get("phase", "observing")
        return ActivityUpdate(
            level=ActivityLevel.DEBUG,
            category="autonomy",
            message=f"Autonomy cycle: {phase}",
            metadata=data,
        )

    def _handle_autonomy_cycle_completed(self, event: Event, data: Dict) -> ActivityUpdate:
        actions = data.get("actions_taken", 0)
        return ActivityUpdate(
            level=ActivityLevel.INFO,
            category="autonomy",
            message=f"Autonomy cycle completed: {actions} actions taken",
            metadata=data,
        )

    def _handle_autonomy_proposal(self, event: Event, data: Dict) -> ActivityUpdate:
        proposal = data.get("proposal", "a proposal")
        return ActivityUpdate(
            level=ActivityLevel.INFO,
            category="autonomy",
            message=f"Autonomous proposal generated: {proposal[:50]}",
            metadata=data,
        )

    # =========================================================================
    # Event Handlers - Decision
    # =========================================================================

    def _handle_decision_made(self, event: Event, data: Dict) -> ActivityUpdate:
        choice = data.get("choice", "a choice")
        confidence = data.get("confidence", 0)
        return ActivityUpdate(
            level=ActivityLevel.INFO,
            category="decision",
            message=f"Decision made: {choice} (confidence: {confidence:.0%})",
            metadata=data,
        )

    # =========================================================================
    # Event Handlers - Conversation Control
    # =========================================================================

    def _handle_control_stop(self, event: Event, data: Dict) -> ActivityUpdate:
        was_executing = data.get("was_executing", False)
        if was_executing:
            preserved = data.get("preserved_completed_tasks", 0)
            return ActivityUpdate(
                level=ActivityLevel.WARNING,
                category="control",
                message=f"Stopped execution ({preserved} tasks preserved)",
            )
        return ActivityUpdate(
            level=ActivityLevel.INFO,
            category="control",
            message="Stopped",
        )

    def _handle_control_cancel(self, event: Event, data: Dict) -> ActivityUpdate:
        return ActivityUpdate(
            level=ActivityLevel.INFO,
            category="control",
            message="Cancelled",
        )

    def _handle_control_pause(self, event: Event, data: Dict) -> ActivityUpdate:
        task = data.get("paused_at_task", "current task")
        completed = data.get("completed_so_far", 0)
        return ActivityUpdate(
            level=ActivityLevel.WARNING,
            category="control",
            message=f"Paused at '{task}' ({completed} steps done)",
        )

    def _handle_control_resume(self, event: Event, data: Dict) -> ActivityUpdate:
        task = data.get("resuming_at_task", "next task")
        return ActivityUpdate(
            level=ActivityLevel.SUCCESS,
            category="control",
            message=f"Resuming at '{task}'",
        )

    def _handle_control_undo(self, event: Event, data: Dict) -> ActivityUpdate:
        action = data.get("undone_action", "the last action")
        remaining = data.get("remaining_undos", 0)
        return ActivityUpdate(
            level=ActivityLevel.INFO,
            category="control",
            message=f"Undid {action} ({remaining} undos remaining)",
        )

    def _handle_control_redo(self, event: Event, data: Dict) -> ActivityUpdate:
        action = data.get("redone_action", "the action")
        remaining = data.get("remaining_redos", 0)
        return ActivityUpdate(
            level=ActivityLevel.INFO,
            category="control",
            message=f"Redid {action} ({remaining} redos remaining)",
        )

    # =========================================================================
    # Public API
    # =========================================================================

    def _emit_activity(self, activity: ActivityUpdate):
        """Emit activity to all outputs."""
        # Apply plain English formatting
        if self._enable_plain_english and not self._debug_mode:
            activity.message = enforce_plain_english(activity.message, self._debug_mode)

        # Store in history
        with self._lock:
            self._history.append(activity)

        # Call callbacks
        for callback in self._callbacks:
            try:
                callback(activity)
            except Exception as e:
                logger.warning(f"Activity callback failed: {e}")

        # Publish to event bus for GUI streaming
        try:
            self._event_bus.publish(Event(
                name="activity.update",
                data=activity.to_dict(),
                source="activity_reporter",
            ))
        except Exception as e:
            logger.warning(f"Failed to publish activity event: {e}")

    def subscribe(self, callback: Callable[[ActivityUpdate], None]) -> str:
        """Subscribe to activity updates.

        Args:
            callback: Function that receives ActivityUpdate objects

        Returns:
            Subscription ID for later unsubscription
        """
        import uuid
        sub_id = str(uuid.uuid4())
        with self._lock:
            self._callbacks.append(callback)
        return sub_id

    def unsubscribe(self, subscription_id: str) -> bool:
        """Unsubscribe from activity updates."""
        # In production, track by ID
        with self._lock:
            if self._callbacks:
                self._callbacks.pop()
                return True
        return False

    def get_history(
        self,
        limit: int = 100,
        category: Optional[str] = None,
        level: Optional[ActivityLevel] = None,
        workflow_id: Optional[str] = None,
    ) -> List[ActivityUpdate]:
        """Get activity history with optional filters."""
        with self._lock:
            activities = list(self._history)

        # Apply filters
        if category:
            activities = [a for a in activities if a.category == category]
        if level:
            activities = [a for a in activities if a.level == level]
        if workflow_id:
            activities = [a for a in activities if a.workflow_id == workflow_id]

        # Return most recent first, limited
        return activities[-limit:]

    def get_recent_summary(self, count: int = 10) -> str:
        """Get a plain English summary of recent activity."""
        recent = self.get_history(limit=count)
        if not recent:
            return "No recent activity."

        lines = []
        for act in reversed(recent):  # Oldest first for chronological order
            time_str = act.timestamp[11:19]  # HH:MM:SS
            level_prefix = {
                ActivityLevel.SUCCESS: "✓",
                ActivityLevel.ERROR: "✗",
                ActivityLevel.WARNING: "⚠",
                ActivityLevel.INFO: "→",
                ActivityLevel.DEBUG: "·",
            }.get(act.level, "•")
            lines.append(f"  {level_prefix} {time_str} - {act.message}")

        return "Recent activity:\n" + "\n".join(lines)

    def clear_history(self):
        """Clear activity history."""
        with self._lock:
            self._history.clear()

    def set_debug_mode(self, enabled: bool):
        """Enable or disable debug mode."""
        self._debug_mode = enabled
        self._formatter = get_plain_english_formatter(enabled)

    def set_plain_english(self, enabled: bool):
        """Enable or disable plain English formatting."""
        self._enable_plain_english = enabled


# =========================================================================
# Conversational Activity Reporter
# =========================================================================

class ConversationalActivityReporter:
    """
    Activity reporter designed for conversational interfaces.

    Provides natural, human-friendly updates that can be spoken
    or displayed in chat interfaces.
    """

    def __init__(self, activity_reporter: ActivityReporter):
        self._reporter = activity_reporter
        self._last_spoken: Dict[str, datetime] = {}
        self._min_interval_seconds = 2.0  # Don't spam updates

    def should_speak(self, activity: ActivityUpdate) -> bool:
        """Determine if this activity should be spoken/announced."""
        # Always speak errors and important events
        if activity.level in (ActivityLevel.ERROR, ActivityLevel.SUCCESS):
            return True

        # Throttle info messages
        import time
        key = f"{activity.category}:{activity.workflow_id or 'global'}"
        now = datetime.now(timezone.utc)
        last = self._last_spoken.get(key)
        if last and (now - last).total_seconds() < self._min_interval_seconds:
            return False
        self._last_spoken[key] = now
        return True

    def format_for_speech(self, activity: ActivityUpdate) -> str:
        """Format activity for text-to-speech or chat."""
        # Remove technical prefixes, make conversational
        msg = activity.message

        # Add context if helpful
        if activity.workflow_name and activity.workflow_name != activity.workflow_id:
            msg = f"In '{activity.workflow_name}', {msg.lower()}"

        return msg

    def get_status_summary(self) -> str:
        """Get a conversational status summary."""
        return self._reporter.get_recent_summary(5)