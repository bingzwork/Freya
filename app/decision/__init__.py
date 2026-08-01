"""Decision Management Package.

This package provides the unified decision-making system for Freya,
including the Decision Manager, Decision Workflow, and Decision History.

Phase 2+ Enhancements:
- Adaptive Decision Revision - Monitor outcomes during execution, re-evaluate when context changes
- Learning From Decisions - Analyze successful vs failed decisions, update confidence models
- Decision Visualization - Decision tree/graph export, timeline view
- Meta-Decision Learning - Learn when to trust/subvert own confidence estimates
- Human Oversight Enhancement - Interactive approval UI, review history, override APIs
"""

from app.decision.models import (
    DecisionCategory,
    DecisionType,
    DecisionContext,
    DecisionOption,
    DecisionResult,
    DecisionRecord,
    DecisionManagerConfig,
)

from app.confidence.confidence_model import (
    DecisionConfidence,
    ActionConfidence,
    RecommendationConfidence,
)
from app.confidence.confidence_scoring import ConfidenceLevel

from app.decision.manager import (
    DecisionManager,
    decide_tool_selection,
    decide_context_sufficiency,
    decide_recovery_action,
    decide_plan_approach,
    decide_replanning_strategy,
    decide_planning_strategy,
    get_default_manager,
)

from app.decision.workflow import DecisionWorkflow, WorkflowStep

from app.decision.history import DecisionHistory

# Phase 2+ Enhancements
from app.decision.adaptive_revision import (
    AdaptiveDecisionRevision,
    ContextChange,
    ContextChangeType,
    RevisionTrigger,
    RevisionResult,
    create_adaptive_revision,
)

from app.decision.learning import (
    LearningFromDecisions,
    DecisionPattern,
    LearningInsight,
    ConfidenceCalibration,
    create_learning_from_decisions,
)

from app.decision.visualization import (
    DecisionVisualization,
    VisualizationNode,
    VisualizationEdge,
    DecisionTimelineEvent,
    create_visualization,
)

from app.decision.meta_learning import (
    MetaDecisionLearning,
    MetaConfidenceRule,
    BiasProfile,
    MetaDecisionEvent,
    create_meta_decision_learning,
)

from app.decision.human_oversight import (
    HumanOversightManager,
    ApprovalRequest,
    ApprovalRule,
    ApprovalStatus,
    ApprovalPriority,
    create_human_oversight_manager,
)

__all__ = [
    # Core models
    "DecisionCategory",
    "DecisionType",
    "DecisionContext",
    "DecisionOption",
    "DecisionResult",
    "DecisionRecord",
    "DecisionManagerConfig",
    # Confidence scoring
    "DecisionConfidence",
    "ActionConfidence",
    "RecommendationConfidence",
    "ConfidenceLevel",
    # Core components
    "DecisionManager",
    "DecisionWorkflow",
    "WorkflowStep",
    "DecisionHistory",
    # Convenience functions
    "decide_tool_selection",
    "decide_context_sufficiency",
    "decide_recovery_action",
    "decide_plan_approach",
    "decide_replanning_strategy",
    "decide_planning_strategy",
    "get_default_manager",
    # Phase 2+ Enhancements
    "AdaptiveDecisionRevision",
    "ContextChange",
    "ContextChangeType",
    "RevisionTrigger",
    "RevisionResult",
    "create_adaptive_revision",
    "LearningFromDecisions",
    "DecisionPattern",
    "LearningInsight",
    "ConfidenceCalibration",
    "create_learning_from_decisions",
    "DecisionVisualization",
    "VisualizationNode",
    "VisualizationEdge",
    "DecisionTimelineEvent",
    "create_visualization",
    "MetaDecisionLearning",
    "MetaConfidenceRule",
    "BiasProfile",
    "MetaDecisionEvent",
    "create_meta_decision_learning",
    "HumanOversightManager",
    "ApprovalRequest",
    "ApprovalRule",
    "ApprovalStatus",
    "ApprovalPriority",
    "create_human_oversight_manager",
]