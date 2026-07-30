"""Evaluation Package - Self-Evaluation for Freya.

This package provides Freya's self-evaluation capabilities:
- EvaluationManager: Main entry point for running evaluations
- EvaluationPipeline: Orchestrates verification and validation
- RequirementVerifier: Verifies completed work against requirements
- ValidationRunner: Runs functional validation (tests, build, lint)
- EvaluationHistory: Persistent storage of evaluation results
- Data models for evaluation results, requirements, validations, confidence

Usage:
    from app.evaluation import EvaluationManager, evaluate_before_delivery

    manager = EvaluationManager(agent=freya_agent)
    result = manager.evaluate_task_completion(
        task_description="Implemented user authentication",
        original_request="Add user login and registration",
    )

    if result.should_deliver:
        print("Work is ready to deliver")
    elif result.requires_rework:
        print(f"Rework needed: {result.rework_reasons}")
"""

from app.evaluation.models import (
    EvaluationType,
    EvaluationStatus,
    EvaluationTrigger,
    VerificationStatus,
    ValidationStatus,
    ConfidenceLevel,
    Requirement,
    RequirementVerification,
    ValidationCheck,
    ValidationResult,
    EvaluationConfig,
    EvaluationResult,
)

from app.evaluation.pipeline import (
    EvaluationPipeline,
    RequirementVerifier,
    ValidationRunner,
)

from app.evaluation.manager import (
    EvaluationManager,
    EvaluationRecord,
    EvaluationHistory,
    get_evaluation_manager,
    evaluate_before_delivery,
)

__all__ = [
    # Models
    "EvaluationType",
    "EvaluationStatus",
    "EvaluationTrigger",
    "VerificationStatus",
    "ValidationStatus",
    "ConfidenceLevel",
    "Requirement",
    "RequirementVerification",
    "ValidationCheck",
    "ValidationResult",
    "EvaluationConfig",
    "EvaluationResult",
    # Pipeline
    "EvaluationPipeline",
    "RequirementVerifier",
    "ValidationRunner",
    # Manager
    "EvaluationManager",
    "EvaluationRecord",
    "EvaluationHistory",
    "get_evaluation_manager",
    "evaluate_before_delivery",
]