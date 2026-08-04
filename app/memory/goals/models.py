"""Goal data models and enums for Freya AI."""

import enum
import hashlib
import json
import math
import re
import statistics
import uuid
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Callable, Set


# ---------------------------------------------------------------------------
# Core Goal Model
# ---------------------------------------------------------------------------


@dataclass
class Goal:
    """A single goal entry.

    Attributes:
        id: Unique goal identifier.
        name: Short human-readable name.
        description: Longer description of the goal's intent.
        status: Lifecycle status (string-typed; standardized values land
            in a later phase).
        priority: Priority level (string-typed; standardized values land
            in a later phase).
        parent_goal_id: ID of this goal's parent, or None for top-level.
        child_goal_ids: IDs of this goal's children.
        depends_on_ids: IDs of goals that must ``status == "completed"``
            before this one becomes eligible for selection.
        created_at: ISO timestamp captured on creation (UTC).
        updated_at: ISO timestamp of the most recent write (UTC).
        metadata: Free-form dictionary for lifecycle side-channel data
            owned by the storage layer (Phase 7: ``previous_status`` /
            ``pause_reason`` / ``stall_reason`` / ``recommend_reason``).
            Backwards compatible — pre-Phase-7 ``goals.json`` files
            load with an empty ``{}`` default.
    """

    id: str
    name: str
    description: str = ""
    status: str = "pending"
    priority: str = "medium"
    parent_goal_id: Optional[str] = None
    child_goal_ids: List[str] = field(default_factory=list)
    depends_on_ids: List[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert goal to dictionary for serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Goal":
        """Create goal from dictionary."""
        return cls(**data)


# ---------------------------------------------------------------------------
# Complexity Assessment
# ---------------------------------------------------------------------------


class ComplexityLevel(enum.Enum):
    """Goal complexity tiers for adaptive decomposition."""
    TRIVIAL = "trivial"      # single straightforward task, no decomposition needed
    SIMPLE = "simple"        # 1-2 subtasks, linear flow
    MODERATE = "moderate"    # 3-5 subtasks, some dependencies
    COMPLEX = "complex"      # 5-8 subtasks, significant dependency graph
    VERY_COMPLEX = "very_complex"  # 8+ subtasks, multi-level hierarchy


class TaskType(enum.Enum):
    """Classification of goal work type for estimation and strategy selection."""
    IMPLEMENTATION = "implementation"
    RESEARCH = "research"
    DEBUGGING = "debugging"
    DOCUMENTATION = "documentation"
    TESTING = "testing"
    REFACTORING = "refactoring"
    INTEGRATION = "integration"
    DEPLOYMENT = "deployment"
    MAINTENANCE = "maintenance"
    FEATURE = "feature"
    UNKNOWN = "unknown"


@dataclass
class GoalComplexity:
    """Assessed complexity of a goal used to drive decomposition decisions.

    Attributes:
        level: Enumerated complexity tier.
        score: Numeric 0.0-1.0 complexity score (0=trivial, 1=most complex).
        suggested_depth: How many hierarchy levels the decomposition should span.
        suggested_subtask_count: Recommended number of direct children.
        signals: Human-readable reasons for the assessment.
    """

    level: ComplexityLevel
    score: float
    suggested_depth: int
    suggested_subtask_count: int
    signals: List[str] = field(default_factory=list)

    def requires_decomposition(self) -> bool:
        """True when decomposition is recommended (moderate and above)."""
        return self.level not in (ComplexityLevel.TRIVIAL, ComplexityLevel.SIMPLE)


# ---------------------------------------------------------------------------
# Decomposition Strategies
# ---------------------------------------------------------------------------


@dataclass
class DecompositionStrategy:
    """A named, composable strategy for breaking down a goal.

    Strategies are registered callables that receive a parent Goal and
    return a list of SubtaskSuggestion objects. They can be chained,
    filtered, and weighted via the ``GoalDecomposer``.
    """

    name: str
    description: str
    applicable_types: List[TaskType]
    min_complexity: "ComplexityLevel"
    generator: Callable[["Goal", int], List["SubtaskSuggestion"]]


class DecompositionStrategyType(enum.Enum):
    """Types of decomposition strategies."""
    TEMPLATE = "template"              # Fixed phase-based decomposition
    SEMANTIC = "semantic"              # Keyword-based work item extraction
    HIERARCHICAL = "hierarchical"      # Multi-level recursive decomposition
    AGILE = "agile"                    # Sprint-oriented decomposition
    WATERFALL = "waterfall"            # Sequential phase decomposition
    HYBRID = "hybrid"                  # Adaptive combination


@dataclass
class EnhancedDecompositionStrategy:
    """Enhanced decomposition strategy with more configuration options."""

    name: str
    description: str
    strategy_type: DecompositionStrategyType
    applicable_types: List[TaskType]
    min_complexity: "ComplexityLevel"
    generator: Callable[["Goal", int, Optional[Dict[str, Any]]], List["SubtaskSuggestion"]]
    weight: float = 1.0
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Milestone:
    """A named checkpoint within a goal's decomposition hierarchy.

    Milestones are not Goals themselves — they are planning artifacts
    that live inside a goal's metadata. They provide intermediate
    progress targets within a decomposed goal.
    """

    id: str
    name: str
    description: str = ""
    order: int = 0
    subtask_ids: List[str] = field(default_factory=list)
    deadline_estimate: Optional[str] = None  # ISO datetime
    completed: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "order": self.order,
            "subtask_ids": list(self.subtask_ids),
            "deadline_estimate": self.deadline_estimate,
            "completed": self.completed,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Milestone":
        return cls(**data)


@dataclass
class HierarchicalDecompositionResult:
    """Result of a hierarchical decomposition operation.

    Contains the full decomposition tree with suggestions at each level,
    milestones, and metadata about the decomposition process.
    """
    root_goal_id: str
    suggestions: List["SubtaskSuggestion"]  # Level 1 suggestions
    child_decompositions: Dict[str, "HierarchicalDecompositionResult"] = field(default_factory=dict)  # Deeper levels
    milestones: List[Milestone] = field(default_factory=list)
    complexity_assessment: Optional["GoalComplexity"] = None
    strategy_used: str = ""
    total_estimated_hours: float = 0.0
    decomposition_depth: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)

    def flatten_suggestions(self) -> List["SubtaskSuggestion"]:
        """Flatten all suggestions from all levels into a single list."""
        result = list(self.suggestions)
        for child_decomp in self.child_decompositions.values():
            result.extend(child_decomp.flatten_suggestions())
        return result


