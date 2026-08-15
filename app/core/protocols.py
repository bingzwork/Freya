"""
Interface Protocols for Freya Architecture.

Defines the contract boundaries between components to break circular dependencies.
All cross-component dependencies should be through these protocols, not concrete types.
"""

from typing import Protocol, Optional, List, Dict, Any
from pathlib import Path


class ChatActivityProvider(Protocol):
    """
    Protocol for components that need to coordinate with chat activity.
    Used by PriorityLLMProvider, AutonomyManager, BackgroundJobService to yield to conversation.
    """
    def chat_started(self) -> None: ...
    def chat_ended(self) -> None: ...
    def chat_activity(self) -> None: ...
    def is_chat_active(self) -> bool: ...
    def wait_for_chat_idle(self, timeout: float) -> bool: ...
    def register_chat_ended_callback(self, callback) -> None: ...
    def unregister_chat_ended_callback(self, callback) -> None: ...


class ExecutorProvider(Protocol):
    """
    Protocol for AutonomyManager to execute capabilities without FreyaAgent reference.
    """
    def execute_capability(self, name: str, inputs: Dict[str, Any]) -> Any: ...
    def get_available_capabilities(self) -> List[str]: ...
    def is_chat_active(self) -> bool: ...


class ExecutionEngineProtocol(Protocol):
    """
    Protocol for Orchestrator to execute workflows/plans.
    """
    def execute_plan(self, task: str, allow_mutations: bool) -> str: ...
    def execute_workflow(self, workflow: Any) -> str: ...
    @property
    def is_executing(self) -> bool: ...
    @property
    def is_paused(self) -> bool: ...
    @property
    def active_plan_id(self) -> Optional[str]: ...
    @property
    def current_task_title(self) -> Optional[str]: ...
    @property
    def completed_tasks(self) -> List[str]: ...
    @property
    def plan_tasks(self) -> List[Any]: ...
    def shutdown(self) -> None: ...


class MemoryProvider(Protocol):
    """
    Protocol for read-only memory access.
    """
    def retrieve_for_planning(self, query: str) -> str: ...
    def retrieve_for_execution(self, query: str) -> str: ...
    def retrieve(self, query: Any) -> List[Any]: ...
    def get_active_goal(self) -> Optional[Any]: ...
    def get_working_memory_snapshot(self) -> Dict[str, Any]: ...
    @property
    def conversation_memory(self) -> Any: ...
    @property
    def working_memory(self) -> Any: ...
    @property
    def goal_storage(self) -> Any: ...


class ToolProvider(Protocol):
    """
    Protocol for tool execution.
    """
    def execute(self, tool_name: str, args: Dict[str, Any]) -> Any: ...
    def list_available(self, allow_mutations: bool) -> List[str]: ...


class RouterProtocol(Protocol):
    """
    Protocol for intent/control/capability routing.
    """
    def route(self, user_input: str, context: Optional[Dict[str, Any]] = None) -> Any: ...
    def execute_capability(self, capability_name: str, query: str, **context) -> Any: ...


class IntelligenceBundle:
    """Bundle of intelligence components for code understanding."""
    def __init__(
        self,
        project_index: Any = None,
        symbol_index: Any = None,
        file_locator: Any = None,
        lexical_search: Any = None,
        dependency_graph: Any = None,
        context_builder: Any = None,
        retriever: Any = None,
    ):
        self.project_index = project_index
        self.symbol_index = symbol_index
        self.file_locator = file_locator
        self.lexical_search = lexical_search
        self.dependency_graph = dependency_graph
        self.context_builder = context_builder
        self.retriever = retriever


class SystemConfig:
    """Configuration for SystemInitializer."""
    def __init__(
        self,
        enable_autonomy: bool = True,
        enable_orchestrator: bool = True,
        enable_diagnostics: bool = True,
        enable_self_improvement: bool = True,
        enable_file_watcher: bool = True,
        enable_config_hot_reload: bool = True,
        enable_observability: bool = True,
        shutdown_timeout_seconds: float = 10.0,
        workspace: Optional[Path] = None,
        autonomy_config: Optional[Any] = None,
    ):
        self.enable_autonomy = enable_autonomy
        self.enable_orchestrator = enable_orchestrator
        self.enable_diagnostics = enable_diagnostics
        self.enable_self_improvement = enable_self_improvement
        self.enable_file_watcher = enable_file_watcher
        self.enable_config_hot_reload = enable_config_hot_reload
        self.enable_observability = enable_observability
        self.shutdown_timeout_seconds = max(0.1, float(shutdown_timeout_seconds))
        self.workspace = workspace
        self.autonomy_config = autonomy_config


class InfrastructureBundle:
    """Bundle of infrastructure components."""
    def __init__(
        self,
        event_bus: Any,
        job_service: Any,
        observability: Any,
        config_hot_reload: Optional[Any] = None,
        file_watcher: Optional[Any] = None,
    ):
        self.event_bus = event_bus
        self.job_service = job_service
        self.observability = observability
        self.config_hot_reload = config_hot_reload
        self.file_watcher = file_watcher


class InitializedSystem:
    """Container for all initialized system components."""
    def __init__(
        self,
        facade: Any,
        chat_activity: Any,
        priority_llm: Any,
        memory: Any,
        execution: Any,
        control: Any,
        autonomy: Optional[Any] = None,
        orchestrator: Optional[Any] = None,
        infra: Optional[InfrastructureBundle] = None,
        intelligence: Optional[IntelligenceBundle] = None,
        learning_pipeline: Optional[Any] = None,
        diagnostics: Optional[Any] = None,
        self_improvement: Optional[Any] = None,
    ):
        self.facade = facade
        self.chat_activity = chat_activity
        self.priority_llm = priority_llm
        self.memory = memory
        self.execution = execution
        self.control = control
        self.autonomy = autonomy
        self.orchestrator = orchestrator
        self.infra = infra
        self.intelligence = intelligence
        self.learning_pipeline = learning_pipeline
        self.diagnostics = diagnostics
        self.self_improvement = self_improvement
