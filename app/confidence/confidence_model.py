"""Confidence models for different types of agent decisions.

This module defines specialized confidence models for different types of
operations (decisions, actions, recommendations) with their own scoring logic.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from enum import Enum

from app.confidence.confidence_scoring import (
    ConfidenceScore,
    ConfidenceLevel,
    ConfidenceEvent,
    ConfidenceEventType,
)


class DecisionType(Enum):
    """Type of decision being made."""
    CODE_CHANGE = "code_change"  # Modifying code
    ARCHITECTURE = "architecture"  # Architectural decision
    DEPENDENCY = "dependency"  # Adding/changing dependencies
    CONFIGURATION = "configuration"  # Configuration change
    DEPLOYMENT = "deployment"  # Deployment decision
    TESTING = "testing"  # Testing strategy
    REFACTORING = "refactoring"  # Code refactoring
    FEATURE = "feature"  # New feature implementation
    BUG_FIX = "bug_fix"  # Bug fix
    DOCUMENTATION = "documentation"  # Documentation change


class ActionType(Enum):
    """Type of action being executed."""
    FILE_EDIT = "file_edit"  # Editing a file
    FILE_CREATE = "file_create"  # Creating a new file
    FILE_DELETE = "file_delete"  # Deleting a file
    TOOL_EXECUTION = "tool_execution"  # Running a tool
    COMMAND_EXECUTION = "command_execution"  # Running a shell command
    API_CALL = "api_call"  # Making an API call
    TEST_RUN = "test_run"  # Running tests
    BUILD = "build"  # Building the project
    DEPLOY = "deploy"  # Deploying


class RecommendationType(Enum):
    """Type of recommendation being provided."""
    CODE_IMPROVEMENT = "code_improvement"  # Code quality improvement
    PERFORMANCE = "performance"  # Performance optimization
    SECURITY = "security"  # Security fix
    ARCHITECTURE = "architecture"  # Architectural change
    BEST_PRACTICE = "best_practice"  # Best practice suggestion
    STYLE = "style"  # Code style
    DOCUMENTATION = "documentation"  # Documentation improvement
    TESTING = "testing"  # Testing improvement


@dataclass
class DecisionConfidence:
    """Confidence model for agent decisions.

    Evaluates confidence based on:
    - Complexity of the decision
    - Number of alternatives considered
    - Alignment with best practices
    - Potential impact
    - Available context
    """
    decision_type: DecisionType
    decision: str  # Description of the decision
    rationale: str = ""  # Reasoning behind the decision
    alternatives_considered: int = 1  # Number of alternatives considered
    complexity: float = 0.5  # 0.0-1.0, higher = more complex
    impact: float = 0.5  # 0.0-1.0, higher = more impact
    context_quality: float = 0.5  # 0.0-1.0, quality of available context
    best_practice_alignment: float = 0.5  # 0.0-1.0, alignment with best practices
    base_score: float = 0.5
    events: List[ConfidenceEvent] = field(default_factory=list)

    @property
    def confidence_score(self) -> ConfidenceScore:
        """Calculate the overall confidence score."""
        # Start with base score
        score_value = self.base_score

        # Adjust based on complexity (more complex = potentially lower confidence)
        complexity_factor = 1.0 - (self.complexity * 0.3)  # Max 30% reduction

        # Adjust based on alternatives considered (more alternatives = higher confidence)
        alternatives_factor = min(1.0, self.alternatives_considered * 0.15)  # Max 150%

        # Adjust based on context quality
        context_factor = self.context_quality

        # Adjust based on best practice alignment
        practice_factor = self.best_practice_alignment

        # Impact modifier (high impact decisions need higher confidence)
        impact_modifier = 1.0 - ((1.0 - self.impact) * 0.2)  # Less impact = less strict

        # Calculate weighted score
        score_value = (
            score_value * complexity_factor * 0.25 +
            score_value * alternatives_factor * 0.20 +
            score_value * context_factor * 0.25 +
            score_value * practice_factor * 0.20 +
            score_value * impact_modifier * 0.10
        )

        score_value = max(0.0, min(1.0, score_value))

        # Create confidence events
        events = [
            ConfidenceEvent(
                event_type=ConfidenceEventType.DECISION,
                component="decision_model",
                description=f"Decision: {self.decision}",
                base_score=score_value,
                weight=1.0,
                metadata={
                    "decision_type": self.decision_type.value,
                    "complexity": self.complexity,
                    "alternatives": self.alternatives_considered,
                    "impact": self.impact,
                },
            ),
        ]

        return ConfidenceScore(
            value=score_value,
            level=ConfidenceLevel.from_score(score_value),
            event_count=1,
            events=events + self.events,
            component="decision_model",
            task=self.decision,
            metadata={
                "decision_type": self.decision_type.value,
                "complexity": self.complexity,
                "alternatives_considered": self.alternatives_considered,
                "impact": self.impact,
                "context_quality": self.context_quality,
                "best_practice_alignment": self.best_practice_alignment,
            },
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        score = self.confidence_score
        return {
            "decision_type": self.decision_type.value,
            "decision": self.decision,
            "rationale": self.rationale,
            "alternatives_considered": self.alternatives_considered,
            "complexity": self.complexity,
            "impact": self.impact,
            "context_quality": self.context_quality,
            "best_practice_alignment": self.best_practice_alignment,
            "base_score": self.base_score,
            "confidence_score": score.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DecisionConfidence":
        """Create from dictionary."""
        return cls(
            decision_type=DecisionType(data.get("decision_type", "code_change")),
            decision=data.get("decision", ""),
            rationale=data.get("rationale", ""),
            alternatives_considered=data.get("alternatives_considered", 1),
            complexity=data.get("complexity", 0.5),
            impact=data.get("impact", 0.5),
            context_quality=data.get("context_quality", 0.5),
            best_practice_alignment=data.get("best_practice_alignment", 0.5),
            base_score=data.get("base_score", 0.5),
        )


@dataclass
class ActionConfidence:
    """Confidence model for agent actions.

    Evaluates confidence based on:
    - Type of action
    - Whether the action is reversible
    - Potential side effects
    - Historical success rate
    - Current system state
    """
    action_type: ActionType
    action: str  # Description of the action
    reversible: bool = True  # Whether the action can be undone
    side_effects: List[str] = field(default_factory=list)  # Potential side effects
    historical_success_rate: float = 0.9  # 0.0-1.0, historical success rate
    system_state: str = "normal"  # Current system state (normal, degraded, critical)
    base_score: float = 0.5
    events: List[ConfidenceEvent] = field(default_factory=list)

    @property
    def confidence_score(self) -> ConfidenceScore:
        """Calculate the overall confidence score."""
        score_value = self.base_score

        # Reversibility factor (reversible actions are safer)
        reversibility_factor = 1.0 if self.reversible else 0.5

        # Side effects factor (more side effects = lower confidence)
        side_effects_penalty = len(self.side_effects) * 0.05
        side_effects_factor = 1.0 - min(0.5, side_effects_penalty)

        # Historical success factor
        success_factor = self.historical_success_rate

        # System state factor
        state_factors = {
            "normal": 1.0,
            "degraded": 0.7,
            "critical": 0.3,
        }
        state_factor = state_factors.get(self.system_state, 1.0)

        # Action type factors
        action_type_factors = {
            ActionType.FILE_EDIT: 0.9,
            ActionType.FILE_CREATE: 0.8,
            ActionType.FILE_DELETE: 0.4,
            ActionType.TOOL_EXECUTION: 0.7,
            ActionType.COMMAND_EXECUTION: 0.5,
            ActionType.API_CALL: 0.6,
            ActionType.TEST_RUN: 0.9,
            ActionType.BUILD: 0.8,
            ActionType.DEPLOY: 0.3,
        }
        action_factor = action_type_factors.get(self.action_type, 0.5)

        # Calculate weighted score
        score_value = (
            score_value * reversibility_factor * 0.20 +
            score_value * side_effects_factor * 0.15 +
            score_value * success_factor * 0.25 +
            score_value * state_factor * 0.15 +
            score_value * action_factor * 0.25
        )

        score_value = max(0.0, min(1.0, score_value))

        # Create confidence events
        events = [
            ConfidenceEvent(
                event_type=ConfidenceEventType.ACTION,
                component="action_model",
                description=f"Action: {self.action}",
                base_score=score_value,
                weight=1.0,
                metadata={
                    "action_type": self.action_type.value,
                    "reversible": self.reversible,
                    "side_effects_count": len(self.side_effects),
                    "historical_success_rate": self.historical_success_rate,
                    "system_state": self.system_state,
                },
            ),
        ]

        return ConfidenceScore(
            value=score_value,
            level=ConfidenceLevel.from_score(score_value),
            event_count=1,
            events=events + self.events,
            component="action_model",
            task=self.action,
            metadata={
                "action_type": self.action_type.value,
                "reversible": self.reversible,
                "side_effects": self.side_effects,
                "historical_success_rate": self.historical_success_rate,
                "system_state": self.system_state,
            },
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        score = self.confidence_score
        return {
            "action_type": self.action_type.value,
            "action": self.action,
            "reversible": self.reversible,
            "side_effects": self.side_effects,
            "historical_success_rate": self.historical_success_rate,
            "system_state": self.system_state,
            "base_score": self.base_score,
            "confidence_score": score.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ActionConfidence":
        """Create from dictionary."""
        return cls(
            action_type=ActionType(data.get("action_type", "file_edit")),
            action=data.get("action", ""),
            reversible=data.get("reversible", True),
            side_effects=data.get("side_effects", []),
            historical_success_rate=data.get("historical_success_rate", 0.9),
            system_state=data.get("system_state", "normal"),
            base_score=data.get("base_score", 0.5),
        )


@dataclass
class RecommendationConfidence:
    """Confidence model for agent recommendations.

    Evaluates confidence based on:
    - Type of recommendation
    - Evidence supporting the recommendation
    - Potential benefit
    - Potential risk
    - Source reliability
    - Applicability to current context
    """
    recommendation_type: RecommendationType
    recommendation: str  # Description of the recommendation
    evidence: List[str] = field(default_factory=list)  # Evidence supporting the recommendation
    potential_benefit: float = 0.5  # 0.0-1.0, potential benefit
    potential_risk: float = 0.5  # 0.0-1.0, potential risk
    source_reliability: float = 0.8  # 0.0-1.0, reliability of the source
    applicability: float = 0.8  # 0.0-1.0, applicability to current context
    base_score: float = 0.5
    events: List[ConfidenceEvent] = field(default_factory=list)

    @property
    def confidence_score(self) -> ConfidenceScore:
        """Calculate the overall confidence score."""
        score_value = self.base_score

        # Evidence factor (more evidence = higher confidence)
        evidence_count = len(self.evidence)
        evidence_factor = min(1.0, evidence_count * 0.15)  # Max 150%

        # Benefit factor (higher benefit = higher priority, but not necessarily higher confidence)
        benefit_factor = self.potential_benefit * 0.1 + 0.9

        # Risk factor (higher risk = lower confidence)
        risk_factor = 1.0 - (self.potential_risk * 0.5)  # Max 50% reduction

        # Source reliability factor
        source_factor = self.source_reliability

        # Applicability factor
        applicability_factor = self.applicability

        # Recommendation type factors
        type_factors = {
            RecommendationType.CODE_IMPROVEMENT: 0.9,
            RecommendationType.PERFORMANCE: 0.9,
            RecommendationType.SECURITY: 0.95,
            RecommendationType.ARCHITECTURE: 0.7,
            RecommendationType.BEST_PRACTICE: 0.9,
            RecommendationType.STYLE: 0.6,
            RecommendationType.DOCUMENTATION: 0.8,
            RecommendationType.TESTING: 0.85,
        }
        type_factor = type_factors.get(self.recommendation_type, 0.7)

        # Calculate weighted score
        score_value = (
            score_value * evidence_factor * 0.25 +
            score_value * benefit_factor * 0.10 +
            score_value * risk_factor * 0.20 +
            score_value * source_factor * 0.15 +
            score_value * applicability_factor * 0.15 +
            score_value * type_factor * 0.15
        )

        score_value = max(0.0, min(1.0, score_value))

        # Create confidence events
        events = [
            ConfidenceEvent(
                event_type=ConfidenceEventType.RECOMMENDATION,
                component="recommendation_model",
                description=f"Recommendation: {self.recommendation}",
                base_score=score_value,
                weight=1.0,
                metadata={
                    "recommendation_type": self.recommendation_type.value,
                    "evidence_count": len(self.evidence),
                    "potential_benefit": self.potential_benefit,
                    "potential_risk": self.potential_risk,
                    "source_reliability": self.source_reliability,
                    "applicability": self.applicability,
                },
            ),
        ]

        return ConfidenceScore(
            value=score_value,
            level=ConfidenceLevel.from_score(score_value),
            event_count=1,
            events=events + self.events,
            component="recommendation_model",
            task=self.recommendation,
            metadata={
                "recommendation_type": self.recommendation_type.value,
                "evidence": self.evidence,
                "potential_benefit": self.potential_benefit,
                "potential_risk": self.potential_risk,
                "source_reliability": self.source_reliability,
                "applicability": self.applicability,
            },
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        score = self.confidence_score
        return {
            "recommendation_type": self.recommendation_type.value,
            "recommendation": self.recommendation,
            "evidence": self.evidence,
            "potential_benefit": self.potential_benefit,
            "potential_risk": self.potential_risk,
            "source_reliability": self.source_reliability,
            "applicability": self.applicability,
            "base_score": self.base_score,
            "confidence_score": score.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RecommendationConfidence":
        """Create from dictionary."""
        return cls(
            recommendation_type=RecommendationType(data.get("recommendation_type", "code_improvement")),
            recommendation=data.get("recommendation", ""),
            evidence=data.get("evidence", []),
            potential_benefit=data.get("potential_benefit", 0.5),
            potential_risk=data.get("potential_risk", 0.5),
            source_reliability=data.get("source_reliability", 0.8),
            applicability=data.get("applicability", 0.8),
            base_score=data.get("base_score", 0.5),
        )


@dataclass
class ConfidenceModel:
    """Main confidence model that combines all sub-models.

    Provides a unified interface for calculating confidence across
    decisions, actions, and recommendations.
    """
    decision_model: Optional[DecisionConfidence] = None
    action_model: Optional[ActionConfidence] = None
    recommendation_model: Optional[RecommendationConfidence] = None

    def calculate(self) -> ConfidenceScore:
        """Calculate overall confidence from all models.

        Returns:
            Aggregated confidence score
        """
        from app.confidence.confidence_scoring import ConfidenceCalculator

        calculator = ConfidenceCalculator()
        events: List[ConfidenceEvent] = []

        if self.decision_model:
            score = self.decision_model.confidence_score
            events.extend(score.events)

        if self.action_model:
            score = self.action_model.confidence_score
            events.extend(score.events)

        if self.recommendation_model:
            score = self.recommendation_model.confidence_score
            events.extend(score.events)

        if not events:
            return ConfidenceScore(
                value=0.5,
                level=ConfidenceLevel.MEDIUM,
                event_count=0,
                events=[],
            )

        return calculator.calculate(events)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "decision_model": self.decision_model.to_dict() if self.decision_model else None,
            "action_model": self.action_model.to_dict() if self.action_model else None,
            "recommendation_model": self.recommendation_model.to_dict() if self.recommendation_model else None,
            "overall_score": self.calculate().to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConfidenceModel":
        """Create from dictionary."""
        return cls(
            decision_model=DecisionConfidence.from_dict(data["decision_model"])
            if data.get("decision_model") else None,
            action_model=ActionConfidence.from_dict(data["action_model"])
            if data.get("action_model") else None,
            recommendation_model=RecommendationConfidence.from_dict(data["recommendation_model"])
            if data.get("recommendation_model") else None,
        )
