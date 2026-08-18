"""Predictive Diagnostics Service for Self Observation.

Provides a framework for forecasting resource exhaustion, performance degradation,
and other operational risks by integrating with Runtime Awareness and Self-Analysis.

This is the framework/integration layer - it does NOT implement forecasting algorithms.
It provides the interfaces, data flow, and integration points for future algorithm implementation.
"""

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from uuid import uuid4

from app.core.events import get_event_bus, Event, EventPriority
from app.core.observability import get_observability_hub, ComponentInfo, ComponentType
from app.self_observation.runtime_awareness import RuntimeAwareness, AwarenessConfig, AwarenessComponent
from app.self_observation.self_analysis import CentralizedSelfAnalysis, AnalysisConfig, AnalysisCategory
from app.self_observation.predictive_models import (
    PredictionType,
    PredictionHorizon,
    PredictionConfidence,
    PredictionStatus,
    PredictionSeverity,
    PredictionInput,
    PredictionResult,
    PredictionModel,
    PredictionEngine,
    PredictionSubscription,
    PredictiveDiagnosticsConfig,
    get_horizon_duration,
    confidence_from_score,
    severity_from_probability_and_impact,
    ResourceForecastingModel,
    create_resource_forecasting_model,
    PerformanceDegradationModel,
    create_performance_degradation_model,
)

logger = logging.getLogger(__name__)


@dataclass
class PredictiveAlert:
    """Alert generated from a prediction."""
    alert_id: str = field(default_factory=lambda: f"palert_{uuid4().hex[:8]}")
    prediction_id: str = ""
    prediction_type: PredictionType = PredictionType.CUSTOM
    horizon: PredictionHorizon = PredictionHorizon.SHORT_TERM
    predicted_issue: str = ""
    confidence: PredictionConfidence = PredictionConfidence.MEDIUM
    confidence_score: float = 0.5
    severity: PredictionSeverity = PredictionSeverity.WARNING
    estimated_time_until_occurrence: Optional[str] = None  # ISO format timestamp
    affected_subsystem: str = ""
    supporting_forecast: Dict[str, Any] = field(default_factory=dict)
    recommended_actions: List[str] = field(default_factory=list)
    mitigation_strategies: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str = "active"  # active, acknowledged, resolved, expired
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "prediction_id": self.prediction_id,
            "prediction_type": self.prediction_type.value,
            "horizon": self.horizon.value,
            "predicted_issue": self.predicted_issue,
            "confidence": self.confidence.value,
            "confidence_score": self.confidence_score,
            "severity": self.severity.value,
            "estimated_time_until_occurrence": self.estimated_time_until_occurrence,
            "affected_subsystem": self.affected_subsystem,
            "supporting_forecast": self.supporting_forecast,
            "recommended_actions": self.recommended_actions,
            "mitigation_strategies": self.mitigation_strategies,
            "timestamp": self.timestamp,
            "status": self.status,
            "metadata": self.metadata,
        }


@dataclass
class PredictionValidationRecord:
    """Record of a prediction validation outcome."""
    validation_id: str = field(default_factory=lambda: f"val_{uuid4().hex[:8]}")
    prediction_id: str = ""
    prediction_type: PredictionType = PredictionType.CUSTOM
    horizon: PredictionHorizon = PredictionHorizon.SHORT_TERM
    was_accurate: bool = False
    false_positive: bool = False
    false_negative: bool = False
    predicted_value: Optional[float] = None
    actual_value: Optional[float] = None
    predicted_state: Optional[str] = None
    actual_state: Optional[str] = None
    confidence_at_prediction: float = 0.0
    confidence_score_at_prediction: float = 0.0
    validation_time: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    time_to_validation_seconds: float = 0.0
    model_name: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    evaluation: str = "UNRESOLVED"  # CORRECT, INCORRECT, PARTIAL, UNRESOLVED
    observation_id: str = ""
    hypothesis_id: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PredictionLearningState:
    """Tracks learning state for a prediction model/type combination."""
    model_name: str = ""
    prediction_type: PredictionType = PredictionType.CUSTOM
    total_predictions: int = 0
    accurate_predictions: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    current_accuracy: float = 0.0
    confidence_adjustment: float = 0.0  # Applied to future predictions
    recent_validation_history: List[bool] = field(default_factory=list)  # Last N validations
    recurring_patterns: Dict[str, int] = field(default_factory=dict)  # Pattern -> count
    last_updated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def update_from_validation(self, was_accurate: bool, false_positive: bool = False, false_negative: bool = False) -> None:
        self.total_predictions += 1
        if was_accurate:
            self.accurate_predictions += 1
        if false_positive:
            self.false_positives += 1
        if false_negative:
            self.false_negatives += 1
        self.current_accuracy = self.accurate_predictions / self.total_predictions if self.total_predictions > 0 else 0.0

        self.recent_validation_history.append(was_accurate)
        if len(self.recent_validation_history) > 50:  # Keep last 50
            self.recent_validation_history.pop(0)

        # Adjust confidence based on recent accuracy
        recent_accuracy = sum(self.recent_validation_history) / len(self.recent_validation_history) if self.recent_validation_history else 0.5
        # If we're being overconfident (high confidence but low accuracy), reduce
        # If we're being underconfident (low confidence but high accuracy), increase
        self.confidence_adjustment = (recent_accuracy - 0.5) * 0.2  # Max +/- 0.1
        self.last_updated = datetime.now(timezone.utc).isoformat()


