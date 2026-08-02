"""
Pipeline Framework - Reusable workflow execution framework for Freya.

Standardizes pipeline execution patterns across:
- app/evaluation/pipeline.py (EvaluationPipeline)
- app/knowledge_retrieval/pipeline.py (KnowledgeRetrievalPipeline)
- app/autonomous_learning/pipeline.py (AutonomousLearningPipeline)
- app/knowledge_extraction/pipeline.py (KnowledgeExtractionPipeline)

Provides:
- Pipeline execution with ordered stages
- Context passing between stages
- Error handling and recovery
- Hooks for observability
- Stage registration and composition
- Extensible pipeline base class
- Shared execution interfaces
"""

import asyncio
import threading
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, TypeVar, Generic, Union
from uuid import uuid4

from app.core.logger import logger
from app.core.events import EventBus, get_event_bus, Event, EventPriority
from app.core.observability import get_observability_hub


class StageStatus(Enum):
    """Status of a pipeline stage."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"


class PipelineStatus(Enum):
    """Status of a pipeline execution."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PARTIAL = "partial"  # Some stages completed, some failed


@dataclass
class StageResult:
    """Result of a stage execution."""
    stage_name: str
    status: StageStatus
    output: Any = None
    error: Optional[str] = None
    duration_seconds: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)
    retry_count: int = 0


