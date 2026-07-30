"""Core data models for the Decision Management system.

Defines the fundamental types used throughout the decision workflow:
- DecisionCategory: High-level category of the decision
- DecisionType: Specific type within a category
- DecisionContext: Information available when making a decision
- DecisionOption: An available choice for the decision
- DecisionResult: Outcome of the decision process
- DecisionRecord: Persistent record of a decision and its outcome
- DecisionManagerConfig: Configuration for the Decision Manager
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union
import uuid


@dataclass
class DecisionManagerConfig:
    """Configuration for the Decision Manager."""

    # Confidence thresholds
    min_confidence_for_auto_execute: float = 0.7
    min_confidence_for_recommendation: float = 0.5

    # Risk thresholds
    max_risk_for_auto_execute: str = "medium"  # critical, high, medium, low, info
    require_approval_above_risk: str = "high"

    # Workflow settings
    max_options_to_evaluate: int = 10
    enable_explainable_decisions: bool = True
    enable_human_oversight: bool = True

    # Learning settings
    record_all_decisions: bool = True
    calibrate_confidence_from_outcomes: bool = True

    # Integration toggles
    use_confidence_scoring: bool = True
    use_risk_assessment: bool = True
    use_goal_scheduling: bool = True
    use_memory_retrieval: bool = True
    use_intent_classification: bool = True


class DecisionCategory(Enum):
    """High-level category of a decision.

    These categories map to the major decision points in Freya's operation.
    """

    EXECUTION = "execution"       # Should I execute this action? (edit file, run tool, etc.)
    INFORMATION = "information"   # Should I gather more info? (read file, search, retrieve memory)
    PLANNING = "planning"         # How should I plan? (break into subtasks, change strategy)
    RECOVERY = "recovery"         # How to recover from failure? (retry, alternative, pause, ask user)
    LEARNING = "learning"         # What should I learn/store? (lesson, experience, knowledge)

    @property
    def description(self) -> str:
        return {
            DecisionCategory.EXECUTION: "Action execution decisions - whether and how to perform an operation",
            DecisionCategory.INFORMATION: "Information gathering decisions - whether to retrieve more context",
            DecisionCategory.PLANNING: "Planning decisions - how to structure and decompose work",
            DecisionCategory.RECOVERY: "Recovery decisions - how to handle failures and setbacks",
            DecisionCategory.LEARNING: "Learning decisions - what to remember and how to improve",
        }[self]


class DecisionType(Enum):
    """Specific types of decisions within each category."""

    # Execution decisions
    TOOL_SELECTION = "tool_selection"       # Which tool to use
    FILE_MODIFICATION = "file_modification"  # Should I modify this file?
    COMMAND_EXECUTION = "command_execution"  # Should I run this command?
    TASK_CONTINUATION = "task_continuation"  # Should I continue the current task?
    PATCH_APPLICATION = "patch_application"  # Should I apply this patch?

    # Information decisions
    CONTEXT_SUFFICIENCY = "context_sufficiency"   # Do I have enough context?
    MEMORY_RETRIEVAL = "memory_retrieval"         # Should I retrieve from memory?
    FILE_READING = "file_reading"                 # Should I read this file?
    SEARCH_QUERY = "search_query"                 # Should I search for more info?

    # Planning decisions
    TASK_DECOMPOSITION = "task_decomposition"     # How to break down a task?
    STRATEGY_SELECTION = "strategy_selection"     # Which planning strategy?
    PRIORITY_ORDERING = "priority_ordering"       # What order to execute?
    RESOURCE_ALLOCATION = "resource_allocation"   # How to allocate resources?

    # Recovery decisions
    RETRY_WITH_ALTERNATIVE = "retry_with_alternative"  # Try a different approach?
    PAUSE_AND_ASK = "pause_and_ask"                    # Pause for user input?
    ABORT_TASK = "abort_task"                          # Give up on this task?
    ESCALATE = "escalate"                              # Escalate to human?

    # Learning decisions
    STORE_LESSON = "store_lesson"             # Store an engineering lesson?
    STORE_EXPERIENCE = "store_experience"     # Store an experience entry?
    CONSOLIDATE_MEMORY = "consolidate_memory" # Consolidate memories?
    UPDATE_CONFIDENCE = "update_confidence"   # Update confidence models?

    @property
    def category(self) -> DecisionCategory:
        mapping = {
            # Execution
            DecisionType.TOOL_SELECTION: DecisionCategory.EXECUTION,
            DecisionType.FILE_MODIFICATION: DecisionCategory.EXECUTION,
            DecisionType.COMMAND_EXECUTION: DecisionCategory.EXECUTION,
            DecisionType.TASK_CONTINUATION: DecisionCategory.EXECUTION,
            DecisionType.PATCH_APPLICATION: DecisionCategory.EXECUTION,
            # Information
            DecisionType.CONTEXT_SUFFICIENCY: DecisionCategory.INFORMATION,
            DecisionType.MEMORY_RETRIEVAL: DecisionCategory.INFORMATION,
            DecisionType.FILE_READING: DecisionCategory.INFORMATION,
            DecisionType.SEARCH_QUERY: DecisionCategory.INFORMATION,
            # Planning
            DecisionType.TASK_DECOMPOSITION: DecisionCategory.PLANNING,
            DecisionType.STRATEGY_SELECTION: DecisionCategory.PLANNING,
            DecisionType.PRIORITY_ORDERING: DecisionCategory.PLANNING,
            DecisionType.RESOURCE_ALLOCATION: DecisionCategory.PLANNING,
            # Recovery
            DecisionType.RETRY_WITH_ALTERNATIVE: DecisionCategory.RECOVERY,
            DecisionType.PAUSE_AND_ASK: DecisionCategory.RECOVERY,
            DecisionType.ABORT_TASK: DecisionCategory.RECOVERY,
            DecisionType.ESCALATE: DecisionCategory.RECOVERY,
            # Learning
            DecisionType.STORE_LESSON: DecisionCategory.LEARNING,
            DecisionType.STORE_EXPERIENCE: DecisionCategory.LEARNING,
            DecisionType.CONSOLIDATE_MEMORY: DecisionCategory.LEARNING,
            DecisionType.UPDATE_CONFIDENCE: DecisionCategory.LEARNING,
        }
        return mapping.get(self, DecisionCategory.EXECUTION)

    @classmethod
    def from_category(cls, category: DecisionCategory) -> List["DecisionType"]:
        return [dt for dt in cls if dt.category == category]


@dataclass
class DecisionContext:
    """Context information available when making a decision."""

    task_description: str = ""
    current_phase: str = "planning"
    component: str = "freya_agent"

    available_context: str = ""
    memory_results: List[Dict[str, Any]] = field(default_factory=list)
    working_memory: Dict[str, Any] = field(default_factory=dict)
    project_state: Dict[str, Any] = field(default_factory=dict)

    active_goal_id: Optional[str] = None
    active_goal_name: Optional[str] = None
    plan_id: Optional[str] = None
    current_step: Optional[str] = None

    recent_failures: int = 0
    recent_successes: int = 0
    system_state: str = "normal"
    risk_tolerance: str = "medium"

    user_input: str = ""
    requires_approval: bool = False
    allow_mutations: bool = False

    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_description": self.task_description,
            "current_phase": self.current_phase,
            "component": self.component,
            "available_context": self.available_context,
            "memory_results": self.memory_results,
            "working_memory": self.working_memory,
            "project_state": self.project_state,
            "active_goal_id": self.active_goal_id,
            "active_goal_name": self.active_goal_name,
            "plan_id": self.plan_id,
            "current_step": self.current_step,
            "recent_failures": self.recent_failures,
            "recent_successes": self.recent_successes,
            "system_state": self.system_state,
            "risk_tolerance": self.risk_tolerance,
            "user_input": self.user_input,
            "requires_approval": self.requires_approval,
            "allow_mutations": self.allow_mutations,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DecisionContext":
        return cls(
            task_description=data.get("task_description", ""),
            current_phase=data.get("current_phase", "planning"),
            component=data.get("component", "freya_agent"),
            available_context=data.get("available_context", ""),
            memory_results=data.get("memory_results", []),
            working_memory=data.get("working_memory", {}),
            project_state=data.get("project_state", {}),
            active_goal_id=data.get("active_goal_id"),
            active_goal_name=data.get("active_goal_name"),
            plan_id=data.get("plan_id"),
            current_step=data.get("current_step"),
            recent_failures=data.get("recent_failures", 0),
            recent_successes=data.get("recent_successes", 0),
            system_state=data.get("system_state", "normal"),
            risk_tolerance=data.get("risk_tolerance", "medium"),
            user_input=data.get("user_input", ""),
            requires_approval=data.get("requires_approval", False),
            allow_mutations=data.get("allow_mutations", False),
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            metadata=data.get("metadata", {}),
        )


@dataclass
class DecisionOption:
    """A single option/choice available for a decision."""

    id: str = field(default_factory=lambda: f"opt_{uuid.uuid4().hex[:8]}")
    name: str = ""
    description: str = ""
    action: str = ""
    category: DecisionCategory = DecisionCategory.EXECUTION
    decision_type: DecisionType = DecisionType.TOOL_SELECTION

    estimated_success: float = 0.5
    estimated_effort: float = 0.5
    estimated_impact: float = 0.5
    risk_level: str = "medium"
    reversible: bool = True

    supporting_evidence: List[str] = field(default_factory=list)
    opposing_evidence: List[str] = field(default_factory=list)
    related_memories: List[str] = field(default_factory=list)

    tool_name: Optional[str] = None
    tool_args: Dict[str, Any] = field(default_factory=dict)
    file_paths: List[str] = field(default_factory=list)

    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "action": self.action,
            "category": self.category.value,
            "decision_type": self.decision_type.value,
            "estimated_success": self.estimated_success,
            "estimated_effort": self.estimated_effort,
            "estimated_impact": self.estimated_impact,
            "risk_level": self.risk_level,
            "reversible": self.reversible,
            "supporting_evidence": self.supporting_evidence,
            "opposing_evidence": self.opposing_evidence,
            "related_memories": self.related_memories,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "file_paths": self.file_paths,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DecisionOption":
        return cls(
            id=data.get("id", f"opt_{uuid.uuid4().hex[:8]}"),
            name=data.get("name", ""),
            description=data.get("description", ""),
            action=data.get("action", ""),
            category=DecisionCategory(data.get("category", "execution")),
            decision_type=DecisionType(data.get("decision_type", "tool_selection")),
            estimated_success=data.get("estimated_success", 0.5),
            estimated_effort=data.get("estimated_effort", 0.5),
            estimated_impact=data.get("estimated_impact", 0.5),
            risk_level=data.get("risk_level", "medium"),
            reversible=data.get("reversible", True),
            supporting_evidence=data.get("supporting_evidence", []),
            opposing_evidence=data.get("opposing_evidence", []),
            related_memories=data.get("related_memories", []),
            tool_name=data.get("tool_name"),
            tool_args=data.get("tool_args", {}),
            file_paths=data.get("file_paths", []),
            metadata=data.get("metadata", {}),
        )


@dataclass
class DecisionResult:
    """Result of a decision process."""

    decision_id: str = field(default_factory=lambda: f"dec_{uuid.uuid4().hex[:8]}")
    decision_type: DecisionType = DecisionType.TOOL_SELECTION
    category: DecisionCategory = DecisionCategory.EXECUTION

    chosen_option: Optional[DecisionOption] = None
    alternatives_considered: List[DecisionOption] = field(default_factory=list)
    rejected_options: List[DecisionOption] = field(default_factory=list)

    confidence: float = 0.5
    confidence_level: str = "medium"
    risk_level: str = "medium"

    rationale: str = ""
    key_factors: List[str] = field(default_factory=list)
    evidence_summary: str = ""

    should_execute: bool = True
    requires_approval: bool = False
    approval_reason: str = ""
    next_steps: List[str] = field(default_factory=list)

    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    component: str = "freya_agent"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.chosen_option:
            self.category = self.chosen_option.category

    @property
    def is_high_risk(self) -> bool:
        return self.risk_level in ("high", "critical")

    @property
    def is_low_confidence(self) -> bool:
        return self.confidence_level in ("critical", "low")

    @property
    def recommendation(self) -> str:
        if self.is_low_confidence and self.is_high_risk:
            return "REJECT - Low confidence, high risk. Do not proceed without review."
        elif self.is_high_risk:
            return "REVIEW - High risk. Human review recommended."
        elif self.is_low_confidence:
            return "REVIEW - Low confidence. Consider alternatives or gather more info."
        elif self.confidence_level == "very_high":
            return "ACCEPT - Very high confidence. Safe to proceed."
        else:
            return "ACCEPT - Proceed with normal monitoring."

    def explain(self) -> str:
        parts = []
        if self.chosen_option:
            parts.append(f"Decision: {self.chosen_option.name}")
            parts.append(f"Action: {self.chosen_option.action}")
        parts.append(f"Confidence: {self.confidence:.0%} ({self.confidence_level})")
        parts.append(f"Risk: {self.risk_level}")
        if self.rationale:
            parts.append(f"Reason: {self.rationale}")
        if self.key_factors:
            parts.append(f"Key factors: {', '.join(self.key_factors)}")
        parts.append(f"Recommendation: {self.recommendation}")
        return "\n".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "decision_type": self.decision_type.value,
            "category": self.category.value,
            "chosen_option": self.chosen_option.to_dict() if self.chosen_option else None,
            "alternatives_considered": [o.to_dict() for o in self.alternatives_considered],
            "rejected_options": [o.to_dict() for o in self.rejected_options],
            "confidence": self.confidence,
            "confidence_level": self.confidence_level,
            "risk_level": self.risk_level,
            "rationale": self.rationale,
            "key_factors": self.key_factors,
            "evidence_summary": self.evidence_summary,
            "should_execute": self.should_execute,
            "requires_approval": self.requires_approval,
            "approval_reason": self.approval_reason,
            "next_steps": self.next_steps,
            "timestamp": self.timestamp,
            "component": self.component,
            "metadata": self.metadata,
            "recommendation": self.recommendation,
            "explanation": self.explain(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DecisionResult":
        chosen = data.get("chosen_option")
        return cls(
            decision_id=data.get("decision_id", f"dec_{uuid.uuid4().hex[:8]}"),
            decision_type=DecisionType(data.get("decision_type", "tool_selection")),
            category=DecisionCategory(data.get("category", "execution")),
            chosen_option=DecisionOption.from_dict(chosen) if chosen else None,
            alternatives_considered=[DecisionOption.from_dict(o) for o in data.get("alternatives_considered", [])],
            rejected_options=[DecisionOption.from_dict(o) for o in data.get("rejected_options", [])],
            confidence=data.get("confidence", 0.5),
            confidence_level=data.get("confidence_level", "medium"),
            risk_level=data.get("risk_level", "medium"),
            rationale=data.get("rationale", ""),
            key_factors=data.get("key_factors", []),
            evidence_summary=data.get("evidence_summary", ""),
            should_execute=data.get("should_execute", True),
            requires_approval=data.get("requires_approval", False),
            approval_reason=data.get("approval_reason", ""),
            next_steps=data.get("next_steps", []),
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            component=data.get("component", "freya_agent"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class DecisionRecord:
    """Persistent record of a decision and its outcome."""

    record_id: str = field(default_factory=lambda: f"rec_{uuid.uuid4().hex[:8]}")
    decision_id: str = ""
    decision_type: DecisionType = DecisionType.TOOL_SELECTION
    category: DecisionCategory = DecisionCategory.EXECUTION

    chosen_option_name: str = ""
    chosen_option_action: str = ""
    alternatives_count: int = 0
    confidence: float = 0.5
    confidence_level: str = "medium"
    risk_level: str = "medium"
    rationale: str = ""
    key_factors: List[str] = field(default_factory=list)

    task_description: str = ""
    component: str = "freya_agent"
    active_goal_id: Optional[str] = None
    plan_id: Optional[str] = None
    system_state: str = "normal"

    executed: bool = False
    outcome: Optional[str] = None
    outcome_details: str = ""
    actual_success: Optional[bool] = None
    actual_effort: Optional[float] = None
    actual_impact: Optional[float] = None
    error: Optional[str] = None

    lesson_learned: str = ""
    confidence_calibration: float = 0.0
    would_repeat: Optional[bool] = None

    decided_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    executed_at: Optional[str] = None
    completed_at: Optional[str] = None

    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_complete(self) -> bool:
        return self.outcome is not None

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.decided_at and self.completed_at:
            try:
                start = datetime.fromisoformat(self.decided_at.replace("Z", "+00:00"))
                end = datetime.fromisoformat(self.completed_at.replace("Z", "+00:00"))
                return (end - start).total_seconds()
            except Exception:
                return None
        return None

    @classmethod
    def from_result(cls, result: DecisionResult, context: DecisionContext) -> "DecisionRecord":
        return cls(
            decision_id=result.decision_id,
            decision_type=result.decision_type,
            category=result.category,
            chosen_option_name=result.chosen_option.name if result.chosen_option else "",
            chosen_option_action=result.chosen_option.action if result.chosen_option else "",
            alternatives_count=len(result.alternatives_considered),
            confidence=result.confidence,
            confidence_level=result.confidence_level,
            risk_level=result.risk_level,
            rationale=result.rationale,
            key_factors=list(result.key_factors),
            task_description=context.task_description,
            component=context.component,
            active_goal_id=context.active_goal_id,
            plan_id=context.plan_id,
            system_state=context.system_state,
        )

    def mark_executed(
        self,
        outcome: str,
        details: str = "",
        error: Optional[str] = None,
        actual_success: Optional[bool] = None,
        actual_effort: Optional[float] = None,
        actual_impact: Optional[float] = None,
    ) -> None:
        self.executed = True
        self.outcome = outcome
        self.outcome_details = details
        self.error = error
        self.actual_success = actual_success
        self.actual_effort = actual_effort
        self.actual_impact = actual_impact
        self.executed_at = datetime.now(timezone.utc).isoformat()
        self.completed_at = self.executed_at

        if actual_success is not None:
            self.confidence_calibration = (1.0 if actual_success else 0.0) - self.confidence

    def add_learning(self, lesson: str, would_repeat: bool) -> None:
        self.lesson_learned = lesson
        self.would_repeat = would_repeat

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "decision_id": self.decision_id,
            "decision_type": self.decision_type.value,
            "category": self.category.value,
            "chosen_option_name": self.chosen_option_name,
            "chosen_option_action": self.chosen_option_action,
            "alternatives_count": self.alternatives_count,
            "confidence": self.confidence,
            "confidence_level": self.confidence_level,
            "risk_level": self.risk_level,
            "rationale": self.rationale,
            "key_factors": self.key_factors,
            "task_description": self.task_description,
            "component": self.component,
            "active_goal_id": self.active_goal_id,
            "plan_id": self.plan_id,
            "system_state": self.system_state,
            "executed": self.executed,
            "outcome": self.outcome,
            "outcome_details": self.outcome_details,
            "actual_success": self.actual_success,
            "actual_effort": self.actual_effort,
            "actual_impact": self.actual_impact,
            "error": self.error,
            "lesson_learned": self.lesson_learned,
            "confidence_calibration": self.confidence_calibration,
            "would_repeat": self.would_repeat,
            "decided_at": self.decided_at,
            "executed_at": self.executed_at,
            "completed_at": self.completed_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DecisionRecord":
        return cls(
            record_id=data.get("record_id", f"rec_{uuid.uuid4().hex[:8]}"),
            decision_id=data.get("decision_id", ""),
            decision_type=DecisionType(data.get("decision_type", "tool_selection")),
            category=DecisionCategory(data.get("category", "execution")),
            chosen_option_name=data.get("chosen_option_name", ""),
            chosen_option_action=data.get("chosen_option_action", ""),
            alternatives_count=data.get("alternatives_count", 0),
            confidence=data.get("confidence", 0.5),
            confidence_level=data.get("confidence_level", "medium"),
            risk_level=data.get("risk_level", "medium"),
            rationale=data.get("rationale", ""),
            key_factors=data.get("key_factors", []),
            task_description=data.get("task_description", ""),
            component=data.get("component", "freya_agent"),
            active_goal_id=data.get("active_goal_id"),
            plan_id=data.get("plan_id"),
            system_state=data.get("system_state", "normal"),
            executed=data.get("executed", False),
            outcome=data.get("outcome"),
            outcome_details=data.get("outcome_details", ""),
            actual_success=data.get("actual_success"),
            actual_effort=data.get("actual_effort"),
            actual_impact=data.get("actual_impact"),
            error=data.get("error"),
            lesson_learned=data.get("lesson_learned", ""),
            confidence_calibration=data.get("confidence_calibration", 0.0),
            would_repeat=data.get("would_repeat"),
            decided_at=data.get("decided_at", datetime.now(timezone.utc).isoformat()),
            executed_at=data.get("executed_at"),
            completed_at=data.get("completed_at"),
            metadata=data.get("metadata", {}),
        )