@dataclass
class PredictiveDiagnosticsConfig:
    """Configuration for the Predictive Diagnostics service."""
    enabled: bool = True
    update_interval_seconds: float = 60.0
    min_data_points: int = 3
    default_horizons: List[PredictionHorizon] = field(default_factory=lambda: [
        PredictionHorizon.SHORT_TERM,
        PredictionHorizon.MEDIUM_TERM,
    ])
    enabled_prediction_types: List[PredictionType] = field(default_factory=lambda: [
        PredictionType.RESOURCE_EXHAUSTION,
        PredictionType.PERFORMANCE_DEGRADATION,
        PredictionType.FAILURE_PROBABILITY,
        PredictionType.GOAL_STALL,
        PredictionType.CAPACITY_BREACH,
        PredictionType.TREND_ANOMALY,
    ])
    confidence_threshold: float = 0.5
    severity_threshold: PredictionSeverity = PredictionSeverity.WARNING
    max_history: int = 100
    trend_window_seconds: float = 3600.0
    auto_validate_predictions: bool = True

    # Alert generation
    enable_alert_generation: bool = True
    alert_cooldown_seconds: float = 300.0  # 5 minutes between similar alerts
    min_confidence_for_alert: float = 0.6
    min_severity_for_alert: PredictionSeverity = PredictionSeverity.WARNING

    # Learning and refinement
    enable_prediction_learning: bool = True
    max_validation_history: int = 500
    learning_window_size: int = 20  # Number of recent validations for confidence adjustment
    confidence_adjustment_rate: float = 0.1  # How much to adjust confidence per validation
    pattern_detection_threshold: int = 3  # Minimum occurrences to detect a pattern

    # Integration
    enable_self_analysis_integration: bool = True
    enable_runtime_awareness_integration: bool = True
    enable_knowledge_base_integration: bool = True
    enable_autonomous_learning_integration: bool = True


