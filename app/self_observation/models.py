"""Data models for Self Observation Completion subsystem.

Provides unified data structures for:
- Runtime Decision Pipeline
- Centralized Self-Analysis
- Runtime Awareness
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4


class DecisionPipelineStage(Enum):
    """Stages in the unified runtime decision pipeline."""
    OBSERVE = "observe"
    GATHER_CONTEXT = "gather_context"
    IDENTIFY_ACTIONS = "identify_actions"
    EVALUATE_OPTIONS = "evaluate_options"
    ESTIMATE_RISK_BENEFIT = "estimate_risk_benefit"
    CHOOSE_BEST = "choose_best"
    EXECUTE = "execute"
    OBSERVE_OUTCOME = "observe_outcome"
    LEARN = "learn"


class AnalysisCategory(Enum):
    """Categories for centralized self-analysis."""
    CAPABILITIES = "capabilities"
    LIMITATIONS = "limitations"
    RESOURCE_UTILIZATION = "resource_utilization"
    GOAL_PROGRESS = "goal_progress"
    TASK_EXECUTION_QUALITY = "task_execution_quality"
    FAILURE_PATTERNS = "failure_patterns"
    LEARNING_PROGRESS = "learning_progress"
    KNOWLEDGE_GAPS = "knowledge_gaps"
    DECISION_QUALITY = "decision_quality"
    SYSTEM_CONFIDENCE = "system_confidence"
    OPERATIONAL_EFFECTIVENESS = "operational_effectiveness"


class AwarenessComponent(Enum):
    """Components of runtime awareness."""
    CURRENT_ACTIVITY = "current_activity"
    RUNNING_TASKS = "running_tasks"
    ACTIVE_GOALS = "active_goals"
    CURRENT_REASONING_STATE = "current_reasoning_state"
    TOOL_USAGE = "tool_usage"
    RESOURCE_CONSUMPTION = "resource_consumption"
    SYSTEM_HEALTH = "system_health"
    MEMORY_STATE = "memory_state"
    PENDING_WORK = "pending_work"
    AUTONOMOUS_BACKGROUND_ACTIVITIES = "autonomous_background_activities"
    OVERALL_EXECUTION_CONTEXT = "overall_execution_context"


class ConfidenceLevel(Enum):
    """Confidence levels for analysis and awareness."""
    VERY_HIGH = "very_high"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    CRITICAL = "critical"


@dataclass
class DecisionPipelineContext:
    """Unified context gathered by the runtime decision pipeline."""
    pipeline_id: str = field(default_factory=lambda: f"pipeline_{uuid4().hex[:8]}")
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    stage: DecisionPipelineStage = DecisionPipelineStage.OBSERVE

    # Current goals
    active_goals: List[Dict[str, Any]] = field(default_factory=list)
    goal_progress: Dict[str, float] = field(default_factory=dict)

    # Active plans
    current_plans: List[Dict[str, Any]] = field(default_factory=list)
    plan_status: Dict[str, str] = field(default_factory=dict)

    # Runtime health
    system_health: str = "unknown"
    health_score: float = 0.0
    health_issues: List[str] = field(default_factory=list)

    # Resource availability
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    disk_percent: float = 0.0
    available_tools: List[str] = field(default_factory=list)

    # Monitoring state
    active_alerts: List[Dict[str, Any]] = field(default_factory=list)
    recent_metrics: Dict[str, float] = field(default_factory=dict)

    # World model
    world_snapshot: Optional[Dict[str, Any]] = None
    project_context: Dict[str, Any] = field(default_factory=dict)

    # Memory state
    working_memory: Dict[str, Any] = field(default_factory=dict)
    relevant_memories: List[Dict[str, Any]] = field(default_factory=list)

    # Knowledge retrieval
    knowledge_context: List[Dict[str, Any]] = field(default_factory=list)
    retrieval_confidence: float = 0.0

    # Current task execution
    running_tasks: List[Dict[str, Any]] = field(default_factory=list)
    current_task: Optional[Dict[str, Any]] = None
    task_progress: Dict[str, float] = field(default_factory=dict)

    # Failure recovery state
    recent_failures: List[Dict[str, Any]] = field(default_factory=list)
    active_recoveries: List[Dict[str, Any]] = field(default_factory=list)
    recovery_success_rate: float = 0.0

    # Safety state
    safety_mode: str = "balanced"
    pending_approvals: List[Dict[str, Any]] = field(default_factory=list)
    safety_violations: List[Dict[str, Any]] = field(default_factory=list)

    # Pipeline metadata
    collection_time_ms: float = 0.0
    stage_results: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalysisResult:
    """Result of a self-analysis in a specific category."""
    category: AnalysisCategory
    score: float  # 0.0 - 1.0
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM
    findings: List[str] = field(default_factory=list)
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class SelfAnalysisReport:
    """Comprehensive self-analysis report."""
    report_id: str = field(default_factory=lambda: f"analysis_{uuid4().hex[:8]}")
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    overall_score: float = 0.0
    overall_confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM
    analysis_results: Dict[AnalysisCategory, AnalysisResult] = field(default_factory=dict)
    summary: str = ""
    critical_issues: List[str] = field(default_factory=list)
    improvement_priorities: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RuntimeAwarenessState:
    """Current runtime awareness state."""
    awareness_id: str = field(default_factory=lambda: f"awareness_{uuid4().hex[:8]}")
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Current activity
    current_activity: str = "idle"
    activity_description: str = ""
    activity_start_time: Optional[str] = None

    # Running tasks
    running_tasks: List[Dict[str, Any]] = field(default_factory=list)
    queued_tasks: List[Dict[str, Any]] = field(default_factory=list)

    # Active goals
    active_goals: List[Dict[str, Any]] = field(default_factory=list)
    current_goal: Optional[Dict[str, Any]] = None

    # Current reasoning state
    reasoning_phase: str = "observing"
    reasoning_context: Dict[str, Any] = field(default_factory=dict)
    decision_history: List[Dict[str, Any]] = field(default_factory=list)

    # Tool usage
    active_tools: List[str] = field(default_factory=list)
    recent_tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    tool_success_rates: Dict[str, float] = field(default_factory=dict)

    # Resource consumption
    # ``None`` means the source did not provide a valid measurement.  It is
    # intentionally different from a measured value of zero.
    cpu_usage: Optional[float] = None
    memory_usage_mb: Optional[float] = None
    disk_io_mb_s: Optional[float] = None
    network_io_mb_s: Optional[float] = None

    # GPU resource consumption
    gpu_devices: List[Dict[str, Any]] = field(default_factory=list)
    gpu_utilization_percent: Optional[float] = None
    gpu_memory_used_mb: Optional[float] = None
    gpu_memory_total_mb: Optional[float] = None
    gpu_temperature_celsius: Optional[float] = None

    # System health
    system_health_status: str = "healthy"
    component_health: Dict[str, str] = field(default_factory=dict)
    alerts: List[Dict[str, Any]] = field(default_factory=list)

    # Memory state
    working_memory_size: int = 0
    long_term_memory_size: int = 0
    episodic_memory_count: int = 0
    consolidation_status: str = "idle"

    # Pending work
    pending_workflows: int = 0
    pending_decisions: int = 0
    pending_approvals: int = 0
    background_jobs: int = 0

    # Autonomous background activities
    autonomous_activities: List[Dict[str, Any]] = field(default_factory=list)
    learning_tasks: List[Dict[str, Any]] = field(default_factory=list)
    maintenance_tasks: List[Dict[str, Any]] = field(default_factory=list)

    # Overall execution context
    execution_mode: str = "normal"
    session_duration_seconds: Optional[float] = None
    total_decisions_made: int = 0
    total_tasks_completed: int = 0
    total_failures: int = 0

    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DecisionPipelineResult:
    """Result of the unified runtime decision pipeline."""
    pipeline_id: str
    context: DecisionPipelineContext
    chosen_action: Optional[Dict[str, Any]] = None
    alternatives: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    risk_level: str = "low"
    rationale: str = ""
    should_execute: bool = True
    requires_approval: bool = False
    stage_times: Dict[str, float] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())