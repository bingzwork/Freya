"""Central Autonomous Orchestrator for Freya.

This is the main orchestrator class that coordinates all capabilities, subsystems,
and components using the capability-driven, event-driven architecture.
"""

import asyncio
import logging
import re
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
from uuid import uuid4

from app.core.events import get_event_bus, Event, EventPriority
from app.core.observability import get_observability_hub, ComponentInfo, ComponentType
from app.core.background_jobs import get_job_service, JobTriggerConfig, JobTriggerType, JobPriority

from app.orchestrator.capability_registry import (
    Capability, CapabilityCategory, CapabilityMetadata, CapabilityRegistry, CapabilityState,
    get_capability_registry, reset_capability_registry
)
from app.orchestrator.workflow_composer import (
    WorkflowComposer, WorkflowSpec, WorkflowStrategy, ComposedWorkflow, WorkflowStatus,
    IntentType
)
from app.orchestrator.task_executor import TaskExecutor, ExecutionState, ExecutableCapability
from app.orchestrator.safety_gate import SafetyGate, SafetyGateMode, SafetyPolicy
from app.orchestrator.self_observer import SelfObserver, ObservationLevel
from app.orchestrator.capabilities import create_all_capabilities
from app.orchestrator.activity_reporter import ActivityReporter, ActivityLevel
from app.orchestrator.gui_interface import OrchestratorGUIInterface, OrchestratorStreamingInterface
from app.orchestrator.failure_recovery_integration import FailureRecoveryIntegration, create_failure_recovery_integration

from app.intent.classifier import IntentClassifier
from app.decision.manager import DecisionManager
from app.decision.models import DecisionContext, DecisionOption, DecisionType, DecisionCategory
from app.planner.task_graph import TaskGraph
from app.world_model.model import WorldModel
from app.memory.unified_retrieval import UnifiedRetrieval
from app.conversational_control import ConversationControlHandler
from app.failure_recovery.orchestrator import RecoveryOrchestrator
from app.autonomous_learning.pipeline import AutonomousLearningPipeline
from app.long_term_autonomy.manager import AutonomyManager
from app.memory.goals import GoalStorage

# Self-Observation components
from app.self_observation.runtime_awareness import RuntimeAwareness, AwarenessConfig, get_runtime_awareness
from app.self_observation.self_analysis import CentralizedSelfAnalysis, AnalysisConfig, get_self_analysis
from app.self_observation.predictive_diagnostics import PredictiveDiagnostics, PredictiveDiagnosticsConfig, get_predictive_diagnostics


logger = logging.getLogger(__name__)


class OrchestratorState(Enum):
    """State of the orchestrator."""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass
class OrchestratorConfig:
    """Configuration for the Central Autonomous Orchestrator."""
    # Capability registry
    auto_discovery: bool = True
    health_check_interval: float = 30.0

    # Workflow composition
    default_strategy: WorkflowStrategy = WorkflowStrategy.ADAPTIVE
    max_workflow_steps: int = 20
    max_parallel_steps: int = 5
    workflow_timeout: float = 300.0

    # Task execution
    max_concurrent_workflows: int = 10
    default_task_retries: int = 3
    checkpoint_interval: int = 5

    # Safety
    safety_mode: SafetyGateMode = SafetyGateMode.BALANCED
    safety_require_approval_for: List[str] = field(default_factory=list)

    # Self-observation
    observation_level: ObservationLevel = ObservationLevel.STANDARD
    snapshot_interval: float = 60.0

    # Intent classification
    enable_intent_classification: bool = True
    intent_confidence_threshold: float = 0.7

    # Decision making
    enable_decision_manager: bool = True
    min_confidence_for_action: float = 0.6

    # World model integration
    enable_world_model: bool = True

    # Memory integration
    enable_memory_retrieval: bool = True

    # Background jobs
    enable_background_jobs: bool = True

    # Conversation control
    enable_conversation_control: bool = True

    # Self-Observation
    enable_runtime_awareness: bool = True
    enable_self_analysis: bool = True
    enable_predictive_diagnostics: bool = True
    runtime_awareness_interval_seconds: float = 10.0
    self_analysis_interval_seconds: float = 300.0
    predictive_diagnostics_interval_seconds: float = 60.0


