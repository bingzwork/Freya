"""Centralized Conversational Control System.

This module provides a single, centralized handler for all conversation control
commands (stop, cancel, pause, resume, undo, redo, status). It integrates
directly with the planner/executor to support interrupting, pausing, resuming,
and cancelling in-flight tasks.

Key features:
- Single point of control for all conversational control commands
- Safe planner interruption with state cleanup
- Pause/resume support for long-running tasks
- Multi-step undo/redo across sessions
- Race condition handling
- Preserves conversation context after interruption
- Automatic state persistence and restoration
- Shared infrastructure: EventBus, BackgroundJobService, ObservabilityHub
"""

import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from app.core.logger import logger
from app.memory.conversation_memory import ConversationMemory, ConversationTurn
from app.planner.plan_manager import Plan, PlanManager, Task, TaskStatus

# Shared infrastructure imports
from app.core.correlation import correlation_scope
from app.core.events import get_event_bus, EventBus, Event
from app.core.background_jobs import get_job_service, BackgroundJobService, JobTriggerConfig, JobTriggerType, JobPriority
from app.core.observability import get_observability_hub, ObservabilityHub, ComponentInfo, ComponentType, HealthResult, HealthStatus


class ControlCommand(Enum):
    """Supported conversational control commands."""
    STOP = "stop"
    HALT = "halt"
    WAIT = "wait"
    CANCEL = "cancel"
    NEVERMIND = "nevermind"
    ABORT = "abort"
    PAUSE = "pause"
    RESUME = "resume"
    UNDO = "undo"
    REDO = "redo"
    STATUS = "status"
    WHAT_ARE_YOU_DOING = "what_are_you_doing"
    CURRENT_PLAN = "current_plan"
    CURRENT_STEP = "current_step"


@dataclass
class ControlState:
    """Tracks the current state of conversational control."""
    # Execution state
    is_executing: bool = False
    is_paused: bool = False
    execution_thread_id: Optional[int] = None

    # Active plan state
    active_plan_id: Optional[str] = None
    active_plan: Optional[Plan] = None
    current_task_id: Optional[str] = None
    current_task_title: Optional[str] = None
    completed_tasks: List[str] = field(default_factory=list)

    # Pause state for resume capability
    paused_plan_state: Optional[Dict[str, Any]] = None
    paused_at_task_index: int = 0

    # Undo/Redo stacks
    undo_stack: List[Dict[str, Any]] = field(default_factory=list)
    redo_stack: List[Dict[str, Any]] = field(default_factory=list)
    max_undo_history: int = 50

    # Lock for thread safety
    _lock: threading.RLock = field(default_factory=threading.RLock)


