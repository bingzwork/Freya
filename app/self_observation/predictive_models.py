"""Predictive Diagnostics Data Models.

Provides unified data structures for:
- Prediction interfaces and base classes
- Prediction data models (types, horizons, confidence)
- Prediction result objects
- Integration with Runtime Awareness and Self-Analysis
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Callable, Awaitable
from uuid import uuid4


class PredictionType(Enum):
    """Types of predictions supported by the framework."""
    RESOURCE_EXHAUSTION = "resource_exhaustion"       # CPU, memory, disk, network depletion
    PERFORMANCE_DEGRADATION = "performance_degradation"  # Slowing response times, throughput drops
    FAILURE_PROBABILITY = "failure_probability"       # Likelihood of component/system failure
    CAPACITY_BREACH = "capacity_breach"               # Exceeding capacity thresholds
    TREND_ANOMALY = "trend_anomaly"                   # Unexpected trend deviations
    GOAL_STALL = "goal_stall"                         # Goals likely to stall
    RECOVERY_NEEDED = "recovery_needed"               # Recovery likely needed soon
    LEARNING_PLATEAU = "learning_plateau"             # Learning progress plateauing
    DECISION_QUALITY_DROP = "decision_quality_drop"   # Decision quality degrading
    CUSTOM = "custom"                                 # User-defined prediction type


class PredictionHorizon(Enum):
    """Time horizons for predictions."""
    IMMEDIATE = "immediate"           # < 1 minute
    SHORT_TERM = "short_term"         # 1 minute - 1 hour
    MEDIUM_TERM = "medium_term"       # 1 hour - 24 hours
    LONG_TERM = "long_term"           # 1 day - 7 days
    EXTENDED = "extended"             # > 7 days


class PredictionConfidence(Enum):
    """Confidence levels for predictions."""
    VERY_HIGH = "very_high"    # 0.9 - 1.0
    HIGH = "high"              # 0.7 - 0.9
    MEDIUM = "medium"          # 0.5 - 0.7
    LOW = "low"                # 0.3 - 0.5
    VERY_LOW = "very_low"      # 0.0 - 0.3


class PredictionStatus(Enum):
    """Status of a prediction."""
    PENDING = "pending"           # Prediction requested, not yet computed
    COMPUTING = "computing"       # Currently being computed
    ACTIVE = "active"             # Valid prediction, within horizon
    EXPIRED = "expired"           # Horizon passed, prediction no longer valid
    INVALIDATED = "invalidated"   # New data contradicts prediction
    FULFILLED = "fulfilled"       # Predicted event occurred
    DISMISSED = "dismissed"       # Explicitly dismissed by user/system


class PredictionSeverity(Enum):
    """Severity of the predicted outcome."""
    INFO = "info"              # Informational, no immediate action needed
    WARNING = "warning"        # Attention needed, monitor closely
    CRITICAL = "critical"      # Action required soon
    URGENT = "urgent"          # Immediate action required


@dataclass
class PredictionInput:
    """Input data for making a prediction."""
    prediction_type: PredictionType
    horizon: PredictionHorizon
    source_data: Dict[str, Any] = field(default_factory=dict)  # Metrics, trends, context
    historical_context: List[Dict[str, Any]] = field(default_factory=list)  # Historical data points
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def get_metric_series(self, metric_name: str) -> List[float]:
        """Extract a time series for a specific metric from historical context."""
        return [
            point.get(metric_name, 0.0)
            for point in self.historical_context
            if metric_name in point
        ]

    def get_latest_value(self, metric_name: str) -> Optional[float]:
        """Get the latest value for a metric."""
        for point in reversed(self.historical_context):
            if metric_name in point:
                return point[metric_name]
        return self.source_data.get(metric_name)


@dataclass
class PredictionResult:
    """Result of a prediction computation."""
    prediction_id: str = field(default_factory=lambda: f"pred_{uuid4().hex[:8]}")
    prediction_type: PredictionType = PredictionType.CUSTOM
    horizon: PredictionHorizon = PredictionHorizon.SHORT_TERM

    # Core prediction
    predicted_value: Optional[float] = None
    predicted_state: Optional[str] = None
    probability: float = 0.0  # 0.0 - 1.0

    # Confidence and metadata
    confidence: PredictionConfidence = PredictionConfidence.MEDIUM
    confidence_score: float = 0.5  # 0.0 - 1.0
    severity: PredictionSeverity = PredictionSeverity.INFO

    # Timing
    prediction_time: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    horizon_start: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    horizon_end: Optional[str] = None  # Computed from horizon
    status: PredictionStatus = PredictionStatus.ACTIVE

    # Supporting data
    evidence: List[str] = field(default_factory=list)  # Human-readable evidence
    contributing_factors: Dict[str, float] = field(default_factory=dict)  # Factor -> weight
    trend_data: Dict[str, Any] = field(default_factory=dict)  # Relevant trend information
    model_info: Dict[str, Any] = field(default_factory=dict)  # Model metadata (name, version, etc.)

    # Recommendations
    recommended_actions: List[str] = field(default_factory=list)
    mitigation_strategies: List[str] = field(default_factory=list)

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Compute horizon_end if not provided."""
        if self.horizon_end is None:
            from datetime import timedelta
            start = datetime.fromisoformat(self.horizon_start.replace('Z', '+00:00'))
            horizon_durations = {
                PredictionHorizon.IMMEDIATE: timedelta(minutes=1),
                PredictionHorizon.SHORT_TERM: timedelta(hours=1),
                PredictionHorizon.MEDIUM_TERM: timedelta(hours=24),
                PredictionHorizon.LONG_TERM: timedelta(days=7),
                PredictionHorizon.EXTENDED: timedelta(days=30),
            }
            duration = horizon_durations.get(self.horizon, timedelta(hours=1))
            self.horizon_end = (start + duration).isoformat()

    def is_expired(self) -> bool:
        """Check if prediction has expired."""
        if self.horizon_end:
            end = datetime.fromisoformat(self.horizon_end.replace('Z', '+00:00'))
            return datetime.now(timezone.utc) > end
        return False

    def is_valid(self) -> bool:
        """Check if prediction is still valid (active and not expired)."""
        return self.status == PredictionStatus.ACTIVE and not self.is_expired()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "prediction_id": self.prediction_id,
            "prediction_type": self.prediction_type.value,
            "horizon": self.horizon.value,
            "predicted_value": self.predicted_value,
            "predicted_state": self.predicted_state,
            "probability": self.probability,
            "confidence": self.confidence.value,
            "confidence_score": self.confidence_score,
            "severity": self.severity.value,
            "prediction_time": self.prediction_time,
            "horizon_start": self.horizon_start,
            "horizon_end": self.horizon_end,
            "status": self.status.value,
            "evidence": self.evidence,
            "contributing_factors": self.contributing_factors,
            "trend_data": self.trend_data,
            "model_info": self.model_info,
            "recommended_actions": self.recommended_actions,
            "mitigation_strategies": self.mitigation_strategies,
            "metadata": self.metadata,
        }


