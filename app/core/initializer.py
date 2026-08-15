"""
SystemInitializer - Single-pass construction of all Freya subsystems.

Breaks circular dependencies by composing all components in the correct order.
No component holds a reference to FreyaAgent; all cross-component deps are protocols.
"""

import time
import threading
from pathlib import Path
from typing import Optional

from app.core.protocols import (
    SystemConfig,
    InfrastructureBundle,
    InitializedSystem,
    IntelligenceBundle,
)

# Infrastructure (no deps)
from app.core.events import EventBus, set_event_bus
from app.core.background_jobs import BackgroundJobService, set_job_service
from app.core.observability import (
    ObservabilityHub,
    ComponentInfo,
    ComponentType,
    HealthCheck,
    HealthResult,
    HealthStatus,
    set_observability_hub,
)
from app.core.config_hot_reload import ConfigHotReload, create_config_hot_reload
from app.core.file_watcher import FileWatcher

# LLM Stack (replaces LLM + Priority + ChatActivity)
from app.core.llm_stack import LLMStack

# Memory Coordinator (depends on workspace)
from app.memory.coordinator import MemoryCoordinator, create_memory_coordinator

# Tool Manager (depends on workspace)
from app.core.tool_manager import ToolManager

# Intelligence (G1, G2, G3) - Knowledge-first routing
from app.intelligence.intelligence import Intelligence, create_intelligence
from app.memory.unified_retrieval import UnifiedRetrieval
from app.decision.manager import DecisionManager

# Knowledge-First Resolver
from app.routing.knowledge_first_resolver import KnowledgeFirstResolver

# Unified Router (depends on memory, tools, priority_llm, chat_activity, unified_retrieval, intelligence)
from app.routing.unified_router import UnifiedRouter

# Execution Engine (depends on router, tools, memory, priority_llm, chat_activity)
from app.execution.engine import ExecutionEngine

# Conversation Control (depends on execution_engine for callbacks)
from app.conversational_control import ConversationControlHandler

# Agent Facade (composes all above)
from app.agent.facade_impl import AgentFacadeImpl

# Canonical autonomy and orchestration
from app.autonomy.manager import AutonomyManager
from app.orchestrator.workflow_orchestrator import WorkflowOrchestrator
from app.orchestrator.capability_registry import CapabilityRegistry
from app.orchestrator.safety_gate import SafetyGate

# Diagnostics (Q1)
from app.diagnostics.diagnostic_engine import DiagnosticEngine, DiagnosticConfig

# SafeSelfImprovement (Q2)
from app.safe_self_improvement.self_improvement import create_self_improvement_engine, SafeSelfImprovementConfig

# LearningPipeline
from app.learning.pipeline import create_learning_pipeline

# AnswerVerifier (V1) with AnswerRepairLoop (AR) and AnswerSafeFailure (SF1)
from app.verification.answer_verifier import AnswerVerifier

from app.core.logger import logger