@dataclass
class PipelineContext:
    """Context passed between pipeline stages."""
    data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    stage_results: Dict[str, StageResult] = field(default_factory=dict)
    errors: List[Dict[str, Any]] = field(default_factory=list)

    def get(self, key: str, default: Any = None) -> Any:
        """Get value from context."""
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set value in context."""
        self.data[key] = value

    def update(self, values: Dict[str, Any]) -> None:
        """Update multiple values."""
        self.data.update(values)

    def has(self, key: str) -> bool:
        """Check if key exists."""
        return key in self.data

    def get_stage_output(self, stage_name: str) -> Any:
        """Get output from a previous stage."""
        result = self.stage_results.get(stage_name)
        return result.output if result else None

    def get_stage_result(self, stage_name: str) -> Optional[StageResult]:
        """Get full result from a previous stage."""
        return self.stage_results.get(stage_name)

    def to_dict(self) -> Dict[str, Any]:
        """Convert context to dictionary."""
        return {
            "data": self.data,
            "metadata": self.metadata,
            "stage_results": {
                k: {
                    "stage_name": v.stage_name,
                    "status": v.status.value,
                    "output": v.output,
                    "error": v.error,
                    "duration_seconds": v.duration_seconds,
                    "timestamp": v.timestamp,
                    "retry_count": v.retry_count,
                }
                for k, v in self.stage_results.items()
            },
            "errors": self.errors,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PipelineContext":
        """Create context from dictionary."""
        context = cls(
            data=data.get("data", {}),
            metadata=data.get("metadata", {}),
        )
        for k, v in data.get("stage_results", {}).items():
            context.stage_results[k] = StageResult(
                stage_name=v["stage_name"],
                status=StageStatus(v["status"]),
                output=v.get("output"),
                error=v.get("error"),
                duration_seconds=v.get("duration_seconds", 0),
                timestamp=v.get("timestamp", ""),
                retry_count=v.get("retry_count", 0),
            )
        context.errors = data.get("errors", [])
        return context


@dataclass
class PipelineConfig:
    """Pipeline execution configuration."""
    continue_on_failure: bool = False
    max_retries: int = 0
    retry_delay_seconds: float = 1.0
    timeout_seconds: Optional[float] = None
    enable_hooks: bool = True
    emit_events: bool = True
    track_metrics: bool = True


class PipelineHook:
    """Hook points for pipeline execution."""

    def __init__(self):
        self._hooks: Dict[str, List[Callable]] = defaultdict(list)

    def register(self, hook_point: str, callback: Callable) -> None:
        """Register a hook callback."""
        self._hooks[hook_point].append(callback)

    def unregister(self, hook_point: str, callback: Callable) -> bool:
        """Unregister a hook callback."""
        if hook_point in self._hooks and callback in self._hooks[hook_point]:
            self._hooks[hook_point].remove(callback)
            return True
        return False

    def trigger(self, hook_point: str, *args, **kwargs) -> List[Any]:
        """Trigger all callbacks for a hook point."""
        results = []
        for callback in self._hooks.get(hook_point, []):
            try:
                result = callback(*args, **kwargs)
                results.append(result)
            except Exception as e:
                logger.error(f"Hook error at {hook_point}: {e}")
        return results

    # Standard hook points
    PIPELINE_START = "pipeline.start"
    PIPELINE_END = "pipeline.end"
    STAGE_START = "stage.start"
    STAGE_END = "stage.end"
    STAGE_ERROR = "stage.error"
    STAGE_RETRY = "stage.retry"


class PipelineStage(ABC):
    """Base class for pipeline stages."""

    def __init__(
        self,
        name: str,
        config: Optional[PipelineConfig] = None,
    ):
        self.name = name
        self.config = config or PipelineConfig()
        self._hooks = PipelineHook()
        self.status = StageStatus.PENDING

    @abstractmethod
    def execute(self, context: PipelineContext) -> Any:
        """Execute the stage with the given context.

        Args:
            context: Pipeline context with data from previous stages

        Returns:
            Stage output (stored in context for next stages)
        """
        pass

    async def execute_async(self, context: PipelineContext) -> Any:
        """Execute the stage asynchronously."""
        # Default: run sync version in executor
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.execute, context)

    def can_skip(self, context: PipelineContext) -> bool:
        """Check if stage can be skipped."""
        return False

    def on_success(self, context: PipelineContext, output: Any) -> None:
        """Called after successful execution."""
        pass

    def on_failure(self, context: PipelineContext, error: Exception) -> None:
        """Called after failed execution."""
        pass

    def validate_input(self, context: PipelineContext) -> bool:
        """Validate input context before execution."""
        return True

    def validate_output(self, context: PipelineContext, output: Any) -> bool:
        """Validate output after execution."""
        return True


class FunctionStage(PipelineStage):
    """Pipeline stage that wraps a function."""

    def __init__(
        self,
        name: str,
        func: Callable[[PipelineContext], Any],
        config: Optional[PipelineConfig] = None,
        can_skip_func: Optional[Callable[[PipelineContext], bool]] = None,
        validate_input_func: Optional[Callable[[PipelineContext], bool]] = None,
        validate_output_func: Optional[Callable[[PipelineContext, Any], bool]] = None,
    ):
        super().__init__(name, config)
        self._func = func
        self._can_skip_func = can_skip_func
        self._validate_input_func = validate_input_func
        self._validate_output_func = validate_output_func

    def execute(self, context: PipelineContext) -> Any:
        return self._func(context)

    def can_skip(self, context: PipelineContext) -> bool:
        if self._can_skip_func:
            return self._can_skip_func(context)
        return False

    def validate_input(self, context: PipelineContext) -> bool:
        if self._validate_input_func:
            return self._validate_input_func(context)
        return True

    def validate_output(self, context: PipelineContext, output: Any) -> bool:
        if self._validate_output_func:
            return self._validate_output_func(context, output)
        return True


class Pipeline:
    """
    Base pipeline class for executing ordered stages.

    Features:
    - Sequential stage execution
    - Context passing between stages
    - Error handling with retry support
    - Hooks for extensibility
    - Event emission for observability
    - Metrics tracking
    - Cancellation support
    """

    def __init__(
        self,
        name: str,
        config: Optional[PipelineConfig] = None,
        event_bus: Optional[EventBus] = None,
        observability: Optional[Any] = None,
    ):
        """
        Initialize the pipeline.

        Args:
            name: Pipeline name
            config: Execution configuration
            event_bus: Event bus for emitting events
            observability: Observability hub for metrics
        """
        self.name = name
        self.config = config or PipelineConfig()
        self._event_bus = event_bus or get_event_bus()
        self._observability = observability or get_observability_hub()
        self._hooks = PipelineHook()
        self._stages: List[PipelineStage] = []
        self._stage_map: Dict[str, PipelineStage] = {}
        self._lock = threading.RLock()

        # Execution state
        self._running = False
        self._cancelled = False
        self._context: Optional[PipelineContext] = None
        self._results: List[StageResult] = []

    def add_stage(self, stage: PipelineStage) -> "Pipeline":
        """Add a stage to the pipeline."""
        with self._lock:
            if stage.name in self._stage_map:
                raise ValueError(f"Stage '{stage.name}' already exists")
            self._stages.append(stage)
            self._stage_map[stage.name] = stage
        return self

    def add_function_stage(
        self,
        name: str,
        func: Callable[[PipelineContext], Any],
        **stage_kwargs,
    ) -> "Pipeline":
        """Add a function-based stage."""
        stage = FunctionStage(name, func, **stage_kwargs)
        return self.add_stage(stage)

    def insert_stage(self, index: int, stage: PipelineStage) -> "Pipeline":
        """Insert a stage at a specific position."""
        with self._lock:
            if stage.name in self._stage_map:
                raise ValueError(f"Stage '{stage.name}' already exists")
            self._stages.insert(index, stage)
            self._stage_map[stage.name] = stage
        return self

    def remove_stage(self, name: str) -> bool:
        """Remove a stage by name."""
        with self._lock:
            stage = self._stage_map.pop(name, None)
            if stage:
                self._stages = [s for s in self._stages if s.name != name]
                return True
        return False

    def get_stage(self, name: str) -> Optional[PipelineStage]:
        """Get a stage by name."""
        with self._lock:
            return self._stage_map.get(name)

    def list_stages(self) -> List[str]:
        """List stage names in order."""
        with self._lock:
            return [s.name for s in self._stages]

    def register_hook(self, hook_point: str, callback: Callable) -> None:
        """Register a pipeline hook."""
        self._hooks.register(hook_point, callback)

    def unregister_hook(self, hook_point: str, callback: Callable) -> bool:
        """Unregister a pipeline hook."""
        return self._hooks.unregister(hook_point, callback)

    def execute(
        self,
        initial_context: Optional[PipelineContext] = None,
        **initial_data,
    ) -> PipelineContext:
        """
        Execute the pipeline synchronously.

        Args:
            initial_context: Optional initial context
            **initial_data: Initial data to populate context

        Returns:
            Final pipeline context with all stage results
        """
        if self._running:
            raise RuntimeError(f"Pipeline '{self.name}' is already running")

        self._running = True
        self._cancelled = False

        # Initialize context
        self._context = initial_context or PipelineContext()
        if initial_data:
            self._context.update(initial_data)

        self._results = []
        start_time = time.time()

        try:
            # Pipeline start hook
            if self.config.enable_hooks:
                self._hooks.trigger(PipelineHook.PIPELINE_START, self._context)

            if self.config.emit_events:
                self._event_bus.emit(
                    "pipeline.started",
                    data={"pipeline": self.name, "stages": len(self._stages)},
                    source=self.name,
                )

            # Execute stages
            for stage in self._stages:
                if self._cancelled:
                    break

                stage_result = self._execute_stage(stage)
                self._results.append(stage_result)
                self._context.stage_results[stage.name] = stage_result

                # Handle stage failure
                if stage_result.status == StageStatus.FAILED:
                    if not self.config.continue_on_failure:
                        break

            # Determine overall status
            statuses = [r.status for r in self._results]
            if all(s == StageStatus.COMPLETED for s in statuses):
                overall_status = PipelineStatus.COMPLETED
            elif any(s == StageStatus.FAILED for s in statuses):
                overall_status = PipelineStatus.FAILED if not self.config.continue_on_failure else PipelineStatus.PARTIAL
            elif any(s == StageStatus.SKIPPED for s in statuses):
                overall_status = PipelineStatus.PARTIAL
            else:
                overall_status = PipelineStatus.PARTIAL

            # Pipeline end hook
            if self.config.enable_hooks:
                self._hooks.trigger(PipelineHook.PIPELINE_END, self._context, overall_status)

            # Emit completion event
            if self.config.emit_events:
                duration = time.time() - start_time
                self._event_bus.emit(
                    "pipeline.completed",
                    data={
                        "pipeline": self.name,
                        "status": overall_status.value,
                        "duration_seconds": duration,
                        "stages_completed": sum(1 for r in self._results if r.status == StageStatus.COMPLETED),
                        "stages_failed": sum(1 for r in self._results if r.status == StageStatus.FAILED),
                        "stages_skipped": sum(1 for r in self._results if r.status == StageStatus.SKIPPED),
                    },
                    source=self.name,
                )

            # Record metrics
            if self.config.track_metrics:
                self._record_metrics(overall_status, time.time() - start_time)

            self._context.metadata["pipeline_status"] = overall_status.value
            self._context.metadata["total_duration"] = time.time() - start_time

            return self._context

        except Exception as e:
            logger.error(f"Pipeline '{self.name}' failed with exception: {e}")
            if self.config.emit_events:
                self._event_bus.emit(
                    "pipeline.failed",
                    data={"pipeline": self.name, "error": str(e)},
                    source=self.name,
                    priority=EventPriority.HIGH,
                )
            raise
        finally:
            self._running = False

    async def execute_async(
        self,
        initial_context: Optional[PipelineContext] = None,
        **initial_data,
    ) -> PipelineContext:
        """
        Execute the pipeline asynchronously.

        Args:
            initial_context: Optional initial context
            **initial_data: Initial data to populate context

        Returns:
            Final pipeline context with all stage results
        """
        if self._running:
            raise RuntimeError(f"Pipeline '{self.name}' is already running")

        self._running = True
        self._cancelled = False

        # Initialize context
        self._context = initial_context or PipelineContext()
        if initial_data:
            self._context.update(initial_data)

        self._results = []
        start_time = time.time()

        try:
            if self.config.enable_hooks:
                self._hooks.trigger(PipelineHook.PIPELINE_START, self._context)

            if self.config.emit_events:
                self._event_bus.emit(
                    "pipeline.started",
                    data={"pipeline": self.name, "stages": len(self._stages)},
                    source=self.name,
                )

            # Execute stages
            for stage in self._stages:
                if self._cancelled:
                    break

                stage_result = await self._execute_stage_async(stage)
                self._results.append(stage_result)
                self._context.stage_results[stage.name] = stage_result

                if stage_result.status == StageStatus.FAILED:
                    if not self.config.continue_on_failure:
                        break

            statuses = [r.status for r in self._results]
            if all(s == StageStatus.COMPLETED for s in statuses):
                overall_status = PipelineStatus.COMPLETED
            elif any(s == StageStatus.FAILED for s in statuses):
                overall_status = PipelineStatus.FAILED if not self.config.continue_on_failure else PipelineStatus.PARTIAL
            else:
                overall_status = PipelineStatus.PARTIAL

            if self.config.enable_hooks:
                self._hooks.trigger(PipelineHook.PIPELINE_END, self._context, overall_status)

            if self.config.emit_events:
                duration = time.time() - start_time
                self._event_bus.emit(
                    "pipeline.completed",
                    data={
                        "pipeline": self.name,
                        "status": overall_status.value,
                        "duration_seconds": duration,
                        "stages_completed": sum(1 for r in self._results if r.status == StageStatus.COMPLETED),
                        "stages_failed": sum(1 for r in self._results if r.status == StageStatus.FAILED),
                        "stages_skipped": sum(1 for r in self._results if r.status == StageStatus.SKIPPED),
                    },
                    source=self.name,
                )

            if self.config.track_metrics:
                self._record_metrics(overall_status, time.time() - start_time)

            self._context.metadata["pipeline_status"] = overall_status.value
            self._context.metadata["total_duration"] = time.time() - start_time

            return self._context

        except Exception as e:
            logger.error(f"Pipeline '{self.name}' failed with exception: {e}")
            if self.config.emit_events:
                self._event_bus.emit(
                    "pipeline.failed",
                    data={"pipeline": self.name, "error": str(e)},
                    source=self.name,
                    priority=EventPriority.HIGH,
                )
            raise
        finally:
            self._running = False

    def _execute_stage(self, stage: PipelineStage) -> StageResult:
        """Execute a single stage synchronously."""
        stage_start = time.time()

        # Check if stage can be skipped
        if stage.can_skip(self._context):
            logger.debug(f"Skipping stage '{stage.name}'")
            return StageResult(
                stage_name=stage.name,
                status=StageStatus.SKIPPED,
                output=None,
                duration_seconds=time.time() - stage_start,
            )

        # Validate input
        if not stage.validate_input(self._context):
            return StageResult(
                stage_name=stage.name,
                status=StageStatus.FAILED,
                error="Input validation failed",
                duration_seconds=time.time() - stage_start,
            )

        # Stage start hook
        if self.config.enable_hooks:
            self._hooks.trigger(PipelineHook.STAGE_START, stage.name, self._context)

        if self.config.emit_events:
            self._event_bus.emit(
                "stage.started",
                data={"pipeline": self.name, "stage": stage.name},
                source=self.name,
            )

        # Execute with retries
        last_error = None
        for attempt in range(self.config.max_retries + 1):
            try:
                stage.status = StageStatus.RUNNING
                output = stage.execute(self._context)

                # Validate output
                if not stage.validate_output(self._context, output):
                    raise ValueError("Output validation failed")

                duration = time.time() - stage_start

                # Success
                stage.status = StageStatus.COMPLETED
                result = StageResult(
                    stage_name=stage.name,
                    status=StageStatus.COMPLETED,
                    output=output,
                    duration_seconds=duration,
                    retry_count=attempt,
                )

                # Calling success hook
                stage.on_success(self._context, output)

                if self.config.enable_hooks:
                    self._hooks.trigger(PipelineHook.STAGE_END, stage.name, self._context, result)

                if self.config.emit_events:
                    self._event_bus.emit(
                        "stage.completed",
                        data={
                            "pipeline": self.name,
                            "stage": stage.name,
                            "duration_seconds": duration,
                            "retry_count": attempt,
                        },
                        source=self.name,
                    )

                return result

            except Exception as e:
                last_error = e
                logger.warning(f"Stage '{stage.name}' attempt {attempt + 1} failed: {e}")

                # Stage error hook
                stage.on_failure(self._context, e)

                if self.config.enable_hooks:
                    self._hooks.trigger(PipelineHook.STAGE_ERROR, stage.name, self._context, e)

                # Retry logic
                if attempt < self.config.max_retries:
                    stage.status = StageStatus.RETRYING
                    if self.config.enable_hooks:
                        self._hooks.trigger(PipelineHook.STAGE_RETRY, stage.name, attempt + 1, e)

                    if self.config.emit_events:
                        self._event_bus.emit(
                            "stage.retrying",
                            data={
                                "pipeline": self.name,
                                "stage": stage.name,
                                "attempt": attempt + 1,
                                "error": str(e),
                            },
                            source=self.name,
                        )

                    time.sleep(self.config.retry_delay_seconds)
                else:
                    break

        # All retries exhausted
        duration = time.time() - stage_start
        stage.status = StageStatus.FAILED

        result = StageResult(
            stage_name=stage.name,
            status=StageStatus.FAILED,
            error=str(last_error),
            duration_seconds=duration,
            retry_count=self.config.max_retries,
        )

        self._context.errors.append({
            "stage": stage.name,
            "error": str(last_error),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        if self.config.emit_events:
            self._event_bus.emit(
                "stage.failed",
                data={
                    "pipeline": self.name,
                    "stage": stage.name,
                    "error": str(last_error),
                    "duration_seconds": duration,
                },
                source=self.name,
                priority=EventPriority.HIGH,
            )

        return result

    async def _execute_stage_async(self, stage: PipelineStage) -> StageResult:
        """Execute a single stage asynchronously."""
        stage_start = time.time()

        if stage.can_skip(self._context):
            logger.debug(f"Skipping stage '{stage.name}'")
            return StageResult(
                stage_name=stage.name,
                status=StageStatus.SKIPPED,
                output=None,
                duration_seconds=time.time() - stage_start,
            )

        if not stage.validate_input(self._context):
            return StageResult(
                stage_name=stage.name,
                status=StageStatus.FAILED,
                error="Input validation failed",
                duration_seconds=time.time() - stage_start,
            )

        if self.config.enable_hooks:
            self._hooks.trigger(PipelineHook.STAGE_START, stage.name, self._context)

        if self.config.emit_events:
            self._event_bus.emit(
                "stage.started",
                data={"pipeline": self.name, "stage": stage.name},
                source=self.name,
            )

        last_error = None
        for attempt in range(self.config.max_retries + 1):
            try:
                stage.status = StageStatus.RUNNING
                output = await stage.execute_async(self._context)

                if not stage.validate_output(self._context, output):
                    raise ValueError("Output validation failed")

                duration = time.time() - stage_start
                stage.status = StageStatus.COMPLETED

                result = StageResult(
                    stage_name=stage.name,
                    status=StageStatus.COMPLETED,
                    output=output,
                    duration_seconds=duration,
                    retry_count=attempt,
                )

                stage.on_success(self._context, output)

                if self.config.enable_hooks:
                    self._hooks.trigger(PipelineHook.STAGE_END, stage.name, self._context, result)

                if self.config.emit_events:
                    self._event_bus.emit(
                        "stage.completed",
                        data={"pipeline": self.name, "stage": stage.name, "duration_seconds": duration, "retry_count": attempt},
                        source=self.name,
                    )

                return result

            except Exception as e:
                last_error = e
                logger.warning(f"Stage '{stage.name}' attempt {attempt + 1} failed: {e}")

                stage.on_failure(self._context, e)

                if self.config.enable_hooks:
                    self._hooks.trigger(PipelineHook.STAGE_ERROR, stage.name, self._context, e)

                if attempt < self.config.max_retries:
                    stage.status = StageStatus.RETRYING
                    if self.config.enable_hooks:
                        self._hooks.trigger(PipelineHook.STAGE_RETRY, stage.name, attempt + 1, e)

                    if self.config.emit_events:
                        self._event_bus.emit(
                            "stage.retrying",
                            data={"pipeline": self.name, "stage": stage.name, "attempt": attempt + 1, "error": str(e)},
                            source=self.name,
                        )

                    await asyncio.sleep(self.config.retry_delay_seconds)

        duration = time.time() - stage_start
        stage.status = StageStatus.FAILED

        result = StageResult(
            stage_name=stage.name,
            status=StageStatus.FAILED,
            error=str(last_error),
            duration_seconds=duration,
            retry_count=self.config.max_retries,
        )

        self._context.errors.append({
            "stage": stage.name,
            "error": str(last_error),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        if self.config.emit_events:
            self._event_bus.emit(
                "stage.failed",
                data={"pipeline": self.name, "stage": stage.name, "error": str(last_error), "duration_seconds": duration},
                source=self.name,
                priority=EventPriority.HIGH,
            )

        return result

    def _record_metrics(self, status: PipelineStatus, duration: float) -> None:
        """Record pipeline execution metrics."""
        try:
            self._observability.record_metric(
                f"pipeline.{self.name}.duration_seconds",
                duration,
                unit="s",
            )
            self._observability.record_metric(
                f"pipeline.{self.name}.status",
                1 if status == PipelineStatus.COMPLETED else 0,
                labels={"status": status.value},
            )
            self._observability.record_metric(
                f"pipeline.{self.name}.stages_completed",
                sum(1 for r in self._results if r.status == StageStatus.COMPLETED),
            )
            self._observability.record_metric(
                f"pipeline.{self.name}.stages_failed",
                sum(1 for r in self._results if r.status == StageStatus.FAILED),
            )
        except Exception as e:
            logger.warning(f"Failed to record pipeline metrics: {e}")

    def cancel(self) -> None:
        """Cancel pipeline execution."""
        self._cancelled = True
        logger.info(f"Pipeline '{self.name}' cancellation requested")

    def get_status(self) -> Dict[str, Any]:
        """Get pipeline status."""
        return {
            "name": self.name,
            "running": self._running,
            "cancelled": self._cancelled,
            "stages": len(self._stages),
            "stage_names": self.list_stages(),
        }

    def get_results(self) -> List[StageResult]:
        """Get stage results from last execution."""
        return self._results.copy()

    def get_context(self) -> Optional[PipelineContext]:
        """Get context from last execution."""
        return self._context

    def reset(self) -> None:
        """Reset pipeline state."""
        self._context = None
        self._results = []
        self._cancelled = False
        for stage in self._stages:
            stage.status = StageStatus.PENDING


class CompositePipeline(Pipeline):
    """Pipeline that can contain sub-pipelines as stages."""

    def __init__(self, name: str, **kwargs):
        super().__init__(name, **kwargs)
        self._sub_pipelines: Dict[str, Pipeline] = {}

    def add_pipeline_stage(self, name: str, pipeline: Pipeline) -> "CompositePipeline":
        """Add a sub-pipeline as a stage."""

        class SubPipelineStage(PipelineStage):
            def __init__(self, sub_pipeline: Pipeline):
                super().__init__(name)
                self.sub_pipeline = sub_pipeline

            def execute(self, context: PipelineContext) -> Any:
                sub_context = PipelineContext.from_dict(context.to_dict())
                result_context = self.sub_pipeline.execute(sub_context)
                # Merge results back
                context.stage_results.update(result_context.stage_results)
                context.data.update(result_context.data)
                context.errors.extend(result_context.errors)
                return result_context.metadata.get("pipeline_status")

        stage = SubPipelineStage(pipeline)
        self.add_stage(stage)
        self._sub_pipelines[name] = pipeline
        return self


# Pipeline builder for fluent construction
class PipelineBuilder:
    """Fluent builder for creating pipelines."""

    def __init__(self, name: str, config: Optional[PipelineConfig] = None):
        self._pipeline = Pipeline(name, config)

    def add_stage(self, stage: PipelineStage) -> "PipelineBuilder":
        self._pipeline.add_stage(stage)
        return self

    def add_function(
        self,
        name: str,
        func: Callable[[PipelineContext], Any],
        **kwargs,
    ) -> "PipelineBuilder":
        self._pipeline.add_function_stage(name, func, **kwargs)
        return self

    def add_hook(self, hook_point: str, callback: Callable) -> "PipelineBuilder":
        self._pipeline.register_hook(hook_point, callback)
        return self

    def build(self) -> Pipeline:
        return self._pipeline


def create_pipeline(name: str, config: Optional[PipelineConfig] = None) -> PipelineBuilder:
    """Create a pipeline builder."""
    return PipelineBuilder(name, config)


# Common stage implementations

class ConditionalStage(PipelineStage):
    """Stage that executes conditionally."""

    def __init__(
        self,
        name: str,
        stage: PipelineStage,
        condition: Callable[[PipelineContext], bool],
    ):
        super().__init__(name)
        self._stage = stage
        self._condition = condition

    def execute(self, context: PipelineContext) -> Any:
        if self._condition(context):
            return self._stage.execute(context)
        return None


class ParallelStage(PipelineStage):
    """Stage that executes multiple sub-stages in parallel."""

    def __init__(
        self,
        name: str,
        stages: List[PipelineStage],
        wait_for_all: bool = True,
    ):
        super().__init__(name)
        self._stages = stages
        self._wait_for_all = wait_for_all

    def execute(self, context: PipelineContext) -> Any:
        import concurrent.futures

        results = {}

        def run_stage(stage: PipelineStage):
            sub_context = PipelineContext.from_dict(context.to_dict())
            return stage.name, stage.execute(sub_context)

        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = [executor.submit(run_stage, s) for s in self._stages]

            if self._wait_for_all:
                for future in concurrent.futures.as_completed(futures):
                    stage_name, output = future.result()
                    results[stage_name] = output
            else:
                # Return first completed
                for future in concurrent.futures.as_completed(futures):
                    stage_name, output = future.result()
                    return {stage_name: output}

        return results

    async def execute_async(self, context: PipelineContext) -> Any:
        async def run_stage(stage: PipelineStage):
            sub_context = PipelineContext.from_dict(context.to_dict())
            output = await stage.execute_async(sub_context)
            return stage.name, output

        tasks = [run_stage(s) for s in self._stages]

        if self._wait_for_all:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            return {name: output for name, output in results if not isinstance(output, Exception)}
        else:
            # Return first completed
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in done:
                name, output = task.result()
                return {name: output}
        return {}


class TransformStage(FunctionStage):
    """Stage that transforms context data."""

    def __init__(
        self,
        name: str,
        transform_func: Callable[[Dict[str, Any]], Dict[str, Any]],
    ):
        def wrapper(context: PipelineContext) -> Dict[str, Any]:
            return transform_func(context.data)

        super().__init__(name, wrapper)