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
from app.core.events import EventBus
from app.core.background_jobs import BackgroundJobService
from app.core.observability import ObservabilityHub, ComponentInfo, ComponentType
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

    Order of initialization per TARGET_ARCHITECTURE.md Section 15:
    1. Infrastructure (EventBus, JobService, Observability, ConfigHotReload, FileWatcher)
    2. LLM Stack (PriorityLLMProvider + ChatActivityProvider)
    3. Memory Coordinator
    4. Tool Manager
    5. Intelligence (G1, G2, G3)
    6. Capability Registry
    7. Safety Gate
    8. Unified Router (with KnowledgeFirstResolver)
    9. Execution Engine
    10. Conversation Control Handler
    11. Agent Facade
    12. Optional: Autonomy Manager
    13. Optional: Workflow Orchestrator
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
        logger.debug("[SystemInitializer] EventBus created")

        job_service = BackgroundJobService(event_bus=event_bus)
        job_service.start()
        logger.debug("[SystemInitializer] BackgroundJobService started")

        observability = ObservabilityHub(event_bus=event_bus)
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
        # 3b. Learning Pipeline (depends on memory_coordinator, event_bus)
        # ------------------------------------------------------------------
        learning_pipeline = create_learning_pipeline(
            memory_coordinator=memory_coordinator,
            event_bus=event_bus,
        )
        logger.debug("[SystemInitializer] LearningPipeline created")

        # ------------------------------------------------------------------
        # 3c. Answer Verifier (V1) with Repair Loop (AR) - depends on learning_pipeline, priority_llm
        # ------------------------------------------------------------------
        answer_verifier = AnswerVerifier(
            learning_pipeline=learning_pipeline,
            priority_llm=priority_llm,
        )
        logger.debug("[SystemInitializer] AnswerVerifier created with AnswerRepairLoop")

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
        # 6. Capability Registry (required for KnowledgeFirstResolver)
        # ------------------------------------------------------------------
        capability_registry = CapabilityRegistry()
        # Register built-in capabilities with the registry
        from app.orchestrator.capabilities import create_all_capabilities
        for cap in create_all_capabilities():
            capability_registry.register(cap)
        capability_registry.start()
        logger.debug("[SystemInitializer] CapabilityRegistry created and started")

        # ------------------------------------------------------------------
        # 7. Safety Gate (required for ExecutionEngine/WorkflowOrchestrator)
        # ------------------------------------------------------------------
        safety_gate = SafetyGate()
        logger.debug("[SystemInitializer] SafetyGate created")

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
            safety_gate=safety_gate,
        )
        logger.debug("[SystemInitializer] ExecutionEngine created")

        # ------------------------------------------------------------------
        # 10. Conversation Control (depends on execution_engine, plan_manager, memory)
        # ------------------------------------------------------------------
        conversation_control = ConversationControlHandler(
            executor=execution_engine,
            plan_manager=execution_engine.plan_manager,
            conversation_memory=memory_coordinator.conversation_memory,
        )
        execution_engine.set_conversation_control(conversation_control)
        logger.debug("[SystemInitializer] ConversationControlHandler created")

        # ------------------------------------------------------------------
        # 11. Agent Facade (composes all above)
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
        # 12. Canonical Workflow Orchestrator
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
            orchestrator.start()
            logger.info("[SystemInitializer] WorkflowOrchestrator started")

        # ------------------------------------------------------------------
        # 13. Canonical Autonomy Manager (depends on the shared learning and orchestration graph)
        # ------------------------------------------------------------------
        autonomy = None
        if self.config.enable_autonomy:
            autonomy = AutonomyManager(
                event_bus=event_bus,
                observability=observability,
                learning_pipeline=learning_pipeline,
                goal_storage=memory_coordinator.goal_storage,
                workflow_orchestrator=orchestrator,
                job_service=job_service,
            )
            autonomy.start()
            logger.info("[SystemInitializer] AutonomyManager started")

        # ------------------------------------------------------------------
        # 14. Diagnostics (Q1) - depends on workspace, event_bus
        # ------------------------------------------------------------------
        diagnostic_engine = None
        if self.config.enable_diagnostics:
            diagnostic_config = DiagnosticConfig()
            diagnostic_engine = DiagnosticEngine(
                workspace=str(self.workspace),
                config=diagnostic_config,
                event_bus=event_bus,
            )
            logger.debug("[SystemInitializer] DiagnosticEngine created")

        # ------------------------------------------------------------------
        # 15. SafeSelfImprovement (Q2) - depends on event_bus, workspace
        # ------------------------------------------------------------------
        self_improvement = None
        if self.config.enable_self_improvement:
            ssi_config = SafeSelfImprovementConfig()
            self_improvement = create_self_improvement_engine(config=ssi_config)
            logger.debug("[SystemInitializer] SafeSelfImprovementEngine created")

        # ------------------------------------------------------------------
        # Finalize
        # ------------------------------------------------------------------
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

    def shutdown(self, system: InitializedSystem) -> None:
        """Gracefully shutdown all subsystems."""
        logger.info("[SystemInitializer] Shutting down system...")

        if system.autonomy:
            system.autonomy.stop()
            logger.debug("[SystemInitializer] AutonomyManager stopped")

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

        system.infra.job_service.shutdown(wait=True, timeout=10.0)
        logger.debug("[SystemInitializer] BackgroundJobService shut down")

        system.infra.event_bus.shutdown()
        logger.debug("[SystemInitializer] EventBus shut down")

        system.priority_llm.shutdown()
        logger.debug("[SystemInitializer] PriorityLLMProvider shut down")

        logger.info("[SystemInitializer] Shutdown complete")