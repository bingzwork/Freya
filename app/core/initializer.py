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

# LLM + Priority (depends on infra)
from app.core.llm import LLM
from app.core.priority_llm import PriorityLLMProvider

# Chat Activity Provider (depends on priority_llm)
from app.core.chat_activity import FreyaChatActivityProvider

# Memory Coordinator (depends on workspace)
from app.memory.coordinator import MemoryCoordinator, create_memory_coordinator

# Tool Manager (depends on workspace)
from app.core.tool_manager import ToolManager

# Unified Router (depends on memory, tools, priority_llm)
from app.routing.unified_router import UnifiedRouter

# Execution Engine (depends on router, tools, memory, priority_llm)
from app.execution.engine import ExecutionEngine

# Conversation Control (depends on execution_engine for callbacks)
from app.conversational_control import ConversationControlHandler

# Agent Facade (composes all above)
from app.agent.facade_impl import AgentFacadeImpl

# Optional: Autonomy
from app.long_term_autonomy.manager import AutonomyManager

# Optional: Orchestrator
from app.orchestrator.workflow_orchestrator import WorkflowOrchestrator
from app.orchestrator.capability_registry import CapabilityRegistry
from app.orchestrator.safety_gate import SafetyGate

# Intelligence components (depend on workspace, built lazily)
from app.core.project_index import ProjectIndex
from app.core.symbol_index import SymbolIndex
from app.intelligence.file_locator import FileLocator
from app.intelligence.lexical_search import LexicalSearch
from app.intelligence.dependency_graph import DependencyGraph
from app.intelligence.context_builder import ContextBuilder
from app.retrieval.enhanced_retriever import EnhancedRetriever

from app.core.logger import logger