@dataclass
class PredictionModel:
    """Base class for prediction models/strategies."""

    name: str
    version: str = "1.0.0"
    supported_types: List[PredictionType] = field(default_factory=lambda: list(PredictionType))
    supported_horizons: List[PredictionHorizon] = field(default_factory=lambda: list(PredictionHorizon))

    # Model metadata
    description: str = ""
    author: str = ""
    tags: List[str] = field(default_factory=list)

    # Performance tracking
    total_predictions: int = 0
    accurate_predictions: int = 0
    accuracy: float = 0.0

    def can_predict(self, prediction_type: PredictionType, horizon: PredictionHorizon) -> bool:
        """Check if this model can handle the given type and horizon."""
        return prediction_type in self.supported_types and horizon in self.supported_horizons

    def predict(self, input_data: PredictionInput) -> PredictionResult:
        """Make a prediction. Override in subclasses."""
        raise NotImplementedError("Subclasses must implement predict()")

    def record_accuracy(self, was_accurate: bool) -> None:
        """Record prediction accuracy for model evaluation."""
        self.total_predictions += 1
        if was_accurate:
            self.accurate_predictions += 1
        self.accuracy = self.accurate_predictions / self.total_predictions if self.total_predictions > 0 else 0.0


class PredictionEngine:
    """Interface for the prediction engine that orchestrates models."""

    def register_model(self, model: PredictionModel) -> None:
        """Register a prediction model."""
        raise NotImplementedError

    def unregister_model(self, model_name: str) -> bool:
        """Unregister a prediction model by name."""
        raise NotImplementedError

    def predict(self, input_data: PredictionInput) -> PredictionResult:
        """Make a prediction using the best available model."""
        raise NotImplementedError

    def predict_batch(self, inputs: List[PredictionInput]) -> List[PredictionResult]:
        """Make multiple predictions."""
        raise NotImplementedError

    def get_model(self, name: str) -> Optional[PredictionModel]:
        """Get a registered model by name."""
        raise NotImplementedError

    def list_models(self) -> List[PredictionModel]:
        """List all registered models."""
        raise NotImplementedError


@dataclass
class PredictionSubscription:
    """Subscription to predictions of a specific type/horizon."""
    subscription_id: str = field(default_factory=lambda: f"sub_{uuid4().hex[:8]}")
    prediction_types: List[PredictionType] = field(default_factory=list)
    horizons: List[PredictionHorizon] = field(default_factory=list)
    callback: Optional[Callable[[PredictionResult], Awaitable[None]]] = None
    min_confidence: PredictionConfidence = PredictionConfidence.LOW
    min_severity: PredictionSeverity = PredictionSeverity.INFO
    active: bool = True
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PredictiveDiagnosticsConfig:
    """Configuration for the Predictive Diagnostics service."""
    enabled: bool = True
    update_interval_seconds: float = 60.0  # How often to run predictions
    min_data_points: int = 10  # Minimum historical data points needed
    default_horizons: List[PredictionHorizon] = field(default_factory=lambda: [
        PredictionHorizon.SHORT_TERM,
        PredictionHorizon.MEDIUM_TERM,
    ])
    enabled_prediction_types: List[PredictionType] = field(default_factory=lambda: [
        PredictionType.RESOURCE_EXHAUSTION,
        PredictionType.PERFORMANCE_DEGRADATION,
        PredictionType.FAILURE_PROBABILITY,
        PredictionType.GOAL_STALL,
    ])
    confidence_threshold: float = 0.5  # Minimum confidence to emit predictions
    severity_threshold: PredictionSeverity = PredictionSeverity.WARNING
    max_history: int = 100  # Max predictions to keep in history
    trend_window_seconds: float = 3600.0  # Time window for trend analysis
    auto_validate_predictions: bool = True  # Automatically validate predictions against outcomes


# Horizon duration mapping
HORIZON_DURATIONS = {
    PredictionHorizon.IMMEDIATE: 60,           # 1 minute
    PredictionHorizon.SHORT_TERM: 3600,        # 1 hour
    PredictionHorizon.MEDIUM_TERM: 86400,      # 24 hours
    PredictionHorizon.LONG_TERM: 604800,       # 7 days
    PredictionHorizon.EXTENDED: 2592000,       # 30 days
}

# Confidence threshold mapping
CONFIDENCE_THRESHOLDS = {
    PredictionConfidence.VERY_HIGH: 0.9,
    PredictionConfidence.HIGH: 0.7,
    PredictionConfidence.MEDIUM: 0.5,
    PredictionConfidence.LOW: 0.3,
    PredictionConfidence.VERY_LOW: 0.0,
}


def get_horizon_duration(horizon: PredictionHorizon) -> int:
    """Get duration in seconds for a prediction horizon."""
    return HORIZON_DURATIONS.get(horizon, 3600)


def get_confidence_threshold(confidence: PredictionConfidence) -> float:
    """Get numeric threshold for a confidence level."""
    return CONFIDENCE_THRESHOLDS.get(confidence, 0.5)


def confidence_from_score(score: float) -> PredictionConfidence:
    """Convert numeric confidence score to confidence level."""
    if score >= 0.9:
        return PredictionConfidence.VERY_HIGH
    elif score >= 0.7:
        return PredictionConfidence.HIGH
    elif score >= 0.5:
        return PredictionConfidence.MEDIUM
    elif score >= 0.3:
        return PredictionConfidence.LOW
    else:
        return PredictionConfidence.VERY_LOW


def severity_from_probability_and_impact(probability: float, impact: float) -> PredictionSeverity:
    """Determine severity from probability and impact scores (both 0.0-1.0)."""
    risk_score = probability * impact
    if risk_score >= 0.7:
        return PredictionSeverity.URGENT
    elif risk_score >= 0.5:
        return PredictionSeverity.CRITICAL
    elif risk_score >= 0.3:
        return PredictionSeverity.WARNING
    else:
        return PredictionSeverity.INFO


