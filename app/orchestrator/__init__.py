"""Central Autonomous Orchestrator for Freya.

This package provides the core orchestration components:
- CapabilityRegistry: Runtime capability management with lifecycle, dependencies, health
- WorkflowComposer: Dynamic workflow composition from capabilities
- TaskExecutor: Long-running task execution with pause/resume/retry/checkpointing
- SafetyGate: Risk analysis, decision integration, human oversight
- SelfObserver: Self-observation via ObservabilityHub
- CentralOrchestrator: Main coordination class integrating all components
- WorkflowOrchestrator: Streamlined workflow orchestration using extracted components
- ActivityReporter: Plain English execution updates for GUI/conversational feedback
- OrchestratorGUIInterface: Stable GUI-compatible interfaces
- FailureRecoveryIntegration: Automatic failure detection and recovery
"""

from app.orchestrator.capability_registry import (
    Capability,
    CapabilityCategory,
    CapabilityMetadata,
    CapabilityRegistry,
    CapabilityState,
    CapabilityHealth,
    CapabilityRegistration,
    get_capability_registry,
    reset_capability_registry,
)

from app.orchestrator.workflow_composer import (
    WorkflowComposer,
    WorkflowSpec,
    WorkflowStrategy,
    ComposedWorkflow,
    WorkflowStatus,
    WorkflowStep,
    CapabilitySelector,
    IntentBasedSelector,
    KeywordBasedSelector,
    DependencyAwareSelector,
)

from app.orchestrator.task_executor import (
    TaskExecutor,
    ExecutionContext,
    ExecutionState,
    Checkpoint,
    ExecutableCapability as TaskExecutableCapability,
)

from app.orchestrator.safety_gate import (
    SafetyGate,
    SafetyPolicy,
    SafetyGateMode,
    SafetyAction,
    SafetyAssessment,
    SafetyViolationError,
    HumanOversightInterface,
    DefaultHumanOversight,
    check_safety,
)

from app.orchestrator.self_observer import (
    SelfObserver,
    ObservationLevel,
    SystemSnapshot,
    AlertRule,
    Alert,
)

from app.orchestrator.capabilities import (
    create_all_capabilities,
    MemoryManagementCapability,
    PlanningEngineCapability,
    CodeExecutionCapability,
    DecisionEngineCapability,
    LearningPipelineCapability,
    SystemMonitoringCapability,
    CommunicationHubCapability,
    ToolRegistryCapability,
    SafetyGuardCapability,
    KnowledgeBaseCapability,
    ReasoningEngineCapability,
    OrchestrationCoreCapability,
    FailureRecoveryCapability,
)

from app.orchestrator.activity_reporter import (
    ActivityReporter,
    ActivityUpdate,
    ActivityLevel,
)

from app.orchestrator.gui_interface import (
    OrchestratorGUIInterface,
    OrchestratorStreamingInterface,
    OrchestratorStatusDTO,
    WorkflowSummaryDTO,
    WorkflowDetailDTO,
    CapabilitySummaryDTO,
    CapabilityDetailDTO,
    ExecutionContextDTO,
    SystemMetricsDTO,
    EventDTO,
    ActivityUpdateDTO,
)

from app.orchestrator.failure_recovery_integration import (
    FailureRecoveryIntegration,
    FailureContext,
    RecoveryAction,
    FailureSeverity,
    create_failure_recovery_integration,
)

from app.orchestrator.workflow_orchestrator import (
    WorkflowOrchestrator,
    WorkflowOrchestratorConfig,
    OrchestratorState as WorkflowOrchestratorState,
    get_workflow_orchestrator,
    reset_workflow_orchestrator,
)

def __getattr__(name):
    """Load the legacy central orchestrator only for explicit compatibility use."""
    if name in {
        "CentralOrchestrator",
        "OrchestratorConfig",
        "OrchestratorState",
        "get_orchestrator",
        "reset_orchestrator",
    }:
        from app.orchestrator import orchestrator as legacy_orchestrator
        return getattr(legacy_orchestrator, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Capability Registry
    "Capability",
    "CapabilityCategory",
    "CapabilityMetadata",
    "CapabilityRegistry",
    "CapabilityState",
    "CapabilityHealth",
    "CapabilityRegistration",
    "get_capability_registry",
    "reset_capability_registry",

    # Workflow Composer
    "WorkflowComposer",
    "WorkflowSpec",
    "WorkflowStrategy",
    "ComposedWorkflow",
    "WorkflowStatus",
    "WorkflowStep",
    "CapabilitySelector",
    "IntentBasedSelector",
    "KeywordBasedSelector",
    "DependencyAwareSelector",

    # Task Executor
    "TaskExecutor",
    "ExecutionContext",
    "ExecutionState",
    "Checkpoint",
    "TaskExecutableCapability",

    # Safety Gate
    "SafetyGate",
    "SafetyPolicy",
    "SafetyGateMode",
    "SafetyAction",
    "SafetyAssessment",
    "SafetyViolationError",
    "HumanOversightInterface",
    "DefaultHumanOversight",
    "check_safety",

    # Self Observer
    "SelfObserver",
    "ObservationLevel",
    "SystemSnapshot",
    "AlertRule",
    "Alert",

    # Main Orchestrator
    "CentralOrchestrator",
    "OrchestratorConfig",
    "OrchestratorState",
    "get_orchestrator",
    "reset_orchestrator",

    # Actual Capability Implementations
    "create_all_capabilities",
    "MemoryManagementCapability",
    "PlanningEngineCapability",
    "CodeExecutionCapability",
    "DecisionEngineCapability",
    "LearningPipelineCapability",
    "SystemMonitoringCapability",
    "CommunicationHubCapability",
    "ToolRegistryCapability",
    "SafetyGuardCapability",
    "KnowledgeBaseCapability",
    "ReasoningEngineCapability",
    "OrchestrationCoreCapability",
    "FailureRecoveryCapability",

    # Activity Reporter
    "ActivityReporter",
    "ActivityUpdate",
    "ActivityLevel",

    # GUI Interface
    "OrchestratorGUIInterface",
    "OrchestratorStreamingInterface",
    "OrchestratorStatusDTO",
    "WorkflowSummaryDTO",
    "WorkflowDetailDTO",
    "CapabilitySummaryDTO",
    "CapabilityDetailDTO",
    "ExecutionContextDTO",
    "SystemMetricsDTO",
    "EventDTO",
    "ActivityUpdateDTO",

    # Failure Recovery Integration
    "FailureRecoveryIntegration",
    "FailureContext",
    "RecoveryAction",
    "FailureSeverity",
    "create_failure_recovery_integration",

    # Workflow Orchestrator
    "WorkflowOrchestrator",
    "WorkflowOrchestratorConfig",
    "WorkflowOrchestratorState",
    "get_workflow_orchestrator",
    "reset_workflow_orchestrator",
]

# Version
__version__ = "1.0.0"