class SystemInitializer:
    """
    Single-pass construction of all Freya subsystems.

    Order of initialization:
    1. Infrastructure (EventBus, JobService, Observability, ConfigHotReload, FileWatcher)
    2. LLM + Priority (base LLM, PriorityLLMProvider)
    3. Chat Activity Provider (FreyaChatActivityProvider)
    4. Memory Coordinator
    5. Tool Manager
    6. Unified Router
    7. Execution Engine
    8. Conversation Control Handler
    9. Agent Facade
    10. Optional: Autonomy Manager
    11. Optional: Workflow Orchestrator
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
        # 2. LLM + Priority (depends on infra)
        # ------------------------------------------------------------------
        base_llm = LLM()
        priority_llm = PriorityLLMProvider(base_llm)
        # Replace global priority LLM so existing code works
        from app.core.priority_llm import set_priority_llm
        set_priority_llm(priority_llm)
        logger.debug("[SystemInitializer] PriorityLLMProvider created")

        # ------------------------------------------------------------------
        # 3. Chat Activity Provider (depends on priority_llm)
        # ------------------------------------------------------------------
        chat_activity = FreyaChatActivityProvider(priority_llm)
        # Set chat activity provider on job service for chat-aware yielding
        job_service.set_chat_activity_provider(chat_activity)
        logger.debug("[SystemInitializer] ChatActivityProvider created and linked")

        # ------------------------------------------------------------------
        # 4. Memory Coordinator (depends on workspace, event_bus)
        # ------------------------------------------------------------------
        memory_coordinator = create_memory_coordinator(self.workspace, event_bus)
        logger.debug("[SystemInitializer] MemoryCoordinator created")

        # ------------------------------------------------------------------
        # 5. Tool Manager (depends on workspace)
        # ------------------------------------------------------------------
        tool_manager = ToolManager(str(self.workspace))
        logger.debug("[SystemInitializer] ToolManager created")

        # ------------------------------------------------------------------
        # 6. Intelligence Components (depend on workspace)
        # ------------------------------------------------------------------
        project_index = ProjectIndex(str(self.workspace))
        project_index.build()
        logger.debug("[SystemInitializer] ProjectIndex built")

        symbol_index = SymbolIndex(str(self.workspace))
        symbol_index.build()
        logger.debug("[SystemInitializer] SymbolIndex built")

        file_locator = FileLocator(symbol_index)
        logger.debug("[SystemInitializer] FileLocator created")

        lexical_search = LexicalSearch(symbol_index)
        logger.debug("[SystemInitializer] LexicalSearch created")

        dependency_graph = DependencyGraph(symbol_index)
        dependency_graph.build()
        logger.debug("[SystemInitializer] DependencyGraph built")

        context_builder = ContextBuilder(symbol_index, dependency_graph)
        logger.debug("[SystemInitializer] ContextBuilder created")

        try:
            retriever = EnhancedRetriever(symbol_index, enable_semantic=False)
        except Exception:
            from app.rag import SimpleRetriever
            retriever = SimpleRetriever(symbol_index)
        logger.debug("[SystemInitializer] Retriever created")

        intelligence = IntelligenceBundle(
            project_index=project_index,
            symbol_index=symbol_index,
            file_locator=file_locator,
            lexical_search=lexical_search,
            dependency_graph=dependency_graph,
            context_builder=context_builder,
            retriever=retriever,
        )

        # ------------------------------------------------------------------
        # 7. Unified Router (depends on memory, tools, priority_llm, chat_activity)
        # ------------------------------------------------------------------
        unified_router = UnifiedRouter(
            memory=memory_coordinator,
            tools=tool_manager,
            llm=priority_llm,
            chat_activity=chat_activity,
        )
        logger.debug("[SystemInitializer] UnifiedRouter created")

        # ------------------------------------------------------------------
        # 8. Execution Engine (depends on router, tools, memory, priority_llm, chat_activity)
        # ------------------------------------------------------------------
        execution_engine = ExecutionEngine(
            router=unified_router,
            tools=tool_manager,
            memory=memory_coordinator,
            llm=priority_llm,
            chat_activity=chat_activity,
        )
        logger.debug("[SystemInitializer] ExecutionEngine created")

        # ------------------------------------------------------------------
        # 9. Conversation Control (depends on execution_engine, plan_manager, memory)
        # ------------------------------------------------------------------
        conversation_control = ConversationControlHandler(
            executor=execution_engine,
            plan_manager=execution_engine.plan_manager,
            conversation_memory=memory_coordinator.conversation_memory,
        )
        execution_engine.set_conversation_control(conversation_control)
        logger.debug("[SystemInitializer] ConversationControlHandler created")

        # ------------------------------------------------------------------
        # 10. Agent Facade (composes all above)
        # ------------------------------------------------------------------
        facade = AgentFacadeImpl(
            router=unified_router,
            execution=execution_engine,
            control=conversation_control,
            chat_activity=chat_activity,
            priority_llm=priority_llm,
            memory=memory_coordinator,
        )
        logger.debug("[SystemInitializer] AgentFacadeImpl created")

        # ------------------------------------------------------------------
        # 11. Optional: Autonomy (depends on execution_engine, router, memory, chat_activity, priority_llm, event_bus, job_service)
        # ------------------------------------------------------------------
        autonomy = None
        if self.config.enable_autonomy:
            autonomy = AutonomyManager(
                workspace=str(self.workspace),
                event_bus=event_bus,
                job_service=job_service,
                observability=observability,
            )
            # Set dependencies that AutonomyManager expects
            autonomy.executor = execution_engine  # Implements ExecutorProvider protocol
            autonomy._chat_activity_provider = chat_activity
            # Register background jobs
            autonomy._register_background_jobs()
            autonomy.start()
            logger.info("[SystemInitializer] AutonomyManager started")

        # ------------------------------------------------------------------
        # 12. Optional: Orchestrator (depends on capability_registry, router, executor, safety_gate, chat_activity, event_bus, job_service)
        # ------------------------------------------------------------------
        orchestrator = None
        if self.config.enable_orchestrator:
            capability_registry = CapabilityRegistry()
            safety_gate = SafetyGate()

            orchestrator = WorkflowOrchestrator(
                capability_registry=capability_registry,
                router=unified_router,  # Shared instance
                executor=execution_engine,  # Protocol
                safety_gate=safety_gate,
                chat_activity=chat_activity,
                event_bus=event_bus,
                job_service=job_service,
            )
            orchestrator.start()
            logger.info("[SystemInitializer] WorkflowOrchestrator started")

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
                    "priority_llm",
                    "chat_activity",
                    "memory_coordinator",
                    "tool_manager",
                    "unified_router",
                    "execution_engine",
                    "conversation_control",
                    "agent_facade",
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