class ResourceForecastingModel(PredictionModel):
    """
    Lightweight resource forecasting model using linear trend extrapolation.

    Forecasts resource usage (CPU, RAM, GPU, VRAM, Disk, Network) based on
    historical monitoring data from ObservabilityHub and RuntimeAwareness.

    Does NOT use ML - uses simple linear regression on time-series data.
    Supports configurable prediction windows and confidence intervals.
    """

    def __init__(
        self,
        name: str = "resource_forecasting",
        version: str = "1.0.0",
        min_data_points: int = 5,
        default_window_seconds: float = 3600.0,
        confidence_interval_std: float = 1.5,  # Standard deviations for confidence band
    ):
        super().__init__(
            name=name,
            version=version,
            supported_types=[PredictionType.RESOURCE_EXHAUSTION, PredictionType.CAPACITY_BREACH],
            supported_horizons=list(PredictionHorizon),
        )
        self.description = "Lightweight resource forecasting via linear trend extrapolation"
        self.author = "Freya Self-Observation"
        self.tags = ["resource", "forecasting", "linear", "lightweight"]

        self._min_data_points = min_data_points
        self._default_window_seconds = default_window_seconds
        self._confidence_interval_std = confidence_interval_std

        # Resource capacity limits (for exhaustion probability calculation)
        self._capacity_limits = {
            "cpu_percent": 100.0,
            "memory_percent": 100.0,
            "disk_percent": 100.0,
            "gpu_utilization_percent": 100.0,
            "gpu_memory_percent": 100.0,
            "network_mbps": 1000.0,  # Assumed 1Gbps, normalized
        }

    def can_predict(self, prediction_type: PredictionType, horizon: PredictionHorizon) -> bool:
        """Check if this model can handle the given type and horizon."""
        return (
            prediction_type in self.supported_types
            and horizon in self.supported_horizons
        )

    def predict(self, input_data: PredictionInput) -> PredictionResult:
        """Make a resource forecast prediction."""
        source_data = input_data.source_data
        historical_context = input_data.historical_context
        horizon = input_data.horizon

        # Get horizon duration in seconds
        horizon_seconds = get_horizon_duration(horizon)

        # Extract metric series from historical context
        metric_series = self._extract_metric_series(historical_context, source_data)

        if not metric_series:
            return self._create_insufficient_data_result(input_data)

        # Forecast each metric
        forecasts = {}
        confidences = {}
        evidence = []
        contributing_factors = {}

        for metric_name, values in metric_series.items():
            if len(values) < self._min_data_points:
                continue

            forecast = self._forecast_linear(values, horizon_seconds)
            if forecast:
                forecasts[metric_name] = forecast
                confidences[metric_name] = forecast["confidence"]
                evidence.append(
                    f"{metric_name}: current={forecast['current']:.1f}, "
                    f"predicted={forecast['predicted']:.1f} "
                    f"(trend: {forecast['trend']}, slope: {forecast['slope']:.4f})"
                )
                contributing_factors[f"{metric_name}_trend"] = abs(forecast["slope"])

        if not forecasts:
            return self._create_insufficient_data_result(input_data)

        # Determine overall prediction
        overall_result = self._determine_overall_prediction(
            forecasts, horizon, horizon_seconds, source_data
        )

        # Build prediction result
        result = PredictionResult(
            prediction_type=input_data.prediction_type,
            horizon=horizon,
            predicted_value=overall_result["predicted_value"],
            predicted_state=overall_result["predicted_state"],
            probability=overall_result["probability"],
            confidence=overall_result["confidence"],
            confidence_score=overall_result["confidence_score"],
            severity=overall_result["severity"],
            evidence=evidence,
            contributing_factors=contributing_factors,
            trend_data={k: v for k, v in forecasts.items()},
            model_info={
                "model": self.name,
                "version": self.version,
                "method": "linear_trend_extrapolation",
                "horizon_seconds": horizon_seconds,
                "data_points_used": {k: len(v) for k, v in metric_series.items() if k in forecasts},
                "forecasts": {k: {
                    "current": v["current"],
                    "predicted": v["predicted"],
                    "trend": v["trend"],
                    "slope": v["slope"],
                    "confidence": v["confidence"],
                    "horizon_end": v["horizon_end"],
                } for k, v in forecasts.items()},
            },
            recommended_actions=overall_result["recommended_actions"],
            mitigation_strategies=overall_result["mitigation_strategies"],
            metadata={
                "forecast_timestamp": datetime.now(timezone.utc).isoformat(),
                "horizon_start": datetime.now(timezone.utc).isoformat(),
                "horizon_end": (datetime.now(timezone.utc) + timedelta(seconds=horizon_seconds)).isoformat(),
            }
        )

        return result

    def _extract_metric_series(
        self,
        historical_context: List[Dict[str, Any]],
        source_data: Dict[str, Any],
    ) -> Dict[str, List[float]]:
        """Extract time series for each resource metric from historical data."""
        metric_series = {}

        # Define metrics we can forecast with their source keys
        metric_mappings = {
            "cpu_percent": ["cpu_usage", "cpu_percent"],
            "memory_percent": ["memory_usage_mb", "memory_percent", "system.memory.percent"],
            "disk_percent": ["disk_io_mb_s", "system.disk.percent"],
            "network_mbps": ["network_io_mb_s", "system.network.sent_mb_s", "system.network.recv_mb_s"],
        }

        # Percentage metrics where 0.0 likely means "unavailable" not "0% utilized"
        # Only skip 0.0 for specific SOURCE KEYS where 0% is unrealistic
        # cpu_usage (from RuntimeAwareness) CAN be 0% (idle system) - don't skip
        skip_zero_for_keys = {
            "memory_percent",   # Process using 0% memory = unavailable
            "system.memory.percent",
            "disk_percent",     # Disk at 0% = unavailable
            "system.disk.percent",
        }

        # Add GPU metrics if available in source data
        if "gpu_metrics" in source_data:
            for idx, gpu in enumerate(source_data["gpu_metrics"]):
                metric_mappings[f"gpu_{idx}_utilization_percent"] = [f"gpu_{idx}_utilization"]
                metric_mappings[f"gpu_{idx}_memory_percent"] = [f"gpu_{idx}_memory_percent"]
                skip_zero_for_keys.add(f"gpu_{idx}_memory_percent")
                # GPU utilization CAN be 0% (idle GPU) - don't skip

        # Extract from historical context
        for point in historical_context:
            for metric_name, source_keys in metric_mappings.items():
                for key in source_keys:
                    if key in point:
                        value = point[key]
                        # Convert memory_mb to percent if needed
                        if metric_name == "memory_percent" and key == "memory_usage_mb":
                            # Need total memory to convert - skip if not available
                            continue
                        if metric_name == "disk_percent" and key == "disk_io_mb_s":
                            # IO rate not the same as usage percent - skip
                            continue
                        fval = float(value)
                        # Skip percentage metrics with 0.0 ONLY for specific keys where 0% is unrealistic
                        if key in skip_zero_for_keys and fval == 0.0:
                            continue
                        if metric_name not in metric_series:
                            metric_series[metric_name] = []
                        metric_series[metric_name].append(fval)
                        break

        # Add current values from source_data as latest points
        for metric_name, source_keys in metric_mappings.items():
            for key in source_keys:
                if key in source_data:
                    value = source_data[key]
                    fval = float(value)
                    # Skip percentage metrics with 0.0 ONLY for specific keys where 0% is unrealistic
                    if key in skip_zero_for_keys and fval == 0.0:
                        continue
                    if metric_name not in metric_series:
                        metric_series[metric_name] = []
                    if metric_series[metric_name] and metric_series[metric_name][-1] == fval:
                        # Don't duplicate if same value
                        pass
                    else:
                        metric_series[metric_name].append(fval)
                    break

        # Filter out metrics with too few points (need at least 2 for linear regression)
        # Constant-value series are VALID - they represent stable system behavior
        # and _forecast_linear handles them correctly (producing stable forecast with low confidence)
        filtered_series = {}
        for metric_name, values in metric_series.items():
            if len(values) < 2:
                continue
            filtered_series[metric_name] = values

        return filtered_series

    def _forecast_linear(
        self,
        values: List[float],
        horizon_seconds: float,
    ) -> Optional[Dict[str, Any]]:
        """
        Forecast using simple linear regression on time-series data.

        Assumes values are equally spaced in time.
        Returns forecast with prediction, trend, slope, and confidence.
        """
        n = len(values)
        if n < 2:
            return None

        # Time indices (0, 1, 2, ...)
        t = list(range(n))
        t_mean = sum(t) / n
        v_mean = sum(values) / n

        # Linear regression: slope and intercept
        numerator = sum((t[i] - t_mean) * (values[i] - v_mean) for i in range(n))
        denominator = sum((t[i] - t_mean) ** 2 for i in range(n))

        if denominator == 0:
            slope = 0.0
        else:
            slope = numerator / denominator

        intercept = v_mean - slope * t_mean

        # Predict next point (t = n)
        # Need to convert horizon_seconds to time steps
        # Assume data points are collected at regular intervals
        # Use default window to estimate interval
        interval_seconds = self._default_window_seconds / max(n, 1) if n > 0 else 60.0
        steps_ahead = max(1, int(horizon_seconds / interval_seconds))
        t_future = n + steps_ahead
        predicted = intercept + slope * t_future

        # Current value
        current = values[-1]

        # Determine trend
        if abs(slope) < 0.001:
            trend = "stable"
        elif slope > 0:
            trend = "increasing"
        else:
            trend = "decreasing"

        # Calculate confidence based on R-squared and data points
        # R-squared = 1 - SS_res / SS_tot
        ss_tot = sum((v - v_mean) ** 2 for v in values)
        ss_res = sum((values[i] - (intercept + slope * t[i])) ** 2 for i in range(n))
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

        # Confidence increases with more data points and higher R-squared
        data_confidence = min(1.0, n / 20.0)  # Max at 20 points
        fit_confidence = max(0.0, r_squared)
        combined_confidence = (data_confidence + fit_confidence) / 2.0

        # Prediction interval (standard error)
        if n > 2:
            mse = ss_res / (n - 2)
            se = (mse * (1 + 1/n + (t_future - t_mean)**2 / denominator)) ** 0.5
            margin = self._confidence_interval_std * se
            lower_bound = predicted - margin
            upper_bound = predicted + margin
        else:
            lower_bound = predicted * 0.5
            upper_bound = predicted * 1.5

        # Horizon end timestamp
        horizon_end = datetime.now(timezone.utc) + timedelta(seconds=horizon_seconds)

        return {
            "current": current,
            "predicted": max(0.0, predicted),  # No negative values
            "trend": trend,
            "slope": slope,
            "confidence": combined_confidence,
            "r_squared": r_squared,
            "data_points": n,
            "lower_bound": max(0.0, lower_bound),
            "upper_bound": upper_bound,
            "horizon_end": horizon_end.isoformat(),
            "steps_ahead": steps_ahead,
        }

    def _determine_overall_prediction(
        self,
        forecasts: Dict[str, Dict[str, Any]],
        horizon: PredictionHorizon,
        horizon_seconds: float,
        source_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Determine overall resource exhaustion prediction from individual forecasts."""
        # Check each forecasted metric against capacity
        exhaustion_risk = 0.0
        max_predicted_percent = 0.0
        critical_metrics = []

        for metric_name, forecast in forecasts.items():
            predicted = forecast["predicted"]
            confidence = forecast["confidence"]

            # Get capacity limit
            limit = self._capacity_limits.get(metric_name, 100.0)

            # Calculate predicted utilization as percentage of capacity
            predicted_percent = (predicted / limit) * 100.0 if limit > 0 else 0.0
            max_predicted_percent = max(max_predicted_percent, predicted_percent)

            # Risk increases as predicted approaches capacity
            if predicted_percent >= 95.0:
                exhaustion_risk = max(exhaustion_risk, 0.9 * confidence)
                critical_metrics.append(f"{metric_name} predicted at {predicted_percent:.1f}%")
            elif predicted_percent >= 85.0:
                exhaustion_risk = max(exhaustion_risk, 0.7 * confidence)
                critical_metrics.append(f"{metric_name} predicted at {predicted_percent:.1f}%")
            elif predicted_percent >= 70.0:
                exhaustion_risk = max(exhaustion_risk, 0.4 * confidence)

        # Overall predicted value (max utilization percentage)
        overall_predicted = max_predicted_percent

        # Determine predicted state
        if overall_predicted >= 95.0:
            predicted_state = "exhaustion_imminent"
        elif overall_predicted >= 85.0:
            predicted_state = "high_risk"
        elif overall_predicted >= 70.0:
            predicted_state = "elevated_risk"
        else:
            predicted_state = "normal"

        # Probability of exhaustion
        probability = min(1.0, exhaustion_risk)

        # Confidence - average of individual confidences weighted by risk
        confidences = [f["confidence"] for f in forecasts.values()]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.5
        confidence_score = avg_confidence * (1.0 if critical_metrics else 0.8)
        confidence = confidence_from_score(confidence_score)

        # Severity
        severity = severity_from_probability_and_impact(probability, 0.9)

        # Recommended actions
        recommended_actions = []
        mitigation_strategies = []

        if critical_metrics:
            recommended_actions.append("Monitor resource usage closely")
            recommended_actions.append("Consider scaling or offloading workloads")
            for metric in critical_metrics:
                if "cpu" in metric.lower():
                    recommended_actions.append("Reduce CPU-intensive tasks or add compute resources")
                    mitigation_strategies.append("Throttle non-critical background jobs")
                elif "memory" in metric.lower():
                    recommended_actions.append("Free memory or add RAM")
                    mitigation_strategies.append("Clear caches, reduce batch sizes")
                elif "gpu" in metric.lower():
                    recommended_actions.append("Reduce GPU workloads or add GPU resources")
                    mitigation_strategies.append("Offload inference to CPU, reduce batch sizes")
                elif "disk" in metric.lower():
                    recommended_actions.append("Free disk space or add storage")
                    mitigation_strategies.append("Clean temp files, rotate logs, compress data")
                elif "network" in metric.lower():
                    recommended_actions.append("Optimize network usage or increase bandwidth")
                    mitigation_strategies.append("Batch requests, enable compression")
        else:
            recommended_actions.append("Continue monitoring - no immediate action needed")
            mitigation_strategies.append("Maintain current resource management")

        return {
            "predicted_value": overall_predicted,
            "predicted_state": predicted_state,
            "probability": probability,
            "confidence": confidence,
            "confidence_score": confidence_score,
            "severity": severity,
            "recommended_actions": recommended_actions,
            "mitigation_strategies": mitigation_strategies,
        }

    def _create_insufficient_data_result(self, input_data: PredictionInput) -> PredictionResult:
        """Create result indicating insufficient data for forecasting."""
        return PredictionResult(
            prediction_type=input_data.prediction_type,
            horizon=input_data.horizon,
            predicted_value=None,
            predicted_state="insufficient_data",
            probability=0.0,
            confidence=PredictionConfidence.VERY_LOW,
            confidence_score=0.1,
            severity=PredictionSeverity.INFO,
            evidence=[f"Insufficient historical data (need {self._min_data_points}+ points)"],
            contributing_factors={},
            trend_data={},
            model_info={
                "model": self.name,
                "version": self.version,
                "note": "Not enough historical data points for reliable forecasting",
                "min_data_points": self._min_data_points,
                "available_points": {
                    k: len(v) for k, v in self._extract_metric_series(
                        input_data.historical_context, input_data.source_data
                    ).items()
                },
            },
            recommended_actions=["Collect more monitoring data before forecasting"],
            mitigation_strategies=[],
            metadata={"is_placeholder": True},
        )


def create_resource_forecasting_model(**kwargs) -> ResourceForecastingModel:
    """Factory function to create a ResourceForecastingModel."""
    return ResourceForecastingModel(**kwargs)


class PerformanceDegradationModel(PredictionModel):
    """
    Performance degradation prediction model using trend analysis and queue theory.

    Forecasts performance degradation including:
    - Slow response times (increasing latency)
    - Queue growth (task backlog accumulation)
    - Scheduler overload (worker saturation)
    - Execution bottlenecks (resource contention)
    - Throughput degradation (declining completion rates)
    - Task backlog growth (pending work accumulation)

    Uses linear trend extrapolation on time-series data from RuntimeAwareness,
    BackgroundJobService, and ObservabilityHub metrics.
    """

    def __init__(
        self,
        name: str = "performance_degradation",
        version: str = "1.0.0",
        min_data_points: int = 5,
        default_window_seconds: float = 3600.0,
        confidence_interval_std: float = 1.5,
        # Thresholds for degradation detection
        latency_degradation_threshold: float = 2.0,  # 2x baseline
        queue_growth_threshold: float = 1.5,         # 50% growth
        scheduler_utilization_threshold: float = 0.85,  # 85% worker utilization
        throughput_drop_threshold: float = 0.3,      # 30% drop
        backlog_growth_threshold: float = 2.0,       # 2x baseline
    ):
        super().__init__(
            name=name,
            version=version,
            supported_types=[PredictionType.PERFORMANCE_DEGRADATION, PredictionType.TREND_ANOMALY],
            supported_horizons=list(PredictionHorizon),
        )
        self.description = "Performance degradation forecasting via trend analysis and queue theory"
        self.author = "Freya Self-Observation"
        self.tags = ["performance", "degradation", "latency", "queue", "throughput", "lightweight"]

        self._min_data_points = min_data_points
        self._default_window_seconds = default_window_seconds
        self._confidence_interval_std = confidence_interval_std

        # Degradation thresholds
        self._latency_degradation_threshold = latency_degradation_threshold
        self._queue_growth_threshold = queue_growth_threshold
        self._scheduler_utilization_threshold = scheduler_utilization_threshold
        self._throughput_drop_threshold = throughput_drop_threshold
        self._backlog_growth_threshold = backlog_growth_threshold

        # Baseline tracking for relative degradation
        self._baselines: Dict[str, float] = {}

    def can_predict(self, prediction_type: PredictionType, horizon: PredictionHorizon) -> bool:
        """Check if this model can handle the given type and horizon."""
        return (
            prediction_type in self.supported_types
            and horizon in self.supported_horizons
        )

    def predict(self, input_data: PredictionInput) -> PredictionResult:
        """Make a performance degradation prediction."""
        source_data = input_data.source_data
        historical_context = input_data.historical_context
        horizon = input_data.horizon

        # Get horizon duration in seconds
        horizon_seconds = get_horizon_duration(horizon)

        # Extract performance metric series from historical context
        metric_series = self._extract_performance_metrics(historical_context, source_data)

        if not metric_series:
            return self._create_insufficient_data_result(input_data)

        # Forecast each performance metric
        forecasts = {}
        confidences = {}
        evidence = []
        contributing_factors = {}
        degradation_signals = []

        for metric_name, values in metric_series.items():
            if len(values) < self._min_data_points:
                continue

            forecast = self._forecast_linear(values, horizon_seconds)
            if forecast:
                forecasts[metric_name] = forecast
                confidences[metric_name] = forecast["confidence"]
                evidence.append(
                    f"{metric_name}: current={forecast['current']:.2f}, "
                    f"predicted={forecast['predicted']:.2f} "
                    f"(trend: {forecast['trend']}, slope: {forecast['slope']:.4f})"
                )
                contributing_factors[f"{metric_name}_trend"] = abs(forecast["slope"])

                # Check for degradation signals
                if self._is_degradation_signal(metric_name, forecast):
                    degradation_signals.append({
                        "metric": metric_name,
                        "current": forecast["current"],
                        "predicted": forecast["predicted"],
                        "threshold_exceeded": self._get_threshold(metric_name),
                        "severity": self._assess_signal_severity(metric_name, forecast),
                    })

        if not forecasts:
            return self._create_insufficient_data_result(input_data)

        # Determine overall degradation prediction
        overall_result = self._determine_overall_degradation(
            forecasts, degradation_signals, horizon, horizon_seconds, source_data
        )

        # Build prediction result
        result = PredictionResult(
            prediction_type=input_data.prediction_type,
            horizon=horizon,
            predicted_value=overall_result["predicted_value"],
            predicted_state=overall_result["predicted_state"],
            probability=overall_result["probability"],
            confidence=overall_result["confidence"],
            confidence_score=overall_result["confidence_score"],
            severity=overall_result["severity"],
            evidence=evidence,
            contributing_factors=contributing_factors,
            trend_data={k: v for k, v in forecasts.items()},
            model_info={
                "model": self.name,
                "version": self.version,
                "method": "linear_trend_extrapolation_with_queue_analysis",
                "horizon_seconds": horizon_seconds,
                "data_points_used": {k: len(v) for k, v in metric_series.items() if k in forecasts},
                "forecasts": {k: {
                    "current": v["current"],
                    "predicted": v["predicted"],
                    "trend": v["trend"],
                    "slope": v["slope"],
                    "confidence": v["confidence"],
                    "horizon_end": v["horizon_end"],
                } for k, v in forecasts.items()},
                "degradation_signals": degradation_signals,
            },
            recommended_actions=overall_result["recommended_actions"],
            mitigation_strategies=overall_result["mitigation_strategies"],
            metadata={
                "forecast_timestamp": datetime.now(timezone.utc).isoformat(),
                "horizon_start": datetime.now(timezone.utc).isoformat(),
                "horizon_end": (datetime.now(timezone.utc) + timedelta(seconds=horizon_seconds)).isoformat(),
                "degradation_categories": overall_result.get("degradation_categories", []),
            }
        )

        return result

    def _extract_performance_metrics(
        self,
        historical_context: List[Dict[str, Any]],
        source_data: Dict[str, Any],
    ) -> Dict[str, List[float]]:
        """Extract time series for performance degradation metrics."""
        metric_series = {}

        # Define performance metrics we can forecast with their source keys
        metric_mappings = {
            # Latency metrics
            "task_avg_latency_ms": ["task_avg_latency_ms", "avg_latency_ms", "avg_task_duration"],
            "workflow_avg_latency_ms": ["workflow_avg_latency_ms", "avg_workflow_duration"],
            "tool_avg_latency_ms": ["tool_avg_latency_ms", "avg_tool_duration"],

            # Queue/backlog metrics
            "pending_tasks": ["pending_tasks", "queued_tasks", "waiting_tasks", "task_queue_size"],
            "pending_workflows": ["pending_workflows", "queued_workflows", "workflow_queue_size"],
            "background_job_queue": ["background_jobs", "job_queue_size", "scheduled_jobs_pending"],

            # Scheduler/throughput metrics
            "tasks_completed_per_min": ["tasks_completed_per_min", "throughput_tasks_per_min", "completion_rate"],
            "workflows_completed_per_min": ["workflows_completed_per_min", "throughput_workflows_per_min"],
            "scheduler_utilization": ["scheduler_utilization", "worker_utilization", "worker_usage_percent"],
            "active_workers": ["active_workers", "running_workers", "worker_count"],
            "max_workers": ["max_workers", "worker_capacity"],

            # Resource contention (execution bottlenecks)
            "cpu_contention": ["cpu_usage", "cpu_percent", "system.cpu.percent"],
            "memory_pressure": ["memory_usage_mb", "memory_percent", "system.memory.percent"],
            "disk_io_wait": ["disk_io_mb_s", "system.disk.read_mb_s", "system.disk.write_mb_s"],
            "gpu_utilization": ["gpu_utilization_percent", "gpu_usage"],

            # Error/retry metrics (indirect degradation indicators)
            "task_failure_rate": ["task_failure_rate", "failure_rate", "error_rate"],
            "task_retry_rate": ["task_retry_rate", "retry_rate"],
            "avg_retry_count": ["avg_retry_count", "retries_per_task"],
        }

        # Metrics where 0.0 likely means "unavailable" not "zero"
        # For percentages: 0% utilization is valid but rare; 0% usually means unavailable
        # For counts: 0 is valid (empty queue)
        # Only skip 0.0 for specific SOURCE KEYS where 0% is unrealistic
        skip_zero_for_keys = {
            "memory_percent",   # Process using 0% memory = unavailable
            "system.memory.percent",  # System memory 0% = unavailable
            "cpu_percent",      # cpu_percent key from other sources might mean unavailable
            "system.cpu.percent",
            # Note: cpu_usage (from RuntimeAwareness) CAN be 0% (idle system) - don't skip
            # Note: gpu_usage, gpu_utilization_percent CAN be 0% (idle GPU) - don't skip
            # Note: worker_utilization, worker_usage_percent CAN be 0% (idle workers) - don't skip
        }

        # Extract from historical context
        for point in historical_context:
            for metric_name, source_keys in metric_mappings.items():
                for key in source_keys:
                    if key in point:
                        value = point[key]
                        fval = float(value)
                        # Skip percentage metrics with 0.0 ONLY for specific keys where 0% is unrealistic
                        if key in skip_zero_for_keys and fval == 0.0:
                            continue
                        if metric_name not in metric_series:
                            metric_series[metric_name] = []
                        metric_series[metric_name].append(fval)
                        break

        # Add current values from source_data as latest points
        for metric_name, source_keys in metric_mappings.items():
            for key in source_keys:
                if key in source_data:
                    value = source_data[key]
                    fval = float(value)
                    # Skip percentage metrics with 0.0 ONLY for specific keys where 0% is unrealistic
                    if key in skip_zero_for_keys and fval == 0.0:
                        continue
                    if metric_name not in metric_series:
                        metric_series[metric_name] = []
                    if metric_series[metric_name] and metric_series[metric_name][-1] == fval:
                        pass  # Don't duplicate if same value
                    else:
                        metric_series[metric_name].append(fval)
                    break

        # Compute derived metrics from available data
        self._compute_derived_metrics(metric_series, source_data)

        # Filter out metrics with too few points (need at least 2 for linear regression)
        # Constant-value series are VALID - they represent stable system behavior
        # and _forecast_linear handles them correctly (producing stable forecast with low confidence)
        filtered_series = {}
        for metric_name, values in metric_series.items():
            if len(values) < 2:
                continue
            filtered_series[metric_name] = values

        return filtered_series

    def _compute_derived_metrics(
        self,
        metric_series: Dict[str, List[float]],
        source_data: Dict[str, Any],
    ) -> None:
        """Compute derived performance metrics from available base metrics."""
        # Scheduler utilization = active_workers / max_workers
        if "active_workers" in metric_series and "max_workers" in metric_series:
            if len(metric_series["active_workers"]) > 0 and len(metric_series["max_workers"]) > 0:
                active = metric_series["active_workers"][-1]
                max_w = metric_series["max_workers"][-1]
                if max_w > 0:
                    if "scheduler_utilization" not in metric_series:
                        metric_series["scheduler_utilization"] = []
                    metric_series["scheduler_utilization"].append(active / max_w)

        # Queue growth rate (if we have pending tasks history)
        if "pending_tasks" in metric_series and len(metric_series["pending_tasks"]) >= 2:
            if "queue_growth_rate" not in metric_series:
                metric_series["queue_growth_rate"] = []
            current = metric_series["pending_tasks"][-1]
            previous = metric_series["pending_tasks"][-2]
            if previous > 0:
                metric_series["queue_growth_rate"].append(current / previous)
            else:
                metric_series["queue_growth_rate"].append(1.0)

        # Throughput trend (completion rate)
        if "tasks_completed_per_min" in metric_series and len(metric_series["tasks_completed_per_min"]) >= 2:
            if "throughput_trend" not in metric_series:
                metric_series["throughput_trend"] = []
            current = metric_series["tasks_completed_per_min"][-1]
            previous = metric_series["tasks_completed_per_min"][-2]
            if previous > 0:
                metric_series["throughput_trend"].append(current / previous)
            else:
                metric_series["throughput_trend"].append(1.0)

    def _forecast_linear(
        self,
        values: List[float],
        horizon_seconds: float,
    ) -> Optional[Dict[str, Any]]:
        """Forecast using simple linear regression on time-series data."""
        n = len(values)
        if n < 2:
            return None

        # Time indices (0, 1, 2, ...)
        t = list(range(n))
        t_mean = sum(t) / n
        v_mean = sum(values) / n

        # Linear regression: slope and intercept
        numerator = sum((t[i] - t_mean) * (values[i] - v_mean) for i in range(n))
        denominator = sum((t[i] - t_mean) ** 2 for i in range(n))

        if denominator == 0:
            slope = 0.0
        else:
            slope = numerator / denominator

        intercept = v_mean - slope * t_mean

        # Predict next point
        # Estimate time interval between data points
        interval_seconds = self._default_window_seconds / max(n, 1) if n > 0 else 60.0
        steps_ahead = max(1, int(horizon_seconds / interval_seconds))
        t_future = n + steps_ahead
        predicted = intercept + slope * t_future

        # Current value
        current = values[-1]

        # Determine trend
        if abs(slope) < 0.001:
            trend = "stable"
        elif slope > 0:
            trend = "increasing"
        else:
            trend = "decreasing"

        # Calculate confidence based on R-squared and data points
        ss_tot = sum((v - v_mean) ** 2 for v in values)
        ss_res = sum((values[i] - (intercept + slope * t[i])) ** 2 for i in range(n))
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

        data_confidence = min(1.0, n / 20.0)
        fit_confidence = max(0.0, r_squared)
        combined_confidence = (data_confidence + fit_confidence) / 2.0

        # Prediction interval
        if n > 2:
            mse = ss_res / (n - 2)
            se = (mse * (1 + 1/n + (t_future - t_mean)**2 / denominator)) ** 0.5
            margin = self._confidence_interval_std * se
            lower_bound = predicted - margin
            upper_bound = predicted + margin
        else:
            lower_bound = predicted * 0.5
            upper_bound = predicted * 1.5

        # Horizon end timestamp
        horizon_end = datetime.now(timezone.utc) + timedelta(seconds=horizon_seconds)

        return {
            "current": current,
            "predicted": max(0.0, predicted),
            "trend": trend,
            "slope": slope,
            "confidence": combined_confidence,
            "r_squared": r_squared,
            "data_points": n,
            "lower_bound": max(0.0, lower_bound),
            "upper_bound": upper_bound,
            "horizon_end": horizon_end.isoformat(),
            "steps_ahead": steps_ahead,
        }

    def _is_degradation_signal(self, metric_name: str, forecast: Dict[str, Any]) -> bool:
        """Check if a forecast indicates performance degradation."""
        current = forecast["current"]
        predicted = forecast["predicted"]
        trend = forecast["trend"]
        # Relative degradation ratios are undefined for a zero or invalid
        # baseline; skip the signal rather than leaking an exception.
        try:
            current_value = float(current)
            predicted_value = float(predicted)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(current_value) or not math.isfinite(predicted_value) or current_value <= 0:
            return False
        current = current_value
        predicted = predicted_value

        threshold = self._get_threshold(metric_name)
        if threshold is None:
            return False

        metric_lower = metric_name.lower()

        # Special handling for utilization metrics (absolute threshold)
        if "scheduler_utilization" in metric_lower or "worker_utilization" in metric_lower:
            return predicted >= threshold

        # For throughput metrics - degradation is DECREASING trend
        if "throughput" in metric_lower and "trend" in metric_lower:
            if trend != "decreasing":
                return False
            if current > 0:
                ratio = predicted / current  # ratio < 1 means degradation
                # Threshold is e.g., 1/0.7 = 1.43 for 30% drop
                # We want ratio < (1 - drop_threshold) i.e., predicted/current < 0.7
                # So ratio should be <= 1/threshold
                return ratio <= (1.0 / threshold)
            return False

        # For other metrics - degradation is INCREASING trend
        if trend != "increasing":
            return False

        # For ratio-based thresholds
        if current > 0:
            ratio = predicted / current
            return ratio >= threshold

        return False

    def _get_threshold(self, metric_name: str) -> Optional[float]:
        """Get degradation threshold for a metric."""
        metric_lower = metric_name.lower()

        # Latency metrics - check for 2x increase
        if any(k in metric_lower for k in ["avg_latency", "latency_ms", "avg_duration"]):
            return self._latency_degradation_threshold

        # Queue/backlog metrics - check for 50% growth
        if any(k in metric_lower for k in ["pending", "queue", "backlog", "waiting"]):
            return self._queue_growth_threshold

        # Scheduler utilization - check for 85% threshold (absolute)
        if "scheduler_utilization" in metric_lower or "worker_utilization" in metric_lower:
            return self._scheduler_utilization_threshold  # Absolute threshold, not ratio

        # Queue growth rate
        if "queue_growth_rate" in metric_lower:
            return self._queue_growth_threshold

        # Throughput trend - check for 30% drop (ratio < 0.7)
        if "throughput" in metric_lower and "trend" in metric_lower:
            return 1.0 / (1.0 - self._throughput_drop_threshold)

        # Bottleneck/resource contention metrics - check for 2x increase
        if any(k in metric_lower for k in ["cpu_contention", "memory_pressure", "disk_io", "gpu_utilization",
                                             "cpu_usage", "memory_percent", "disk_percent", "gpu_memory"]):
            return self._backlog_growth_threshold  # Use backlog threshold for resource metrics

        # Reliability metrics
        if any(k in metric_lower for k in ["failure_rate", "retry_rate", "error_rate", "retries"]):
            return 2.0

        return None

    def _assess_signal_severity(self, metric_name: str, forecast: Dict[str, Any]) -> str:
        """Assess severity of a degradation signal."""
        current = forecast["current"]
        predicted = forecast["predicted"]
        # A zero, negative, NaN, or infinite baseline cannot support a
        # meaningful relative-severity ratio. Treat it as unknown rather than
        # allowing a background diagnostic failure to escape.
        try:
            current_value = float(current)
            predicted_value = float(predicted)
        except (TypeError, ValueError):
            return "unknown"
        if not math.isfinite(current_value) or not math.isfinite(predicted_value) or current_value <= 0:
            return "unknown"
        current = current_value
        predicted = predicted_value

        ratio = predicted / current
        threshold = self._get_threshold(metric_name) or 1.5

        if ratio >= threshold * 2.0:
            return "critical"
        elif ratio >= threshold * 1.5:
            return "high"
        elif ratio >= threshold:
            return "medium"
        else:
            return "low"

    def _determine_overall_degradation(
        self,
        forecasts: Dict[str, Dict[str, Any]],
        degradation_signals: List[Dict[str, Any]],
        horizon: PredictionHorizon,
        horizon_seconds: float,
        source_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Determine overall performance degradation prediction."""
        # Categorize degradation signals
        degradation_categories = []
        critical_signals = []
        high_signals = []
        medium_signals = []
        low_signals = []

        for signal in degradation_signals:
            cat = self._categorize_metric(signal["metric"])
            if cat not in degradation_categories:
                degradation_categories.append(cat)

            if signal["severity"] == "critical":
                critical_signals.append(signal)
            elif signal["severity"] == "high":
                high_signals.append(signal)
            elif signal["severity"] == "medium":
                medium_signals.append(signal)
            else:
                low_signals.append(signal)

        # Calculate overall probability
        probability = 0.0
        if critical_signals:
            probability = max(probability, 0.9)
        if high_signals:
            probability = max(probability, 0.7)
        if medium_signals:
            probability = max(probability, 0.5)
        if low_signals:
            probability = max(probability, 0.3)

        # Weight by confidence of forecasts
        confidences = [f["confidence"] for f in forecasts.values()]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.5
        probability *= avg_confidence

        # Predicted value: degradation score (0-100)
        # 0 = no degradation, 100 = severe degradation
        predicted_value = min(100.0, probability * 100)

        # Determine predicted state
        if critical_signals:
            predicted_state = "severe_degradation_imminent"
        elif high_signals:
            predicted_state = "high_degradation_risk"
        elif medium_signals:
            predicted_state = "moderate_degradation_risk"
        elif low_signals:
            predicted_state = "early_degradation_signs"
        else:
            predicted_state = "stable"

        # Confidence
        confidence_score = avg_confidence * (1.0 if degradation_signals else 0.7)
        confidence = confidence_from_score(confidence_score)

        # Severity
        severity = severity_from_probability_and_impact(probability, 0.8)

        # Recommended actions
        recommended_actions = []
        mitigation_strategies = []

        if critical_signals:
            recommended_actions.append("URGENT: Performance degradation imminent - immediate action required")
            recommended_actions.append("Scale compute resources or offload workloads")
            mitigation_strategies.extend([
                "Enable aggressive task prioritization",
                "Throttle non-critical background jobs",
                "Increase worker pool size if possible",
                "Consider load shedding for low-priority tasks",
            ])
        elif high_signals:
            recommended_actions.append("High risk of performance degradation detected")
            recommended_actions.append("Monitor queue depths and latency closely")
            mitigation_strategies.extend([
                "Pre-scale workers for anticipated load",
                "Optimize slow-running tasks",
                "Review and tune batch sizes",
            ])
        elif medium_signals:
            recommended_actions.append("Moderate degradation risk - investigate trends")
            mitigation_strategies.extend([
                "Review resource allocation",
                "Check for resource contention",
                "Monitor scheduler utilization",
            ])
        elif low_signals:
            recommended_actions.append("Early degradation signals - preventive monitoring")
            mitigation_strategies.extend([
                "Establish performance baselines",
                "Set up automated alerts for key metrics",
            ])
        else:
            recommended_actions.append("Performance stable - continue monitoring")
            mitigation_strategies.append("Maintain current observability practices")

        # Add category-specific recommendations
        for cat in degradation_categories:
            if cat == "latency":
                recommended_actions.append("Investigate increasing task/workflow latency")
                mitigation_strategies.append("Profile slow operations, check for blocking calls")
            elif cat == "queue":
                recommended_actions.append("Task/workflow queues growing - risk of backlog")
                mitigation_strategies.append("Increase worker throughput, consider horizontal scaling")
            elif cat == "scheduler":
                recommended_actions.append("Scheduler approaching capacity - worker saturation")
                mitigation_strategies.append("Scale worker pool, optimize task scheduling")
            elif cat == "throughput":
                recommended_actions.append("Throughput declining - completion rate dropping")
                mitigation_strategies.append("Identify bottlenecks, check for resource contention")
            elif cat == "bottleneck":
                recommended_actions.append("Resource contention detected - execution bottlenecks")
                mitigation_strategies.append("Analyze resource usage, optimize critical paths")
            elif cat == "reliability":
                recommended_actions.append("Rising failure/retry rates - reliability degrading")
                mitigation_strategies.append("Investigate root cause of failures, improve error handling")

        return {
            "predicted_value": predicted_value,
            "predicted_state": predicted_state,
            "probability": probability,
            "confidence": confidence,
            "confidence_score": confidence_score,
            "severity": severity,
            "recommended_actions": recommended_actions,
            "mitigation_strategies": mitigation_strategies,
            "degradation_categories": degradation_categories,
        }

    def _categorize_metric(self, metric_name: str) -> str:
        """Categorize a metric into a degradation category."""
        latency_metrics = ["avg_latency", "latency"]
        queue_metrics = ["pending", "queue", "backlog", "waiting"]
        scheduler_metrics = ["scheduler_utilization", "worker_utilization", "active_workers", "worker_count"]
        throughput_metrics = ["throughput", "completed_per_min", "completion_rate"]
        bottleneck_metrics = ["cpu", "memory", "disk", "gpu", "contention", "pressure"]
        reliability_metrics = ["failure_rate", "retry_rate", "error_rate", "retries"]

        metric_lower = metric_name.lower()

        for m in latency_metrics:
            if m in metric_lower:
                return "latency"
        for m in queue_metrics:
            if m in metric_lower:
                return "queue"
        for m in scheduler_metrics:
            if m in metric_lower:
                return "scheduler"
        for m in throughput_metrics:
            if m in metric_lower:
                return "throughput"
        for m in bottleneck_metrics:
            if m in metric_lower:
                return "bottleneck"
        for m in reliability_metrics:
            if m in metric_lower:
                return "reliability"

        return "unknown"

    def _create_insufficient_data_result(self, input_data: PredictionInput) -> PredictionResult:
        """Create result indicating insufficient data for forecasting."""
        available = self._extract_performance_metrics(
            input_data.historical_context, input_data.source_data
        )
        return PredictionResult(
            prediction_type=input_data.prediction_type,
            horizon=input_data.horizon,
            predicted_value=None,
            predicted_state="insufficient_data",
            probability=0.0,
            confidence=PredictionConfidence.VERY_LOW,
            confidence_score=0.1,
            severity=PredictionSeverity.INFO,
            evidence=[f"Insufficient historical data (need {self._min_data_points}+ points per metric)"],
            contributing_factors={},
            trend_data={},
            model_info={
                "model": self.name,
                "version": self.version,
                "note": "Not enough historical data points for reliable performance forecasting",
                "min_data_points": self._min_data_points,
                "available_metrics": {k: len(v) for k, v in available.items()},
            },
            recommended_actions=["Collect more monitoring data before performance forecasting"],
            mitigation_strategies=[],
            metadata={"is_placeholder": True},
        )


def create_performance_degradation_model(**kwargs) -> PerformanceDegradationModel:
    """Factory function to create a PerformanceDegradationModel."""
    return PerformanceDegradationModel(**kwargs)