@dataclass
class DecompositionFeedback:
    """Feedback on a decomposition for continuous improvement.

    Captures what worked, what didn't, and suggestions for improvement.
    """
    goal_id: str
    decomposition_cache_key: str
    rating: float  # 0.0-1.0
    successful_suggestions: List[str] = field(default_factory=list)  # Suggestion names that worked
    failed_suggestions: List[str] = field(default_factory=list)
    missing_work_items: List[str] = field(default_factory=list)
    notes: str = ""
    submitted_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "decomposition_cache_key": self.decomposition_cache_key,
            "rating": self.rating,
            "successful_suggestions": self.successful_suggestions,
            "failed_suggestions": self.failed_suggestions,
            "missing_work_items": self.missing_work_items,
            "notes": self.notes,
            "submitted_at": self.submitted_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DecompositionFeedback":
        return cls(**data)


# ---------------------------------------------------------------------------
# Duration Estimation
# ---------------------------------------------------------------------------


@dataclass
class DurationEstimate:
    """Intelligent duration estimation for a goal or subtask.

    Attributes:
        estimated_seconds: Best-estimate duration in seconds.
        min_seconds: Optimistic (fastest plausible) duration.
        max_seconds: Pessimistic (worst-case) duration.
        confidence: 0.0-1.0 confidence in the estimate.
        task_type: Classified type used to inform the estimate.
        complexity_score: Assessed complexity score that fed the estimate.
        source: How the estimate was derived (e.g. "complexity_model",
            "historical", "heuristic", "explicit").
        refinable: Whether the estimate can be updated by historical data.
        last_updated: ISO timestamp of last update.
        metadata: Free-form extra context.
    """

    estimated_seconds: float
    min_seconds: float = 0.0
    max_seconds: float = 0.0
    confidence: float = 0.5
    task_type: TaskType = TaskType.UNKNOWN
    complexity_score: float = 0.0
    source: str = "fallback"
    refinable: bool = True
    last_updated: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "estimated_seconds": self.estimated_seconds,
            "min_seconds": self.min_seconds,
            "max_seconds": self.max_seconds,
            "confidence": self.confidence,
            "task_type": self.task_type.value if self.task_type else None,
            "complexity_score": self.complexity_score,
            "source": self.source,
            "refinable": self.refinable,
            "last_updated": self.last_updated,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DurationEstimate":
        task_type = data.get("task_type")
        if isinstance(task_type, str):
            task_type = TaskType(task_type)
        return cls(
            estimated_seconds=data.get("estimated_seconds", 0.0),
            min_seconds=data.get("min_seconds", 0.0),
            max_seconds=data.get("max_seconds", 0.0),
            confidence=data.get("confidence", 0.5),
            task_type=task_type,
            complexity_score=data.get("complexity_score", 0.0),
            source=data.get("source", "fallback"),
            refinable=data.get("refinable", True),
            last_updated=data.get("last_updated", ""),
            metadata=data.get("metadata", {}),
        )

    def apply_historical_actual(self, actual_seconds: float) -> "DurationEstimate":
        """Refine estimate using an actual duration from historical data.

        Uses weighted averaging: 70% model + 30% actual on first update,
        then exponential smoothing on subsequent updates.  Confidence
        increases monotonically as data accumulates.
        """
        if not self.refinable:
            return self
        if self.metadata.get("update_count", 0) == 0:
            # First historical point: weighted average toward actual
            new_est = 0.7 * self.estimated_seconds + 0.3 * actual_seconds
            new_min = min(self.min_seconds or actual_seconds, actual_seconds * 0.8)
            new_max = max(self.max_seconds or actual_seconds, actual_seconds * 1.5)
        else:
            # Exponential moving average for subsequent updates
            alpha = 0.3
            new_est = (1 - alpha) * self.estimated_seconds + alpha * actual_seconds
            new_min = (1 - alpha) * (self.min_seconds or self.estimated_seconds) + alpha * actual_seconds * 0.8
            new_max = (1 - alpha) * (self.max_seconds or self.estimated_seconds) + alpha * actual_seconds * 1.5
        update_count = self.metadata.get("update_count", 0) + 1
        confidence = min(0.95, 0.5 + 0.1 * update_count)
        return DurationEstimate(
            estimated_seconds=round(new_est, 1),
            min_seconds=round(new_min, 1),
            max_seconds=round(new_max, 1),
            confidence=round(confidence, 3),
            task_type=self.task_type,
            complexity_score=self.complexity_score,
            source="historical",
            refinable=True,
            last_updated=datetime.now(timezone.utc).isoformat(),
            metadata={**self.metadata, "update_count": update_count},
        )


