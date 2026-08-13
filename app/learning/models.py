
"""
Data models for the Self-Learning Pipeline.

Defines the core data structures for learning candidates, observations,
outcomes, and pipeline results per TARGET_ARCHITECTURE.md.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4


class LearningCandidateType(Enum):
    """Types of learning candidates that can be fed into the pipeline."""
    ANSWER_VERIFICATION = "answer_verification"       # From AnswerVerifier
    EXECUTION_OUTCOME = "execution_outcome"           # From ExecutionVerifier
    WATCHDOG_OBSERVATION = "watchdog_observation"     # From Watchdog
    EVENT_BUS_EVENT = "event_bus_event"               # From EventBus
    CONVERSATION_FEEDBACK = "conversation_feedback"   # From conversation flow
    MANUAL_INPUT = "manual_input"                     # Direct manual input


class PipelineStage(Enum):
    """Stages of the learning pipeline in exact order per TARGET_ARCHITECTURE.md."""
    OBSERVE = "observe"
    EVALUATE = "evaluate"
    EXTRACT_LEARNING = "extract_learning"
    VALIDATE_LEARNING = "validate_learning"
    WORTH_REMEMBERING = "worth_remembering"


class WorthRememberingDecision(Enum):
    """Decision from the Worth Remembering? stage."""
    YES = "yes"           # Write to durable memory via MemoryCoordinator
    NO = "no"             # Discard or keep temporary only


@dataclass
class LearningCandidate:
    """
    Input to the learning pipeline from various sources.
    
    This is the clean public input that AnswerVerifier, ExecutionVerifier,
    Watchdog, and EventBus can feed into the pipeline.
    """
    id: str = field(default_factory=lambda: str(uuid4())[:8])
    candidate_type: LearningCandidateType = LearningCandidateType.MANUAL_INPUT
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Source identification
    source_component: str = ""  # e.g., "AnswerVerifier", "ExecutionVerifier", "Watchdog", "EventBus"
    source_session_id: str = ""  # Session/task/conversation ID
    
    # Payload
    raw_observation: Dict[str, Any] = field(default_factory=dict)  # Raw data from source
    context: Dict[str, Any] = field(default_factory=dict)  # Additional context
    
    # Metadata
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "candidate_type": self.candidate_type.value,
            "timestamp": self.timestamp.isoformat(),
            "source_component": self.source_component,
            "source_session_id": self.source_session_id,
            "raw_observation": self.raw_observation,
            "context": self.context,
            "tags": self.tags,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LearningCandidate":
        return cls(
            id=data.get("id", str(uuid4())[:8]),
            candidate_type=LearningCandidateType(data.get("candidate_type", "manual_input")),
            timestamp=datetime.fromisoformat(data["timestamp"]) if data.get("timestamp") else datetime.now(timezone.utc),
            source_component=data.get("source_component", ""),
            source_session_id=data.get("source_session_id", ""),
            raw_observation=data.get("raw_observation", {}),
            context=data.get("context", {}),
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ObservedData:
    """Result of the Observe stage - structured observation from raw candidate."""
    candidate_id: str
    structured_observation: Dict[str, Any] = field(default_factory=dict)
    extracted_signals: List[str] = field(default_factory=list)  # Key signals identified
    confidence: float = 0.5  # Confidence in the observation quality
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvaluationResult:
    """Result of the Evaluate stage - assessment of learning potential."""
    candidate_id: str
    has_learning_potential: bool = False
    relevance_score: float = 0.0  # 0-1 relevance to current goals/context
    novelty_score: float = 0.0    # 0-1 how new this information is
    actionability_score: float = 0.0  # 0-1 how actionable the learning would be
    evaluation_notes: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractedLearning:
    """Result of the Extract Learning stage - candidate knowledge items."""
    candidate_id: str
    knowledge_items: List[Dict[str, Any]] = field(default_factory=list)  # Each: {title, content, category, confidence, source}
    extraction_notes: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    """Result of the Validate Learning stage - validated knowledge with confidence."""
    candidate_id: str
    validated_items: List[Dict[str, Any]] = field(default_factory=list)  # Subset of extracted items that pass validation
    rejected_items: List[Dict[str, Any]] = field(default_factory=list)   # Items that failed validation
    validation_details: Dict[str, Any] = field(default_factory=dict)     # Per-item validation results
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorthRememberingResult:
    """Result of the Worth Remembering? stage."""
    candidate_id: str
    decision: WorthRememberingDecision = WorthRememberingDecision.NO
    items_to_store: List[Dict[str, Any]] = field(default_factory=list)   # Items approved for durable storage
    items_temporary: List[Dict[str, Any]] = field(default_factory=list)  # Items kept temporary only
    reasoning: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LearningPipelineResult:
    """Complete result of a learning pipeline run for a single candidate."""
    pipeline_run_id: str = field(default_factory=lambda: str(uuid4())[:8])
    candidate_id: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Stage results
    observe_result: Optional[ObservedData] = None
    evaluate_result: Optional[EvaluationResult] = None
    extract_result: Optional[ExtractedLearning] = None
    validate_result: Optional[ValidationResult] = None
    worth_remembering_result: Optional[WorthRememberingResult] = None
    
    # Final outcome
    final_decision: WorthRememberingDecision = WorthRememberingDecision.NO
    items_stored_via_memory_coordinator: List[str] = field(default_factory=list)  # IDs of items written to MemoryCoordinator
    items_kept_temporary: List[str] = field(default_factory=list)
    items_discarded: List[str] = field(default_factory=list)
    
    # Performance
    duration_seconds: float = 0.0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "pipeline_run_id": self.pipeline_run_id,
            "candidate_id": self.candidate_id,
            "timestamp": self.timestamp.isoformat(),
            "observe_result": self.observe_result.__dict__ if self.observe_result else None,
            "evaluate_result": self.evaluate_result.__dict__ if self.evaluate_result else None,
            "extract_result": self.extract_result.__dict__ if self.extract_result else None,
            "validate_result": self.validate_result.__dict__ if self.validate_result else None,
            "worth_remembering_result": self.worth_remembering_result.__dict__ if self.worth_remembering_result else None,
            "final_decision": self.final_decision.value,
            "items_stored_via_memory_coordinator": self.items_stored_via_memory_coordinator,
            "items_kept_temporary": self.items_kept_temporary,
            "items_discarded": self.items_discarded,
            "duration_seconds": self.duration_seconds,
            "errors": self.errors,
            "warnings": self.warnings,
        }
