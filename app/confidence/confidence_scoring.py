"""Core confidence scoring classes and utilities.

This module defines the fundamental classes for representing and calculating
confidence scores in the Freya AI system.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Any, Optional, Callable
import json
from pathlib import Path
import uuid


class ConfidenceLevel(Enum):
    """Level of confidence in a decision or action."""
    CRITICAL = "critical"  # 0.0-0.2: Extremely low confidence, high risk
    LOW = "low"  # 0.2-0.4: Low confidence, caution advised
    MEDIUM = "medium"  # 0.4-0.6: Moderate confidence
    HIGH = "high"  # 0.6-0.8: High confidence
    VERY_HIGH = "very_high"  # 0.8-1.0: Very high confidence, low risk

    @property
    def min_score(self) -> float:
        """Minimum score for this level."""
        levels = {
            ConfidenceLevel.CRITICAL: 0.0,
            ConfidenceLevel.LOW: 0.2,
            ConfidenceLevel.MEDIUM: 0.4,
            ConfidenceLevel.HIGH: 0.6,
            ConfidenceLevel.VERY_HIGH: 0.8,
        }
        return levels.get(self, 0.0)

    @property
    def max_score(self) -> float:
        """Maximum score for this level."""
        levels = {
            ConfidenceLevel.CRITICAL: 0.2,
            ConfidenceLevel.LOW: 0.4,
            ConfidenceLevel.MEDIUM: 0.6,
            ConfidenceLevel.HIGH: 0.8,
            ConfidenceLevel.VERY_HIGH: 1.0,
        }
        return levels.get(self, 1.0)

    @property
    def description(self) -> str:
        """Human-readable description of this confidence level."""
        descriptions = {
            ConfidenceLevel.CRITICAL: "Extremely low confidence - High risk, verify manually",
            ConfidenceLevel.LOW: "Low confidence - Consider alternatives, review carefully",
            ConfidenceLevel.MEDIUM: "Moderate confidence - Generally safe but review recommended",
            ConfidenceLevel.HIGH: "High confidence - Safe to proceed with minimal review",
            ConfidenceLevel.VERY_HIGH: "Very high confidence - Safe to proceed without review",
        }
        return descriptions.get(self, "Unknown confidence level")

    @classmethod
    def from_score(cls, score: float) -> "ConfidenceLevel":
        """Get the confidence level for a given score."""
        if score >= 0.8:
            return cls.VERY_HIGH
        elif score >= 0.6:
            return cls.HIGH
        elif score >= 0.4:
            return cls.MEDIUM
        elif score >= 0.2:
            return cls.LOW
        return cls.CRITICAL


class ConfidenceEventType(Enum):
    """Type of event that affects confidence."""
    DECISION = "decision"  # A decision was made
    ACTION = "action"  # An action was executed
    RECOMMENDATION = "recommendation"  # A recommendation was provided
    VERIFICATION = "verification"  # A verification check passed/failed
    TEST = "test"  # A test was run
    ANALYSIS = "analysis"  # Code/file analysis was performed
    PATTERN_MATCH = "pattern_match"  # A known pattern was matched
    FALLBACK = "fallback"  # A fallback mechanism was used
    ERROR = "error"  # An error occurred
    SUCCESS = "success"  # An operation succeeded
    FAILURE = "failure"  # An operation failed


@dataclass
class ConfidenceEvent:
    """Represents an event that affects confidence calculation."""
    event_type: ConfidenceEventType
    event_id: str = field(default_factory=lambda: f"confidence_event_{uuid.uuid4().hex[:8]}")
    component: str = ""  # Which component generated this event
    description: str = ""  # Description of the event
    base_score: float = 0.5  # Base confidence score (0.0-1.0)
    weight: float = 1.0  # Weight of this event in overall calculation
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "event_type": self.event_type.value,
            "event_id": self.event_id,
            "component": self.component,
            "description": self.description,
            "base_score": self.base_score,
            "weight": self.weight,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConfidenceEvent":
        """Create from dictionary."""
        return cls(
            event_type=ConfidenceEventType(data.get("event_type", "decision")),
            event_id=data.get("event_id", f"confidence_event_{uuid.uuid4().hex[:8]}"),
            component=data.get("component", ""),
            description=data.get("description", ""),
            base_score=data.get("base_score", 0.5),
            weight=data.get("weight", 1.0),
            timestamp=data.get("timestamp", ""),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ConfidenceScore:
    """Represents a confidence score with context."""
    value: float  # 0.0 to 1.0
    level: ConfidenceLevel = ConfidenceLevel.MEDIUM
    event_count: int = 0  # Number of events contributing to this score
    events: List[ConfidenceEvent] = field(default_factory=list)
    component: str = ""  # Component that generated this score
    task: str = ""  # Task being evaluated
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if isinstance(self.level, str):
            self.level = ConfidenceLevel(self.level)
        if self.value < 0 or self.value > 1:
            raise ValueError("Confidence score must be between 0.0 and 1.0")
        # Only recalculate level from value if it's the default MEDIUM
        # This allows explicit level setting to take precedence
        if self.level == ConfidenceLevel.MEDIUM:
            self.level = ConfidenceLevel.from_score(self.value)

    @property
    def recommendation(self) -> str:
        """Get a recommendation based on the confidence level."""
        if self.level == ConfidenceLevel.CRITICAL:
            return "REJECT - Manual verification required"
        elif self.level == ConfidenceLevel.LOW:
            return "REVIEW - Human review strongly recommended"
        elif self.level == ConfidenceLevel.MEDIUM:
            return "ACCEPT - Proceed with caution"
        elif self.level == ConfidenceLevel.HIGH:
            return "ACCEPT - Safe to proceed"
        else:
            return "ACCEPT - Highly recommended"

    @property
    def color(self) -> str:
        """Get a color code for this confidence level."""
        colors = {
            ConfidenceLevel.CRITICAL: "red",
            ConfidenceLevel.LOW: "orange",
            ConfidenceLevel.MEDIUM: "yellow",
            ConfidenceLevel.HIGH: "light_green",
            ConfidenceLevel.VERY_HIGH: "green",
        }
        return colors.get(self.level, "gray")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "value": self.value,
            "level": self.level.value,
            "event_count": self.event_count,
            "events": [e.to_dict() for e in self.events],
            "component": self.component,
            "task": self.task,
            "timestamp": self.timestamp,
            "recommendation": self.recommendation,
            "color": self.color,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConfidenceScore":
        """Create from dictionary."""
        score = cls(
            value=data.get("value", 0.5),
            level=data.get("level", "medium"),
            event_count=data.get("event_count", 0),
            component=data.get("component", ""),
            task=data.get("task", ""),
            timestamp=data.get("timestamp", ""),
            metadata=data.get("metadata", {}),
        )
        score.events = [ConfidenceEvent.from_dict(e) for e in data.get("events", [])]
        return score

    def __str__(self) -> str:
        return f"ConfidenceScore(value={self.value:.2f}, level={self.level.value}, recommendation='{self.recommendation}')"


class ConfidenceCalculator:
    """Calculates confidence scores from events.

    Uses a weighted average approach where each event contributes to the
    overall confidence based on its base score and weight.
    """

    def __init__(self):
        self._event_weights: Dict[ConfidenceEventType, float] = {
            ConfidenceEventType.DECISION: 1.0,
            ConfidenceEventType.ACTION: 1.2,
            ConfidenceEventType.RECOMMENDATION: 1.0,
            ConfidenceEventType.VERIFICATION: 1.5,
            ConfidenceEventType.TEST: 1.3,
            ConfidenceEventType.ANALYSIS: 1.1,
            ConfidenceEventType.PATTERN_MATCH: 1.4,
            ConfidenceEventType.FALLBACK: 0.5,
            ConfidenceEventType.ERROR: 0.1,
            ConfidenceEventType.SUCCESS: 1.0,
            ConfidenceEventType.FAILURE: 0.2,
        }
        self._default_weight = 1.0

    def calculate(self, events: List[ConfidenceEvent]) -> ConfidenceScore:
        """Calculate a confidence score from a list of events.

        Args:
            events: List of confidence events to evaluate

        Returns:
            ConfidenceScore with aggregated value and level
        """
        if not events:
            return ConfidenceScore(
                value=0.5,
                level=ConfidenceLevel.MEDIUM,
                event_count=0,
                events=[],
            )

        weighted_sum = 0.0
        total_weight = 0.0

        for event in events:
            weight = self._event_weights.get(event.event_type, self._default_weight)
            weighted_score = event.base_score * weight * event.weight
            weighted_sum += weighted_score
            total_weight += weight * event.weight

        if total_weight == 0:
            average_score = 0.5
        else:
            average_score = weighted_sum / total_weight

        # Clamp to 0-1 range
        average_score = max(0.0, min(1.0, average_score))

        return ConfidenceScore(
            value=average_score,
            level=ConfidenceLevel.from_score(average_score),
            event_count=len(events),
            events=events.copy(),
        )

    def calculate_by_component(self, events: List[ConfidenceEvent]) -> Dict[str, ConfidenceScore]:
        """Calculate confidence scores grouped by component.

        Args:
            events: List of confidence events

        Returns:
            Dictionary mapping component names to ConfidenceScore
        """
        by_component: Dict[str, List[ConfidenceEvent]] = {}
        for event in events:
            component = event.component or "unknown"
            if component not in by_component:
                by_component[component] = []
            by_component[component].append(event)

        return {
            component: self.calculate(component_events)
            for component, component_events in by_component.items()
        }

    def adjust_for_risk(self, score: ConfidenceScore, risk_level: str) -> ConfidenceScore:
        """Adjust confidence score based on risk level.

        Higher risk should decrease confidence.

        Args:
            score: The original confidence score
            risk_level: The risk level (e.g., 'critical', 'high', 'medium', 'low')

        Returns:
            Adjusted confidence score
        """
        risk_multipliers = {
            "critical": 0.2,
            "high": 0.4,
            "medium": 0.7,
            "low": 0.9,
            "info": 1.0,
        }
        multiplier = risk_multipliers.get(risk_level.lower(), 0.7)

        new_value = score.value * multiplier
        new_value = max(0.0, min(1.0, new_value))

        return ConfidenceScore(
            value=new_value,
            level=ConfidenceLevel.from_score(new_value),
            event_count=score.event_count,
            events=score.events,
            component=score.component,
            task=score.task,
            metadata={**score.metadata, "risk_adjusted": True, "risk_level": risk_level},
        )


class ConfidenceTracker:
    """Tracks confidence events and scores over time.

    Maintains a history of confidence scores and events for analysis
    and reporting.
    """

    def __init__(self, workspace: Optional[str] = None):
        self._events: List[ConfidenceEvent] = []
        self._scores: List[ConfidenceScore] = []
        self._workspace = Path(workspace) if workspace else Path(".")
        self._history_file = self._workspace / ".confidence_history.json"
        self._load_history()

    def _load_history(self) -> None:
        """Load history from disk."""
        if not self._history_file.exists():
            return
        try:
            with open(self._history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._events = [ConfidenceEvent.from_dict(e) for e in data.get("events", [])]
                self._scores = [ConfidenceScore.from_dict(s) for s in data.get("scores", [])]
        except Exception as e:
            print(f"Error loading confidence history: {e}")

    def _save_history(self) -> None:
        """Save history to disk."""
        self._workspace.mkdir(parents=True, exist_ok=True)
        data = {
            "events": [e.to_dict() for e in self._events],
            "scores": [s.to_dict() for s in self._scores],
        }
        try:
            with open(self._history_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving confidence history: {e}")

    def add_event(self, event: ConfidenceEvent) -> None:
        """Add a confidence event to the tracker.

        Args:
            event: The confidence event to add
        """
        self._events.append(event)
        self._save_history()

    def add_score(self, score: ConfidenceScore) -> None:
        """Add a confidence score to the tracker.

        Args:
            score: The confidence score to add
        """
        self._scores.append(score)
        self._save_history()

    def calculate_current(self) -> ConfidenceScore:
        """Calculate the current confidence score from all events.

        Returns:
            Aggregated confidence score
        """
        calculator = ConfidenceCalculator()
        return calculator.calculate(self._events)

    def get_events(
        self,
        event_type: Optional[ConfidenceEventType] = None,
        component: Optional[str] = None,
        since: Optional[str] = None,
    ) -> List[ConfidenceEvent]:
        """Get confidence events with optional filters.

        Args:
            event_type: Filter by event type
            component: Filter by component
            since: Filter by timestamp (ISO format)

        Returns:
            List of matching events
        """
        events = self._events

        if event_type:
            events = [e for e in events if e.event_type == event_type]
        if component:
            events = [e for e in events if e.component == component]
        if since:
            events = [e for e in events if e.timestamp >= since]

        return events

    def get_scores(
        self,
        component: Optional[str] = None,
        since: Optional[str] = None,
    ) -> List[ConfidenceScore]:
        """Get confidence scores with optional filters.

        Args:
            component: Filter by component
            since: Filter by timestamp (ISO format)

        Returns:
            List of matching scores
        """
        scores = self._scores

        if component:
            scores = [s for s in scores if s.component == component]
        if since:
            scores = [s for s in scores if s.timestamp >= since]

        return scores

    @property
    def average_confidence(self) -> float:
        """Get the average confidence score."""
        if not self._scores:
            return 0.5
        return sum(s.value for s in self._scores) / len(self._scores)

    @property
    def event_count(self) -> int:
        """Get the total number of events."""
        return len(self._events)

    @property
    def score_count(self) -> int:
        """Get the total number of scores."""
        return len(self._scores)

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of confidence tracking data.

        Returns:
            Summary dictionary with statistics
        """
        calculator = ConfidenceCalculator()
        current = calculator.calculate(self._events)

        # Count events by type
        by_type: Dict[str, int] = {}
        for event in self._events:
            type_key = event.event_type.value
            by_type[type_key] = by_type.get(type_key, 0) + 1

        # Count events by component
        by_component: Dict[str, int] = {}
        for event in self._events:
            component = event.component or "unknown"
            by_component[component] = by_component.get(component, 0) + 1

        # Count scores by level
        by_level: Dict[str, int] = {}
        for score in self._scores:
            level_key = score.level.value
            by_level[level_key] = by_level.get(level_key, 0) + 1

        return {
            "current_confidence": current.to_dict(),
            "average_confidence": self.average_confidence,
            "total_events": self.event_count,
            "total_scores": self.score_count,
            "events_by_type": by_type,
            "events_by_component": by_component,
            "scores_by_level": by_level,
        }

    def clear(self) -> None:
        """Clear all tracked data."""
        self._events = []
        self._scores = []
        try:
            self._history_file.unlink()
        except FileNotFoundError:
            pass
