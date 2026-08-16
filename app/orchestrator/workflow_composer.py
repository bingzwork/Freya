"""Dynamic Workflow Composer for the Central Autonomous Orchestrator.

This module composes executable workflows from available capabilities based on
user intent, goals, context, and capability metadata. It uses the CapabilityRegistry
to discover and select appropriate capabilities, then constructs a TaskGraph
for execution.
"""

import logging
import threading
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from uuid import uuid4

from app.orchestrator.capability_registry import (
    Capability, CapabilityCategory, CapabilityMetadata, CapabilityRegistry, CapabilityState, get_capability_registry
)
from app.planner.task_graph import TaskGraph
from app.planner.task import Task, TaskPriority, TaskStatus
from app.planner.scheduler import Scheduler, SchedulingStrategy
from app.planner.resource_allocator import ResourceAllocator, Resource, ResourceType
from app.decision.manager import DecisionManager, DecisionContext, DecisionType, DecisionCategory
from app.intent.classifier import IntentClassifier, IntentType
from app.core.events import get_event_bus, Event, EventPriority
from app.core.observability import get_observability_hub, ComponentInfo, ComponentType
from app.memory.unified_retrieval import UnifiedRetrieval


logger = logging.getLogger(__name__)


class WorkflowStrategy(Enum):
    """Strategy for workflow composition."""
    SEQUENTIAL = "sequential"           # Execute capabilities in sequence
    PARALLEL = "parallel"               # Execute independent capabilities in parallel
    PIPELINE = "pipeline"               # Chain capabilities (output of one feeds next)
    ADAPTIVE = "adaptive"               # Decision-driven dynamic composition
    FAN_OUT_FAN_IN = "fan_out_fan_in"   # Parallel branches converging


class WorkflowStatus(Enum):
    """Status of a composed workflow."""
    PENDING = "pending"
    COMPOSING = "composing"
    READY = "ready"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class WorkflowStep:
    """A single step in a composed workflow."""
    step_id: str = field(default_factory=lambda: f"step_{uuid4().hex[:8]}")
    capability_name: str = ""
    capability_category: CapabilityCategory = CapabilityCategory.CUSTOM
    action: str = ""
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)  # Expected output keys
    depends_on: List[str] = field(default_factory=list)  # Step IDs
    condition: Optional[str] = None  # Optional condition expression
    retry_policy: Dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float = 30.0
    priority: TaskPriority = TaskPriority.MEDIUM
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowSpec:
    """Specification for a workflow to be composed."""
    workflow_id: str = field(default_factory=lambda: f"wf_{uuid4().hex[:8]}")
    name: str = ""
    description: str = ""
    intent: Optional[IntentType] = None
    goal_id: Optional[str] = None
    strategy: WorkflowStrategy = WorkflowStrategy.ADAPTIVE
    required_capabilities: List[str] = field(default_factory=list)  # Capability names
    preferred_capabilities: List[str] = field(default_factory=list)
    excluded_capabilities: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    constraints: Dict[str, Any] = field(default_factory=dict)
    success_criteria: List[str] = field(default_factory=list)
    max_steps: int = 20
    max_parallel: int = 5
    timeout_seconds: float = 300.0


@dataclass
class ComposedWorkflow:
    """A fully composed workflow ready for execution."""
    spec: WorkflowSpec
    steps: List[WorkflowStep] = field(default_factory=list)
    task_graph: Optional[TaskGraph] = None
    status: WorkflowStatus = WorkflowStatus.PENDING
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class CapabilitySelector(ABC):
    """Abstract base for capability selection strategies."""

    @abstractmethod
    def select(self, spec: WorkflowSpec, registry: CapabilityRegistry) -> List[Capability]:
        """Select capabilities for the workflow spec."""
        pass