class SystemInitializer:
    """
    Single-pass construction of all Freya subsystems.

    Target construction order:
    1. Infrastructure
    2. LLMStack
    3. MemoryCoordinator
    4. IntelligenceEngine
    5. CapabilityRegistry
    6. UnifiedRouter
    7. ExecutionEngine
    8. WorkflowOrchestrator
    9. ConversationControl
    10. AgentFacadeImpl
    11. AutonomyManager
    12. LearningPipeline
    13. Diagnostics
    14. Safe Self-Improvement

    Supporting dependencies such as ToolManager and SafetyGate are constructed
    only to satisfy the declared target components. Dependencies that would
    violate target order are late-bound after their target component exists.
    """

    def __init__(self, workspace: Path, config: Optional[SystemConfig] = None):
        self.workspace = workspace
        self.config = config or SystemConfig()
        self._start_time = time.time()

    def initialize(self) -> InitializedSystem:
        """Initialize all subsystems in the correct dependency order."""
        logger.info("[SystemInitializer] Starting system initialization...")

        # ------------------------------------------------------------------
        # 1. Infrastructure (no deps)
        # ------------------------------------------------------------------
        event_bus = EventBus()
        self.event_bus = event_bus
        # Compatibility collaborators still obtain shared infrastructure through
        # module-level accessors.  Bind those accessors before constructing any
        # production component so every service joins this application graph.
        set_event_bus(event_bus)
        logger.debug("[SystemInitializer] EventBus created")

        job_service = BackgroundJobService(event_bus=event_bus)
        set_job_service(job_service)
        job_service.start()
        logger.debug("[SystemInitializer] BackgroundJobService started")

        observability = ObservabilityHub(event_bus=event_bus)
        set_observability_hub(observability)
        if self.config.enable_observability:
            observability.start()
        logger.debug("[SystemInitializer] ObservabilityHub started")

        config_hot_reload = None
        if self.config.enable_config_hot_reload:
            from app.core.config import config as global_config
            config_hot_reload = create_config_hot_reload(
                config=global_config,
                event_bus=event_bus,
            )
            config_hot_reload.start()
        logger.debug("[SystemInitializer] ConfigHotReload started")

        file_watcher = None
        if self.config.enable_file_watcher:
            file_watcher = FileWatcher(
                event_bus=event_bus,
                paths=[str(self.workspace)],
                recursive=True,
            )
            file_watcher.start()
        logger.debug("[SystemInitializer] FileWatcher started")

        # ------------------------------------------------------------------
        # 2. LLM Stack (replaces LLM + Priority + ChatActivity)
        # ------------------------------------------------------------------
        llm_stack = LLMStack()
        priority_llm = llm_stack.priority_llm
        chat_activity = llm_stack.chat_activity
        # Replace global priority LLM so existing code works
        from app.core.priority_llm import set_priority_llm
        set_priority_llm(priority_llm)
        # Set chat activity provider on job service for chat-aware yielding
        job_service.set_chat_activity_provider(chat_activity)
        logger.debug("[SystemInitializer] LLMStack created (PriorityLLM + ChatActivity)")

        # ------------------------------------------------------------------
        # 3. Memory Coordinator (depends on workspace, event_bus)
        # ------------------------------------------------------------------
        memory_coordinator = create_memory_coordinator(self.workspace, event_bus)
        logger.debug("[SystemInitializer] MemoryCoordinator created")

        # ------------------------------------------------------------------
        # 4. Tool Manager (depends on workspace)
        # ------------------------------------------------------------------
        tool_manager = ToolManager(str(self.workspace))
        logger.debug("[SystemInitializer] ToolManager created")

        # ------------------------------------------------------------------
        # 5. Intelligence (G1, G2, G3) - Knowledge-First Routing
        #    Depends on memory_coordinator (unified_retrieval, goal_storage, conversation_memory)
        # ------------------------------------------------------------------
        intelligence = create_intelligence(
            unified_retrieval=memory_coordinator.unified_retrieval,
            goal_storage=memory_coordinator.goal_storage,
            conversation_memory=memory_coordinator.conversation_memory,
        )
        logger.debug("[SystemInitializer] Intelligence created")

        # ------------------------------------------------------------------
        # 5a. Decision Manager (shared by decision and safety capabilities)
        # ------------------------------------------------------------------
        decision_manager = DecisionManager(
            workspace=str(self.workspace),
            goal_storage=memory_coordinator.goal_storage,
            unified_retrieval=memory_coordinator.unified_retrieval,
            event_bus=event_bus,
            job_service=job_service,
            observability=observability,
        )
        self.decision_manager = decision_manager
        logger.debug("[SystemInitializer] DecisionManager created")

        # ------------------------------------------------------------------
        # 6. Capability Registry (required for KnowledgeFirstResolver)
        # ------------------------------------------------------------------
        capability_registry = CapabilityRegistry()
        # Register built-in capabilities with the registry
        from app.orchestrator.capabilities import create_all_capabilities
        for cap in create_all_capabilities():
            capability_registry.register(cap)
        research_capability = capability_registry.get_capability("research_capability")
        if research_capability is not None and hasattr(research_capability, "set_tool_manager"):
            research_capability.set_tool_manager(tool_manager)
        capability_registry.start()

        # The execution path uses this non-discoverable capability after the
        # SafetyGate approves an action.  Its registered handler delegates to
        # ToolManager, completing the target capability-to-tool chain without
        # creating another capability owner.
        from app.orchestrator.capability_registry import Capability, CapabilityMetadata

        def dispatch_tool_action(inputs):
            tool_name = inputs.get("tool")
            tool_args = inputs.get("args", {})
            if not isinstance(tool_name, str) or not tool_name:
                return {"success": False, "message": "An approved action requires a tool name."}
            if not isinstance(tool_args, dict):
                return {"success": False, "message": "Tool arguments must be an object."}
            tool_result = tool_manager.execute(tool_name, **tool_args)
            return {
                "success": tool_result.success,
                "tool_result": tool_result,
                "message": tool_result.error,
            }

        capability_registry.register(Capability(
            CapabilityMetadata(
                name="tool_dispatch",
                description="Internal approved action dispatch to ToolManager",
                auto_discoverable=False,
                default_action="execute",
                supported_actions=["execute"],
                required_collaborators=["tool_manager"],
            ),
            handler=dispatch_tool_action,
        ), registered_by="SystemInitializer")
        capability_audit = capability_registry.audit_startup(
            collaborators={"tool_manager": tool_manager},
            isolate_unsafe_discoverability=True,
        )
        if not capability_audit["passed"]:
            raise RuntimeError(
                "Capability startup audit failed: " + "; ".join(capability_audit["errors"])
            )
        self.capability_audit = capability_audit
        logger.debug("[SystemInitializer] CapabilityRegistry created, started, and audited")

        # ------------------------------------------------------------------
        # 7. Safety Gate (required for ExecutionEngine/WorkflowOrchestrator)
        # ------------------------------------------------------------------
        safety_gate = SafetyGate(registry=capability_registry)
        browser_capability = capability_registry.get_capability("browser_capability")
        if browser_capability is not None:
            if hasattr(browser_capability, "set_profile_dir"):
                browser_capability.set_profile_dir(str(self.workspace / "data" / "browser-profile"))
            if hasattr(browser_capability, "set_safety_gate"):
                browser_capability.set_safety_gate(safety_gate)
        logger.debug("[SystemInitializer] SafetyGate created and BrowserCapability bound")

        # ------------------------------------------------------------------
        # 8. Unified Router (depends on memory, tools, priority_llm, chat_activity, unified_retrieval, intelligence, llm_stack)
        # ------------------------------------------------------------------
        unified_router = UnifiedRouter(
            memory=memory_coordinator,
            tools=tool_manager,
            llm=priority_llm,
            chat_activity=chat_activity,
            unified_retrieval=memory_coordinator.unified_retrieval,
            intelligence=intelligence,
            llm_stack=llm_stack,
            capability_registry=capability_registry,
        )
        logger.debug("[SystemInitializer] UnifiedRouter created with KnowledgeFirstResolver")

        # ------------------------------------------------------------------
        # 9. Execution Engine (depends on router, tools, memory, priority_llm, chat_activity, safety_gate)
        # ------------------------------------------------------------------
        execution_engine = ExecutionEngine(
            router=unified_router,
            tools=tool_manager,
            memory=memory_coordinator,
            llm=priority_llm,
            chat_activity=chat_activity,
            observability_hub=observability,
            safety_gate=safety_gate,
        )
        logger.debug("[SystemInitializer] ExecutionEngine created")

        # AnswerVerifier belongs to the execution/answer path.  It is created
        # here with the LLM dependency and receives LearningPipeline only after
        # step 12, preserving the target initialization order.
        answer_verifier = AnswerVerifier(priority_llm=priority_llm)
        logger.debug("[SystemInitializer] AnswerVerifier created with late-bound learning")

        # ------------------------------------------------------------------
        # 8. WorkflowOrchestrator
        # ------------------------------------------------------------------
        orchestrator = None
        if self.config.enable_orchestrator:
            orchestrator = WorkflowOrchestrator(
                capability_registry=capability_registry,
                router=unified_router,
                executor=execution_engine,
                safety_gate=safety_gate,
                chat_activity=chat_activity,
                event_bus=event_bus,
                job_service=job_service,
            )
            if not orchestrator.start():
                raise RuntimeError("WorkflowOrchestrator failed to start")
            logger.info("[SystemInitializer] WorkflowOrchestrator started")

        # ------------------------------------------------------------------
        # 9. ConversationControl
        # ------------------------------------------------------------------
        conversation_control = ConversationControlHandler(
            executor=execution_engine,
            plan_manager=execution_engine.plan_manager,
            conversation_memory=memory_coordinator.conversation_memory,
            router=unified_router,
            memory_coordinator=memory_coordinator,
            intelligence=intelligence,
            chat_activity=chat_activity,
        )
        execution_engine.set_conversation_control(conversation_control)
        logger.debug("[SystemInitializer] ConversationControlHandler created")

        # ------------------------------------------------------------------
        # 10. AgentFacadeImpl
        # ------------------------------------------------------------------
        facade = AgentFacadeImpl(
            router=unified_router,
            execution=execution_engine,
            control=conversation_control,
            chat_activity=chat_activity,
            priority_llm=priority_llm,
            memory=memory_coordinator,
            answer_verifier=answer_verifier,
        )
        logger.debug("[SystemInitializer] AgentFacadeImpl created")

        # ------------------------------------------------------------------
        # 11. AutonomyManager.  It is constructed before LearningPipeline and
        # started only after the late-bound learning edge is attached.
        # ------------------------------------------------------------------
        autonomy = None
        if self.config.enable_autonomy:
            autonomy = AutonomyManager(
                event_bus=event_bus,
                observability=observability,
                learning_pipeline=None,
                goal_storage=memory_coordinator.goal_storage,
                workflow_orchestrator=orchestrator,
                job_service=job_service,
            )
            logger.debug("[SystemInitializer] AutonomyManager created with late-bound learning")

        # ------------------------------------------------------------------
        # 12. LearningPipeline and late-bound collaborators
        # ------------------------------------------------------------------
        learning_pipeline = create_learning_pipeline(
            memory_coordinator=memory_coordinator,
            event_bus=event_bus,
        )
        if research_capability is not None and hasattr(research_capability, "set_learning_pipeline"):
            research_capability.set_learning_pipeline(learning_pipeline)
        execution_engine.set_learning_pipeline(learning_pipeline)
        answer_verifier.set_learning_pipeline(learning_pipeline)
        if autonomy is not None:
            autonomy.set_learning_pipeline(learning_pipeline)
            if not autonomy.start() or not autonomy.is_running():
                raise RuntimeError("AutonomyManager failed to start")
            logger.info("[SystemInitializer] AutonomyManager started")
        logger.debug("[SystemInitializer] LearningPipeline created and late-bound")

        # ------------------------------------------------------------------
        # 13. Diagnostics (Q1)
        # ------------------------------------------------------------------
        diagnostic_engine = None
        if self.config.enable_diagnostics:
            diagnostic_config = DiagnosticConfig()
            diagnostic_engine = DiagnosticEngine(
                workspace=str(self.workspace),
                config=diagnostic_config,
                event_bus=event_bus,
            )
            execution_engine.set_diagnostics(diagnostic_engine)
            logger.debug("[SystemInitializer] DiagnosticEngine created")

        # ------------------------------------------------------------------
        # 14. Safe Self-Improvement (Q2)
        # ------------------------------------------------------------------
        self_improvement = None
        if self.config.enable_self_improvement:
            ssi_config = SafeSelfImprovementConfig()
            self_improvement = create_self_improvement_engine(
                config=ssi_config,
                event_bus=event_bus,
                workflow_orchestrator=orchestrator,
            )
            logger.debug("[SystemInitializer] SafeSelfImprovementEngine created")

        # Bind the already-registered capability objects to this initializer's
        # production graph.  This is deliberately late-bound because execution
        # and orchestration are constructed after the registry, and it never
        # creates replacement managers or a second capability registry.
        self._bind_registered_capabilities(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            decision_manager=decision_manager,
            observability=observability,
            safety_gate=safety_gate,
            execution_engine=execution_engine,
            orchestrator=orchestrator,
        )

        # ------------------------------------------------------------------
        # Finalize
        # ------------------------------------------------------------------
        # Query adapters are registered by UnifiedRouter after the first audit.
        # Re-audit the complete surface now that their explicit safe-query
        # contracts are present, still using the same canonical registry.
        capability_audit = capability_registry.audit_startup(
            collaborators={"tool_manager": tool_manager},
            isolate_unsafe_discoverability=True,
        )
        if not capability_audit["passed"]:
            raise RuntimeError(
                "Capability startup audit failed: " + "; ".join(capability_audit["errors"])
            )
        self.capability_audit = capability_audit
        self._register_readiness_checks(
            observability=observability,
            job_service=job_service,
            priority_llm=priority_llm,
            facade=facade,
            orchestrator=orchestrator,
            autonomy=autonomy,
            memory_coordinator=memory_coordinator,
            capability_registry=capability_registry,
            unified_router=unified_router,
            execution_engine=execution_engine,
            learning_pipeline=learning_pipeline,
            tool_manager=tool_manager,
        )
        # Populate the existing observability state before exposing readiness.
        observability.run_health_checks()

        infra = InfrastructureBundle(
            event_bus=event_bus,
            job_service=job_service,
            observability=observability,
            config_hot_reload=config_hot_reload,
            file_watcher=file_watcher,
        )

        elapsed = time.time() - self._start_time
        logger.info(f"[SystemInitializer] System initialized in {elapsed:.2f}s")

        # Emit initialization event
        event_bus.emit(
            "system.initialized",
            data={
                "components": [
                    "event_bus",
                    "job_service",
                    "observability",
                    "llm_stack",
                    "chat_activity",
                    "memory_coordinator",
                    "learning_pipeline",
                    "tool_manager",
                    "intelligence",
                    "capability_registry",
                    "safety_gate",
                    "unified_router",
                    "execution_engine",
                    "conversation_control",
                    "agent_facade",
                    "diagnostics",
                    "self_improvement",
                ] + (["autonomy"] if autonomy else []) + (["orchestrator"] if orchestrator else []),
                "elapsed_seconds": elapsed,
            },
            source="SystemInitializer",
        )

        return InitializedSystem(
            facade=facade,
            chat_activity=chat_activity,
            priority_llm=priority_llm,
            memory=memory_coordinator,
            execution=execution_engine,
            control=conversation_control,
            autonomy=autonomy,
            orchestrator=orchestrator,
            infra=infra,
            intelligence=intelligence,
            learning_pipeline=learning_pipeline,
            diagnostics=diagnostic_engine,
            self_improvement=self_improvement,
        )

    def _bind_registered_capabilities(
        self,
        *,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        decision_manager: DecisionManager,
        observability: ObservabilityHub,
        safety_gate: SafetyGate,
        execution_engine: ExecutionEngine,
        orchestrator: Optional[WorkflowOrchestrator],
    ) -> None:
        """Late-bind registered capabilities to the canonical production graph."""
        code_execution = capability_registry.get_capability("code_execution")
        if code_execution is not None and hasattr(code_execution, "set_components"):
            code_execution.set_components(
                execution_engine._executor,
                execution_engine.verification_runner,
                execution_engine.repair_loop.patch_engine,
                tool_manager,
            )

        decision = capability_registry.get_capability("decision_engine")
        if decision is not None and hasattr(decision, "set_decision_manager"):
            decision.set_decision_manager(decision_manager)

        monitoring = capability_registry.get_capability("system_monitoring")
        if monitoring is not None and hasattr(monitoring, "set_observability"):
            monitoring.set_observability(observability)

        tool_registry = capability_registry.get_capability("tool_registry")
        if tool_registry is not None and hasattr(tool_registry, "set_tools"):
            tool_registry.set_tools(tool_manager)

        safety = capability_registry.get_capability("safety_guard")
        if safety is not None and hasattr(safety, "set_safety_gate"):
            safety.set_safety_gate(safety_gate)

        orchestration = capability_registry.get_capability("orchestration_core")
        if orchestration is not None and orchestrator is not None and hasattr(orchestration, "set_orchestrator"):
            orchestration.set_orchestrator(orchestrator)

    def _register_readiness_checks(
        self,
        *,
        observability: ObservabilityHub,
        job_service: BackgroundJobService,
        priority_llm,
        facade,
        orchestrator,
        autonomy,
        memory_coordinator=None,
        capability_registry=None,
        unified_router=None,
        execution_engine=None,
        learning_pipeline=None,
        tool_manager=None,
    ) -> None:
        """Register required runtime dependencies with the shared health monitor."""
        self._register_readiness_component(
            observability,
            name="agent_facade",
            component_type=ComponentType.AGENT,
            category="agent",
            check=lambda: facade is not None,
        )
        self._register_readiness_component(
            observability,
            name="llm_providers",
            component_type=ComponentType.EXTERNAL,
            category="providers",
            check=lambda: self._provider_readiness_result(priority_llm),
        )
        self._register_readiness_component(
            observability,
            name="background_job_service",
            component_type=ComponentType.SERVICE,
            category="background_service",
            check=job_service.is_running,
        )
        self._register_readiness_component(
            observability,
            name="memory_coordinator",
            component_type=ComponentType.SERVICE,
            category="target_path",
            check=lambda: (
                memory_coordinator is not None
                and getattr(memory_coordinator, "unified_retrieval", None) is not None
                and callable(getattr(memory_coordinator, "record_conversation", None))
            ),
        )
        self._register_readiness_component(
            observability,
            name="capability_registry",
            component_type=ComponentType.SERVICE,
            category="target_path",
            check=lambda: (
                capability_registry is not None
                and capability_registry.is_running()
                and bool(capability_registry.get_all())
            ),
        )
        self._register_readiness_component(
            observability,
            name="unified_router",
            component_type=ComponentType.SERVICE,
            category="target_path",
            check=lambda: callable(getattr(unified_router, "route", None)),
        )
        self._register_readiness_component(
            observability,
            name="execution_engine",
            component_type=ComponentType.SERVICE,
            category="target_path",
            check=lambda: callable(getattr(execution_engine, "execute_plan", None)),
        )
        self._register_readiness_component(
            observability,
            name="learning_pipeline",
            component_type=ComponentType.SERVICE,
            category="target_path",
            check=lambda: callable(getattr(learning_pipeline, "run", None)),
        )
        self._register_readiness_component(
            observability,
            name="tool_manager",
            component_type=ComponentType.SERVICE,
            category="target_path",
            check=lambda: (
                callable(getattr(tool_manager, "execute", None))
                and callable(getattr(tool_manager, "register", None))
            ),
        )
        self._register_readiness_component(
            observability,
            name="bounded_shutdown",
            component_type=ComponentType.SERVICE,
            category="lifecycle",
            check=lambda: self.config.shutdown_timeout_seconds > 0,
        )

        if orchestrator is not None:
            self._register_readiness_component(
                observability,
                name="workflow_orchestrator",
                component_type=ComponentType.SERVICE,
                category="background_service",
                check=lambda: (
                    orchestrator.get_system_status()["orchestrator"]["state"] == "running"
                ),
            )
        if autonomy is not None:
            self._register_readiness_component(
                observability,
                name="autonomy_manager",
                component_type=ComponentType.SERVICE,
                category="background_service",
                check=autonomy.is_running,
            )

    @staticmethod
    def _register_readiness_component(
        observability: ObservabilityHub,
        *,
        name: str,
        component_type: ComponentType,
        category: str,
        check,
    ) -> None:
        observability.register_component(ComponentInfo(
            name=name,
            component_type=component_type,
            metadata={"readiness": {"category": category, "required": True}},
        ))
        observability.add_health_check(HealthCheck(
            name=f"{name}.readiness",
            component=name,
            component_type=component_type,
            check_func=check,
            critical=True,
        ))

    @staticmethod
    def _provider_readiness_result(priority_llm) -> HealthResult:
        """Translate active provider observations into one readiness health result."""
        provider_health = priority_llm.get_provider_health()
        providers = {
            name: {
                "healthy": status.is_healthy,
                "reachable": status.is_reachable,
                "model_available": status.model_available,
                "state": status.state.value,
                "error": status.error_message,
                "checked_at": status.checked_at,
            }
            for name, status in provider_health.items()
        }
        healthy_count = sum(1 for status in provider_health.values() if status.is_healthy)
        local_model_state = (
            "healthy" if providers and healthy_count == len(providers)
            else "degraded" if healthy_count
            else "unavailable_but_safe"
        )
        readiness_metadata = {
            "providers": providers,
            "local_model_state": local_model_state,
            "safe_paths": ["local_memory", "registered_capabilities"],
        }

        if not providers:
            return HealthResult(
                name="llm_providers.readiness",
                component="llm_providers",
                status=HealthStatus.UNHEALTHY,
                message="No LLM providers are configured",
                metadata=readiness_metadata,
            )
        if healthy_count == len(providers):
            status = HealthStatus.HEALTHY
            message = "All configured LLM providers are available"
        elif healthy_count:
            status = HealthStatus.DEGRADED
            message = "At least one configured LLM provider is available"
        else:
            status = HealthStatus.UNHEALTHY
            message = "No configured LLM provider is available"

        return HealthResult(
            name="llm_providers.readiness",
            component="llm_providers",
            status=status,
            message=message,
            metadata=readiness_metadata,
        )

    def shutdown(self, system: InitializedSystem) -> None:
        """Gracefully shutdown all subsystems."""
        logger.info("[SystemInitializer] Shutting down system...")

        if system.autonomy:
            system.autonomy.stop()
            logger.debug("[SystemInitializer] AutonomyManager stopped")

        if system.self_improvement:
            system.self_improvement.shutdown()
            logger.debug("[SystemInitializer] SafeSelfImprovementEngine stopped")

        if system.orchestrator:
            system.orchestrator.stop()
            logger.debug("[SystemInitializer] WorkflowOrchestrator stopped")

        if system.infra.config_hot_reload:
            system.infra.config_hot_reload.stop()
            logger.debug("[SystemInitializer] ConfigHotReload stopped")

        if system.infra.file_watcher:
            system.infra.file_watcher.stop()
            logger.debug("[SystemInitializer] FileWatcher stopped")

        if system.infra.observability:
            system.infra.observability.stop()
            logger.debug("[SystemInitializer] ObservabilityHub stopped")

        shutdown_started = time.monotonic()
        system.infra.job_service.shutdown(
            wait=True,
            timeout=self.config.shutdown_timeout_seconds,
        )
        shutdown_elapsed = time.monotonic() - shutdown_started
        if shutdown_elapsed > self.config.shutdown_timeout_seconds:
            logger.warning(
                "[SystemInitializer] BackgroundJobService exceeded shutdown budget "
                f"({shutdown_elapsed:.2f}s > {self.config.shutdown_timeout_seconds:.2f}s)"
            )
        else:
            logger.debug(
                "[SystemInitializer] BackgroundJobService shut down within budget "
                f"({shutdown_elapsed:.2f}s)"
            )

        system.infra.event_bus.shutdown()
        logger.debug("[SystemInitializer] EventBus shut down")

        system.priority_llm.shutdown()
        logger.debug("[SystemInitializer] PriorityLLMProvider shut down")

        # Do not leave module-level accessors pointing at shut-down services.
        # The next FreyaApp start constructs and binds a fresh runtime graph.
        set_observability_hub(None)
        set_job_service(None)
        set_event_bus(None)

        logger.info("[SystemInitializer] Shutdown complete")
