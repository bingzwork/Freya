"""Task Executor for the Central Autonomous Orchestrator.

Provides long-running task support with pause/resume/cancel/retry,
checkpointing, and recovery capabilities.
"""

import asyncio
import logging
import pickle
import threading
import time
import traceback
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set
from uuid import uuid4

from app.planner.task_graph import TaskGraph
from app.planner.task import Task, TaskPriority, TaskStatus
from app.planner.scheduler import Scheduler, SchedulingStrategy
from app.orchestrator.capability_registry import Capability, CapabilityRegistry, CapabilityState, get_capability_registry
from app.core.events import get_event_bus, Event, EventPriority
from app.core.observability import get_observability_hub, ComponentInfo, ComponentType, HealthCheck
from app.core.background_jobs import get_job_service, JobTriggerConfig, JobTriggerType, JobPriority


logger = logging.getLogger(__name__)


class ExecutionState(Enum):
    """State of a task execution."""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"
    CHECKPOINTING = "checkpointing"
    RECOVERING = "recovering"


@dataclass
class Checkpoint:
    """A checkpoint for task execution recovery."""
    checkpoint_id: str = field(default_factory=lambda: f"cp_{uuid4().hex[:8]}")
    task_id: str = ""
    workflow_id: str = ""
    step_index: int = 0
    completed_steps: List[str] = field(default_factory=list)
    step_outputs: Dict[str, Any] = field(default_factory=dict)
    workflow_state: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionContext:
    """Context for task execution."""
    workflow_id: str
    task_graph: TaskGraph
    capabilities: Dict[str, Capability]
    checkpoint_dir: Path
    global_inputs: Dict[str, Any] = field(default_factory=dict)
    global_outputs: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Runtime state
    current_step_index: int = 0
    completed_steps: Set[str] = field(default_factory=set)
    step_outputs: Dict[str, Any] = field(default_factory=dict)
    step_errors: Dict[str, str] = field(default_factory=dict)
    retries: Dict[str, int] = field(default_factory=dict)

    # Checkpointing
    last_checkpoint: Optional[Checkpoint] = None
    checkpoint_interval: int = 5  # Checkpoint every N steps

    # Control
    pause_requested: bool = False
    cancel_requested: bool = False
    max_retries: int = 3


