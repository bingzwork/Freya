"""
Safe Self-Improvement Module

Provides production-safe autonomous modification capabilities for Freya:
- File allowlists/denylists for controlling modification scope
- Safe modification boundaries
- Risk-based execution with RiskAnalyzer integration
- Human approval gates with DecisionManager integration
- Improvement prioritization
- Rollback checkpoints with automatic rollback on failure
- Safe patch promotion
- Safe self-improvement policies
"""

from app.safe_self_improvement.allowlist import AllowlistEntry, DenylistEntry, AllowlistManager
from app.safe_self_improvement.boundaries import ModificationBoundary, BoundaryManager
from app.safe_self_improvement.risk_execution import RiskBasedExecutor, ExecutionRiskAssessment
from app.safe_self_improvement.approval_gates import ApprovalGateManager, ApprovalDecision
from app.safe_self_improvement.prioritization import ImprovementPrioritizer, PrioritizationCriteria
from app.safe_self_improvement.rollback import RollbackManager, RollbackCheckpoint, RollbackAction
from app.safe_self_improvement.promotion import PatchPromotionManager, PromotionResult, PromotionStage
from app.safe_self_improvement.promotion_contract import (
    PromotionRequest,
    PromotionProvenance,
    PromotionValidation,
    RollbackEvidence,
    VerificationEvidence,
)
from app.safe_self_improvement.policies import SelfImprovementPolicy, PolicyEngine
from app.safe_self_improvement.self_improvement import SafeSelfImprovementEngine, create_self_improvement_engine
from app.safe_self_improvement.canary import CanaryDecision, CanaryEvidence, CanaryValidator
from app.safe_self_improvement.measurement import (
    MetricDirection,
    ComparisonStatus,
    MetricMeasurement,
    MetricComparison,
    ImprovementEvidence,
    ImprovementMeasurement,
    measure_improvement,
)
from app.safe_self_improvement.models import (
    SafeSelfImprovementConfig,
    ImprovementCandidate,
    FileModification,
    ModificationType,
    ImprovementCategory,
    RiskLevel,
    ApprovalRequest,
    ApprovalStatus,
    ExecutionResult,
    RollbackCheckpoint,
    RollbackReason,
)

__all__ = [
    # Allowlist/Denylist
    "AllowlistEntry",
    "DenylistEntry",
    "AllowlistManager",
    # Boundaries
    "ModificationBoundary",
    "BoundaryManager",
    # Risk-based execution
    "RiskBasedExecutor",
    "ExecutionRiskAssessment",
    # Approval gates
    "ApprovalGateManager",
    "ApprovalDecision",
    # Prioritization
    "ImprovementPrioritizer",
    "PrioritizationCriteria",
    # Rollback
    "RollbackManager",
    "RollbackCheckpoint",
    "RollbackAction",
    # Promotion
    "PatchPromotionManager",
    "PromotionResult",
    "PromotionStage",
    "PromotionRequest",
    "PromotionProvenance",
    "PromotionValidation",
    "RollbackEvidence",
    "VerificationEvidence",
    # Policies
    "SelfImprovementPolicy",
    "PolicyEngine",
    # Main engine
    "SafeSelfImprovementEngine",
    "create_self_improvement_engine",
    # Config
    "SafeSelfImprovementConfig",
    # Models
    "ImprovementCandidate",
    "FileModification",
    "ModificationType",
    "ImprovementCategory",
    "RiskLevel",
    "ApprovalRequest",
    "ApprovalStatus",
    "ExecutionResult",
    "RollbackCheckpoint",
    "RollbackReason",
    # Controlled canary validation
    "CanaryDecision",
    "CanaryEvidence",
    "CanaryValidator",
    # Before/after evidence
    "MetricDirection",
    "ComparisonStatus",
    "MetricMeasurement",
    "MetricComparison",
    "ImprovementEvidence",
    "ImprovementMeasurement",
    "measure_improvement",
]