class ConversationControlHandler:
    """Centralized handler for all conversational control commands.

    This handler manages:
    - Stop/Cancel: Immediately interrupt execution, clean up planner state
    - Pause/Resume: Temporarily suspend and later resume execution
    - Undo/Redo: Multi-step undo/redo across sessions
    - Status: Report current execution state

    All control commands route through this single handler to ensure
    consistent behavior and prevent race conditions.
    """

    def __init__(
        self,
        plan_manager: PlanManager,
        executor: Any = None,
        conversation_memory: Optional[ConversationMemory] = None,
        workspace: str = ".",
        storage_path: str = "data/memory/conversation_control.json",
        # Shared infrastructure
        event_bus: Optional[EventBus] = None,
        job_service: Optional[BackgroundJobService] = None,
        observability: Optional[ObservabilityHub] = None,
        router: Optional[Any] = None,
        memory_coordinator: Optional[Any] = None,
        intelligence: Optional[Any] = None,
        chat_activity: Optional[Any] = None,
    ):
        self.plan_manager = plan_manager
        self.executor = executor
        self.conversation_memory = conversation_memory
        # Question traffic is configured through these existing target
        # components.  ConversationControl is the ingress boundary; it never
        # constructs replacement routers, memory stores, or intelligence.
        self._router = router
        self._memory_coordinator = memory_coordinator
        self._intelligence = intelligence
        self._chat_activity = chat_activity

        # Shared infrastructure
        self.event_bus = event_bus or get_event_bus()
        self.job_service = job_service or get_job_service()
        self.observability = observability or get_observability_hub()

        self._workspace = Path(workspace).resolve()
        self._storage_path = self._workspace / storage_path
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)

        self._state = ControlState()
        self._execution_callback: Optional[Callable[[], None]] = None
        self._pause_event = threading.Event()
        self._pause_event.set()  # Not paused initially
        self._stop_event = threading.Event()
        self._resume_event = threading.Event()

        # Register with observability
        self._register_with_observability()

        # Schedule periodic state persistence
        self._schedule_state_persistence()

        # Load persisted state on initialization
        self._load_persisted_state()

        logger.info("[ConversationControl] Handler initialized with shared infrastructure")

    def _register_with_observability(self) -> None:
        """Register this subsystem with the shared ObservabilityHub."""
        if self.observability:
            from app.core.observability import HealthCheck
            self.observability.add_health_check(HealthCheck(
                name="conversation_control_health",
                component="conversation_control",
                check_func=self._health_check,
                interval_seconds=60.0,
            ))

            # Register component
            self.observability.register_component(ComponentInfo(
                name="ConversationControlHandler",
                component_type=ComponentType.SERVICE,
                version="1.0.0",
                description="Centralized handler for all conversational control commands (stop, cancel, pause, resume, undo, redo, status)",
                metadata={},
            ))

    def _health_check(self) -> HealthResult:
        """Health check for ConversationControlHandler."""
        try:
            is_executing = self._state.is_executing
            is_paused = self._state.is_paused
            has_plan = self._state.active_plan is not None
            return HealthResult(
                name="conversation_control_health",
                component="conversation_control",
                status=HealthStatus.HEALTHY,
                message=f"ConversationControl operational (executing={is_executing}, paused={is_paused}, has_plan={has_plan})",
                metadata={
                    "is_executing": is_executing,
                    "is_paused": is_paused,
                    "has_active_plan": has_plan,
                    "active_plan_id": self._state.active_plan_id,
                    "completed_tasks_count": len(self._state.completed_tasks),
                    "undo_stack_size": len(self._state.undo_stack),
                    "redo_stack_size": len(self._state.redo_stack),
                }
            )
        except Exception as e:
            return HealthResult(
                name="conversation_control_health",
                component="conversation_control",
                status=HealthStatus.UNHEALTHY,
                message=f"Health check failed: {e}",
                metadata={"error": str(e)}
            )

    def _publish_event(
        self,
        event_name: str,
        data: Dict[str, Any],
        *,
        correlation_id: Optional[str] = None,
    ) -> None:
        """Publish an event to the shared EventBus with request correlation."""
        try:
            with correlation_scope(correlation_id, prefix="request"):
                self.event_bus.emit(
                    name=event_name,
                    data=data,
                    source="ConversationControlHandler",
                )
        except Exception as e:
            logger.warning(f"[ConversationControl] Failed to publish event {event_name}: {e}")

    def _schedule_state_persistence(self, interval_seconds: int = 60) -> str:
        """Schedule periodic state persistence using shared BackgroundJobService.

        Args:
            interval_seconds: Interval between saves (default 60s)

        Returns:
            Job ID of the scheduled persistence job
        """
        job_id = "conversation_control_persist_state"
        self.job_service.schedule(
            job_id=job_id,
            func=self._save_persisted_state,
            trigger=JobTriggerConfig(type=JobTriggerType.RECURRING, interval_seconds=interval_seconds),
            priority=JobPriority.LOW,
            max_retries=3,
            replace_existing=True,
        )
        logger.info(f"[ConversationControl] Scheduled state persistence (interval: {interval_seconds}s)")
        return job_id


    # =========================================================================
    # Canonical question ingress
    # =========================================================================

    def configure_question_flow(
        self,
        *,
        router: Any,
        memory_coordinator: Any,
        intelligence: Any,
        chat_activity: Any,
    ) -> None:
        """Attach the target question-flow collaborators after construction."""
        self._router = router
        self._memory_coordinator = memory_coordinator
        self._intelligence = intelligence
        self._chat_activity = chat_activity

    def route_question(self, user_input: str, *, correlation_id: Optional[str] = None, request_context: Optional[Dict[str, Any]] = None) -> Any:
        """Route one normal question through the target ingress contract.

        The control layer obtains bounded context and the active goal through
        ``MemoryCoordinator`` and passes that state to ``UnifiedRouter``.  The
        router then invokes the existing intelligence interface as part of its
        knowledge-first decision; no direct facade-to-router bypass remains.
        """
        if self._router is None or self._memory_coordinator is None:
            raise RuntimeError("ConversationControl question flow is not configured")

        with correlation_scope(correlation_id, prefix="request") as active_correlation_id:
            if self._chat_activity is not None:
                self._chat_activity.chat_started()
            context = {
                "recent_conversation": self._memory_coordinator.get_conversation_context(limit=3),
                "active_goal": self._memory_coordinator.get_active_goal(),
                "ingress": "ConversationControl",
                "correlation_id": active_correlation_id,
                "request_id": active_correlation_id,
                **(request_context or {}),
            }
            self._publish_event(
                "conversation.question.received",
                {"question": user_input[:500], "has_active_goal": context["active_goal"] is not None},
                correlation_id=active_correlation_id,
            )
            route_result = self._router.route(user_input, context=context)
            self._publish_event(
                "conversation.question.routed",
                {"question": user_input[:500], "route_reason": getattr(route_result, "reason", "")},
                correlation_id=active_correlation_id,
            )
            return route_result

    def record_question_exchange(
        self,
        user_input: str,
        response: str,
        *,
        correlation_id: Optional[str] = None,
    ) -> None:
        """Persist both turns through the canonical MemoryCoordinator boundary."""
        if self._memory_coordinator is None:
            raise RuntimeError("ConversationControl memory coordinator is not configured")
        with correlation_scope(correlation_id, prefix="request") as active_correlation_id:
            self._memory_coordinator.record_conversation({"role": "user", "content": user_input})
            self._memory_coordinator.record_conversation({"role": "assistant", "content": response})
            self._publish_event(
                "conversation.question.completed",
                {"response_length": len(response)},
                correlation_id=active_correlation_id,
            )

    def finish_question(self) -> None:
        """End chat activity after the caller has produced the final response."""
        if self._chat_activity is not None:
            self._chat_activity.chat_ended()

    def report_partial_failure(self, task: str, error: str, details: Optional[Dict[str, Any]] = None) -> None:
        """Report an exhausted execution failure through the control boundary."""
        self._publish_event(
            "conversation.execution.partial_failure",
            {"task": task, "error": error, **(details or {})},
        )

    def handle_stop(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Handle 'stop'/'halt'/'wait' command - immediate interruption.

        This is the strongest form of interruption. It:
        1. Sets stop flag for running executor
        2. Cancels any in-flight planner operations
        3. Cleans up planner state (preserves completed tasks)
        4. Returns control to user immediately
        """
        with self._state._lock:
            logger.info("[ConversationControl] STOP command received")

            # Signal stop to executor
            self._stop_event.set()

            # If paused, also signal resume so it can stop cleanly
            self._pause_event.set()
            self._resume_event.set()

            # Record what we're stopping for undo
            if self._state.is_executing and self._state.active_plan:
                self._record_undo_state("stop", {
                    "plan_id": self._state.active_plan_id,
                    "completed_tasks": self._state.completed_tasks.copy(),
                    "current_task_id": self._state.current_task_id,
                    "current_task_title": self._state.current_task_title,
                    "was_executing": True,
                })

            # Clear execution state
            was_executing = self._state.is_executing
            self._state.is_executing = False
            self._state.is_paused = False
            self._state.execution_thread_id = None
            self._state.current_task_id = None
            self._state.current_task_title = None

            # Trigger execution callback if registered
            if self._execution_callback:
                try:
                    self._execution_callback()
                except Exception as e:
                    logger.error(f"[ConversationControl] Execution callback error: {e}")

            # Save state after stop
            self._save_persisted_state()

            # Publish event
            self._publish_event("conversation.control.stop", {
                "was_executing": was_executing,
                "preserved_completed_tasks": len(self._state.completed_tasks),
            })

            if was_executing:
                return {
                    "success": True,
                    "command": "stop",
                    "control_command": "stop",
                    "message": "Stopped. What's next?",
                    "was_executing": True,
                    "preserved_completed_tasks": len(self._state.completed_tasks),
                }
            else:
                return {
                    "success": True,
                    "command": "stop",
                    "control_command": "stop",
                    "message": "Stopped. What's next?",
                    "was_executing": False,
                }

    def register_execution_callback(self, callback: Callable[[], None]) -> None:
        """Register a callback to be invoked when execution should stop.

        This allows external components (like FreyaAgent) to be notified
        when a stop/cancel/pause command is executed.

        Args:
            callback: A callable that takes no arguments and returns None
        """
        self._execution_callback = callback

    def handle_cancel(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Handle 'cancel'/'nevermind'/'abort' command - cancel pending action.

        Similar to stop but semantically indicates user changed their mind
        about a pending operation rather than interrupting active execution.
        """
        with self._state._lock:
            logger.info("[ConversationControl] CANCEL command received")

            self._stop_event.set()
            self._pause_event.set()
            self._resume_event.set()

            # Record for undo
            if self._state.active_plan:
                self._record_undo_state("cancel", {
                    "plan_id": self._state.active_plan_id,
                    "completed_tasks": self._state.completed_tasks.copy(),
                    "current_task_id": self._state.current_task_id,
                    "current_task_title": self._state.current_task_title,
                    "was_executing": self._state.is_executing,
                })

            was_executing = self._state.is_executing
            self._state.is_executing = False
            self._state.is_paused = False
            self._state.execution_thread_id = None
            self._state.current_task_id = None
            self._state.current_task_title = None

            if self._execution_callback:
                try:
                    self._execution_callback()
                except Exception as e:
                    logger.error(f"[ConversationControl] Execution callback error: {e}")

            # Save state after cancel
            self._save_persisted_state()

            # Publish event
            self._publish_event("conversation.control.cancel", {
                "was_executing": was_executing,
            })

            if was_executing:
                return {
                    "success": True,
                    "command": "cancel",
                    "control_command": "cancel",
                    "message": "Cancelled.",
                    "was_executing": True,
                }
            else:
                return {
                    "success": True,
                    "command": "cancel",
                    "control_command": "cancel",
                    "message": "Cancelled.",
                    "was_executing": False,
                }

    def handle_pause(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Handle 'pause' command - temporarily suspend execution.

        Pauses the current execution at the next safe point (between tasks).
        Can be resumed later with 'resume' command.
        """
        with self._state._lock:
            logger.info("[ConversationControl] PAUSE command received")

            if not self._state.is_executing:
                return {
                    "success": True,
                    "command": "pause",
                    "control_command": "pause",
                    "message": "Already idle. Nothing to pause.",
                    "was_executing": False,
                }

            if self._state.is_paused:
                return {
                    "success": True,
                    "command": "pause",
                    "control_command": "pause",
                    "message": "Already paused. Use 'resume' to continue.",
                    "was_executing": True,
                    "already_paused": True,
                }

            # Signal pause - the executor should check this between tasks
            self._pause_event.clear()
            self._state.is_paused = True

            # Save pause state for potential resume
            if self._state.active_plan and self._state.active_plan._graph:
                self._save_pause_state()

            # Save state after pause
            self._save_persisted_state()

            # Publish event
            self._publish_event("conversation.control.pause", {
                "paused_at_task": self._state.current_task_title,
                "completed_so_far": len(self._state.completed_tasks),
            })

            return {
                "success": True,
                "command": "pause",
                "control_command": "pause",
                "message": "Paused. Say 'resume' to continue.",
                "was_executing": True,
                "paused_at_task": self._state.current_task_title,
                "completed_so_far": len(self._state.completed_tasks),
            }

    def handle_resume(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Handle 'resume' command - continue paused execution."""
        with self._state._lock:
            logger.info("[ConversationControl] RESUME command received")

            if not self._state.is_paused:
                return {
                    "success": False,
                    "command": "resume",
                    "control_command": "resume",
                    "message": "Nothing to resume. Not currently paused.",
                    "was_paused": False,
                }

            # Check if we have a valid paused state
            if not self._state.active_plan:
                return {
                    "success": False,
                    "command": "resume",
                    "control_command": "resume",
                    "message": "Cannot resume - no active plan found.",
                    "was_paused": True,
                }

            # Clear pause, signal resume
            self._pause_event.set()
            self._resume_event.set()
            self._state.is_paused = False

            # Save state after resume
            self._save_persisted_state()

            # Publish event
            self._publish_event("conversation.control.resume", {
                "resuming_at_task": self._state.current_task_title,
            })

            return {
                "success": True,
                "command": "resume",
                "control_command": "resume",
                "message": "Resuming...",
                "was_paused": True,
                "resuming_at_task": self._state.current_task_title,
            }

    def handle_undo(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Handle 'undo' command - revert the most recent action.

        Supports multi-step undo across sessions. Restores:
        - Conversation history
        - Planner state (if applicable)
        - User-visible state
        """
        with self._state._lock:
            logger.info("[ConversationControl] UNDO command received")

            if not self._state.undo_stack:
                return {
                    "success": True,
                    "command": "undo",
                    "control_command": "undo",
                    "message": "Nothing to undo in this session.",
                    "can_undo": False,
                }

            # Pop the last action from undo stack
            undo_entry = self._state.undo_stack.pop()

            # Push to redo stack (for potential redo)
            self._state.redo_stack.append(undo_entry)

            # Trim redo stack
            if len(self._state.redo_stack) > self._state.max_undo_history:
                self._state.redo_stack = self._state.redo_stack[-self._state.max_undo_history:]

            # Apply the undo based on action type
            action_type = undo_entry.get("action_type", "unknown")
            state = undo_entry.get("state", {})

            # Restore planner state if applicable
            if action_type in ("stop", "cancel", "finish", "plan_created", "execution_started"):
                if self._state.active_plan_id or state.get("plan_id"):
                    plan_id = self._state.active_plan_id or state.get("plan_id")
                    plan = self.plan_manager.load_plan(plan_id)
                    if plan:
                        self._restore_plan_state(plan, undo_entry)

            # Also undo conversation if possible
            if self.conversation_memory:
                self._undo_conversation(state)

            # Update active plan ID if it was changed
            if "plan_id" in state:
                self._state.active_plan_id = state["plan_id"]
                plan = self.plan_manager.load_plan(state["plan_id"])
                if plan:
                    self._state.active_plan = plan

            # Restore completed tasks
            if "completed_tasks" in state:
                self._state.completed_tasks = state["completed_tasks"]

            # Save state after undo
            self._save_persisted_state()

            # Publish event
            self._publish_event("conversation.control.undo", {
                "undone_action": action_type,
                "remaining_undos": len(self._state.undo_stack),
            })

            return {
                "success": True,
                "command": "undo",
                "control_command": "undo",
                "message": "Done. I've undone the last action.",
                "can_undo": True,
                "undone_action": action_type,
                "remaining_undos": len(self._state.undo_stack),
            }

    def handle_redo(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Handle 'redo' command - reapply the most recently undone action."""
        with self._state._lock:
            logger.info("[ConversationControl] REDO command received")

            if not self._state.redo_stack:
                return {
                    "success": True,
                    "command": "redo",
                    "control_command": "redo",
                    "message": "Nothing to redo.",
                    "can_redo": False,
                }

            # Pop from redo stack
            redo_entry = self._state.redo_stack.pop()

            # Push back to undo stack
            self._state.undo_stack.append(redo_entry)

            # Apply the redo based on action type
            action_type = redo_entry.get("action_type", "unknown")
            state = redo_entry.get("state", {})

            # For redo, we re-apply the action by restoring the state that was present
            # when the action was originally performed (before it was undone)
            if action_type in ("stop", "cancel", "finish", "plan_created", "execution_started"):
                if state.get("plan_id"):
                    plan = self.plan_manager.load_plan(state["plan_id"])
                    if plan:
                        self._restore_plan_state(plan, redo_entry)

            # Redo conversation - restore the turns that were removed
            if self.conversation_memory:
                self._redo_conversation(redo_entry)

            # Restore completed tasks
            if "completed_tasks" in state:
                self._state.completed_tasks = state["completed_tasks"]

            # Restore active plan ID
            if "plan_id" in state:
                self._state.active_plan_id = state["plan_id"]
                plan = self.plan_manager.load_plan(state["plan_id"])
                if plan:
                    self._state.active_plan = plan

            # Save state after redo
            self._save_persisted_state()

            # Publish event
            self._publish_event("conversation.control.redo", {
                "redone_action": action_type,
                "remaining_redos": len(self._state.redo_stack),
            })

            return {
                "success": True,
                "command": "redo",
                "control_command": "redo",
                "message": "Done. I've reapplied the action.",
                "can_redo": True,
                "redone_action": action_type,
                "remaining_redos": len(self._state.redo_stack),
            }

    def handle_status(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Handle 'status'/'what are you doing' command - report current state."""
        with self._state._lock:
            logger.info("[ConversationControl] STATUS command received")

            if not self._state.is_executing:
                return {
                    "success": True,
                    "command": "status",
                    "control_command": "status",
                    "message": "Idle. Waiting for next request.",
                    "is_executing": False,
                    "is_paused": False,
                }

            # Build status message
            parts = []
            if self._state.is_paused:
                parts.append("Paused")
            else:
                parts.append("Working")

            if self._state.active_plan:
                plan_name = self._state.active_plan.config.name
                parts.append(f"on '{plan_name}'")

            if self._state.current_task_title:
                parts.append(f"(current: {self._state.current_task_title})")

            completed = len(self._state.completed_tasks)
            total = len(self._state.active_plan.tasks) if self._state.active_plan else 0
            if total > 0:
                parts.append(f"{completed}/{total} steps done")

            message = " ".join(parts) + ". "

            return {
                "success": True,
                "command": "status",
                "control_command": "status",
                "message": message,
                "is_executing": True,
                "is_paused": self._state.is_paused,
                "plan_name": self._state.active_plan.config.name if self._state.active_plan else None,
                "current_task": self._state.current_task_title,
                "completed_tasks": completed,
                "total_tasks": total,
            }

    # =========================================================================
    # Execution Integration Methods (called by executor/planner)
    # =========================================================================

    def start_execution(self, plan: Plan, execution_thread_id: Optional[int] = None) -> None:
        """Called when execution starts. Sets up control state."""
        with self._state._lock:
            # Handle both Plan objects and dict plans (for tests)
            plan_name = getattr(plan, 'config', None)
            if plan_name:
                plan_name = plan_name.name
            elif isinstance(plan, dict):
                plan_name = plan.get('name', 'unknown')
            logger.info(f"[ConversationControl] Execution started for plan: {plan_name}")

            # Reset stop/pause events
            self._stop_event.clear()
            self._pause_event.set()
            self._resume_event.clear()

            self._state.is_executing = True
            self._state.is_paused = False
            self._state.execution_thread_id = execution_thread_id or threading.get_ident()
            self._state.active_plan_id = getattr(plan, 'id', plan.get('id', str(uuid.uuid4())) if isinstance(plan, dict) else None)
            self._state.active_plan = plan if isinstance(plan, Plan) else None
            self._state.completed_tasks = []
            self._state.current_task_id = None
            self._state.current_task_title = None
            self._state.paused_plan_state = None
            self._state.paused_at_task_index = 0

            # Record plan creation for undo/redo
            if self._state.active_plan_id:
                self._record_undo_state("plan_created", {
                    "plan_id": self._state.active_plan_id,
                    "completed_tasks": [],
                    "was_executing": False,
                })

    def before_task(self, task: Task) -> bool:
        """Called before each task execution. Returns False if should stop."""
        with self._state._lock:
            # Check for stop signal
            if self._stop_event.is_set():
                logger.info("[ConversationControl] Stop signal detected before task")
                return False

            # Wait if paused
            if not self._pause_event.is_set():
                logger.info("[ConversationControl] Paused, waiting for resume...")
                self._pause_event.wait()  # Blocks until resume

                # Check stop again after resume
                if self._stop_event.is_set():
                    return False

            # Update current task
            self._state.current_task_id = task.id
            self._state.current_task_title = task.title

            return True

    def after_task(self, task: Task, success: bool) -> bool:
        """Called after each task execution. Returns False if should stop."""
        with self._state._lock:
            # Check for stop signal
            if self._stop_event.is_set():
                logger.info("[ConversationControl] Stop signal detected after task")
                return False

            if success:
                self._state.completed_tasks.append(task.id)

            # Clear current task
            self._state.current_task_id = None
            self._state.current_task_title = None

            return True

    def finish_execution(self, success: bool = True) -> None:
        """Called when execution finishes (success or failure)."""
        with self._state._lock:
            logger.info(f"[ConversationControl] Execution finished: success={success}")

            # Record final state for potential undo
            if self._state.active_plan:
                self._record_undo_state("finish", {
                    "plan_id": self._state.active_plan_id,
                    "completed_tasks": self._state.completed_tasks.copy(),
                    "success": success,
                    "was_executing": True,
                })

            # Reset state
            self._state.is_executing = False
            self._state.is_paused = False
            self._state.execution_thread_id = None
            self._state.current_task_id = None
            self._state.current_task_title = None
            self._stop_event.clear()
            self._pause_event.set()
            self._resume_event.set()

            # Save state after finish
            self._save_persisted_state()

    def check_stop_requested(self) -> bool:
        """Check if stop was requested (for use in long-running operations)."""
        return self._stop_event.is_set()

    def wait_if_paused(self) -> bool:
        """Wait if paused. Returns False if stop was requested."""
        if not self._pause_event.is_set():
            self._pause_event.wait()
            return not self._stop_event.is_set()
        return True

    # =========================================================================
    # Internal Helper Methods
    # =========================================================================

    def _record_undo_state(self, action_type: str, state: Dict[str, Any]) -> None:
        """Record current state for potential undo.

        Captures comprehensive state including:
        - Plan state (active plan ID, completed tasks, current task)
        - Conversation state (turns that will be affected)
        """
        # Capture conversation state for potential undo
        conversation_state = {}
        if self.conversation_memory:
            turns = self.conversation_memory.get_history()
            # Save the last few turns that would be affected by undo
            # We store the last 4 turns (2 user/assistant pairs) for safety
            conversation_state = {
                "turns_count": len(turns),
                "last_turns": [
                    {"role": t.role, "content": t.content, "timestamp": t.timestamp}
                    for t in turns[-4:]
                ] if turns else [],
            }

        entry = {
            "action_type": action_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "state": {
                **state,
                "conversation": conversation_state,
            },
        }
        self._state.undo_stack.append(entry)

        # Trim undo stack
        if len(self._state.undo_stack) > self._state.max_undo_history:
            self._state.undo_stack = self._state.undo_stack[-self._state.max_undo_history:]

        # Clear redo stack on new action (but NOT on undo - that's handled in handle_undo)
        self._state.redo_stack.clear()

    def _save_pause_state(self) -> None:
        """Save the current execution state for resume."""
        if not self._state.active_plan or not self._state.active_plan._graph:
            return

        # Get task graph state
        graph = self._state.active_plan._graph
        all_task_ids = graph.get_task_order()

        # Find current task index
        current_index = 0
        if self._state.current_task_id:
            try:
                current_index = all_task_ids.index(self._state.current_task_id)
            except ValueError:
                current_index = len(self._state.completed_tasks)

        self._state.paused_plan_state = {
            "plan_id": self._state.active_plan_id,
            "plan_name": self._state.active_plan.config.name,
            "completed_task_ids": self._state.completed_tasks.copy(),
            "current_task_index": current_index,
            "all_task_ids": all_task_ids,
            "task_statuses": {
                task_id: graph.get_task(task_id).status.value
                for task_id in all_task_ids
                if graph.get_task(task_id)
            },
        }
        self._state.paused_at_task_index = current_index

    def _restore_plan_state(self, plan: Plan, undo_entry: Dict[str, Any]) -> None:
        """Restore plan state from undo entry."""
        state = undo_entry.get("state", {})
        completed_tasks = state.get("completed_tasks", [])

        # Restore task statuses
        if plan._graph:
            for task_id in completed_tasks:
                task = plan._graph.get_task(task_id)
                if task:
                    task.status = TaskStatus.COMPLETED

            # Reset current task if it was in progress
            current_task_id = state.get("current_task_id")
            if current_task_id:
                task = plan._graph.get_task(current_task_id)
                if task and task.status == TaskStatus.IN_PROGRESS:
                    task.status = TaskStatus.PENDING

            # Update tracker
            if plan._tracker:
                for task in plan.tasks:
                    plan._tracker.update_task(task)

    def _undo_conversation(self, state: Dict[str, Any]) -> None:
        """Undo the last conversation exchange (user + assistant)."""
        if not self.conversation_memory:
            return

        turns = self.conversation_memory.get_history()
        if not turns:
            return

        # Find the last assistant turn
        for i in range(len(turns) - 1, -1, -1):
            if turns[i].role == "assistant":
                # Remove assistant turn and preceding user turn if present
                self.conversation_memory._turns.pop(i)
                if i > 0 and self.conversation_memory._turns[i - 1].role == "user":
                    self.conversation_memory._turns.pop(i - 1)
                self.conversation_memory._rebuild_entity_index()
                self.conversation_memory._save()
                break

    def _redo_conversation(self, redo_entry: Dict[str, Any]) -> None:
        """Redo (restore) the conversation turns that were removed by undo."""
        if not self.conversation_memory:
            return

        state = redo_entry.get("state", {})
        conversation_state = state.get("conversation", {})
        last_turns = conversation_state.get("last_turns", [])

        if not last_turns:
            return

        # Restore the conversation turns that were saved
        # We need to add them back in order, but only if they don't already exist
        current_turns = self.conversation_memory.get_history()
        current_count = len(current_turns)

        # The saved last_turns represent the turns that were present BEFORE the undo
        # We restore them by adding any that are missing from the current state
        for turn_data in last_turns:
            if current_count >= conversation_state.get("turns_count", 0):
                break
            # Check if this turn already exists (by content and role)
            exists = any(
                t.role == turn_data["role"] and t.content == turn_data["content"]
                for t in self.conversation_memory._turns
            )
            if not exists:
                from app.memory.conversation_memory import ConversationTurn
                turn = ConversationTurn(
                    role=turn_data["role"],
                    content=turn_data["content"],
                    timestamp=turn_data["timestamp"],
                )
                self.conversation_memory._turns.append(turn)

        self.conversation_memory._rebuild_entity_index()
        self.conversation_memory._save()

    def _undo_conversation_turns(self, assistant_index: int) -> None:
        """Remove conversation turns for undo (legacy method, kept for compatibility)."""
        if not self.conversation_memory:
            return

        # Get turns and remove from assistant_index backwards
        turns = self.conversation_memory.get_history()
        if assistant_index < len(turns):
            # Remove assistant turn and preceding user turn if present
            self.conversation_memory._turns.pop(assistant_index)
            if assistant_index > 0 and self.conversation_memory._turns[assistant_index - 1].role == "user":
                self.conversation_memory._turns.pop(assistant_index - 1)
            self.conversation_memory._rebuild_entity_index()
            self.conversation_memory._save()

    # =========================================================================
    # Persistence Support
    # =========================================================================

    def _save_persisted_state(self) -> None:
        """Save control state to disk for cross-session persistence."""
        with self._state._lock:
            try:
                temp_path = self._storage_path.with_suffix(".tmp")
                data = {
                    "undo_stack": self._state.undo_stack,
                    "redo_stack": self._state.redo_stack,
                    "active_plan_id": self._state.active_plan_id,
                    "completed_tasks": self._state.completed_tasks,
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                }
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                temp_path.replace(self._storage_path)
            except Exception as e:
                logger.warning(f"[ConversationControl] Failed to save state: {e}")

    def _load_persisted_state(self) -> None:
        """Load control state from disk for cross-session persistence."""
        if not self._storage_path.exists():
            return
        try:
            with open(self._storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._state.undo_stack = data.get("undo_stack", [])
            self._state.redo_stack = data.get("redo_stack", [])
            self._state.active_plan_id = data.get("active_plan_id")
            self._state.completed_tasks = data.get("completed_tasks", [])

            # If there's an active plan ID, load it
            if self._state.active_plan_id:
                plan = self.plan_manager.load_plan(self._state.active_plan_id)
                if plan:
                    self._state.active_plan = plan
            logger.info(f"[ConversationControl] Loaded persisted state: {len(self._state.undo_stack)} undo entries, {len(self._state.redo_stack)} redo entries")
        except Exception as e:
            logger.warning(f"[ConversationControl] Failed to load state: {e}")
            self._state.undo_stack = []
            self._state.redo_stack = []
            self._state.active_plan_id = None
            self._state.completed_tasks = []

    def get_persistable_state(self) -> Dict[str, Any]:
        """Get state that should be persisted across sessions (backward compat)."""
        with self._state._lock:
            return {
                "undo_stack": self._state.undo_stack,
                "redo_stack": self._state.redo_stack,
                "active_plan_id": self._state.active_plan_id,
                "completed_tasks": self._state.completed_tasks,
            }

    def restore_persisted_state(self, state: Dict[str, Any]) -> None:
        """Restore state from persistence (backward compat)."""
        with self._state._lock:
            self._state.undo_stack = state.get("undo_stack", [])
            self._state.redo_stack = state.get("redo_stack", [])
            self._state.active_plan_id = state.get("active_plan_id")
            self._state.completed_tasks = state.get("completed_tasks", [])

            # If there's an active plan ID, load it
            if self._state.active_plan_id:
                plan = self.plan_manager.load_plan(self._state.active_plan_id)
                if plan:
                    self._state.active_plan = plan

    def save(self) -> None:
        """Explicitly save state to disk."""
        self._save_persisted_state()


# Global instance for registration
_conversation_control_handler: Optional[ConversationControlHandler] = None


def get_conversation_control_handler() -> Optional[ConversationControlHandler]:
    """Get the global conversation control handler."""
    return _conversation_control_handler


def create_conversation_control_handler(
    plan_manager: PlanManager,
    executor: Any = None,
    conversation_memory: Optional[ConversationMemory] = None,
) -> ConversationControlHandler:
    """Create and register the global conversation control handler."""
    global _conversation_control_handler
    # Get workspace from plan_manager
    workspace = getattr(plan_manager, 'workspace', '.')
    _conversation_control_handler = ConversationControlHandler(
        plan_manager=plan_manager,
        executor=executor,
        conversation_memory=conversation_memory,
        workspace=str(workspace),
    )
    return _conversation_control_handler