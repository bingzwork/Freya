"""Self Observation Package - Runtime Awareness, Self-Analysis, and Predictive Diagnostics."""

from .models import (
    DecisionPipelineStage,
    AnalysisCategory,
    AwarenessComponent,
    ConfidenceLevel,
    DecisionPipelineContext,
    AnalysisResult,
    SelfAnalysisReport,
    RuntimeAwarenessState,
    DecisionPipelineResult,
)

from .runtime_awareness import (
    RuntimeAwareness,
    AwarenessConfig,
    get_runtime_awareness,
    set_runtime_awareness,
)

from .self_analysis import (
    CentralizedSelfAnalysis,
    AnalysisConfig,
    get_self_analysis,
    set_self_analysis,
)

from .decision_pipeline import (
    UnifiedRuntimeDecisionPipeline,
    get_unified_pipeline,
    set_unified_pipeline,
)

from .predictive_models import (
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
    get_confidence_threshold,
    confidence_from_score,
    severity_from_probability_and_impact,
    ResourceForecastingModel,
    create_resource_forecasting_model,
)

from .predictive_diagnostics import (
    PredictiveDiagnostics,
    get_predictive_diagnostics,
    set_predictive_diagnostics,
)

__all__ = [
    # Models
    "DecisionPipelineStage",
    "AnalysisCategory",
    "AwarenessComponent",
    "ConfidenceLevel",
    "DecisionPipelineContext",
    "AnalysisResult",
    "SelfAnalysisReport",
    "RuntimeAwarenessState",
    "DecisionPipelineResult",

    # Runtime Awareness
    "RuntimeAwareness",
    "AwarenessConfig",
    "get_runtime_awareness",
    "set_runtime_awareness",

    # Self-Analysis
    "CentralizedSelfAnalysis",
    "AnalysisConfig",
    "get_self_analysis",
    "set_self_analysis",

    # Decision Pipeline
    "UnifiedRuntimeDecisionPipeline",
    "get_unified_pipeline",
    "set_unified_pipeline",

    # Predictive Diagnostics Models
    "PredictionType",
    "PredictionHorizon",
    "PredictionConfidence",
    "PredictionStatus",
    "PredictionSeverity",
    "PredictionInput",
    "PredictionResult",
    "PredictionModel",
    "PredictionEngine",
    "PredictionSubscription",
    "PredictiveDiagnosticsConfig",
    "get_horizon_duration",
    "get_confidence_threshold",
    "confidence_from_score",
    "severity_from_probability_and_impact",
    "ResourceForecastingModel",
    "create_resource_forecasting_model",

    # Predictive Diagnostics Service
    "PredictiveDiagnostics",
    "get_predictive_diagnostics",
    "set_predictive_diagnostics",
]