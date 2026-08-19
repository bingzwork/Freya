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
from app.core.events import Event, EventBus, set_event_bus
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
from app.avatar.runtime import AvatarRuntime

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

# Runtime observation and diagnostics
from app.self_observation.runtime_awareness import RuntimeAwareness, AwarenessConfig, set_runtime_awareness
from app.self_observation.system_anatomy import SystemAnatomy
from app.self_observation.predictive_diagnostics import PredictiveDiagnostics, PredictiveDiagnosticsConfig
from app.diagnostics.diagnostic_engine import DiagnosticEngine, DiagnosticConfig
from app.diagnostics.grouping import DiagnosticEvent, DiagnosticGrouper

# SafeSelfImprovement (Q2)
from app.safe_self_improvement.self_improvement import create_self_improvement_engine, SafeSelfImprovementConfig
from app.safe_self_improvement.measurement import ImprovementMeasurement
from app.safe_self_improvement.canary import CanaryValidator, CanaryDecision
from app.safe_self_improvement.promotion import PatchPromotionManager, PromotionPipelineConfig
from app.safe_self_improvement.rollback import create_rollback_manager
from app.core.safety_gates import SafetyPromotionGates, set_safety_gates

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

        avatar_runtime = None
        avatar_bridge = None
        if self.config.enable_avatar:
            try:
                model_path = self.config.avatar_model_path or (self.workspace / "client" / "public" / "avatars" / "current_avatar.vrm")
                avatar_runtime = AvatarRuntime(event_bus, enabled=True, model_path=model_path)
                avatar_runtime.start()
                avatar_bridge = avatar_runtime.create_ui_bridge()
                logger.debug("[SystemInitializer] AvatarRuntime started")
            except Exception as exc:
                # Avatar rendering is non-critical UI; Freya must still start.
                logger.warning(f"[SystemInitializer] AvatarRuntime unavailable: {exc}")

        job_service = BackgroundJobService(event_bus=event_bus)
        set_job_service(job_service)
        logger.debug("[SystemInitializer] BackgroundJobService constructed")

        observability = ObservabilityHub(event_bus=event_bus)
        set_observability_hub(observability)
        logger.debug("[SystemInitializer] ObservabilityHub constructed")

        config_hot_reload = None
        if self.config.enable_config_hot_reload:
            from app.core.config import config as global_config
            config_hot_reload = create_config_hot_reload(
                config=global_config,
                event_bus=event_bus,
            )
        logger.debug("[SystemInitializer] ConfigHotReload constructed")

        file_watcher = None
        if self.config.enable_file_watcher:
            file_watcher = FileWatcher(
                event_bus=event_bus,
                paths=[str(self.workspace)],
                recursive=True,
            )
        logger.debug("[SystemInitializer] FileWatcher constructed")

        # ------------------------------------------------------------------
        # 2. LLM Stack (replaces LLM + Priority + ChatActivity)
        # ------------------------------------------------------------------
        from app.core.config import config as global_config
        llm_stack = LLMStack(model=global_config.model)
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
        self._memory_coordinator = memory_coordinator
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
        self._intelligence = intelligence
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
        # Keep the ten audited extension areas on the same canonical registry.
        # Providers are injectable and remain unavailable-safe when optional
        # credentials, hardware, binaries, or SDKs are not configured.
        from app.capabilities.extended import build_extended_capabilities
        for cap in build_extended_capabilities(workspace=self.workspace, database_path=getattr(self.config, "database_path", None)):
            capability_registry.register(cap, registered_by="SystemInitializer")
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
                auto_discoverable=True,
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
        research_capability = capability_registry.get_capability("research_capability")
        if research_capability is not None and hasattr(research_capability, "set_browser_capability"):
            research_capability.set_browser_capability(browser_capability)
        vision_capability = capability_registry.get_capability("vision")
        if research_capability is not None and vision_capability is not None and hasattr(research_capability, "set_vision_capability"):
            research_capability.set_vision_capability(vision_capability)
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
            logger.debug("[SystemInitializer] WorkflowOrchestrator constructed")

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
                config=self.config.autonomy_config,
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
        self._learning_pipeline = learning_pipeline
        if research_capability is not None and hasattr(research_capability, "set_learning_pipeline"):
            research_capability.set_learning_pipeline(learning_pipeline)
        execution_engine.set_learning_pipeline(learning_pipeline)
        answer_verifier.set_learning_pipeline(learning_pipeline)
        if autonomy is not None:
            autonomy.set_learning_pipeline(learning_pipeline)
        logger.debug("[SystemInitializer] LearningPipeline created and late-bound")

        # ------------------------------------------------------------------
        # 13. Runtime observation and live anatomy
        # ------------------------------------------------------------------
        runtime_awareness = None
        system_anatomy = None
        if self.config.enable_diagnostics:
            runtime_awareness = RuntimeAwareness(
                orchestrator=orchestrator,
                decision_manager=decision_manager,
                memory_retrieval=memory_coordinator.unified_retrieval,
                autonomy_manager=autonomy,
                goal_storage=memory_coordinator.goal_storage,
                config=AwarenessConfig(),
                event_bus=event_bus,
                observability=observability,
            )
            set_runtime_awareness(runtime_awareness)
            system_anatomy = SystemAnatomy(
                observability=observability,
                capability_registry=capability_registry,
                orchestrator=orchestrator,
            )
            logger.debug("[SystemInitializer] RuntimeAwareness and SystemAnatomy created")

        # ------------------------------------------------------------------
        # 14. Diagnostics and deterministic post-processing
        # ------------------------------------------------------------------
        diagnostic_engine = None
        diagnostic_grouper = None
        if self.config.enable_diagnostics:
            diagnostic_engine = DiagnosticEngine(
                workspace=str(self.workspace),
                config=DiagnosticConfig(),
                event_bus=event_bus,
            )
            execution_engine.set_diagnostics(diagnostic_engine)
            dependencies = {
                node["name"]: node.get("dependencies", [])
                for node in system_anatomy.list_nodes()
            }
            diagnostic_grouper = DiagnosticGrouper(dependencies=dependencies)

            def _group_completed_diagnostics(event: Event):
                grouped_events = []
                for index, issue in enumerate((event.data or {}).get("issues", [])):
                    if not isinstance(issue, dict):
                        continue
                    grouped_events.append(DiagnosticEvent(
                        event_id=str(issue.get("id") or f"diagnostic-{index}"),
                        source="DiagnosticEngine",
                        failure_type=str(issue.get("type") or issue.get("severity") or "unknown"),
                        component=str(issue.get("file") or issue.get("component") or "workspace"),
                        operation=str(issue.get("operation") or "diagnostic"),
                        message=str(issue.get("description") or issue.get("message") or ""),
                        fingerprint=str(issue.get("fingerprint") or issue.get("code") or ""),
                        timestamp=str(issue.get("timestamp") or event.timestamp),
                        dependencies=list(issue.get("dependencies", [])) if isinstance(issue.get("dependencies", []), list) else [],
                        workflow_id=str(issue.get("workflow_id") or ""),
                        causal_parent=(str(issue["causal_parent"]) if issue.get("causal_parent") else None),
                        metadata=issue,
                    ))
                try:
                    self._last_diagnostic_grouping = diagnostic_grouper.group(grouped_events)
                except Exception as error:
                    self._last_diagnostic_grouping = None
                    logger.error(f"[SystemInitializer] Diagnostic grouping failed: {error}")
                    event_bus.emit(
                        "diagnostics.grouping_failed",
                        {
                            "error": str(error),
                            "raw_event_id": event.event_id,
                            "issue_count": len(grouped_events),
                        },
                        source="DiagnosticGrouper",
                    )
                    return

                event_bus.emit(
                    "diagnostics.grouped",
                    {
                        "report": self._last_diagnostic_grouping.to_dict(),
                        "raw_event_id": event.event_id,
                    },
                    source="DiagnosticGrouper",
                )

            self._last_diagnostic_grouping = None
            self._diagnostic_grouping_subscription = event_bus.subscribe(
                "diagnostics.completed", _group_completed_diagnostics
            )
            logger.debug("[SystemInitializer] DiagnosticEngine and DiagnosticGrouper connected")

        # ------------------------------------------------------------------
        # 15. Predictive diagnostics, measurement, and controlled canary
        # ------------------------------------------------------------------
        predictive_diagnostics = None
        if self.config.enable_diagnostics:
            predictive_diagnostics = PredictiveDiagnostics(
                runtime_awareness=runtime_awareness,
                config=PredictiveDiagnosticsConfig(),
                event_bus=event_bus,
                observability=observability,
            )

        improvement_measurement = ImprovementMeasurement(
            collector=observability.get_system_metrics,
            provenance="ObservabilityHub",
        )

        def _controlled_canary_executor(candidate, execution_result):
            if execution_result.candidate_id != candidate.id:
                return {
                    "tested": "canonical verification runner",
                    "environment": "controlled-canary",
                    "executed": False,
                    "outcome": None,
                    "decision": CanaryDecision.INCONCLUSIVE.value,
                    "failures": ["candidate identity mismatch"],
                }
            verification_runner = getattr(execution_engine, "verification_runner", None)
            if verification_runner is None:
                return {
                    "tested": "canonical verification runner",
                    "environment": "controlled-canary",
                    "executed": False,
                    "outcome": None,
                    "decision": CanaryDecision.INCONCLUSIVE.value,
                    "failures": ["canonical verification runner unavailable"],
                }
            lint_result = verification_runner.lint()
            health = observability.get_health()
            health_status = health.get("status", "unknown") if isinstance(health, dict) else "unknown"
            passed = bool(lint_result.success) and health_status in {"healthy", "degraded"}
            return {
                "tested": "canonical verification runner lint plus live health",
                "environment": "controlled-canary",
                "executed": True,
                "outcome": "success" if passed else "failure",
                "decision": CanaryDecision.PASS.value if passed else CanaryDecision.FAIL.value,
                "metrics": {
                    "lint_passed": bool(lint_result.success),
                    "health_status": health_status,
                    "health_passed": health_status in {"healthy", "degraded"},
                },
                "baseline": (getattr(execution_result, "metadata", {}) or {}).get("canary_baseline", {}),
                "failures": [] if passed else ["controlled canary health or lint check failed"],
            }

        canary_validator = CanaryValidator(_controlled_canary_executor)

        # ------------------------------------------------------------------
        # 16. Authoritative safety and promotion boundary
        # ------------------------------------------------------------------
        safety_promotion_gates = SafetyPromotionGates()
        set_safety_gates(safety_promotion_gates)
        rollback_manager = create_rollback_manager(
            checkpoint_dir=str(self.workspace / "data" / "checkpoints")
        )
        promotion_manager = PatchPromotionManager(
            safety_gates=safety_promotion_gates,
            config=PromotionPipelineConfig(canary_validator=canary_validator),
            staging_dir=str(self.workspace / "data" / "promotion" / "staging"),
            production_dir=str(self.workspace / "data" / "promotion" / "production"),
            rollback_manager=rollback_manager,
        )

        # ------------------------------------------------------------------
        # 17. Safe Self-Improvement orchestration
        # ------------------------------------------------------------------
        self_improvement = None
        if self.config.enable_self_improvement:
            self_improvement = create_self_improvement_engine(
                config=SafeSelfImprovementConfig(),
                event_bus=event_bus,
                workflow_orchestrator=orchestrator,
                promotion_manager=promotion_manager,
                rollback_manager=rollback_manager,
                improvement_measurement=improvement_measurement,
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

        # Late-bind the new adapters to the same production collaborators. No
        # capability creates a replacement scheduler, HTTP stack, or workflow path.
        automation = capability_registry.get_capability("automation")
        if automation is not None and hasattr(automation, "set_services"):
            automation.set_services(job_service, orchestrator, workspace=self.workspace)
            automation.restore_persisted()

        vision = capability_registry.get_capability("vision")
        if vision is not None and hasattr(vision, "set_file_allowlist"):
            from app.core.file_allowlist import get_file_allowlist
            vision.set_file_allowlist(get_file_allowlist())

        api_connector = capability_registry.get_capability("api_connector")
        if api_connector is not None:
            if hasattr(api_connector, "set_safety_gate"):
                api_connector.set_safety_gate(safety_gate)
            if hasattr(api_connector, "set_policy"):
                import os
                configured_domains = {
                    item.strip() for item in os.getenv("FREYA_API_ALLOWED_DOMAINS", "").split(",")
                    if item.strip()
                }
                api_connector.set_policy(allowed_domains=configured_domains)

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

        # ------------------------------------------------------------------
        # Activation occurs only after construction, late binding, and event
        # subscriptions are complete.  This prevents partial-graph emissions.
        # ------------------------------------------------------------------
        job_service.start()
        if self.config.enable_observability:
            observability.start()
        if config_hot_reload is not None:
            config_hot_reload.start()
        if file_watcher is not None:
            file_watcher.start()
        if orchestrator is not None:
            if not orchestrator.start():
                raise RuntimeError("WorkflowOrchestrator failed to start")
            logger.info("[SystemInitializer] WorkflowOrchestrator started")
        if autonomy is not None and self.config.start_autonomy_on_boot:
            if not autonomy.start() or not autonomy.is_running():
                raise RuntimeError("AutonomyManager failed to start")
            logger.info("[SystemInitializer] AutonomyManager started")
        elif autonomy is not None:
            logger.info("[SystemInitializer] AutonomyManager constructed; startup state is OFF")
        if runtime_awareness is not None:
            runtime_awareness.start()
        if predictive_diagnostics is not None:
            predictive_diagnostics.start()

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
            runtime_awareness=runtime_awareness,
            system_anatomy=system_anatomy,
            diagnostic_engine=diagnostic_engine,
            diagnostic_grouper=diagnostic_grouper,
            predictive_diagnostics=predictive_diagnostics,
            improvement_measurement=improvement_measurement,
            canary_validator=canary_validator,
            promotion_manager=promotion_manager,
            self_improvement=self_improvement,
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
                    "runtime_awareness",
                    "system_anatomy",
                    "diagnostic_engine",
                    "diagnostic_grouper",
                    "predictive_diagnostics",
                    "improvement_measurement",
                    "canary_validator",
                    "patch_promotion_manager",
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
            diagnostic_grouper=diagnostic_grouper,
            predictive_diagnostics=predictive_diagnostics,
            runtime_awareness=runtime_awareness,
            system_anatomy=system_anatomy,
            improvement_measurement=improvement_measurement,
            canary_validator=canary_validator,
            patch_promotion_manager=promotion_manager,
            self_improvement=self_improvement,
            avatar=avatar_runtime,
            avatar_bridge=avatar_bridge,
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

        memory_capability = capability_registry.get_capability("memory_management")
        if memory_capability is not None and hasattr(memory_capability, "set_memory_coordinator"):
            memory_capability.set_memory_coordinator(self._memory_coordinator)

        learning_capability = capability_registry.get_capability("learning_pipeline")
        if learning_capability is not None and hasattr(learning_capability, "set_learning_pipeline"):
            learning_capability.set_learning_pipeline(self._learning_pipeline, self._memory_coordinator)

        knowledge_capability = capability_registry.get_capability("knowledge_base")
        if knowledge_capability is not None and hasattr(knowledge_capability, "set_memory_services"):
            knowledge_capability.set_memory_services(
                self._memory_coordinator,
                self._memory_coordinator.unified_retrieval,
            )

        reasoning_capability = capability_registry.get_capability("reasoning_engine")
        if reasoning_capability is not None and hasattr(reasoning_capability, "set_intelligence"):
            reasoning_capability.set_intelligence(self._intelligence)

        planning = capability_registry.get_capability("planning_engine")
        if planning is not None and hasattr(planning, "set_components"):
            if hasattr(execution_engine._planner, "set_plan_manager"):
                execution_engine._planner.set_plan_manager(execution_engine.plan_manager)
            planning.set_components(
                execution_engine._planner,
                execution_engine.plan_manager,
                decision_manager,
            )

        communication = capability_registry.get_capability("communication_hub")
        if communication is not None and hasattr(communication, "set_event_bus"):
            communication.set_event_bus(self.event_bus)

        debugging = capability_registry.get_capability("debugging")
        if debugging is not None and hasattr(debugging, "set_components"):
            debugging.set_components(
                tool_manager,
                execution_engine.verification_runner,
                safety_gate,
            )

        dependency_management = capability_registry.get_capability("dependency_management")
        if dependency_management is not None and hasattr(dependency_management, "set_components"):
            from app.audit.capability_auditor import CapabilityAuditor
            dependency_management.set_components(
                tool_manager,
                execution_engine.verification_runner,
                safety_gate,
                CapabilityAuditor(registry=capability_registry, workspace=str(self.workspace)),
            )

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
        runtime_awareness=None,
        system_anatomy=None,
        diagnostic_engine=None,
        diagnostic_grouper=None,
        predictive_diagnostics=None,
        improvement_measurement=None,
        canary_validator=None,
        promotion_manager=None,
        self_improvement=None,
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
            name="runtime_awareness",
            component_type=ComponentType.SERVICE,
            category="runtime_observation",
            check=lambda: runtime_awareness is None or callable(getattr(runtime_awareness, "get_current_state", None)),
        )
        self._register_readiness_component(
            observability,
            name="system_anatomy",
            component_type=ComponentType.SERVICE,
            category="runtime_observation",
            check=lambda: system_anatomy is None or callable(getattr(system_anatomy, "snapshot", None)),
        )
        self._register_readiness_component(
            observability,
            name="diagnostic_pipeline",
            component_type=ComponentType.SERVICE,
            category="diagnostics",
            check=lambda: diagnostic_engine is None or diagnostic_grouper is not None,
        )
        self._register_readiness_component(
            observability,
            name="predictive_diagnostics",
            component_type=ComponentType.SERVICE,
            category="diagnostics",
            check=lambda: predictive_diagnostics is None or runtime_awareness is not None,
        )
        self._register_readiness_component(
            observability,
            name="improvement_measurement",
            component_type=ComponentType.SERVICE,
            category="self_improvement",
            check=lambda: improvement_measurement is not None and callable(getattr(improvement_measurement, "compare", None)),
        )
        self._register_readiness_component(
            observability,
            name="controlled_canary",
            component_type=ComponentType.SERVICE,
            category="self_improvement",
            check=lambda: canary_validator is not None and callable(getattr(canary_validator, "validate", None)) and callable(getattr(canary_validator, "_executor", None)),
        )
        self._register_readiness_component(
            observability,
            name="promotion_boundary",
            component_type=ComponentType.SERVICE,
            category="self_improvement",
            check=lambda: promotion_manager is not None and callable(getattr(promotion_manager, "promote", None)) and getattr(promotion_manager, "safety_gates", None) is not None,
        )
        self._register_readiness_component(
            observability,
            name="safe_self_improvement",
            component_type=ComponentType.SERVICE,
            category="self_improvement",
            check=lambda: self_improvement is None or getattr(self_improvement, "promotion_manager", None) is promotion_manager,
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
                                check=lambda: autonomy.is_running() or getattr(autonomy, "_state", "") == "OFF",

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

        if system.avatar_bridge:
            system.avatar_bridge.close()
            logger.debug("[SystemInitializer] Avatar UI bridge closed")

        if system.avatar:
            system.avatar.stop()
            logger.debug("[SystemInitializer] AvatarRuntime stopped")

        if system.autonomy:
            system.autonomy.stop()
            logger.debug("[SystemInitializer] AutonomyManager stopped")

        if system.self_improvement:
            system.self_improvement.shutdown()
            logger.debug("[SystemInitializer] SafeSelfImprovementEngine stopped")

        if system.predictive_diagnostics:
            system.predictive_diagnostics.stop()
            logger.debug("[SystemInitializer] PredictiveDiagnostics stopped")

        if system.runtime_awareness:
            system.runtime_awareness.stop()
            set_runtime_awareness(None)
            logger.debug("[SystemInitializer] RuntimeAwareness stopped")

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
