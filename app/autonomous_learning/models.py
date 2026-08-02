"""
Data models for Autonomous Learning system.

Defines the core data structures for:
- Learning pipeline results
- Knowledge gap detection
- Autonomous research tasks
- Learning events and audit trail
- Configuration
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
import uuid


class GapPriority(Enum):
    """Priority levels for knowledge gaps."""

    CRITICAL = "critical"  # Blocking active tasks/goals
    HIGH = "high"  # Needed for upcoming work
    MEDIUM = "medium"  # Would improve efficiency
    LOW = "low"  # Nice to have / exploratory


class GapStatus(Enum):
    """Status of a knowledge gap."""

    DETECTED = "detected"  # Gap identified, not yet addressed
    RESEARCHING = "researching"  # Autonomous research in progress
    VALIDATING = "validating"  # Extracted knowledge being validated
    RESOLVED = "resolved"  # Knowledge acquired and stored
    DEFERRED = "deferred"  # Intentionally postponed
    REJECTED = "rejected"  # Gap determined to be invalid/unnecessary


class ResearchStatus(Enum):
    """Status of an autonomous research task."""

    PENDING = "pending"
    SEARCHING = "searching"
    EXTRACTING = "extracting"
    VALIDATING = "validating"
    STORING = "storing"
    COMPLETED = "completed"
    FAILED = "failed"


class ResearchSource(Enum):
    """Trusted sources for autonomous research."""

    OFFICIAL_DOCUMENTATION = "official_documentation"
    STANDARDS_SPECIFICATIONS = "standards_specifications"
    VENDOR_DOCUMENTATION = "vendor_documentation"
    PACKAGE_DOCUMENTATION = "package_documentation"
    GITHUB_REPOSITORY = "github_repository"
    TECHNICAL_BLOG = "technical_blog"
    COMMUNITY_FORUM = "community_forum"
    ACADEMIC_PAPER = "academic_paper"
    RFC_STANDARD = "rfc_standard"
    W3C_STANDARD = "w3c_standard"
    ISO_STANDARD = "iso_standard"


class LearningEventType(Enum):
    """Types of learning events for audit trail."""

    EXPERIENCE_COLLECTED = "experience_collected"
    EXPERIENCE_ANALYZED = "experience_analyzed"
    KNOWLEDGE_EXTRACTED = "knowledge_extracted"
    KNOWLEDGE_VALIDATED = "knowledge_validated"
    KNOWLEDGE_STORED = "knowledge_stored"
    KNOWLEDGE_REJECTED = "knowledge_rejected"
    GAP_DETECTED = "gap_detected"
    RESEARCH_STARTED = "research_started"
    RESEARCH_COMPLETED = "research_completed"
    RESEARCH_FAILED = "research_failed"
    CONSOLIDATION_RUN = "consolidation_run"
    FORGETTING_RUN = "forgetting_run"
    PATTERN_DETECTED = "pattern_detected"
    INSIGHT_GENERATED = "insight_generated"


@dataclass
class LearningPipelineResult:
    """Result of a full autonomous learning pipeline run."""

    pipeline_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: datetime = field(default_factory=datetime.now)

    # Experience processing
    experiences_processed: int = 0
    experiences_analyzed: int = 0

    # Knowledge extraction
    knowledge_objects_extracted: int = 0
    knowledge_objects_validated: int = 0
    knowledge_objects_stored: int = 0
    knowledge_objects_rejected: int = 0

    # Gap detection
    gaps_detected: int = 0
    gaps_resolved: int = 0
    goal_gaps_detected: int = 0

    # Research
    research_tasks_started: int = 0
    research_tasks_completed: int = 0
    research_tasks_failed: int = 0

    # Consolidation
    consolidation_runs: int = 0
    experiences_promoted: int = 0
    lessons_promoted: int = 0
    entries_archived: int = 0

    # Errors and warnings
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # Performance metrics
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "pipeline_id": self.pipeline_id,
            "timestamp": self.timestamp.isoformat(),
            "experiences_processed": self.experiences_processed,
            "experiences_analyzed": self.experiences_analyzed,
            "knowledge_objects_extracted": self.knowledge_objects_extracted,
            "knowledge_objects_validated": self.knowledge_objects_validated,
            "knowledge_objects_stored": self.knowledge_objects_stored,
            "knowledge_objects_rejected": self.knowledge_objects_rejected,
            "gaps_detected": self.gaps_detected,
            "gaps_resolved": self.gaps_resolved,
            "goal_gaps_detected": self.goal_gaps_detected,
            "research_tasks_started": self.research_tasks_started,
            "research_tasks_completed": self.research_tasks_completed,
            "research_tasks_failed": self.research_tasks_failed,
            "consolidation_runs": self.consolidation_runs,
            "experiences_promoted": self.experiences_promoted,
            "lessons_promoted": self.lessons_promoted,
            "entries_archived": self.entries_archived,
            "errors": self.errors,
            "warnings": self.warnings,
            "duration_seconds": self.duration_seconds,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "pipeline_id": self.pipeline_id,
            "timestamp": self.timestamp.isoformat(),
            "experiences_processed": self.experiences_processed,
            "experiences_analyzed": self.experiences_analyzed,
            "knowledge_objects_extracted": self.knowledge_objects_extracted,
            "knowledge_objects_validated": self.knowledge_objects_validated,
            "knowledge_objects_stored": self.knowledge_objects_stored,
            "knowledge_objects_rejected": self.knowledge_objects_rejected,
            "gaps_detected": self.gaps_detected,
            "gaps_resolved": self.gaps_resolved,
            "research_tasks_started": self.research_tasks_started,
            "research_tasks_completed": self.research_tasks_completed,
            "research_tasks_failed": self.research_tasks_failed,
            "errors": self.errors,
            "warnings": self.warnings,
            "duration_seconds": self.duration_seconds,
        }


@dataclass
class KnowledgeGap:
    """Represents a detected gap in knowledge."""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    title: str = ""
    description: str = ""

    # Gap classification
    category: str = ""  # e.g., "framework", "tool", "concept", "pattern", "technology", "documentation"
    sub_category: str = ""  # More specific classification

    # What's missing
    missing_concepts: list[str] = field(default_factory=list)
    missing_tools: list[str] = field(default_factory=list)
    missing_frameworks: list[str] = field(default_factory=list)
    missing_documentation: list[str] = field(default_factory=list)

    # Context
    related_task_types: list[str] = field(default_factory=list)
    related_goals: list[str] = field(default_factory=list)
    trigger_context: str = ""  # What task/context triggered this gap detection

    # Priority and confidence
    priority: GapPriority = GapPriority.MEDIUM
    confidence: float = 0.5  # 0-1 confidence this is a real gap
    estimated_effort_hours: float = 1.0

    # Status tracking
    status: GapStatus = GapStatus.DETECTED
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    resolved_at: Optional[datetime] = None

    # Research tracking
    research_task_id: Optional[str] = None
    research_attempts: int = 0
    max_research_attempts: int = 3

    # Resolution
    resolved_by: Optional[str] = None  # "autonomous_research", "manual", "deferred"
    resolution_notes: str = ""
    knowledge_items_created: list[str] = field(default_factory=list)  # IDs of created knowledge

    # Metadata
    source_experiences: list[str] = field(default_factory=list)  # Experience IDs that revealed this gap
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "sub_category": self.sub_category,
            "missing_concepts": self.missing_concepts,
            "missing_tools": self.missing_tools,
            "missing_frameworks": self.missing_frameworks,
            "missing_documentation": self.missing_documentation,
            "related_task_types": self.related_task_types,
            "related_goals": self.related_goals,
            "trigger_context": self.trigger_context,
            "priority": self.priority.value,
            "confidence": self.confidence,
            "estimated_effort_hours": self.estimated_effort_hours,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "research_task_id": self.research_task_id,
            "research_attempts": self.research_attempts,
            "max_research_attempts": self.max_research_attempts,
            "resolved_by": self.resolved_by,
            "resolution_notes": self.resolution_notes,
            "knowledge_items_created": self.knowledge_items_created,
            "source_experiences": self.source_experiences,
            "tags": self.tags,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KnowledgeGap":
        gap = cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            title=data.get("title", ""),
            description=data.get("description", ""),
            category=data.get("category", ""),
            sub_category=data.get("sub_category", ""),
            missing_concepts=data.get("missing_concepts", []),
            missing_tools=data.get("missing_tools", []),
            missing_frameworks=data.get("missing_frameworks", []),
            missing_documentation=data.get("missing_documentation", []),
            related_task_types=data.get("related_task_types", []),
            related_goals=data.get("related_goals", []),
            trigger_context=data.get("trigger_context", ""),
            priority=GapPriority(data.get("priority", "medium")),
            confidence=data.get("confidence", 0.5),
            estimated_effort_hours=data.get("estimated_effort_hours", 1.0),
            status=GapStatus(data.get("status", "detected")),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.now(),
            resolved_at=datetime.fromisoformat(data["resolved_at"]) if data.get("resolved_at") else None,
            research_task_id=data.get("research_task_id"),
            research_attempts=data.get("research_attempts", 0),
            max_research_attempts=data.get("max_research_attempts", 3),
            resolved_by=data.get("resolved_by"),
            resolution_notes=data.get("resolution_notes", ""),
            knowledge_items_created=data.get("knowledge_items_created", []),
            source_experiences=data.get("source_experiences", []),
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
        )
        return gap


@dataclass
class ResearchTask:
    """An autonomous research task to fill a knowledge gap."""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    gap_id: str = ""

    # Research parameters
    query: str = ""  # Search query
    target_sources: list[ResearchSource] = field(default_factory=list)
    max_results_per_source: int = 5
    language_hint: str = "en"

    # Status
    status: ResearchStatus = ResearchStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Results
    search_results: list[dict[str, Any]] = field(default_factory=list)  # Raw search results
    extracted_knowledge: list[dict[str, Any]] = field(default_factory=list)  # KnowledgeObject dicts
    validated_knowledge: list[dict[str, Any]] = field(default_factory=list)  # Validation results
    stored_knowledge_ids: list[str] = field(default_factory=list)

    # Errors
    error_message: str = ""
    retry_count: int = 0
    max_retries: int = 2

    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "gap_id": self.gap_id,
            "query": self.query,
            "target_sources": [s.value for s in self.target_sources],
            "max_results_per_source": self.max_results_per_source,
            "language_hint": self.language_hint,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "search_results": self.search_results,
            "extracted_knowledge": self.extracted_knowledge,
            "validated_knowledge": self.validated_knowledge,
            "stored_knowledge_ids": self.stored_knowledge_ids,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResearchTask":
        task = cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            gap_id=data.get("gap_id", ""),
            query=data.get("query", ""),
            target_sources=[ResearchSource(s) for s in data.get("target_sources", [])],
            max_results_per_source=data.get("max_results_per_source", 5),
            language_hint=data.get("language_hint", "en"),
            status=ResearchStatus(data.get("status", "pending")),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            search_results=data.get("search_results", []),
            extracted_knowledge=data.get("extracted_knowledge", []),
            validated_knowledge=data.get("validated_knowledge", []),
            stored_knowledge_ids=data.get("stored_knowledge_ids", []),
            error_message=data.get("error_message", ""),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 2),
            metadata=data.get("metadata", {}),
        )
        return task


@dataclass
class LearningEvent:
    """Audit trail event for autonomous learning activities."""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    event_type: LearningEventType = LearningEventType.EXPERIENCE_COLLECTED
    timestamp: datetime = field(default_factory=datetime.now)

    # Context
    agent_session_id: str = ""
    task_id: Optional[str] = None
    goal_id: Optional[str] = None

    # Event details
    description: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    # Outcomes
    success: bool = True
    error_message: str = ""

    # Related entities
    related_experience_ids: list[str] = field(default_factory=list)
    related_knowledge_ids: list[str] = field(default_factory=list)
    related_gap_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "agent_session_id": self.agent_session_id,
            "task_id": self.task_id,
            "goal_id": self.goal_id,
            "description": self.description,
            "details": self.details,
            "success": self.success,
            "error_message": self.error_message,
            "related_experience_ids": self.related_experience_ids,
            "related_knowledge_ids": self.related_knowledge_ids,
            "related_gap_ids": self.related_gap_ids,
        }


@dataclass
class AutonomousLearningConfig:
    """Configuration for autonomous learning system."""

    # Pipeline settings
    enabled: bool = True
    run_interval_minutes: int = 30  # How often to run the pipeline
    max_experiences_per_run: int = 50
    min_experience_confidence: float = 0.5

    # Knowledge extraction
    extraction_confidence_threshold: float = 0.6
    max_knowledge_objects_per_run: int = 20

    # Knowledge validation
    validation_auto_store_threshold: float = 0.8
    validation_manual_review_threshold: float = 0.7
    validation_reject_threshold: float = 0.4

    # Gap detection
    gap_detection_enabled: bool = True
    min_gap_confidence: float = 0.6
    max_gaps_per_run: int = 10
    gap_categories: list[str] = field(default_factory=lambda: [
        "framework", "tool", "concept", "pattern", "technology", "documentation", "api", "library"
    ])

    # Autonomous research
    research_enabled: bool = True
    max_concurrent_research: int = 3
    research_timeout_seconds: int = 300
    trusted_sources: list[ResearchSource] = field(default_factory=lambda: [
        ResearchSource.OFFICIAL_DOCUMENTATION,
        ResearchSource.STANDARDS_SPECIFICATIONS,
        ResearchSource.VENDOR_DOCUMENTATION,
        ResearchSource.PACKAGE_DOCUMENTATION,
        ResearchSource.GITHUB_REPOSITORY,
        ResearchSource.RFC_STANDARD,
        ResearchSource.W3C_STANDARD,
    ])

    # Storage
    storage_path: str = "data/memory/autonomous_learning"
    events_retention_days: int = 90
    max_events: int = 10000

    # Integration
    use_consolidation_engine: bool = True
    use_forgetting_engine: bool = True
    use_knowledge_validator: bool = True

    # Multi-agent learning
    multi_agent_enabled: bool = False
    shared_knowledge_dir: str = "data/multi_agent_learning"
    instance_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # Goal-driven learning
    goal_driven_learning_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "run_interval_minutes": self.run_interval_minutes,
            "max_experiences_per_run": self.max_experiences_per_run,
            "min_experience_confidence": self.min_experience_confidence,
            "extraction_confidence_threshold": self.extraction_confidence_threshold,
            "max_knowledge_objects_per_run": self.max_knowledge_objects_per_run,
            "validation_auto_store_threshold": self.validation_auto_store_threshold,
            "validation_manual_review_threshold": self.validation_manual_review_threshold,
            "validation_reject_threshold": self.validation_reject_threshold,
            "gap_detection_enabled": self.gap_detection_enabled,
            "min_gap_confidence": self.min_gap_confidence,
            "max_gaps_per_run": self.max_gaps_per_run,
            "gap_categories": self.gap_categories,
            "research_enabled": self.research_enabled,
            "max_concurrent_research": self.max_concurrent_research,
            "research_timeout_seconds": self.research_timeout_seconds,
            "trusted_sources": [s.value for s in self.trusted_sources],
            "storage_path": self.storage_path,
            "events_retention_days": self.events_retention_days,
            "max_events": self.max_events,
            "use_consolidation_engine": self.use_consolidation_engine,
            "use_forgetting_engine": self.use_forgetting_engine,
            "use_knowledge_validator": self.use_knowledge_validator,
            "multi_agent_enabled": self.multi_agent_enabled,
            "shared_knowledge_dir": self.shared_knowledge_dir,
            "instance_id": self.instance_id,
            "goal_driven_learning_enabled": self.goal_driven_learning_enabled,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AutonomousLearningConfig":
        return cls(
            enabled=data.get("enabled", True),
            run_interval_minutes=data.get("run_interval_minutes", 30),
            max_experiences_per_run=data.get("max_experiences_per_run", 50),
            min_experience_confidence=data.get("min_experience_confidence", 0.5),
            extraction_confidence_threshold=data.get("extraction_confidence_threshold", 0.6),
            max_knowledge_objects_per_run=data.get("max_knowledge_objects_per_run", 20),
            validation_auto_store_threshold=data.get("validation_auto_store_threshold", 0.8),
            validation_manual_review_threshold=data.get("validation_manual_review_threshold", 0.7),
            validation_reject_threshold=data.get("validation_reject_threshold", 0.4),
            gap_detection_enabled=data.get("gap_detection_enabled", True),
            min_gap_confidence=data.get("min_gap_confidence", 0.6),
            max_gaps_per_run=data.get("max_gaps_per_run", 10),
            gap_categories=data.get("gap_categories", ["framework", "tool", "concept", "pattern", "technology", "documentation", "api", "library"]),
            research_enabled=data.get("research_enabled", True),
            max_concurrent_research=data.get("max_concurrent_research", 3),
            research_timeout_seconds=data.get("research_timeout_seconds", 300),
            trusted_sources=[ResearchSource(s) for s in data.get("trusted_sources", [
                "official_documentation", "standards_specifications", "vendor_documentation",
                "package_documentation", "github_repository", "rfc_standard", "w3c_standard"
            ])],
            storage_path=data.get("storage_path", "data/memory/autonomous_learning"),
            events_retention_days=data.get("events_retention_days", 90),
            max_events=data.get("max_events", 10000),
            use_consolidation_engine=data.get("use_consolidation_engine", True),
            use_forgetting_engine=data.get("use_forgetting_engine", True),
            use_knowledge_validator=data.get("use_knowledge_validator", True),
            multi_agent_enabled=data.get("multi_agent_enabled", False),
            shared_knowledge_dir=data.get("shared_knowledge_dir", "data/multi_agent_learning"),
            instance_id=data.get("instance_id", str(uuid.uuid4())),
            goal_driven_learning_enabled=data.get("goal_driven_learning_enabled", False),
        )