class CentralOrchestrator:
    """
    The Central Autonomous Orchestrator - Freya's primary coordination system.

    This orchestrates all capabilities, subsystems, and components using:
    - Dynamic capability discovery and lifecycle management
    - Event-driven coordination via EventBus
    - Intent-driven workflow composition
    - Decision-engine integration for continuous evaluation
    - Safety gates with risk analysis and human oversight
    - Long-running task support with checkpointing/recovery
    - Self-observation via ObservabilityHub
    """

    def __init__(self, config: Optional[OrchestratorConfig] = None):
        self.config = config or OrchestratorConfig()
        self._state = OrchestratorState.STOPPED
        self._lock = threading.RLock()

        # Core components (initialized in start())
        self._capability_registry: Optional[CapabilityRegistry] = None
        self._workflow_composer: Optional[WorkflowComposer] = None
        self._task_executor: Optional[TaskExecutor] = None
        self._safety_gate: Optional[SafetyGate] = None
        self._self_observer: Optional[SelfObserver] = None

        # Supporting systems
        self._intent_classifier: Optional[IntentClassifier] = None
        self._decision_manager: Optional[DecisionManager] = None
        self._world_model: Optional[WorldModel] = None
        self._memory_retrieval: Optional[UnifiedRetrieval] = None

        # Infrastructure
        self._event_bus = get_event_bus()
        self._observability = get_observability_hub()
        self._job_service = get_job_service()

        # Runtime state
        self._start_time: Optional[float] = None
        self._main_thread: Optional[threading.Thread] = None
        self._shutdown_event = threading.Event()
        self._active_workflows: Dict[str, ComposedWorkflow] = {}
        self._workflow_lock = threading.RLock()

        # New components
        self._activity_reporter: Optional[ActivityReporter] = None
        self._gui_interface: Optional[OrchestratorGUIInterface] = None
        self._streaming_interface: Optional[OrchestratorStreamingInterface] = None
        self._failure_recovery: Optional[FailureRecoveryIntegration] = None

        # Pipeline coordination components
        self._conversation_control: Optional[ConversationControlHandler] = None
        self._shared_context: Dict[str, Any] = {}  # Shared execution context
        self._context_lock = threading.RLock()

        # Self-Observation components
        self._runtime_awareness: Optional[RuntimeAwareness] = None
        self._self_analysis: Optional[CentralizedSelfAnalysis] = None
        self._predictive_diagnostics: Optional[PredictiveDiagnostics] = None

        # Register with observability
        self._observability.register_component(ComponentInfo(
            name="CentralOrchestrator",
            component_type=ComponentType.SERVICE,
            version="1.0.0",
            description="Central Autonomous Orchestrator - primary coordination system for Freya",
            metadata={}
        ))

    @property
    def state(self) -> OrchestratorState:
        return self._state

    @property
    def capability_registry(self) -> Optional[CapabilityRegistry]:
        return self._capability_registry

    @property
    def workflow_composer(self) -> Optional[WorkflowComposer]:
        return self._workflow_composer

    @property
    def task_executor(self) -> Optional[TaskExecutor]:
        return self._task_executor

    @property
    def safety_gate(self) -> Optional[SafetyGate]:
        return self._safety_gate

    @property
    def self_observer(self) -> Optional[SelfObserver]:
        return self._self_observer

    @property
    def activity_reporter(self) -> Optional[ActivityReporter]:
        return self._activity_reporter

    @property
    def gui_interface(self) -> Optional[OrchestratorGUIInterface]:
        return self._gui_interface

    @property
    def streaming_interface(self) -> Optional[OrchestratorStreamingInterface]:
        return self._streaming_interface

    @property
    def failure_recovery(self) -> Optional[FailureRecoveryIntegration]:
        return self._failure_recovery

    @property
    def conversation_control(self) -> Optional[ConversationControlHandler]:
        return self._conversation_control

    @property
    def runtime_awareness(self) -> Optional[RuntimeAwareness]:
        return self._runtime_awareness

    @property
    def self_analysis(self) -> Optional[CentralizedSelfAnalysis]:
        return self._self_analysis

    @property
    def predictive_diagnostics(self) -> Optional[PredictiveDiagnostics]:
        return self._predictive_diagnostics

    def set_conversation_control(self, handler: ConversationControlHandler) -> None:
        """Set the ConversationControlHandler externally.

        The ConversationControlHandler requires a PlanManager and other dependencies
        that are typically created by FreyaAgent. This method allows setting it
        after the orchestrator is initialized.

        Args:
            handler: The ConversationControlHandler instance
        """
        self._conversation_control = handler
        logger.info("ConversationControlHandler set on orchestrator")

    def start(self) -> bool:
        """Start the orchestrator and all components."""
        with self._lock:
            if self._state != OrchestratorState.STOPPED:
                logger.warning(f"Orchestrator already in state: {self._state}")
                return False

            self._state = OrchestratorState.STARTING

        try:
            logger.info("Starting Central Autonomous Orchestrator...")

            # Initialize core components
            self._initialize_components()

            # Start components
            self._start_components()

            # Register built-in capabilities
            self._register_builtin_capabilities()

            # Start background jobs
            if self.config.enable_background_jobs:
                self._start_background_jobs()

            self._state = OrchestratorState.RUNNING
            self._start_time = time.time()
            self._shutdown_event.clear()

            # Start main coordination loop
            self._main_thread = threading.Thread(
                target=self._coordination_loop,
                daemon=True,
                name="Orchestrator-Coordination"
            )
            self._main_thread.start()

            self._publish_event("orchestrator.started", {
                "timestamp": datetime.now(timezone.utc).isoformat()
            })

            logger.info("Central Autonomous Orchestrator started successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to start orchestrator: {e}")
            self._state = OrchestratorState.ERROR
            return False

    def stop(self, timeout: float = 30.0) -> bool:
        """Stop the orchestrator and all components."""
        with self._lock:
            if self._state == OrchestratorState.STOPPED:
                return True
            if self._state == OrchestratorState.STOPPING:
                # Already stopping, wait
                pass
            self._state = OrchestratorState.STOPPING

        try:
            logger.info("Stopping Central Autonomous Orchestrator...")

            # Signal shutdown
            self._shutdown_event.set()

            # Wait for main thread
            if self._main_thread and self._main_thread.is_alive():
                self._main_thread.join(timeout=timeout)

            # Stop components
            self._stop_components()

            self._state = OrchestratorState.STOPPED

            self._publish_event("orchestrator.stopped", {
                "timestamp": datetime.now(timezone.utc).isoformat()
            })

            logger.info("Central Autonomous Orchestrator stopped")
            return True

        except Exception as e:
            logger.error(f"Error stopping orchestrator: {e}")
            self._state = OrchestratorState.ERROR
            return False

    def pause(self) -> bool:
        """Pause the orchestrator."""
        with self._lock:
            if self._state != OrchestratorState.RUNNING:
                return False
            self._state = OrchestratorState.PAUSED

        if self._task_executor:
            for wf_id in self._task_executor.list_active_workflows():
                self._task_executor.pause(wf_id)

        self._publish_event("orchestrator.paused", {})
        logger.info("Orchestrator paused")
        return True

    def resume(self) -> bool:
        """Resume the orchestrator."""
        with self._lock:
            if self._state != OrchestratorState.PAUSED:
                return False
            self._state = OrchestratorState.RUNNING

        if self._task_executor:
            for wf_id in self._task_executor.list_active_workflows():
                self._task_executor.resume(wf_id)

        self._publish_event("orchestrator.resumed", {})
        logger.info("Orchestrator resumed")
        return True

    def _initialize_components(self):
        """Initialize all core components."""
        # Capability Registry
        self._capability_registry = CapabilityRegistry(
            auto_discovery=self.config.auto_discovery,
            health_check_interval=self.config.health_check_interval
        )

        # Intent Classifier
        if self.config.enable_intent_classification:
            self._intent_classifier = IntentClassifier()

        # Decision Manager
        if self.config.enable_decision_manager:
            self._decision_manager = DecisionManager()

        # World Model
        if self.config.enable_world_model:
            self._world_model = WorldModel()

        # Memory Retrieval
        if self.config.enable_memory_retrieval:
            self._memory_retrieval = UnifiedRetrieval()

        # Conversation Control - created externally via factory, not initialized here
        # The ConversationControlHandler requires PlanManager, executor, and conversation_memory
        # It should be set via set_conversation_control() if needed
        self._conversation_control = None

        # Workflow Composer
        self._workflow_composer = WorkflowComposer(
            registry=self._capability_registry,
            decision_manager=self._decision_manager,
            intent_classifier=self._intent_classifier,
            memory_retrieval=self._memory_retrieval,
        )

        # Task Executor
        self._task_executor = TaskExecutor(
            registry=self._capability_registry,
            max_concurrent_workflows=self.config.max_concurrent_workflows,
        )

        # Safety Gate
        safety_policy = SafetyPolicy(
            mode=self.config.safety_mode,
            always_require_approval=set(self.config.safety_require_approval_for),
        )
        self._safety_gate = SafetyGate(
            decision_manager=self._decision_manager,
            policy=safety_policy,
            registry=self._capability_registry,
        )

        # Self Observer
        self._self_observer = SelfObserver(
            capability_registry=self._capability_registry,
            workflow_composer=self._workflow_composer,
            task_executor=self._task_executor,
            safety_gate=self._safety_gate,
            observation_level=self.config.observation_level,
            snapshot_interval=self.config.snapshot_interval,
        )

        # Activity Reporter
        self._activity_reporter = ActivityReporter(
            enable_plain_english=True,
            debug_mode=False,
        )

        # GUI Interface
        self._gui_interface = OrchestratorGUIInterface(self)
        self._streaming_interface = OrchestratorStreamingInterface(self._gui_interface)

        # Failure Recovery Integration
        self._failure_recovery = create_failure_recovery_integration(
            task_executor=self._task_executor,
            workflow_composer=self._workflow_composer,
            capability_registry=self._capability_registry,
        )

        # Self-Observation: Runtime Awareness
        if self.config.enable_runtime_awareness:
            self._runtime_awareness = get_runtime_awareness(
                orchestrator=self,
                decision_manager=self._decision_manager,
                world_model=self._world_model,
                memory_retrieval=self._memory_retrieval,
                failure_recovery=self._failure_recovery._recovery_orchestrator if self._failure_recovery else None,
                autonomous_learning=None,  # Set externally by FreyaAgent if needed
                autonomy_manager=None,  # Set externally by FreyaAgent if needed
                goal_storage=None,  # Set externally by FreyaAgent if needed
                config=AwarenessConfig(update_interval_seconds=self.config.runtime_awareness_interval_seconds),
            )

        # Self-Observation: Centralized Self-Analysis
        if self.config.enable_self_analysis and self._runtime_awareness:
            self._self_analysis = get_self_analysis(
                orchestrator=self,
                decision_manager=self._decision_manager,
                world_model=self._world_model,
                memory_retrieval=self._memory_retrieval,
                failure_recovery=self._failure_recovery._recovery_orchestrator if self._failure_recovery else None,
                autonomous_learning=None,  # Set externally by FreyaAgent if needed
                autonomy_manager=None,  # Set externally by FreyaAgent if needed
                config=AnalysisConfig(analysis_interval_seconds=self.config.self_analysis_interval_seconds),
            )

        # Self-Observation: Predictive Diagnostics
        if self.config.enable_predictive_diagnostics and self._runtime_awareness and self._self_analysis:
            self._predictive_diagnostics = get_predictive_diagnostics(
                runtime_awareness=self._runtime_awareness,
                self_analysis=self._self_analysis,
                config=PredictiveDiagnosticsConfig(update_interval_seconds=self.config.predictive_diagnostics_interval_seconds),
            )

        # Note: Built-in capabilities are registered in start() after registry is started

    def _start_components(self):
        """Start all components."""
        self._capability_registry.start()

        if self._intent_classifier:
            # Intent classifier doesn't have explicit start
            pass

        if self._decision_manager:
            # Decision manager doesn't have explicit start
            pass

        if self._world_model:
            # World model doesn't have explicit start
            pass

        if self._memory_retrieval:
            # Memory retrieval doesn't have explicit start
            pass

        self._workflow_composer  # No explicit start needed

        self._task_executor  # No explicit start needed

        self._safety_gate  # No explicit start needed

        if self._self_observer:
            self._self_observer.start()

        # Self-Observation: Runtime Awareness
        if self._runtime_awareness:
            self._runtime_awareness.start()

        # Self-Observation: Centralized Self-Analysis
        if self._self_analysis:
            self._self_analysis.start()

        # Self-Observation: Predictive Diagnostics
        if self._predictive_diagnostics:
            self._predictive_diagnostics.start()

        # Activity reporter starts automatically via event subscriptions

    def _stop_components(self):
        """Stop all components."""
        # Self-Observation: Predictive Diagnostics
        if self._predictive_diagnostics:
            self._predictive_diagnostics.stop()

        # Self-Observation: Centralized Self-Analysis
        if self._self_analysis:
            self._self_analysis.stop()

        # Self-Observation: Runtime Awareness
        if self._runtime_awareness:
            self._runtime_awareness.stop()

        if self._self_observer:
            self._self_observer.stop()

        if self._capability_registry:
            self._capability_registry.stop()

    def _register_builtin_capabilities(self):
        """Register built-in capabilities with actual implementations."""
        if not self._capability_registry:
            return

        # Create actual capability instances
        capabilities = create_all_capabilities()

        for cap in capabilities:
            self._capability_registry.register(cap, registered_by="orchestrator:builtin")

    def _start_background_jobs(self):
        """Start background jobs."""
        # Capability health checks
        self._job_service.schedule(
            job_id="orchestrator_capability_health",
            func=self._capability_health_check_job,
            trigger=JobTriggerConfig(type=JobTriggerType.RECURRING, interval_seconds=self.config.health_check_interval),
            priority=JobPriority.NORMAL,
            replace_existing=True,
        )

        # Workflow cleanup
        self._job_service.schedule(
            job_id="orchestrator_workflow_cleanup",
            func=self._workflow_cleanup_job,
            trigger=JobTriggerConfig(type=JobTriggerType.RECURRING, interval_seconds=3600),
            priority=JobPriority.LOW,
            replace_existing=True,
        )

        # Metrics aggregation
        self._job_service.schedule(
            job_id="orchestrator_metrics_aggregation",
            func=self._metrics_aggregation_job,
            trigger=JobTriggerConfig(type=JobTriggerType.RECURRING, interval_seconds=60),
            priority=JobPriority.LOW,
            replace_existing=True,
        )

        # Predictive Diagnostics - run analysis and generate predictions
        if self.config.enable_predictive_diagnostics:
            self._job_service.schedule(
                job_id="orchestrator_predictive_diagnostics",
                func=self._predictive_diagnostics_job,
                trigger=JobTriggerConfig(type=JobTriggerType.RECURRING, interval_seconds=self.config.predictive_diagnostics_interval_seconds),
                priority=JobPriority.NORMAL,
                replace_existing=True,
            )

    def _predictive_diagnostics_job(self):
        """Background job for predictive diagnostics."""
        if not self._predictive_diagnostics:
            return
        try:
            # Run predictive diagnostics analysis - this triggers the service to run
            import asyncio
            asyncio.create_task(self._predictive_diagnostics.run_diagnostics())
        except Exception as e:
            logger.error(f"Predictive diagnostics job failed: {e}")

    def _capability_health_check_job(self):
        """Background job for capability health checks."""
        # Handled by registry's own health check job
        pass

    def _workflow_cleanup_job(self):
        """Clean up completed/failed workflows."""
        with self._workflow_lock:
            to_remove = []
            for wf_id, wf in self._active_workflows.items():
                if wf.status in (WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED):
                    # Keep for a while then clean up
                    if wf.completed_at:
                        try:
                            completed = datetime.fromisoformat(wf.completed_at.replace('Z', '+00:00'))
                            if (datetime.now(timezone.utc) - completed).total_seconds() > 3600:
                                to_remove.append(wf_id)
                        except:
                            pass
            for wf_id in to_remove:
                del self._active_workflows[wf_id]

    def _metrics_aggregation_job(self):
        """Aggregate and publish metrics."""
        if self._self_observer:
            stats = self._self_observer.get_performance_stats()
            for key, value in stats.items():
                self._observability.record_metric(f"orchestrator.aggregated.{key}", value)

    def _coordination_loop(self):
        """Main coordination loop."""
        logger.info("Orchestrator coordination loop started")

        while not self._shutdown_event.is_set():
            try:
                if self._state != OrchestratorState.RUNNING:
                    time.sleep(1.0)
                    continue

                # Coordination tasks
                self._coordinate_capabilities()
                self._coordinate_workflows()
                self._check_system_health()

                # Sleep briefly
                time.sleep(5.0)

            except Exception as e:
                logger.error(f"Error in coordination loop: {e}")
                time.sleep(10.0)

        logger.info("Orchestrator coordination loop ended")

    def _coordinate_capabilities(self):
        """Coordinate capability lifecycle."""
        if not self._capability_registry:
            return

        # Check for capabilities that should be activated based on demand
        # This is where dynamic capability loading would happen
        pass

    def _coordinate_workflows(self):
        """Coordinate active workflows."""
        if not self._task_executor:
            return

        # Check for stalled workflows
        active = self._task_executor.list_active_workflows()
        for wf_id in active:
            context = self._task_executor.get_context(wf_id)
            if context and context.current_step_index > 0:
                # Could add stall detection here
                pass

    def _check_system_health(self):
        """Check overall system health."""
        if self._self_observer and not self._self_observer.is_healthy():
            logger.warning("System health check failed - degraded state detected")
            self._publish_event("orchestrator.health_degraded", {
                "timestamp": datetime.now(timezone.utc).isoformat()
            })

    # ==================== Public API ====================

    def execute_intent(
        self,
        user_input: str,
        context: Optional[Dict[str, Any]] = None,
        goal_id: Optional[str] = None,
        async_mode: bool = True,
    ) -> str:
        """
        Execute a user intent by composing and running a workflow through the full pipeline.

        Pipeline:
        User Request → Natural Conversation → Goal Management → Planning → Decision →
        Memory/Knowledge/WorldModel → Tool Execution → Failure Recovery →
        Autonomous Learning → Self Observation → Safe Self Improvement → Final Response

        Args:
            user_input: The user's request/input
            context: Additional context
            goal_id: Optional goal ID to associate with
            async_mode: Run asynchronously

        Returns:
            Workflow ID
        """
        if self._state != OrchestratorState.RUNNING:
            raise RuntimeError(f"Orchestrator not running (state: {self._state})")

        # Initialize shared execution context (uses dict, not RuntimeContext class)
        execution_context = context or {}
        execution_context.update({
            "user_input": user_input,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ========== Stage 1: Natural Conversation ==========
        conversation_context = {}
        if self._conversation_control:
            # Use conversation control for status/control - it doesn't process user input directly
            # but provides context about current conversation state
            conversation_context = {
                "conversation_id": getattr(self._conversation_control, '_conversation_id', None),
                "is_executing": self._conversation_control._state.is_executing,
                "is_paused": self._conversation_control._state.is_paused,
                "active_plan": self._conversation_control._state.active_plan_id,
                "completed_tasks": len(self._conversation_control._state.completed_tasks),
            }
            execution_context["conversation"] = conversation_context

            # Publish event for activity reporting
            self._publish_event("conversation.context.gathered", {
                "is_executing": conversation_context['is_executing'],
                "is_paused": conversation_context['is_paused'],
                "active_plan": conversation_context['active_plan'],
                "completed_tasks": conversation_context['completed_tasks'],
            })

        # ========== Stage 2: Goal Management ==========
        goal_context = {}
        if goal_id:
            goal_context["goal_id"] = goal_id
            execution_context["goal_id"] = goal_id
        else:
            # Extract or create goal from conversation
            goal_context["inferred"] = True
            execution_context["goal_inferred"] = True

        # ========== Stage 3: Intent Classification ==========
        intent = None
        intent_confidence = 0.0
        if self._intent_classifier:
            intent_result = self._intent_classifier.classify(user_input)
            intent = intent_result.intent
            intent_confidence = intent_result.confidence

            execution_context["intent"] = intent.value if intent else None
            execution_context["intent_confidence"] = intent_confidence

            # Publish event for activity reporting
            self._publish_event("intent.classified", {
                "intent": intent.value if intent else None,
                "confidence": intent_confidence,
            })

        # ========== Stage 4: Decision Making (Pre-planning) ==========
        decision_context = {}
        if self._decision_manager and intent:
            # Make initial decision on approach strategy using simplified API
            options = [
                DecisionOption(
                    id="strategy_standard",
                    name="Standard Planning",
                    description="Balanced approach with standard thoroughness",
                    action="standard",
                    category=DecisionCategory.PLANNING,
                    decision_type=DecisionType.STRATEGY_SELECTION,
                    estimated_success=0.8,
                    estimated_effort=0.5,
                    estimated_impact=0.7,
                    risk_level="low",
                ),
                DecisionOption(
                    id="strategy_fast",
                    name="Fast Planning",
                    description="Quick approach with minimal steps",
                    action="fast",
                    category=DecisionCategory.PLANNING,
                    decision_type=DecisionType.STRATEGY_SELECTION,
                    estimated_success=0.6,
                    estimated_effort=0.2,
                    estimated_impact=0.5,
                    risk_level="medium",
                ),
                DecisionOption(
                    id="strategy_thorough",
                    name="Thorough Planning",
                    description="Comprehensive approach with detailed analysis",
                    action="thorough",
                    category=DecisionCategory.PLANNING,
                    decision_type=DecisionType.STRATEGY_SELECTION,
                    estimated_success=0.9,
                    estimated_effort=0.8,
                    estimated_impact=0.9,
                    risk_level="low",
                ),
            ]

            decision_result = self._decision_manager.decide_simple(
                decision_type=DecisionType.STRATEGY_SELECTION,
                task_description=f"Select planning strategy for: {user_input}",
                options=options,
                component="central_orchestrator",
                metadata={"intent": intent.value if intent else None, "confidence": intent_confidence, "user_input": user_input},
            )

            selected_strategy = decision_result.chosen_option.action if decision_result.chosen_option else "standard"
            decision_context = {
                "selected_strategy": selected_strategy,
                "confidence": decision_result.confidence,
                "risk_level": decision_result.risk_level,
            }
            execution_context["planning_strategy"] = selected_strategy

            # Publish event for activity reporting
            self._publish_event("decision.made", {
                "selected": {"strategy": selected_strategy, "confidence": decision_result.confidence},
                "context": "planning_strategy_selection",
            })

        # ========== Stage 5: Memory/Knowledge/WorldModel Retrieval ==========
        retrieval_context = {}
        if self._memory_retrieval:
            # Retrieve relevant knowledge for the task
            try:
                from app.memory.unified_retrieval import RetrievalQuery
                query_obj = RetrievalQuery(
                    query=user_input,
                    context=execution_context,
                    max_results=10,
                )
                retrieval_results = self._memory_retrieval.retrieve(query_obj)
                retrieval_context = {
                    "results": [r.to_dict() for r in retrieval_results],
                    "total_results": len(retrieval_results),
                }
                execution_context["retrieval"] = retrieval_context

                # Publish event for activity reporting
                self._publish_event("memory.retrieved", {
                    "total_results": retrieval_context.get('total_results', 0),
                    "query": user_input[:100],
                })
            except Exception as e:
                logger.warning(f"Memory retrieval failed: {e}")
                retrieval_context = {"error": str(e)}

        # World Model context
        world_context = {}
        if self._world_model:
            try:
                # Get relevant context for the task type
                task_type = "general"
                if intent:
                    intent_str = intent.value.lower()
                    if "code" in intent_str or "build" in intent_str:
                        task_type = "code"
                    elif "test" in intent_str:
                        task_type = "test"
                    elif "debug" in intent_str:
                        task_type = "debug"
                    elif "deploy" in intent_str:
                        task_type = "deploy"
                    elif "refactor" in intent_str:
                        task_type = "refactor"

                snapshot = self._world_model.get_relevant_context(task_type)
                world_context = {
                    "snapshot": snapshot.to_dict() if hasattr(snapshot, 'to_dict') else str(snapshot),
                    "task_type": task_type,
                }
                execution_context["world_model"] = world_context
            except Exception as e:
                logger.warning(f"World model query failed: {e}")

        # ========== Stage 6: Planning (Workflow Composition) ==========
        # Use the selected strategy for composition
        strategy_str = execution_context.get("planning_strategy", self.config.default_strategy)

        # Map strategy string to WorkflowStrategy enum
        strategy_map = {
            "standard": WorkflowStrategy.ADAPTIVE,
            "fast": WorkflowStrategy.SEQUENTIAL,
            "thorough": WorkflowStrategy.ADAPTIVE,
        }
        workflow_strategy = strategy_map.get(strategy_str, WorkflowStrategy.ADAPTIVE)

        spec = WorkflowSpec(
            name=f"Intent: {user_input[:50]}",
            description=user_input,
            intent=intent,
            goal_id=goal_id,
            strategy=workflow_strategy,
            context=execution_context,
            max_steps=self.config.max_workflow_steps,
            max_parallel=self.config.max_parallel_steps,
            timeout_seconds=self.config.workflow_timeout,
        )

        workflow = self._workflow_composer.compose(spec)

        with self._workflow_lock:
            self._active_workflows[workflow.spec.workflow_id] = workflow

        # Store workflow context in shared context dict for tracking
        execution_context["workflow_id"] = workflow.spec.workflow_id
        execution_context["workflow_spec"] = spec
        execution_context["conversation_context"] = conversation_context
        execution_context["goal_context"] = goal_context
        execution_context["retrieval_context"] = retrieval_context
        execution_context["world_context"] = world_context

        # ========== Stage 7: Prepare Capabilities ==========
        capabilities = {}
        for step in workflow.steps:
            cap = self._capability_registry.get_capability(step.capability_name)
            if cap:
                capabilities[step.capability_name] = cap

        # ========== Stage 8: Tool Execution (with Failure Recovery) ==========
        execution_id = self._task_executor.execute(
            workflow_id=workflow.spec.workflow_id,
            task_graph=workflow.task_graph,
            capabilities=capabilities,
            global_inputs=execution_context,
            async_mode=async_mode,
        )

        # Update workflow status
        workflow.status = WorkflowStatus.EXECUTING
        workflow.started_at = datetime.now(timezone.utc).isoformat()

        # ========== Stage 9: Register Failure Recovery ==========
        # The FailureRecoveryIntegration is already wired into TaskExecutor
        # via the _failure_recovery component's handle_task_failure callback

        # Publish workflow started event for activity reporting
        self._publish_event("workflow.started", {
            "workflow_id": workflow.spec.workflow_id,
            "intent": intent.value if intent else None,
            "steps": len(workflow.steps),
        })

        # ========== Stage 10: Self Observation (automatic via SelfObserver) ==========
        # SelfObserver continuously monitors and reports metrics

        # ========== Stage 11: Autonomous Learning & Safe Self Improvement ==========
        # These are handled async via background jobs and event handlers

        # Publish event for pipeline completion (intent execution started)
        self._publish_event("orchestrator.intent_executed", {
            "workflow_id": workflow.spec.workflow_id,
            "execution_id": execution_id,
            "intent": intent.value if intent else None,
            "user_input": user_input[:100],
            "pipeline_stages": [
                "conversation", "goal_management", "intent_classification",
                "decision_making", "memory_retrieval", "world_model",
                "planning", "tool_execution", "failure_recovery",
                "autonomous_learning", "self_observation", "self_improvement"
            ],
        })

        return execution_id

    def execute_workflow_spec(self, spec: WorkflowSpec, async_mode: bool = True) -> str:
        """Execute a pre-defined workflow specification."""
        if self._state != OrchestratorState.RUNNING:
            raise RuntimeError(f"Orchestrator not running (state: {self._state})")

        workflow = self._workflow_composer.compose(spec)

        with self._workflow_lock:
            self._active_workflows[workflow.spec.workflow_id] = workflow

        capabilities = {}
        for step in workflow.steps:
            cap = self._capability_registry.get_capability(step.capability_name)
            if cap:
                capabilities[step.capability_name] = cap

        execution_id = self._task_executor.execute(
            workflow_id=workflow.spec.workflow_id,
            task_graph=workflow.task_graph,
            capabilities=capabilities,
            global_inputs=spec.context,
            async_mode=async_mode,
        )

        workflow.status = WorkflowStatus.EXECUTING
        workflow.started_at = datetime.now(timezone.utc).isoformat()

        return execution_id

    def get_workflow_status(self, workflow_id: str) -> Optional[WorkflowStatus]:
        """Get the status of a workflow."""
        with self._workflow_lock:
            workflow = self._active_workflows.get(workflow_id)
            if workflow:
                return workflow.status

        # Check executor
        if self._task_executor:
            exec_state = self._task_executor.get_status(workflow_id)
            if exec_state:
                # Map execution state to workflow status
                mapping = {
                    ExecutionState.PENDING: WorkflowStatus.PENDING,
                    ExecutionState.QUEUED: WorkflowStatus.PENDING,
                    ExecutionState.RUNNING: WorkflowStatus.EXECUTING,
                    ExecutionState.PAUSED: WorkflowStatus.EXECUTING,
                    ExecutionState.COMPLETED: WorkflowStatus.COMPLETED,
                    ExecutionState.FAILED: WorkflowStatus.FAILED,
                    ExecutionState.CANCELLED: WorkflowStatus.CANCELLED,
                    ExecutionState.RETRYING: WorkflowStatus.EXECUTING,
                    ExecutionState.CHECKPOINTING: WorkflowStatus.EXECUTING,
                    ExecutionState.RECOVERING: WorkflowStatus.EXECUTING,
                }
                return mapping.get(exec_state, WorkflowStatus.PENDING)

        return None

    def pause_workflow(self, workflow_id: str) -> bool:
        """Pause a running workflow."""
        if self._task_executor:
            return self._task_executor.pause(workflow_id)
        return False

    def resume_workflow(self, workflow_id: str) -> bool:
        """Resume a paused workflow."""
        if self._task_executor:
            return self._task_executor.resume(workflow_id)
        return False

    def cancel_workflow(self, workflow_id: str) -> bool:
        """Cancel a workflow."""
        if self._task_executor:
            return self._task_executor.cancel(workflow_id)
        return False

    def register_capability(self, capability: Capability, registered_by: str = "user") -> bool:
        """Register a new capability at runtime."""
        if not self._capability_registry:
            return False
        return self._capability_registry.register(capability, registered_by)

    def unregister_capability(self, name: str) -> bool:
        """Unregister a capability."""
        if not self._capability_registry:
            return False
        return self._capability_registry.unregister(name)

    def get_capability(self, name: str) -> Optional[Capability]:
        """Get a capability by name."""
        if not self._capability_registry:
            return None
        return self._capability_registry.get_capability(name)

    def list_capabilities(self, category: Optional[CapabilityCategory] = None) -> List[CapabilityMetadata]:
        """List all capabilities."""
        if not self._capability_registry:
            return []
        return self._capability_registry.list_capabilities(category=category, active_only=True)

    def check_safety(self, operation: str, operation_type: str, context: Dict[str, Any] = None):
        """Check safety for an operation."""
        if not self._safety_gate:
            return None
        return self._safety_gate.check_and_enforce(operation, operation_type, context)

    def get_system_status(self) -> Dict[str, Any]:
        """Get comprehensive system status."""
        return {
            "orchestrator": {
                "state": self._state.value,
                "uptime_seconds": time.time() - self._start_time if self._start_time else 0,
            },
            "capability_registry": self._capability_registry.get_stats() if self._capability_registry else {},
            "workflow_composer": self._workflow_composer.get_stats() if self._workflow_composer else {},
            "task_executor": self._task_executor.get_stats() if self._task_executor else {},
            "safety_gate": self._safety_gate.get_stats() if self._safety_gate else {},
            "self_observer": self._self_observer.get_stats() if self._self_observer else {},
        }

    def set_safety_mode(self, mode: SafetyGateMode):
        """Change the safety mode."""
        if self._safety_gate:
            self._safety_gate.set_mode(mode)

    # ==================== New Component APIs ====================

    def get_activity_reporter(self) -> Optional[ActivityReporter]:
        """Get the activity reporter for plain English updates."""
        return self._activity_reporter

    def get_activity_history(
        self,
        limit: int = 100,
        category: Optional[str] = None,
        workflow_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get activity history as plain English updates."""
        if not self._activity_reporter:
            return []
        activities = self._activity_reporter.get_history(
            limit=limit,
            category=category,
            workflow_id=workflow_id,
        )
        return [a.to_dict() for a in activities]

    def get_recent_activity_summary(self, count: int = 10) -> str:
        """Get a plain English summary of recent activity."""
        if not self._activity_reporter:
            return "Activity reporter not available."
        return self._activity_reporter.get_recent_summary(count)

    def get_gui_interface(self) -> Optional[OrchestratorGUIInterface]:
        """Get the GUI interface for status and control."""
        return self._gui_interface

    def get_streaming_interface(self) -> Optional[OrchestratorStreamingInterface]:
        """Get the streaming interface for real-time GUI updates."""
        return self._streaming_interface

    def get_failure_recovery(self) -> Optional[FailureRecoveryIntegration]:
        """Get the failure recovery integration."""
        return self._failure_recovery

    def get_failure_stats(self) -> Dict[str, Any]:
        """Get failure recovery statistics."""
        if not self._failure_recovery:
            return {}
        return self._failure_recovery.get_recovery_stats()

    def set_auto_recovery(self, enabled: bool):
        """Enable or disable automatic failure recovery."""
        if self._failure_recovery:
            self._failure_recovery.set_auto_recovery(enabled)

    def get_failure_history(self, workflow_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Get failure history."""
        if not self._failure_recovery:
            return []
        failures = self._failure_recovery.get_failure_history(workflow_id, limit)
        return [
            {
                "workflow_id": f.workflow_id,
                "task_id": f.task_id,
                "capability_name": f.capability_name,
                "error": f.error,
                "error_type": f.error_type,
                "attempt": f.attempt,
                "timestamp": f.timestamp,
            }
            for f in failures
        ]

    def _publish_event(self, event_type: str, payload: Dict[str, Any]):
        """Publish an event to the event bus."""
        try:
            event = Event(
                name=event_type,
                data=payload,
                source="central_orchestrator",
                priority=EventPriority.NORMAL
            )
            self._event_bus.publish(event)
        except Exception as e:
            logger.warning(f"Failed to publish event {event_type}: {e}")


class _BuiltinCapability(Capability):
    """Placeholder built-in capability."""

    def _initialize(self) -> bool:
        return True

    def _activate(self) -> bool:
        return True

    def _deactivate(self) -> bool:
        return True


# Global orchestrator instance
_orchestrator_instance: Optional[CentralOrchestrator] = None
_orchestrator_lock = threading.Lock()


def get_orchestrator(config: Optional[OrchestratorConfig] = None) -> CentralOrchestrator:
    """Get the global orchestrator instance."""
    global _orchestrator_instance
    with _orchestrator_lock:
        if _orchestrator_instance is None:
            _orchestrator_instance = CentralOrchestrator(config)
        return _orchestrator_instance


def reset_orchestrator() -> None:
    """Reset the global orchestrator instance (for testing)."""
    global _orchestrator_instance
    with _orchestrator_lock:
        if _orchestrator_instance:
            _orchestrator_instance.stop()
        _orchestrator_instance = None