class IntentBasedSelector(CapabilitySelector):
    """Select capabilities based on classified intent."""

    # Intent to category mapping
    INTENT_CATEGORIES = {
        IntentType.TASK: [CapabilityCategory.EXECUTION, CapabilityCategory.PLANNING],
        IntentType.CODE_TASK: [CapabilityCategory.EXECUTION, CapabilityCategory.PLANNING, CapabilityCategory.REASONING],
        IntentType.FILE_OPERATION: [CapabilityCategory.EXECUTION, CapabilityCategory.KNOWLEDGE],
        IntentType.TOOL_REQUEST: [CapabilityCategory.TOOL, CapabilityCategory.EXECUTION],
        IntentType.GIT_OPERATION: [CapabilityCategory.EXECUTION, CapabilityCategory.RECOVERY],
        IntentType.QUESTION: [CapabilityCategory.KNOWLEDGE, CapabilityCategory.REASONING, CapabilityCategory.MEMORY],
        IntentType.SYSTEM_STATUS: [CapabilityCategory.MONITORING, CapabilityCategory.KNOWLEDGE],
    }

    def select(self, spec: WorkflowSpec, registry: CapabilityRegistry) -> List[Capability]:
        if not spec.intent:
            return []

        categories = self.INTENT_CATEGORIES.get(spec.intent, [])
        if not categories:
            return []

        selected = []
        for cat in categories:
            caps = registry.get_capabilities_by_category(cat)
            for cap in caps:
                if cap.metadata.name not in spec.excluded_capabilities:
                    selected.append(cap)

        return selected


class KeywordBasedSelector(CapabilitySelector):
    """Select capabilities based on keywords in the spec context."""

    def select(self, spec: WorkflowSpec, registry: CapabilityRegistry) -> List[Capability]:
        keywords = []

        # Extract keywords from context
        if "user_query" in spec.context:
            keywords.extend(spec.context["user_query"].lower().split())
        if "keywords" in spec.context:
            keywords.extend(spec.context["keywords"])
        if "tags" in spec.context:
            keywords.extend(spec.context["tags"])

        if not keywords:
            return []

        # Find capabilities matching keywords
        return registry.find_capabilities_by_keywords(keywords)


class DependencyAwareSelector(CapabilitySelector):
    """Select capabilities respecting dependencies and conflicts."""

    def select(self, spec: WorkflowSpec, registry: CapabilityRegistry) -> List[Capability]:
        # Start with required capabilities
        selected_names = set(spec.required_capabilities)
        selected = []

        # Add required capabilities and their dependencies
        for name in spec.required_capabilities:
            cap = registry.get_capability(name)
            if cap and cap.state == CapabilityState.ACTIVE:
                selected.append(cap)
                # Add dependencies
                for dep_name in cap.metadata.depends_on:
                    if dep_name not in selected_names:
                        dep_cap = registry.get_capability(dep_name)
                        if dep_cap and dep_cap.state == CapabilityState.ACTIVE:
                            selected.append(dep_cap)
                            selected_names.add(dep_name)

        # Add preferred capabilities if they don't conflict
        for name in spec.preferred_capabilities:
            if name in selected_names:
                continue
            cap = registry.get_capability(name)
            if cap and cap.state == CapabilityState.ACTIVE:
                if self._check_no_conflicts(cap, selected):
                    selected.append(cap)
                    selected_names.add(name)

        return selected

    def _check_no_conflicts(self, cap: Capability, existing: List[Capability]) -> bool:
        for existing_cap in existing:
            if cap.metadata.name in existing_cap.metadata.conflicts_with:
                return False
            if existing_cap.metadata.name in cap.metadata.conflicts_with:
                return False
        return True


