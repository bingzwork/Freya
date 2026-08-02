"""
Core infrastructure module for Freya.

This package provides the foundational shared infrastructure:
- EventBus: Communication backbone
- BackgroundJobService: Unified background execution
- ObservabilityHub: Centralized monitoring
- Pipeline Framework: Reusable workflow execution
- FileWatcher: File system monitoring
- ConfigHotReload: Configuration hot-reload
"""

from app.core.events import (
    EventBus,
    Event,
    EventPriority,
    Subscription,
    EventHistory,
    get_event_bus,
    set_event_bus,
    events,
)

from app.core.background_jobs import (
    BackgroundJobService,
    Job,
    JobStatus,
    JobType,
    JobResult,
    RetryConfig,
    get_job_service,
    set_job_service,
    schedule_job,
    schedule_recurring_job,
)

from app.core.observability import (
    ObservabilityHub,
    HealthMonitor,
    MetricsCollector,
    SystemMetricsCollector,
    AlertManager,
    HealthStatus,
    ComponentType,
    HealthCheck,
    HealthResult,
    MetricPoint,
    ComponentInfo,
    get_observability_hub,
    set_observability_hub,
)

from app.core.pipeline import (
    Pipeline,
    PipelineStage,
    FunctionStage,
    CompositePipeline,
    PipelineBuilder,
    PipelineConfig,
    PipelineContext,
    StageResult,
    PipelineStatus,
    StageStatus,
    PipelineHook,
    create_pipeline,
    ConditionalStage,
    ParallelStage,
    TransformStage,
)

from app.core.file_watcher import (
    FileWatcher,
    FileEvent,
    FileEventType,
    FileEventBusIntegration,
    FileSystemEventHandler,
    create_file_watcher,
    create_file_event_integration,
)

from app.core.config_hot_reload import (
    ConfigHotReload,
    ConfigValidator,
    ConfigChange,
    ReloadResult,
    create_config_hot_reload,
    setup_config_hot_reload_for_agent,
)

__all__ = [
    # EventBus
    "EventBus",
    "Event",
    "EventPriority",
    "Subscription",
    "EventHistory",
    "get_event_bus",
    "set_event_bus",
    "events",
    # Background Jobs
    "BackgroundJobService",
    "Job",
    "JobStatus",
    "JobType",
    "JobResult",
    "RetryConfig",
    "get_job_service",
    "set_job_service",
    "schedule_job",
    "schedule_recurring_job",
    # Observability
    "ObservabilityHub",
    "HealthMonitor",
    "MetricsCollector",
    "SystemMetricsCollector",
    "AlertManager",
    "HealthStatus",
    "ComponentType",
    "HealthCheck",
    "HealthResult",
    "MetricPoint",
    "ComponentInfo",
    "get_observability_hub",
    "set_observability_hub",
    # Pipeline
    "Pipeline",
    "PipelineStage",
    "FunctionStage",
    "CompositePipeline",
    "PipelineBuilder",
    "PipelineConfig",
    "PipelineContext",
    "StageResult",
    "PipelineStatus",
    "StageStatus",
    "PipelineHook",
    "create_pipeline",
    "ConditionalStage",
    "ParallelStage",
    "TransformStage",
    # File Watcher
    "FileWatcher",
    "FileEvent",
    "FileEventType",
    "FileEventBusIntegration",
    "FileSystemEventHandler",
    "create_file_watcher",
    "create_file_event_integration",
    # Config Hot-Reload
    "ConfigHotReload",
    "ConfigValidator",
    "ConfigChange",
    "ReloadResult",
    "create_config_hot_reload",
    "setup_config_hot_reload_for_agent",
]