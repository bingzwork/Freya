"""
Learning Package for Freya's Self-Learning Pipeline.

Public exports for the learning subsystem.
"""

from .pipeline import LearningPipeline, create_learning_pipeline
from .models import (
    LearningCandidate,
    LearningCandidateType,
    LearningPipelineResult,
    ObservedData,
    EvaluationResult,
    ExtractedLearning,
    ValidationResult,
    WorthRememberingResult,
    WorthRememberingDecision,
    PipelineStage,
)

__all__ = [
    # Main pipeline class
    "LearningPipeline",
    "create_learning_pipeline",

    # Data models
    "LearningCandidate",
    "LearningCandidateType",
    "LearningPipelineResult",
    "ObservedData",
    "EvaluationResult",
    "ExtractedLearning",
    "ValidationResult",
    "WorthRememberingResult",
    "WorthRememberingDecision",
    "PipelineStage",
]