# ---------------------------------------------------------------------------
# Better Task Decomposition — Enhanced Classes
# ---------------------------------------------------------------------------


@dataclass
class DecompositionCacheEntry:
    """Cached decomposition result for deterministic reuse.

    The cache key is a hash of the goal's name, description, and relevant
    context. This ensures the same goal always produces the same decomposition
    unless the goal content changes.
    """
    goal_id: str
    cache_key: str
    suggestions: List["SubtaskSuggestion"]
    milestones: List[Milestone]
    complexity_level: "ComplexityLevel"
    created_at: str
    access_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "cache_key": self.cache_key,
            "suggestions": [
                {
                    "name": s.name,
                    "description": s.description,
                    "priority": s.priority,
                    "planner_category": s.planner_category,
                    "estimated_hours": s.estimated_hours,
                }
                for s in self.suggestions
            ],
            "milestones": [m.to_dict() for m in self.milestones],
            "complexity_level": self.complexity_level.value,
            "created_at": self.created_at,
            "access_count": self.access_count,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DecompositionCacheEntry":
        suggestions = [
            SubtaskSuggestion(
                name=s["name"],
                description=s["description"],
                priority=s["priority"],
                planner_category=s.get("planner_category"),
                estimated_hours=s.get("estimated_hours"),
            )
            for s in data.get("suggestions", [])
        ]
        milestones = [Milestone.from_dict(m) for m in data.get("milestones", [])]
        return cls(
            goal_id=data["goal_id"],
            cache_key=data["cache_key"],
            suggestions=suggestions,
            milestones=milestones,
            complexity_level=ComplexityLevel(data["complexity_level"]),
            created_at=data["created_at"],
            access_count=data.get("access_count", 0),
        )


@dataclass
class WorkItem:
    """A single logical work item extracted from a goal description.

    Work items represent atomic units of work that can be independently
    executed. They are derived from semantic analysis of the goal's
    name and description.
    """
    id: str
    title: str
    description: str
    category: str  # e.g., "research", "implement", "test", "document", "verify"
    dependencies: List[str] = field(default_factory=list)  # IDs of other work items
    estimated_effort: float = 1.0  # Relative effort (1.0 = baseline)
    signals: List[str] = field(default_factory=list)  # Why this item was identified


# ---------------------------------------------------------------------------
# Subtask Suggestion
# ---------------------------------------------------------------------------


@dataclass
class SubtaskSuggestion:
    """A draft child-goal proposal produced by ``GoalStorage.decompose_goal``.

    Suggestions are deliberately inert: they are returned to the caller by
    ``decompose_goal`` and only materialise as real ``Goal`` records when
    passed to ``apply_decomposition``. This is the manual-approval gate
    for Phase 6 — users can review, edit, or drop suggestions before they
    become persistent child goals.

    Attributes:
        name: Human-readable name for the proposed child goal.
        description: Longer description of the proposed child goal
            (default mirrors the decompose-template description, with the
            parent context appended on the first suggestion).
        priority: Inherited from the parent goal by default; callers may
            override per-suggestion before calling
            ``apply_decomposition``.
        planner_category: Optional planner ``TaskCategory`` (or any value
            accepted by ``PlanManager.add_task``) — when set and a
            ``plan_manager`` is supplied to ``apply_decomposition``, the
            parallel planner ``Task`` is created with this category.
        estimated_hours: Optional forwarded estimate for the parallel
            planner ``Task``; defaults to ``None`` (planner uses its own
            default).
    """

    name: str
    description: str = ""
    priority: str = "medium"
    planner_category: Optional[Any] = None
    estimated_hours: Optional[float] = None