class WorkflowComposer:
    """
    Dynamically composes executable workflows from capabilities.

    This is the core of the Central Autonomous Orchestrator - it takes
    high-level intent/goals and composes a concrete execution plan
    using available capabilities from the registry.
    """

    def __init__(
        self,
        registry: Optional[CapabilityRegistry] = None,
        decision_manager: Optional[DecisionManager] = None,
        intent_classifier: Optional[IntentClassifier] = None,
        memory_retrieval: Optional[UnifiedRetrieval] = None,
    ):
        self.registry = registry or get_capability_registry()
        self.decision_manager = decision_manager
        self.intent_classifier = intent_classifier
        self.memory_retrieval = memory_retrieval

        self._scheduler = Scheduler()
        self._resource_allocator = ResourceAllocator()
        self._event_bus = get_event_bus()
        self._observability = get_observability_hub()

        # Selectors for capability discovery
        self._selectors: List[CapabilitySelector] = [
            DependencyAwareSelector(),
            IntentBasedSelector(),
            KeywordBasedSelector(),
        ]

        # Composition strategies
        self._strategies: Dict[WorkflowStrategy, Callable] = {
            WorkflowStrategy.SEQUENTIAL: self._compose_sequential,
            WorkflowStrategy.PARALLEL: self._compose_parallel,
            WorkflowStrategy.PIPELINE: self._compose_pipeline,
            WorkflowStrategy.ADAPTIVE: self._compose_adaptive,
            WorkflowStrategy.FAN_OUT_FAN_IN: self._compose_fan_out_fan_in,
        }

        self._lock = threading.RLock()
        self._composed_workflows: Dict[str, ComposedWorkflow] = {}

        # Register with observability
        self._observability.register_component(ComponentInfo(
            name="WorkflowComposer",
            component_type=ComponentType.SERVICE,
            version="1.0.0",
            description="Dynamic workflow composition from capabilities",
            metadata={}
        ))

    def compose(self, spec: WorkflowSpec) -> ComposedWorkflow:
        """
        Compose a workflow from the specification.

        This is the main entry point for dynamic workflow composition.
        """
        with self._lock:
            logger.info(f"Composing workflow: {spec.name} ({spec.workflow_id})")

            # Update status
            workflow = ComposedWorkflow(spec=spec, status=WorkflowStatus.COMPOSING)
            self._composed_workflows[spec.workflow_id] = workflow

        try:
            # Step 1: Select capabilities
            capabilities = self._select_capabilities(spec)
            logger.info(f"Selected {len(capabilities)} capabilities for workflow")

            # Step 2: Determine composition strategy
            strategy = self._determine_strategy(spec, capabilities)

            # Step 3: Compose workflow steps
            steps = self._strategies[strategy](spec, capabilities)

            # Step 4: Build task graph
            task_graph = self._build_task_graph(spec, steps)

            # Step 5: Validate workflow
            if not self._validate_workflow(workflow, steps):
                raise ValueError("Workflow validation failed")

            # Update workflow
            with self._lock:
                workflow.steps = steps
                workflow.task_graph = task_graph
                workflow.status = WorkflowStatus.READY
                workflow.metadata["strategy_used"] = strategy.value
                workflow.metadata["capabilities_used"] = [c.metadata.name for c in capabilities]

            self._publish_event("workflow.composed", {
                "workflow_id": spec.workflow_id,
                "name": spec.name,
                "steps": len(steps),
                "strategy": strategy.value
            })

            logger.info(f"Workflow composed successfully: {len(steps)} steps")
            return workflow

        except Exception as e:
            logger.error(f"Workflow composition failed: {e}")
            with self._lock:
                workflow.status = WorkflowStatus.FAILED
                workflow.metadata["error"] = str(e)
            raise

    def _select_capabilities(self, spec: WorkflowSpec) -> List[Capability]:
        """Select capabilities using all registered selectors."""
        all_selected = []
        seen_names = set()

        # Always include explicitly required capabilities
        for name in spec.required_capabilities:
            cap = self.registry.get_capability(name)
            if cap and cap.state == CapabilityState.ACTIVE and name not in seen_names:
                all_selected.append(cap)
                seen_names.add(name)

        # Run each selector
        for selector in self._selectors:
            try:
                selected = selector.select(spec, self.registry)
                for cap in selected:
                    if cap.metadata.name not in seen_names and cap.state == CapabilityState.ACTIVE:
                        all_selected.append(cap)
                        seen_names.add(cap.metadata.name)
            except Exception as e:
                logger.warning(f"Selector {selector.__class__.__name__} failed: {e}")

        # Filter by max capabilities
        if len(all_selected) > spec.max_steps:
            # Prioritize required > preferred > others
            prioritized = []
            for cap in all_selected:
                if cap.metadata.name in spec.required_capabilities:
                    prioritized.insert(0, cap)
                elif cap.metadata.name in spec.preferred_capabilities:
                    prioritized.append(cap)
                else:
                    prioritized.append(cap)
            all_selected = prioritized[:spec.max_steps]

        return all_selected

    def _determine_strategy(self, spec: WorkflowSpec, capabilities: List[Capability]) -> WorkflowStrategy:
        """Determine the best composition strategy."""
        # If explicitly specified, use it
        if spec.strategy != WorkflowStrategy.ADAPTIVE:
            return spec.strategy

        # Adaptive strategy selection based on capabilities and context
        if not capabilities:
            return WorkflowStrategy.SEQUENTIAL

        # Check if capabilities have data dependencies (pipeline)
        has_pipeline_potential = any(
            cap.metadata.provides for cap in capabilities
        )

        # Check for parallelizable independent capabilities
        independent_count = sum(
            1 for cap in capabilities
            if not cap.metadata.depends_on
        )

        # Check intent for guidance
        if spec.intent == IntentType.CODE_TASK:
            return WorkflowStrategy.PIPELINE
        elif spec.intent == IntentType.QUESTION:
            return WorkflowStrategy.FAN_OUT_FAN_IN
        elif spec.intent == IntentType.TASK:
            return WorkflowStrategy.SEQUENTIAL
        elif independent_count > 2 and len(capabilities) > 3:
            return WorkflowStrategy.PARALLEL
        elif has_pipeline_potential:
            return WorkflowStrategy.PIPELINE
        else:
            return WorkflowStrategy.SEQUENTIAL

    def _compose_sequential(self, spec: WorkflowSpec, capabilities: List[Capability]) -> List[WorkflowStep]:
        """Compose capabilities in sequential order."""
        steps = []
        previous_step_id = None

        for i, cap in enumerate(capabilities):
            # Use the capability's default action
            action = cap.metadata.default_action or f"execute_{cap.metadata.name}"
            step = WorkflowStep(
                capability_name=cap.metadata.name,
                capability_category=cap.metadata.category,
                action=action,
                depends_on=[previous_step_id] if previous_step_id else [],
                timeout_seconds=cap.metadata.timeout_seconds,
                priority=TaskPriority.MEDIUM,
                metadata={"step_index": i, "capability_version": cap.metadata.version}
            )
            steps.append(step)
            previous_step_id = step.step_id

        return steps

    def _compose_parallel(self, spec: WorkflowSpec, capabilities: List[Capability]) -> List[WorkflowStep]:
        """Compose capabilities for parallel execution (with max_parallel limit)."""
        steps = []
        # Group capabilities into batches of max_parallel
        for i in range(0, len(capabilities), spec.max_parallel):
            batch = capabilities[i:i + spec.max_parallel]
            # First batch has no dependencies, subsequent batches depend on previous batch completion
            depends_on = []
            if i > 0:
                # Depend on all steps from previous batch
                batch_start = i - spec.max_parallel
                batch_end = i
                depends_on = [f"step_{j}" for j in range(batch_start, min(batch_end, len(steps)))]

            for j, cap in enumerate(batch):
                step_idx = i + j
                action = cap.metadata.default_action or f"execute_{cap.metadata.name}"
                step = WorkflowStep(
                    capability_name=cap.metadata.name,
                    capability_category=cap.metadata.category,
                    action=action,
                    depends_on=depends_on,
                    timeout_seconds=cap.metadata.timeout_seconds,
                    priority=TaskPriority.NORMAL,
                    metadata={"step_index": step_idx, "batch": i // spec.max_parallel, "capability_version": cap.metadata.version}
                )
                steps.append(step)

        return steps

    def _compose_pipeline(self, spec: WorkflowSpec, capabilities: List[Capability]) -> List[WorkflowStep]:
        """Compose capabilities as a pipeline (output of one feeds next)."""
        steps = []
        previous_outputs = set()

        for i, cap in enumerate(capabilities):
            # Determine inputs from previous step's outputs
            inputs = {}
            if i > 0 and previous_outputs:
                # Map common output patterns to inputs
                for out in previous_outputs:
                    inputs[out] = f"${{steps.{steps[-1].step_id}.outputs.{out}}}"

            action = cap.metadata.default_action or f"execute_{cap.metadata.name}"
            step = WorkflowStep(
                capability_name=cap.metadata.name,
                capability_category=cap.metadata.category,
                action=action,
                inputs=inputs,
                depends_on=[steps[-1].step_id] if steps else [],
                timeout_seconds=cap.metadata.timeout_seconds,
                priority=TaskPriority.NORMAL,
                metadata={"step_index": i, "pipeline": True, "capability_version": cap.metadata.version}
            )
            steps.append(step)

            # Track what this capability provides
            previous_outputs.update(cap.metadata.provides)

        return steps

    def _compose_fan_out_fan_in(self, spec: WorkflowSpec, capabilities: List[Capability]) -> List[WorkflowStep]:
        """Compose as fan-out (parallel) then fan-in (aggregate)."""
        if len(capabilities) < 2:
            return self._compose_sequential(spec, capabilities)

        steps = []

        # Fan-out phase: parallel execution of first N-1 capabilities
        fan_out_caps = capabilities[:-1]
        fan_in_cap = capabilities[-1]

        fan_out_step_ids = []
        for i, cap in enumerate(fan_out_caps):
            action = cap.metadata.default_action or f"execute_{cap.metadata.name}"
            step = WorkflowStep(
                capability_name=cap.metadata.name,
                capability_category=cap.metadata.category,
                action=action,
                depends_on=[],
                timeout_seconds=cap.metadata.timeout_seconds,
                priority=TaskPriority.NORMAL,
                metadata={"step_index": i, "phase": "fan_out", "capability_version": cap.metadata.version}
            )
            steps.append(step)
            fan_out_step_ids.append(step.step_id)

        # Fan-in phase: aggregate results
        fan_in_action = fan_in_cap.metadata.default_action or f"execute_{fan_in_cap.metadata.name}"
        fan_in_step = WorkflowStep(
            capability_name=fan_in_cap.metadata.name,
            capability_category=fan_in_cap.metadata.category,
            action=fan_in_action,
            inputs={f"input_{i}": f"${{steps.{sid}.outputs}}" for i, sid in enumerate(fan_out_step_ids)},
            depends_on=fan_out_step_ids,
            timeout_seconds=fan_in_cap.metadata.timeout_seconds,
            priority=TaskPriority.HIGH,
            metadata={"phase": "fan_in", "capability_version": fan_in_cap.metadata.version}
        )
        steps.append(fan_in_step)

        return steps

    def _compose_adaptive(self, spec: WorkflowSpec, capabilities: List[Capability]) -> List[WorkflowStep]:
        """Compose using decision manager for adaptive workflow generation."""
        # For adaptive, we create a decision-driven workflow
        # that can dynamically choose next steps at runtime

        # Start with a planning step
        steps = []

        # First, use decision manager to create an execution plan
        if self.decision_manager:
            context = DecisionContext(
                task_description=spec.description or "Adaptive workflow execution",
                current_phase="planning",
                component="workflow_composer",
                available_context=str(spec.context),
                project_state=spec.context,
            )

            # Let decision manager create options
            decision = self.decision_manager.make_decision(
                context=context,
                decision_type=DecisionType.STRATEGY_SELECTION
            )

            if decision and decision.chosen_option:
                # Use the decision to guide composition
                strategy_name = decision.chosen_option.metadata.get("strategy", "sequential")
                try:
                    strategy = WorkflowStrategy(strategy_name)
                except ValueError:
                    strategy = WorkflowStrategy.SEQUENTIAL
            else:
                strategy = WorkflowStrategy.SEQUENTIAL
        else:
            strategy = WorkflowStrategy.SEQUENTIAL

        # Delegate to the chosen strategy
        return self._strategies[strategy](spec, capabilities)

    def _build_task_graph(self, spec: WorkflowSpec, steps: List[WorkflowStep]) -> TaskGraph:
        """Build a TaskGraph from workflow steps."""
        task_graph = TaskGraph()

        for step in steps:
            step_inputs = dict(step.inputs)
            if step.action in {'search', 'search_web'} and not step_inputs.get('query'):
                for candidate in (
                    spec.context.get('query'),
                    spec.context.get('user_query'),
                    spec.description,
                ):
                    if isinstance(candidate, str) and candidate.strip():
                        step_inputs['query'] = candidate.strip()
                        break
            task = Task(
                id=step.step_id,
                title=f"{step.capability_name}: {step.action}",
                description=f"Execute {step.capability_name} capability",
                status=TaskStatus.PENDING,
                priority=step.priority,
                dependencies=step.depends_on,
                metadata={
                    "workflow_id": spec.workflow_id,
                    "capability_name": step.capability_name,
                    "capability_category": step.capability_category.value,
                    "action": step.action,
                    "inputs": step_inputs,
                    "expected_outputs": step.outputs,
                    "timeout_seconds": step.timeout_seconds,
                    "retry_policy": step.retry_policy,
                    "condition": step.condition
                }
            )
            task_graph.add_task(task)

        return task_graph

    def _validate_workflow(self, workflow: ComposedWorkflow, steps: List[WorkflowStep]) -> bool:
        """Validate the composed workflow."""
        if not steps:
            logger.warning("Workflow has no steps")
            return False

        # Check for circular dependencies
        step_ids = {s.step_id for s in steps}
        for step in steps:
            for dep in step.depends_on:
                if dep not in step_ids:
                    logger.warning(f"Step {step.step_id} depends on unknown step {dep}")
                    return False

        # Check all capabilities exist and are active
        for step in steps:
            cap = self.registry.get_capability(step.capability_name)
            if not cap:
                logger.warning(f"Capability {step.capability_name} not found")
                return False
            if cap.state != CapabilityState.ACTIVE:
                logger.warning(f"Capability {step.capability_name} not active (state: {cap.state})")
                return False

        return True

    def get_workflow(self, workflow_id: str) -> Optional[ComposedWorkflow]:
        """Get a composed workflow by ID."""
        with self._lock:
            return self._composed_workflows.get(workflow_id)

    def list_workflows(self, status: Optional[WorkflowStatus] = None) -> List[ComposedWorkflow]:
        """List composed workflows."""
        with self._lock:
            workflows = list(self._composed_workflows.values())
            if status:
                workflows = [w for w in workflows if w.status == status]
            return workflows

    def _publish_event(self, event_type: str, payload: Dict[str, Any]):
        """Publish an event to the event bus."""
        try:
            event = Event(
                name=event_type,
                data=payload,
                source="workflow_composer",
                priority=EventPriority.NORMAL
            )
            self._event_bus.publish(event)
        except Exception as e:
            logger.warning(f"Failed to publish event {event_type}: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get composer statistics."""
        with self._lock:
            return {
                "total_composed": len(self._composed_workflows),
                "by_status": {s.value: sum(1 for w in self._composed_workflows.values() if w.status == s)
                             for s in WorkflowStatus},
                "avg_steps": sum(len(w.steps) for w in self._composed_workflows.values()) / len(self._composed_workflows)
                if self._composed_workflows else 0
            }