class PredictiveDiagnostics:
    """
    Predictive Diagnostics Service.

    Integrates with Runtime Awareness and Self-Analysis to provide predictive capabilities.
    This is a framework that provides:
    - Data collection from existing monitoring systems
    - Prediction input preparation
    - Model registry and management
    - Prediction execution and result handling
    - Integration with existing event system
    - Validation of predictions against outcomes

    Does NOT implement forecasting algorithms - provides integration points for them.
    """

    def __init__(
        self,
        runtime_awareness: Optional[RuntimeAwareness] = None,
        self_analysis: Optional[CentralizedSelfAnalysis] = None,
        config: Optional[PredictiveDiagnosticsConfig] = None,
        event_bus=None,
        observability=None,
    ):
        """Initialize the predictive diagnostics service."""
        self._runtime_awareness = runtime_awareness
        self._self_analysis = self_analysis
        self._config = config or PredictiveDiagnosticsConfig()

        self._event_bus = event_bus or get_event_bus()
        self._observability = observability or get_observability_hub()
        if self._event_bus is None:
            raise ValueError("PredictiveDiagnostics requires the canonical EventBus")
        if self._observability is None:
            raise ValueError("PredictiveDiagnostics requires the canonical ObservabilityHub")

        self._lock = threading.RLock()
        self._running = False
        self._diagnostics_thread: Optional[threading.Thread] = None

        # Model registry (framework for future ML models)
        self._models: Dict[str, PredictionModel] = {}
        self._model_lock = threading.RLock()

        # Register default resource forecasting model
        self._register_default_models()

        # Prediction history
        self._prediction_history: List[PredictionResult] = []
        self._max_history = self._config.max_history

        # Active subscriptions
        self._subscriptions: Dict[str, PredictionSubscription] = {}

        # Validation tracking
        self._pending_validations: Dict[str, PredictionResult] = {}
        self._validated_prediction_ids: Set[str] = set()

        # Alert generation
        self._generated_alerts: List[PredictiveAlert] = []
        self._max_alerts = 200
        self._alert_cooldowns: Dict[str, float] = {}  # Key -> last alert time

        # Learning and refinement
        self._validation_history: List[PredictionValidationRecord] = []
        self._max_validation_history = self._config.max_validation_history
        self._learning_states: Dict[str, PredictionLearningState] = {}  # Key: "model_type" -> state
        self._false_positive_patterns: Dict[str, int] = defaultdict(int)
        self._false_negative_patterns: Dict[str, int] = defaultdict(int)

        # Integration references
        self._autonomous_learning: Optional[Any] = None
        self._knowledge_base: Optional[Any] = None

        # Register with observability
        self._register_with_observability()

        # Subscribe to events
        self._subscribe_events()

        logger.info("PredictiveDiagnostics initialized")

    def _register_with_observability(self) -> None:
        """Register this subsystem with the shared ObservabilityHub."""
        if self._observability:
            self._observability.register_component(
                ComponentInfo(
                    name="PredictiveDiagnostics",
                    component_type=ComponentType.SERVICE,
                    version="1.0.0",
                    description="Predictive diagnostics framework for forecasting operational risks",
                )
            )

    def _subscribe_events(self) -> None:
        """Subscribe to events from integrated subsystems."""
        # Runtime Awareness updates
        self._event_bus.subscribe("runtime_awareness.updated", self._on_awareness_updated)

        # Self-Analysis completions
        self._event_bus.subscribe("self_analysis.completed", self._on_analysis_completed)

        # System health changes
        self._event_bus.subscribe("health.check.completed", self._on_health_changed)

        # Component lifecycle
        self._event_bus.subscribe("component.registered", self._on_component_event)

        # Orchestrator events for context
        self._event_bus.subscribe("orchestrator.intent_executed", self._on_activity_event)

    def _register_default_models(self) -> None:
        """Register default prediction models."""
        # Register lightweight resource forecasting model
        resource_model = create_resource_forecasting_model(
            min_data_points=self._config.min_data_points,
        )
        self.register_model(resource_model)
        logger.info("Registered default ResourceForecastingModel")

        # Register performance degradation model
        perf_model = create_performance_degradation_model(
            min_data_points=self._config.min_data_points,
        )
        self.register_model(perf_model)
        logger.info("Registered default PerformanceDegradationModel")

    def start(self) -> None:
        """Start the predictive diagnostics service."""
        with self._lock:
            if self._running:
                return
            if not self._config.enabled:
                logger.info("PredictiveDiagnostics disabled by config")
                return
            self._running = True

        self._diagnostics_thread = threading.Thread(
            target=self._diagnostics_loop,
            daemon=True,
            name="PredictiveDiagnostics",
        )
        self._diagnostics_thread.start()
        logger.info("PredictiveDiagnostics started")

    def stop(self) -> None:
        """Stop the predictive diagnostics service."""
        with self._lock:
            if not self._running:
                return
            self._running = False

        if self._diagnostics_thread and self._diagnostics_thread.is_alive():
            self._diagnostics_thread.join(timeout=5.0)
        self._diagnostics_thread = None

        logger.info("PredictiveDiagnostics stopped")

    def _diagnostics_loop(self) -> None:
        """Background prediction loop."""
        while self._running:
            try:
                self.run_predictions()
            except Exception as e:
                logger.error(f"Error in diagnostics loop: {e}")

            time.sleep(self._config.update_interval_seconds)

    def run_predictions(self, force: bool = False) -> List[PredictionResult]:
        """
        Run predictions for all enabled types and horizons.

        Args:
            force: Force prediction even if not enough time has passed

        Returns:
            List of prediction results
        """
        if not self._runtime_awareness:
            logger.warning("RuntimeAwareness not available, skipping predictions")
            return []

        start_time = time.perf_counter()
        results = []

        # Get current awareness state
        awareness_state = self._runtime_awareness.get_current_state()
        if not awareness_state:
            logger.debug("No awareness state available")
            return []

        # Prepare historical context from awareness
        historical_context = self._get_historical_context()

        # Run predictions for each enabled type and horizon
        for pred_type in self._config.enabled_prediction_types:
            for horizon in self._config.default_horizons:
                try:
                    # Prepare input
                    input_data = self._prepare_prediction_input(
                        pred_type, horizon, awareness_state, historical_context
                    )

                    # Make prediction
                    result = self._make_prediction(input_data)
                    if result and self._should_emit_prediction(result):
                        results.append(result)
                        self._record_prediction(result)
                        self._notify_subscriptions(result)

                except Exception as e:
                    # Each background model is best-effort. Do not let one
                    # malformed/insufficient series abort the foreground chat
                    # or suppress the remaining prediction types.
                    logger.warning(
                        "trend_anomaly %s prediction skipped: %s",
                        horizon.value,
                        e,
                    )

        # Validate pending predictions if enabled
        if self._config.auto_validate_predictions:
            self._validate_pending_predictions()

        # Emit event
        self._event_bus.emit(
            "predictive_diagnostics.completed",
            data={
                "predictions_generated": len(results),
                "prediction_types": [r.prediction_type.value for r in results],
                "duration_ms": (time.perf_counter() - start_time) * 1000,
            },
            source="PredictiveDiagnostics"
        )

        # Record metrics
        self._observability.record_metric("predictive_diagnostics.predictions_generated", len(results))

        logger.debug(f"Generated {len(results)} predictions in {(time.perf_counter() - start_time) * 1000:.1f}ms")
        return results

    def _get_historical_context(self) -> List[Dict[str, Any]]:
        """Get historical context from Runtime Awareness and Self-Analysis."""
        context = []

        # From Runtime Awareness
        if self._runtime_awareness:
            history = self._runtime_awareness.get_history(limit=50)
            for state in history:
                ctx = {
                    "timestamp": state.timestamp,
                    "cpu_usage": state.cpu_usage,
                    "memory_usage_mb": state.memory_usage_mb,
                    "running_tasks": len(state.running_tasks),
                    "active_goals": len(state.active_goals),
                    "pending_workflows": state.pending_workflows,
                    "background_jobs": state.background_jobs,
                    "system_health": state.system_health_status,
                }

                # Add performance degradation metrics
                ctx["pending_tasks"] = len([t for t in state.running_tasks if t.get("paused", False)])
                ctx["queued_tasks"] = state.pending_workflows
                ctx["cpu_contention"] = state.cpu_usage
                ctx["gpu_utilization"] = state.gpu_utilization_percent
                ctx["gpu_memory_percent"] = (
                    (state.gpu_memory_used_mb / state.gpu_memory_total_mb * 100)
                    if state.gpu_memory_total_mb is not None and state.gpu_memory_used_mb is not None and state.gpu_memory_total_mb > 0 else 0.0
                )
                ctx["disk_io_mb_s"] = state.disk_io_mb_s
                ctx["network_io_mb_s"] = state.network_io_mb_s

                # Add worker/scheduler metrics from GPU devices if available
                if state.gpu_devices:
                    ctx["active_workers"] = len(state.gpu_devices)  # Placeholder - using GPU count

                context.append(ctx)

        # From Self-Analysis
        if self._self_analysis:
            analysis_history = self._self_analysis.get_history(limit=20)
            for report in analysis_history:
                context.append({
                    "timestamp": report.timestamp,
                    "overall_score": report.overall_score,
                    "categories": {
                        cat.value: result.score
                        for cat, result in report.analysis_results.items()
                    },
                })

        return context

    def _prepare_prediction_input(
        self,
        pred_type: PredictionType,
        horizon: PredictionHorizon,
        awareness_state: Any,
        historical_context: List[Dict[str, Any]],
    ) -> PredictionInput:
        """Prepare prediction input from current state and history."""
        source_data = {
            "prediction_type": pred_type.value,
            "horizon": horizon.value,
        }

        # Get system metrics from ObservabilityHub for more detailed data
        system_metrics = {}
        if self._observability:
            system_metrics = self._observability.get_system_metrics()

        # Get GPU metrics if available
        gpu_metrics = self._get_gpu_metrics()

        # Add current metrics based on prediction type
        if pred_type == PredictionType.RESOURCE_EXHAUSTION:
            # CPU usage
            cpu_percent = system_metrics.get("system.cpu.percent", awareness_state.cpu_usage)
            source_data["cpu_percent"] = cpu_percent

            # Memory usage (system-wide percentage)
            memory_percent = system_metrics.get("system.memory.percent", 0.0)
            if memory_percent == 0.0 and awareness_state.memory_usage_mb is not None and awareness_state.memory_usage_mb > 0:
                # Fallback: estimate from process memory
                mem_total = system_metrics.get("system.memory.total_gb", 0.0)
                if mem_total > 0:
                    memory_percent = (awareness_state.memory_usage_mb / 1024.0) / mem_total * 100.0
            source_data["memory_percent"] = memory_percent

            # Disk usage percentage
            disk_percent = system_metrics.get("system.disk.percent", 0.0)
            source_data["disk_percent"] = disk_percent

            # Disk I/O rates
            source_data["disk_read_mb_s"] = system_metrics.get("system.disk.read_mb_s", 0.0)
            source_data["disk_write_mb_s"] = system_metrics.get("system.disk.write_mb_s", 0.0)

            # Network usage (sent + received MB/s)
            net_sent = system_metrics.get("system.network.sent_mb_s", 0.0)
            net_recv = system_metrics.get("system.network.recv_mb_s", 0.0)
            source_data["network_mbps"] = (net_sent + net_recv) * 8  # Convert MB/s to Mbps
            source_data["network_io_mb_s"] = awareness_state.network_io_mb_s

            # GPU metrics
            if gpu_metrics:
                source_data["gpu_metrics"] = gpu_metrics

        elif pred_type == PredictionType.PERFORMANCE_DEGRADATION:
            # Get job service metrics for queue/throughput data
            job_service_metrics = {}
            try:
                from app.core.background_jobs import get_job_service
                job_service = get_job_service()
                job_stats = job_service.get_stats()
                job_service_metrics = {
                    "background_jobs": job_stats.get("active_jobs", 0),
                    "job_status_counts": job_stats.get("status_counts", {}),
                    "workers_available": job_stats.get("workers_available", 0),
                    "worker_capacity": job_stats.get("worker_capacity", 0),
                }
                # Calculate scheduler utilization
                if job_stats.get("worker_capacity", 0) > 0:
                    job_service_metrics["scheduler_utilization"] = (
                        1.0 - (job_stats.get("workers_available", 0) / job_stats.get("worker_capacity", 1))
                    )
            except Exception:
                pass

            # Get task executor metrics if available
            task_metrics = {}
            if self._runtime_awareness and hasattr(self._runtime_awareness, '_orchestrator') and self._runtime_awareness._orchestrator:
                try:
                    executor = self._runtime_awareness._orchestrator.task_executor
                    if executor:
                        exec_stats = executor.get_stats()
                        task_metrics = {
                            "completed_workflows": exec_stats.get("completed_workflows", 0),
                            "failed_workflows": exec_stats.get("failed_workflows", 0),
                            "active_workflows": exec_stats.get("active_workflows", 0),
                        }
                        # Calculate throughput (completed per minute)
                        if exec_stats.get("total_workflows", 0) > 0 and awareness_state.session_duration_seconds is not None and awareness_state.session_duration_seconds > 60:
                            task_metrics["workflows_completed_per_min"] = (
                                exec_stats.get("completed_workflows", 0) / (awareness_state.session_duration_seconds / 60)
                            )
                except Exception:
                    pass

            # Get observability metric history for latency data
            latency_metrics = {}
            if self._observability:
                try:
                    # Try to get task/workflow latency metrics
                    for metric_name in ["task_avg_latency_ms", "workflow_avg_latency_ms", "tool_avg_latency_ms",
                                        "avg_task_duration", "avg_workflow_duration", "avg_tool_duration"]:
                        point = self._observability.get_metric(metric_name)
                        if point:
                            latency_metrics[metric_name] = point.value
                except Exception:
                    pass

            source_data.update({
                # Task/queue metrics
                "running_tasks": len(awareness_state.running_tasks),
                "pending_workflows": awareness_state.pending_workflows,
                "pending_tasks": len([t for t in awareness_state.running_tasks if t.get("paused", False)]),
                "queued_tasks": awareness_state.pending_workflows,  # Workflows waiting to start

                # Resource metrics
                "cpu_usage": awareness_state.cpu_usage,
                "memory_usage_mb": awareness_state.memory_usage_mb,
                "cpu_contention": awareness_state.cpu_usage,
                "memory_pressure": system_metrics.get("system.memory.percent", 0.0),

                # GPU metrics
                "gpu_utilization": awareness_state.gpu_utilization_percent,
                "gpu_memory_percent": (
                    (awareness_state.gpu_memory_used_mb / awareness_state.gpu_memory_total_mb * 100)
                    if awareness_state.gpu_memory_total_mb is not None and awareness_state.gpu_memory_used_mb is not None and awareness_state.gpu_memory_total_mb > 0 else 0.0
                ),

                # Scheduler/worker metrics from job service
                **job_service_metrics,

                # Task executor metrics
                **task_metrics,

                # Latency metrics
                **latency_metrics,

                # System metrics that indicate bottlenecks
                "disk_io_mb_s": system_metrics.get("system.disk.read_mb_s", 0.0) + system_metrics.get("system.disk.write_mb_s", 0.0),
                "network_io_mb_s": system_metrics.get("system.network.sent_mb_s", 0.0) + system_metrics.get("system.network.recv_mb_s", 0.0),
                "system_load_1min": system_metrics.get("system.load.1min", 0.0),
                "system_load_5min": system_metrics.get("system.load.5min", 0.0),
            })
        elif pred_type == PredictionType.FAILURE_PROBABILITY:
            source_data.update({
                "system_health": awareness_state.system_health_status,
                "alert_count": len(awareness_state.alerts),
                "running_tasks": len(awareness_state.running_tasks),
                "total_failures": awareness_state.total_failures,
            })
        elif pred_type == PredictionType.GOAL_STALL:
            source_data.update({
                "active_goals": len(awareness_state.active_goals),
                "pending_workflows": awareness_state.pending_workflows,
                "background_jobs": awareness_state.background_jobs,
                "session_duration": awareness_state.session_duration_seconds,
            })

        # Add trends from awareness
        trends = self._runtime_awareness.get_all_trends(window_seconds=self._config.trend_window_seconds)
        source_data["trends"] = trends

        return PredictionInput(
            prediction_type=pred_type,
            horizon=horizon,
            source_data=source_data,
            historical_context=historical_context,
            metadata={
                "awareness_id": awareness_state.awareness_id,
                "generated_from": "runtime_awareness",
            }
        )

    def _get_gpu_metrics(self) -> Optional[List[Dict[str, Any]]]:
        """Get GPU metrics from available GPU monitoring."""
        try:
            # Try to import and use GPU monitor
            from app.monitoring.gpu_monitor import get_gpu_monitor, GPUMetrics

            # Check if there's a global GPU monitor instance
            # We'll create a temporary one if needed
            gpu_monitor = get_gpu_monitor()
            if not gpu_monitor or not gpu_monitor.enabled:
                return None

            metrics = gpu_monitor.get_current_metrics()
            if not metrics:
                return None

            return [
                {
                    "index": m.index,
                    "vendor": m.vendor.value if hasattr(m.vendor, 'value') else str(m.vendor),
                    "name": m.name,
                    "utilization_percent": m.gpu_utilization_percent,
                    "memory_percent": m.memory_utilization_percent,
                    "memory_used_mb": m.memory_used_mb,
                    "memory_free_mb": m.memory_free_mb,
                    "memory_total_mb": m.memory_total_mb,
                    "temperature_celsius": m.temperature_celsius,
                    "power_draw_watts": m.power_draw_watts,
                }
                for m in metrics
            ]
        except Exception:
            # GPU monitoring not available
            return None

    def _make_prediction(self, input_data: PredictionInput) -> Optional[PredictionResult]:
        """
        Make a prediction using registered models.

        This is the extension point for forecasting algorithms.
        Currently returns a framework placeholder that indicates
        what data is available for prediction.
        """
        # Find suitable model
        model = self._find_best_model(input_data.prediction_type, input_data.horizon)

        if model:
            try:
                return model.predict(input_data)
            except Exception as e:
                logger.error(f"Model {model.name} prediction failed: {e}")

        # No model available - return framework placeholder with available data
        return self._create_placeholder_prediction(input_data)

    def _find_best_model(self, pred_type: PredictionType, horizon: PredictionHorizon) -> Optional[PredictionModel]:
        """Find the best registered model for the given type and horizon."""
        with self._model_lock:
            suitable_models = [
                m for m in self._models.values()
                if m.can_predict(pred_type, horizon)
            ]

            if not suitable_models:
                return None

            # Prefer model with highest accuracy
            return max(suitable_models, key=lambda m: m.accuracy)

    def _create_placeholder_prediction(self, input_data: PredictionInput) -> PredictionResult:
        """
        Create a placeholder prediction indicating what data is available.

        This is NOT a real prediction - it's a framework indicator showing
        what data would be available to a real forecasting algorithm.
        """
        pred_type = input_data.prediction_type
        horizon = input_data.horizon
        source = input_data.source_data
        trends = source.get("trends", {})

        # Build evidence from available data
        evidence = []
        contributing_factors = {}

        if pred_type == PredictionType.RESOURCE_EXHAUSTION:
            cpu = source.get("cpu_percent", 0)
            mem = source.get("memory_percent", 0)
            evidence.append(f"Current CPU: {cpu:.1f}%, Memory: {mem:.1f}%")
            if "cpu_usage" in trends:
                evidence.append(f"CPU trend: {trends['cpu_usage'].get('trend', 'unknown')} (slope: {trends['cpu_usage'].get('slope', 0):.4f})")
                contributing_factors["cpu_trend"] = abs(trends['cpu_usage'].get('slope', 0))
            if "memory_usage_mb" in trends:
                evidence.append(f"Memory trend: {trends['memory_usage_mb'].get('trend', 'unknown')}")
                contributing_factors["memory_trend"] = abs(trends['memory_usage_mb'].get('slope', 0))

        elif pred_type == PredictionType.PERFORMANCE_DEGRADATION:
            tasks = source.get("running_tasks", 0)
            pending = source.get("pending_workflows", 0)
            evidence.append(f"Running tasks: {tasks}, Pending workflows: {pending}")
            if "running_tasks" in trends:
                evidence.append(f"Task trend: {trends['running_tasks'].get('trend', 'unknown')}")
                contributing_factors["task_trend"] = abs(trends['running_tasks'].get('slope', 0))

        elif pred_type == PredictionType.FAILURE_PROBABILITY:
            health = source.get("system_health", "unknown")
            alerts = source.get("alert_count", 0)
            evidence.append(f"System health: {health}, Active alerts: {alerts}")
            if "system_health" in trends:
                pass  # System health is categorical

        elif pred_type == PredictionType.GOAL_STALL:
            goals = source.get("active_goals", 0)
            pending = source.get("pending_workflows", 0)
            evidence.append(f"Active goals: {goals}, Pending workflows: {pending}")

        # Calculate placeholder confidence based on data availability
        data_points = len(input_data.historical_context)
        confidence_score = min(1.0, data_points / self._config.min_data_points * 0.5 + 0.2)
        confidence = confidence_from_score(confidence_score)

        # Severity based on current state
        if pred_type == PredictionType.RESOURCE_EXHAUSTION:
            cpu = source.get("cpu_percent", 0)
            mem = source.get("memory_percent", 0)
            severity = severity_from_probability_and_impact(
                max(cpu, mem) / 100.0, 0.8
            )
        else:
            severity = PredictionSeverity.INFO

        return PredictionResult(
            prediction_type=pred_type,
            horizon=horizon,
            predicted_value=None,  # No algorithm implemented
            predicted_state="framework_placeholder",
            probability=0.0,
            confidence=confidence,
            confidence_score=confidence_score,
            severity=severity,
            evidence=evidence,
            contributing_factors=contributing_factors,
            trend_data=trends,
            model_info={
                "model": "framework_placeholder",
                "note": "No forecasting algorithm implemented - data available for future models",
                "available_metrics": list(source.keys()),
                "historical_points": data_points,
            },
            recommended_actions=["Implement forecasting algorithm for this prediction type"],
            mitigation_strategies=[],
            metadata={
                "is_placeholder": True,
                "data_available": data_points >= self._config.min_data_points,
            }
        )

    def _should_emit_prediction(self, result: PredictionResult) -> bool:
        """Check if prediction meets emission thresholds."""
        # Don't emit placeholder predictions by default
        if result.metadata.get("is_placeholder"):
            return result.confidence_score >= self._config.confidence_threshold

        return (
            result.confidence_score >= self._config.confidence_threshold
            and self._severity_meets_threshold(result.severity)
        )

    def _severity_meets_threshold(self, severity: PredictionSeverity) -> bool:
        """Check if severity meets threshold."""
        severity_order = {
            PredictionSeverity.INFO: 0,
            PredictionSeverity.WARNING: 1,
            PredictionSeverity.CRITICAL: 2,
            PredictionSeverity.URGENT: 3,
        }
        return severity_order.get(severity, 0) >= severity_order.get(self._config.severity_threshold, 1)

    def _record_prediction(self, result: PredictionResult) -> None:
        """Record prediction in history."""
        with self._lock:
            self._prediction_history.append(result)
            if len(self._prediction_history) > self._max_history:
                self._prediction_history.pop(0)

            # Track for validation
            if self._config.auto_validate_predictions and result.horizon_end:
                self._pending_validations[result.prediction_id] = result

    def _validate_pending_predictions(self) -> None:
        """Validate pending predictions against current state."""
        if not self._runtime_awareness:
            return

        current_state = self._runtime_awareness.get_current_state()
        if not current_state:
            return

        now = datetime.now(timezone.utc)
        to_remove = []

        for pred_id, prediction in self._pending_validations.items():
            # Check if horizon has passed
            if prediction.horizon_end:
                horizon_end = datetime.fromisoformat(prediction.horizon_end.replace('Z', '+00:00'))
                if now > horizon_end:
                    # Horizon passed - validate
                    was_accurate = self._validate_prediction(prediction, current_state)
                    self._record_validation_result(prediction, was_accurate)
                    to_remove.append(pred_id)

        for pred_id in to_remove:
            self._pending_validations.pop(pred_id, None)

    def _validate_prediction(self, prediction: PredictionResult, current_state: Any) -> bool:
        """Compare a prediction with an actual runtime observation."""
        actual_state = getattr(current_state, "system_health_status", None)
        if prediction.predicted_state is not None and isinstance(actual_state, str):
            return prediction.predicted_state == actual_state
        metric_name = prediction.metadata.get("metric") if isinstance(prediction.metadata, dict) else None
        actual_value = getattr(current_state, metric_name, None) if metric_name else None
        if isinstance(prediction.predicted_value, (int, float)) and isinstance(actual_value, (int, float)):
            tolerance = prediction.metadata.get("tolerance", 0.0) if isinstance(prediction.metadata, dict) else 0.0
            return abs(prediction.predicted_value - actual_value) <= tolerance
        return False

    def record_actual_outcome(
        self,
        prediction_id: str,
        *,
        actual_state: Optional[str] = None,
        actual_value: Optional[float] = None,
        observation_id: str = "",
        evidence: Optional[Dict[str, Any]] = None,
    ) -> Optional[PredictionValidationRecord]:
        """Evaluate a prediction once against an explicitly recorded outcome."""
        with self._lock:
            prediction = next((item for item in self._prediction_history if item.prediction_id == prediction_id), None)
            if prediction is None or prediction_id in self._validated_prediction_ids:
                return None
            self._validated_prediction_ids.add(prediction_id)

        has_state = prediction.predicted_state is not None and actual_state is not None
        has_value = isinstance(prediction.predicted_value, (int, float)) and isinstance(actual_value, (int, float))
        if has_state:
            evaluation = "CORRECT" if prediction.predicted_state == actual_state else "INCORRECT"
            accurate = evaluation == "CORRECT"
        elif has_value:
            tolerance = prediction.metadata.get("tolerance", 0.0) if isinstance(prediction.metadata, dict) else 0.0
            evaluation = "CORRECT" if abs(prediction.predicted_value - actual_value) <= tolerance else "INCORRECT"
            accurate = evaluation == "CORRECT"
        else:
            evaluation, accurate = "UNRESOLVED", False
        record = PredictionValidationRecord(
            prediction_id=prediction_id,
            prediction_type=prediction.prediction_type,
            horizon=prediction.horizon,
            was_accurate=accurate,
            predicted_value=prediction.predicted_value,
            actual_value=actual_value,
            predicted_state=prediction.predicted_state,
            actual_state=actual_state,
            confidence_at_prediction=prediction.confidence_score,
            confidence_score_at_prediction=prediction.confidence_score,
            model_name=prediction.model_info.get("model", ""),
            evaluation=evaluation,
            observation_id=observation_id,
            hypothesis_id=str(prediction.metadata.get("hypothesis_id", "")),
            evidence=evidence or {},
        )
        with self._lock:
            self._validation_history.append(record)
            if len(self._validation_history) > self._max_validation_history:
                self._validation_history.pop(0)
        if evaluation != "UNRESOLVED":
            self._record_validation_result(prediction, accurate)
        return record

    def get_prediction_accuracy(self) -> Dict[str, Any]:
        with self._lock:
            resolved = [record for record in self._validation_history if record.evaluation in {"CORRECT", "INCORRECT", "PARTIAL"}]
            counts = {status: sum(1 for record in self._validation_history if record.evaluation == status) for status in ("CORRECT", "INCORRECT", "PARTIAL", "UNRESOLVED")}
        return {"resolved": len(resolved), "total": len(self._validation_history), "accuracy": (counts["CORRECT"] + 0.5 * counts["PARTIAL"]) / len(resolved) if resolved else None, "counts": counts}

    def get_validation_history(self, limit: int = 50) -> List[PredictionValidationRecord]:
        with self._lock:
            return self._validation_history[-limit:]

    def _record_validation_result(self, prediction: PredictionResult, was_accurate: bool) -> None:
        """Record validation result and update model accuracy."""
        logger.info(f"Prediction {prediction.prediction_id} validated: accurate={was_accurate}")

        # Update model accuracy if model was used
        model_name = prediction.model_info.get("model")
        if model_name and model_name in self._models:
            self._models[model_name].record_accuracy(was_accurate)

        # Emit validation event
        self._event_bus.emit(
            "predictive_diagnostics.validated",
            data={
                "prediction_id": prediction.prediction_id,
                "prediction_type": prediction.prediction_type.value,
                "horizon": prediction.horizon.value,
                "was_accurate": was_accurate,
            },
            source="PredictiveDiagnostics"
        )

    def _notify_subscriptions(self, result: PredictionResult) -> None:
        """Notify active subscriptions of new prediction."""
        for sub in self._subscriptions.values():
            if not sub.active:
                continue
            if result.prediction_type not in sub.prediction_types:
                continue
            if result.horizon not in sub.horizons:
                continue
            if not self._severity_meets_threshold(result.severity):
                continue
            if result.confidence_score < self._confidence_to_score(sub.min_confidence):
                continue

            if sub.callback:
                try:
                    # Run callback in background
                    threading.Thread(
                        target=lambda: sub.callback(result),
                        daemon=True
                    ).start()
                except Exception as e:
                    logger.error(f"Subscription callback failed: {e}")

    def _confidence_to_score(self, confidence: PredictionConfidence) -> float:
        """Convert confidence enum to score."""
        return {
            PredictionConfidence.VERY_HIGH: 0.9,
            PredictionConfidence.HIGH: 0.7,
            PredictionConfidence.MEDIUM: 0.5,
            PredictionConfidence.LOW: 0.3,
            PredictionConfidence.VERY_LOW: 0.0,
        }.get(confidence, 0.0)

    # Model management
    def register_model(self, model: PredictionModel) -> None:
        """Register a prediction model."""
        with self._model_lock:
            self._models[model.name] = model
        logger.info(f"Registered prediction model: {model.name} v{model.version}")

    def unregister_model(self, model_name: str) -> bool:
        """Unregister a prediction model."""
        with self._model_lock:
            if model_name in self._models:
                del self._models[model_name]
                logger.info(f"Unregistered prediction model: {model_name}")
                return True
        return False

    def get_model(self, name: str) -> Optional[PredictionModel]:
        """Get a registered model by name."""
        with self._model_lock:
            return self._models.get(name)

    def list_models(self) -> List[PredictionModel]:
        """List all registered models."""
        with self._model_lock:
            return list(self._models.values())

    # Subscription management
    def subscribe(
        self,
        prediction_types: List[PredictionType],
        horizons: List[PredictionHorizon],
        callback: Callable[[PredictionResult], None],
        min_confidence: PredictionConfidence = PredictionConfidence.LOW,
        min_severity: PredictionSeverity = PredictionSeverity.INFO,
    ) -> str:
        """Subscribe to predictions."""
        subscription = PredictionSubscription(
            prediction_types=prediction_types,
            horizons=horizons,
            callback=callback,
            min_confidence=min_confidence,
            min_severity=min_severity,
        )
        self._subscriptions[subscription.subscription_id] = subscription
        return subscription.subscription_id

    def unsubscribe(self, subscription_id: str) -> bool:
        """Unsubscribe from predictions."""
        if subscription_id in self._subscriptions:
            del self._subscriptions[subscription_id]
            return True
        return False

    # Event handlers
    def _on_awareness_updated(self, event: Event) -> None:
        """Handle runtime awareness updates."""
        # Could trigger immediate predictions for critical changes
        pass

    def _on_analysis_completed(self, event: Event) -> None:
        """Handle self-analysis completion."""
        # Could use analysis results for predictions
        pass

    def _on_health_changed(self, event: Event) -> None:
        """Handle health check changes."""
        pass

    def _on_component_event(self, event: Event) -> None:
        """Handle component registration events."""
        pass

    def _on_activity_event(self, event: Event) -> None:
        """Handle activity events."""
        pass

    # Public API
    def get_latest_predictions(self, limit: int = 10) -> List[PredictionResult]:
        """Get most recent predictions."""
        with self._lock:
            return self._prediction_history[-limit:]

    def get_predictions_by_type(self, pred_type: PredictionType) -> List[PredictionResult]:
        """Get predictions filtered by type."""
        with self._lock:
            return [p for p in self._prediction_history if p.prediction_type == pred_type]

    def get_active_predictions(self) -> List[PredictionResult]:
        """Get currently valid (non-expired) predictions."""
        with self._lock:
            return [p for p in self._prediction_history if p.is_valid()]

    def get_prediction_history(self, limit: int = 50) -> List[PredictionResult]:
        """Get prediction history."""
        with self._lock:
            return self._prediction_history[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        """Get service statistics."""
        with self._lock:
            active = sum(1 for p in self._prediction_history if p.is_valid())
            by_type = {}
            for p in self._prediction_history:
                by_type[p.prediction_type.value] = by_type.get(p.prediction_type.value, 0) + 1

            return {
                "running": self._running,
                "total_predictions": len(self._prediction_history),
                "active_predictions": active,
                "predictions_by_type": by_type,
                "registered_models": len(self._models),
                "active_subscriptions": len([s for s in self._subscriptions.values() if s.active]),
                "pending_validations": len(self._pending_validations),
                "config": {
                    "update_interval_seconds": self._config.update_interval_seconds,
                    "enabled_types": [t.value for t in self._config.enabled_prediction_types],
                    "default_horizons": [h.value for h in self._config.default_horizons],
                }
            }

    def get_summary(self) -> Dict[str, Any]:
        """Get human-readable summary."""
        stats = self.get_stats()
        active_predictions = self.get_active_predictions()

        # Group by severity
        by_severity = {}
        for p in active_predictions:
            by_severity[p.severity.value] = by_severity.get(p.severity.value, 0) + 1

        return {
            "status": "running" if self._running else "stopped",
            "total_predictions": stats["total_predictions"],
            "active_predictions": stats["active_predictions"],
            "by_severity": by_severity,
            "by_type": stats["predictions_by_type"],
            "models_available": stats["registered_models"],
            "subscriptions": stats["active_subscriptions"],
        }

    async def run_diagnostics(self) -> List[PredictionResult]:
        """
        Run diagnostic predictions asynchronously.

        This is a convenience wrapper around run_predictions() for use
        in async contexts (e.g., background jobs).

        Returns:
            List of generated predictions
        """
        # Run predictions synchronously but in async context
        return self.run_predictions()


# Global instance
_predictive_diagnostics: Optional[PredictiveDiagnostics] = None
_diagnostics_lock = threading.Lock()


def get_predictive_diagnostics(
    runtime_awareness: Optional[RuntimeAwareness] = None,
    self_analysis: Optional[CentralizedSelfAnalysis] = None,
    config: Optional[PredictiveDiagnosticsConfig] = None,
) -> PredictiveDiagnostics:
    """Get or create the global predictive diagnostics instance."""
    global _predictive_diagnostics
    with _diagnostics_lock:
        if _predictive_diagnostics is None:
            _predictive_diagnostics = PredictiveDiagnostics(
                runtime_awareness=runtime_awareness,
                self_analysis=self_analysis,
                config=config,
            )
        return _predictive_diagnostics


def set_predictive_diagnostics(diagnostics: PredictiveDiagnostics) -> None:
    """Set the global predictive diagnostics instance."""
    global _predictive_diagnostics
    with _diagnostics_lock:
        _predictive_diagnostics = diagnostics