class TaskExecutor:
    """
    Executes composed workflows with full lifecycle management:
    - Pause/Resume/Cancel
    - Retry with exponential backoff
    - Checkpointing for recovery
    - Parallel execution with resource management
    """

    def __init__(
        self,
        registry: Optional[CapabilityRegistry] = None,
        checkpoint_dir: Optional[Path] = None,
        max_concurrent_workflows: int = 10,
    ):
        self.registry = registry or get_capability_registry()
        self.checkpoint_dir = checkpoint_dir or Path("data/checkpoints")
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        self._scheduler = Scheduler()
        self._event_bus = get_event_bus()
        self._observability = get_observability_hub()
        self._job_service = get_job_service()

        self._max_concurrent = max_concurrent_workflows
        self._active_executions: Dict[str, ExecutionContext] = {}
        self._execution_states: Dict[str, ExecutionState] = {}
        self._execution_threads: Dict[str, threading.Thread] = {}
        self._lock = threading.RLock()

        # Register with observability
        self._observability.register_component(ComponentInfo(
            name="TaskExecutor",
            component_type=ComponentType.SERVICE,
            version="1.0.0",
            description="Long-running task execution with checkpointing and recovery",
            metadata={}
        ))

        # Register health check
        self._observability.add_health_check(HealthCheck(
            name="task_executor_health",
            component="task_executor",
            check_func=self._health_check,
            interval_seconds=30.0,
            component_type=ComponentType.SERVICE,
        ))

    def execute(
        self,
        workflow_id: str,
        task_graph: TaskGraph,
        capabilities: Dict[str, Capability],
        global_inputs: Optional[Dict[str, Any]] = None,
        async_mode: bool = True,
    ) -> str:
        """
        Execute a workflow.

        Args:
            workflow_id: Unique identifier for the workflow execution
            task_graph: The TaskGraph to execute
            capabilities: Map of capability name -> Capability instance
            global_inputs: Initial inputs for the workflow
            async_mode: If True, run in background thread

        Returns:
            Execution ID (same as workflow_id)
        """
        with self._lock:
            if len(self._active_executions) >= self._max_concurrent:
                raise RuntimeError(f"Max concurrent workflows ({self._max_concurrent}) reached")

            if workflow_id in self._active_executions:
                raise ValueError(f"Workflow {workflow_id} already executing")

            # Create execution context
            context = ExecutionContext(
                workflow_id=workflow_id,
                task_graph=task_graph,
                capabilities=capabilities,
                checkpoint_dir=self.checkpoint_dir / workflow_id,
                global_inputs=global_inputs or {},
            )
            context.checkpoint_dir.mkdir(parents=True, exist_ok=True)

            self._active_executions[workflow_id] = context
            self._execution_states[workflow_id] = ExecutionState.QUEUED

        try:
            if async_mode:
                thread = threading.Thread(
                    target=self._execute_workflow,
                    args=(workflow_id,),
                    daemon=True,
                    name=f"Executor-{workflow_id[:8]}"
                )
                self._execution_threads[workflow_id] = thread
                thread.start()
            else:
                self._execute_workflow(workflow_id)

            return workflow_id
        except Exception as e:
            with self._lock:
                self._execution_states[workflow_id] = ExecutionState.FAILED
                if workflow_id in self._active_executions:
                    del self._active_executions[workflow_id]
            raise

    def _execute_workflow(self, workflow_id: str):
        """Main workflow execution loop."""
        context = self._active_executions.get(workflow_id)
        if not context:
            return

        self._set_state(workflow_id, ExecutionState.RUNNING)
        self._publish_event("workflow.started", {"workflow_id": workflow_id})

        start_time = time.time()
        error = None

        try:
            # Try to recover from checkpoint
            if self._recover_from_checkpoint(context):
                logger.info(f"Recovered workflow {workflow_id} from checkpoint")
                self._publish_event("workflow.recovered", {"workflow_id": workflow_id})

            # Execute tasks in topological order
            self._execute_tasks(context)

            # Mark completed
            self._set_state(workflow_id, ExecutionState.COMPLETED)
            self._publish_event("workflow.completed", {
                "workflow_id": workflow_id,
                "duration_seconds": time.time() - start_time,
                "outputs": context.global_outputs
            })

        except Exception as e:
            error = str(e)
            logger.error(f"Workflow {workflow_id} failed: {e}")
            logger.error(traceback.format_exc())

            self._set_state(workflow_id, ExecutionState.FAILED)
            self._publish_event("workflow.failed", {
                "workflow_id": workflow_id,
                "error": error,
                "duration_seconds": time.time() - start_time
            })

        finally:
            # Cleanup
            with self._lock:
                if workflow_id in self._execution_threads:
                    del self._execution_threads[workflow_id]

    def _execute_tasks(self, context: ExecutionContext):
        """Execute tasks in the task graph."""
        task_graph = context.task_graph

        # Get execution order (topological sort)
        execution_order = task_graph.get_execution_order()

        for step_index, task_id in enumerate(execution_order):
            # Check for pause/cancel
            if context.cancel_requested:
                self._set_state(context.workflow_id, ExecutionState.CANCELLED)
                self._publish_event("workflow.cancelled", {"workflow_id": context.workflow_id})
                return

            while context.pause_requested:
                self._set_state(context.workflow_id, ExecutionState.PAUSED)
                self._publish_event("workflow.paused", {"workflow_id": context.workflow_id})
                time.sleep(0.5)
                # Wait for resume
                if context.cancel_requested:
                    return

            self._set_state(context.workflow_id, ExecutionState.RUNNING)
            context.current_step_index = step_index

            task = task_graph.get_task(task_id)
            if not task:
                continue

            # Execute task with retry logic
            self._execute_task(context, task)

            # Checkpoint periodically
            if step_index % context.checkpoint_interval == 0:
                self._create_checkpoint(context)

        # Final checkpoint on completion
        self._create_checkpoint(context)

    def _execute_task(self, context: ExecutionContext, task: Task):
        """Execute a single task."""
        workflow_id = context.workflow_id
        task_id = task.id

        capability_name = task.metadata.get("capability_name")
        if not capability_name:
            task.status = TaskStatus.FAILED
            task.error = "No capability_name in task metadata"
            return

        capability = context.capabilities.get(capability_name)
        if not capability:
            task.status = TaskStatus.FAILED
            task.error = f"Capability {capability_name} not available"
            return

        if capability.state != CapabilityState.ACTIVE:
            task.status = TaskStatus.FAILED
            task.error = f"Capability {capability_name} not active (state: {capability.state})"
            return

        self._publish_event("task.started", {
            "workflow_id": workflow_id,
            "task_id": task_id,
            "capability": capability_name
        })

        # Prepare inputs
        inputs = self._prepare_task_inputs(context, task)

        # Retry logic
        max_retries = context.max_retries
        retry_count = context.retries.get(task_id, 0)

        while retry_count <= max_retries:
            try:
                # Execute the capability
                task.status = TaskStatus.IN_PROGRESS
                start_time = time.time()

                # Call the capability's execute method
                result = self._invoke_capability(capability, task, inputs)

                duration_ms = (time.time() - start_time) * 1000
                capability.record_success(duration_ms)

                # Store outputs
                context.step_outputs[task_id] = result
                context.completed_steps.add(task_id)
                task.status = TaskStatus.COMPLETED
                task.result = result
                task.completed_at = datetime.now(timezone.utc).isoformat()

                self._publish_event("task.completed", {
                    "workflow_id": workflow_id,
                    "task_id": task_id,
                    "capability": capability_name,
                    "duration_ms": duration_ms
                })

                break  # Success, exit retry loop

            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000 if 'start_time' in locals() else 0
                capability.record_failure(str(e))

                retry_count += 1
                context.retries[task_id] = retry_count
                context.step_errors[task_id] = str(e)

                if retry_count <= max_retries:
                    self._set_state(workflow_id, ExecutionState.RETRYING)
                    self._publish_event("task.retrying", {
                        "workflow_id": workflow_id,
                        "task_id": task_id,
                        "attempt": retry_count,
                        "max_retries": max_retries,
                        "error": str(e)
                    })
                    # Exponential backoff
                    backoff = min(2 ** retry_count, 60)  # Cap at 60 seconds
                    time.sleep(backoff)
                else:
                    # All retries exhausted
                    task.status = TaskStatus.FAILED
                    task.error = f"Failed after {max_retries} retries: {e}"
                    context.step_errors[task_id] = str(e)

                    self._set_state(workflow_id, ExecutionState.FAILED)
                    self._publish_event("task.failed", {
                        "workflow_id": workflow_id,
                        "task_id": task_id,
                        "capability": capability_name,
                        "error": str(e),
                        "retries": retry_count
                    })
                    raise

    def _prepare_task_inputs(self, context: ExecutionContext, task: Task) -> Dict[str, Any]:
        """Prepare inputs for a task from global inputs and previous step outputs."""
        inputs = context.global_inputs.copy()

        # Add step outputs from dependencies
        for dep_id in task.dependencies:
            if dep_id in context.step_outputs:
                inputs[f"dependency.{dep_id}"] = context.step_outputs[dep_id]

        # Add task-specific inputs from metadata
        task_inputs = task.metadata.get("inputs", {})
        for key, value in task_inputs.items():
            # Resolve template variables like ${steps.xxx.outputs.yyy}
            if isinstance(value, str) and value.startswith("${"):
                resolved = self._resolve_template(value, context)
                inputs[key] = resolved
            else:
                inputs[key] = value

        return inputs

    def _resolve_template(self, template: str, context: ExecutionContext) -> Any:
        """Resolve template variables in inputs."""
        # Simple template resolution for ${steps.TASK_ID.outputs.KEY}
        import re
        pattern = r'\$\{steps\.([^.]+)\.outputs\.([^}]+)\}'

        def replace(match):
            task_id = match.group(1)
            key = match.group(2)
            if task_id in context.step_outputs:
                output = context.step_outputs[task_id]
                if isinstance(output, dict) and key in output:
                    return output[key]
            return match.group(0)  # Return original if not found

        result = re.sub(pattern, replace, template)
        return result

    def _invoke_capability(self, capability: Capability, task: Task, inputs: Dict[str, Any]) -> Any:
        """Invoke a capability's execute method."""
        action = task.metadata.get("action", "execute")

        # Try to call the capability's execute method
        if hasattr(capability, 'execute'):
            return capability.execute(action, inputs)
        elif hasattr(capability, 'run'):
            return capability.run(inputs)
        elif hasattr(capability, '__call__'):
            return capability(inputs)
        else:
            # Default: try to find a method matching the action
            method = getattr(capability, action, None)
            if method:
                return method(inputs)
            raise NotImplementedError(f"Capability {capability.name} has no execute method or action '{action}'")

    def _create_checkpoint(self, context: ExecutionContext):
        """Create a checkpoint for recovery."""
        workflow_id = context.workflow_id
        context.last_checkpoint = Checkpoint(
            task_id=list(context.completed_steps)[-1] if context.completed_steps else "",
            workflow_id=workflow_id,
            step_index=context.current_step_index,
            completed_steps=list(context.completed_steps),
            step_outputs=context.step_outputs.copy(),
            workflow_state={
                "global_inputs": context.global_inputs,
                "global_outputs": context.global_outputs,
                "metadata": context.metadata,
            }
        )

        # Save to disk
        checkpoint_path = context.checkpoint_dir / f"checkpoint_{context.last_checkpoint.checkpoint_id}.pkl"
        try:
            with open(checkpoint_path, 'wb') as f:
                pickle.dump(context.last_checkpoint, f)
            logger.debug(f"Created checkpoint {context.last_checkpoint.checkpoint_id} for {workflow_id}")
        except Exception as e:
            logger.error(f"Failed to save checkpoint: {e}")

    def _recover_from_checkpoint(self, context: ExecutionContext) -> bool:
        """Recover from the latest checkpoint."""
        checkpoint_files = sorted(context.checkpoint_dir.glob("checkpoint_*.pkl"))
        if not checkpoint_files:
            return False

        latest_checkpoint = checkpoint_files[-1]
        try:
            with open(latest_checkpoint, 'rb') as f:
                checkpoint: Checkpoint = pickle.load(f)

            # Restore state
            context.completed_steps = set(checkpoint.completed_steps)
            context.step_outputs = checkpoint.step_outputs.copy()
            context.global_inputs.update(checkpoint.workflow_state.get("global_inputs", {}))
            context.global_outputs.update(checkpoint.workflow_state.get("global_outputs", {}))
            context.metadata.update(checkpoint.workflow_state.get("metadata", {}))

            context.last_checkpoint = checkpoint
            self._set_state(context.workflow_id, ExecutionState.RECOVERING)
            self._publish_event("workflow.recovering", {"workflow_id": context.workflow_id})

            return True
        except Exception as e:
            logger.error(f"Failed to recover from checkpoint: {e}")
            return False

    def pause(self, workflow_id: str) -> bool:
        """Pause a running workflow."""
        with self._lock:
            context = self._active_executions.get(workflow_id)
            if not context:
                return False
            if self._execution_states.get(workflow_id) != ExecutionState.RUNNING:
                return False
            context.pause_requested = True
            return True

    def resume(self, workflow_id: str) -> bool:
        """Resume a paused workflow."""
        with self._lock:
            context = self._active_executions.get(workflow_id)
            if not context:
                return False
            if self._execution_states.get(workflow_id) != ExecutionState.PAUSED:
                return False
            context.pause_requested = False
            return True

    def cancel(self, workflow_id: str) -> bool:
        """Cancel a workflow."""
        with self._lock:
            context = self._active_executions.get(workflow_id)
            if not context:
                return False
            context.cancel_requested = True
            return True

    def get_status(self, workflow_id: str) -> Optional[ExecutionState]:
        """Get the execution state of a workflow."""
        return self._execution_states.get(workflow_id)

    def get_context(self, workflow_id: str) -> Optional[ExecutionContext]:
        """Get the execution context (for inspection)."""
        return self._active_executions.get(workflow_id)

    def list_active_workflows(self) -> List[str]:
        """List all active workflow IDs."""
        with self._lock:
            return list(self._active_executions.keys())

    def _set_state(self, workflow_id: str, state: ExecutionState):
        """Set the execution state."""
        with self._lock:
            self._execution_states[workflow_id] = state

    def _publish_event(self, event_type: str, payload: Dict[str, Any]):
        """Publish an event to the event bus."""
        try:
            event = Event(
                name=event_type,
                data=payload,
                source="task_executor",
                priority=EventPriority.NORMAL
            )
            self._event_bus.publish(event)
        except Exception as e:
            logger.warning(f"Failed to publish event {event_type}: {e}")

    def _health_check(self) -> Dict[str, Any]:
        """Health check for the executor."""
        with self._lock:
            active = len(self._active_executions)
            states = defaultdict(int)
            for state in self._execution_states.values():
                states[state.value] += 1

        return {
            "active_workflows": active,
            "max_concurrent": self._max_concurrent,
            "states": dict(states),
            "healthy": active < self._max_concurrent
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get executor statistics."""
        with self._lock:
            return {
                "active_workflows": len(self._active_executions),
                "max_concurrent": self._max_concurrent,
                "states": {s.value: sum(1 for st in self._execution_states.values() if st == s)
                          for s in ExecutionState},
                "checkpoint_dir": str(self.checkpoint_dir)
            }


# Capability base class extension for executor
class ExecutableCapability(Capability):
    """Base class for capabilities that can be executed by the TaskExecutor."""

    @abstractmethod
    def execute(self, action: str, inputs: Dict[str, Any]) -> Any:
        """Execute a specific action with inputs."""
        pass