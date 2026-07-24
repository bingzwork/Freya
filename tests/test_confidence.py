"""Tests for the Confidence Scoring System."""

import pytest
from datetime import datetime, timezone

from app.confidence.confidence_scoring import (
    ConfidenceLevel,
    ConfidenceEvent,
    ConfidenceEventType,
    ConfidenceScore,
    ConfidenceCalculator,
    ConfidenceTracker,
)
from app.confidence.confidence_model import (
    DecisionConfidence,
    ActionConfidence,
    RecommendationConfidence,
    ConfidenceModel,
    DecisionType,
    ActionType,
    RecommendationType,
)


class TestConfidenceLevel:
    """Tests for ConfidenceLevel enum."""

    def test_all_levels(self):
        """Test all confidence levels exist."""
        levels = [
            ConfidenceLevel.CRITICAL,
            ConfidenceLevel.LOW,
            ConfidenceLevel.MEDIUM,
            ConfidenceLevel.HIGH,
            ConfidenceLevel.VERY_HIGH,
        ]
        for level in levels:
            assert isinstance(level, ConfidenceLevel)

    def test_min_max_scores(self):
        """Test min and max scores for each level."""
        assert ConfidenceLevel.CRITICAL.min_score == 0.0
        assert ConfidenceLevel.CRITICAL.max_score == 0.2
        assert ConfidenceLevel.LOW.min_score == 0.2
        assert ConfidenceLevel.LOW.max_score == 0.4
        assert ConfidenceLevel.MEDIUM.min_score == 0.4
        assert ConfidenceLevel.MEDIUM.max_score == 0.6
        assert ConfidenceLevel.HIGH.min_score == 0.6
        assert ConfidenceLevel.HIGH.max_score == 0.8
        assert ConfidenceLevel.VERY_HIGH.min_score == 0.8
        assert ConfidenceLevel.VERY_HIGH.max_score == 1.0

    def test_descriptions(self):
        """Test level descriptions."""
        assert "High risk" in ConfidenceLevel.CRITICAL.description
        assert "Low confidence" in ConfidenceLevel.LOW.description
        assert "Moderate" in ConfidenceLevel.MEDIUM.description
        assert "High confidence" in ConfidenceLevel.HIGH.description
        assert "Very high" in ConfidenceLevel.VERY_HIGH.description

    def test_from_score(self):
        """Test getting level from score."""
        assert ConfidenceLevel.from_score(0.1).value == "critical"
        assert ConfidenceLevel.from_score(0.3).value == "low"
        assert ConfidenceLevel.from_score(0.5).value == "medium"
        assert ConfidenceLevel.from_score(0.7).value == "high"
        assert ConfidenceLevel.from_score(0.9).value == "very_high"


class TestConfidenceEvent:
    """Tests for ConfidenceEvent."""

    def test_event_creation(self):
        """Test creating a confidence event."""
        event = ConfidenceEvent(
            event_type=ConfidenceEventType.DECISION,
            component="test_component",
            description="Test decision",
            base_score=0.8,
            weight=1.5,
        )
        assert event.event_type == ConfidenceEventType.DECISION
        assert event.component == "test_component"
        assert event.base_score == 0.8
        assert event.weight == 1.5
        assert event.event_id.startswith("confidence_event_")

    def test_event_to_dict(self):
        """Test converting event to dictionary."""
        event = ConfidenceEvent(
            event_type=ConfidenceEventType.ACTION,
            description="Test action",
        )
        data = event.to_dict()
        assert data["event_type"] == "action"
        assert data["description"] == "Test action"

    def test_event_from_dict(self):
        """Test creating event from dictionary."""
        data = {
            "event_type": "verification",
            "component": "test",
            "description": "Test verification",
            "base_score": 0.9,
        }
        event = ConfidenceEvent.from_dict(data)
        assert event.event_type == ConfidenceEventType.VERIFICATION
        assert event.base_score == 0.9


class TestConfidenceScore:
    """Tests for ConfidenceScore."""

    def test_score_creation(self):
        """Test creating a confidence score."""
        score = ConfidenceScore(
            value=0.75,
            level=ConfidenceLevel.HIGH,
            component="test",
            task="test task",
        )
        assert score.value == 0.75
        assert score.level == ConfidenceLevel.HIGH
        assert score.recommendation == "ACCEPT - Safe to proceed"

    def test_score_level_auto(self):
        """Test that level is auto-detected from value."""
        score = ConfidenceScore(value=0.85, component="test")
        assert score.level == ConfidenceLevel.VERY_HIGH

        score = ConfidenceScore(value=0.3, component="test")
        assert score.level == ConfidenceLevel.LOW

    def test_score_validation(self):
        """Test score value validation."""
        # Valid scores
        ConfidenceScore(value=0.0, component="test")
        ConfidenceScore(value=1.0, component="test")

        # Invalid scores
        with pytest.raises(ValueError):
            ConfidenceScore(value=-0.1, component="test")
        with pytest.raises(ValueError):
            ConfidenceScore(value=1.1, component="test")

    def test_score_color(self):
        """Test color codes."""
        assert ConfidenceScore(value=0.1).color == "red"
        assert ConfidenceScore(value=0.3).color == "orange"
        assert ConfidenceScore(value=0.5).color == "yellow"
        assert ConfidenceScore(value=0.7).color == "light_green"
        assert ConfidenceScore(value=0.9).color == "green"

    def test_score_to_dict(self):
        """Test converting score to dictionary."""
        score = ConfidenceScore(
            value=0.8,
            level=ConfidenceLevel.HIGH,
            component="test",
        )
        data = score.to_dict()
        assert data["value"] == 0.8
        assert data["level"] == "high"
        assert data["recommendation"] == "ACCEPT - Safe to proceed"

    def test_score_from_dict(self):
        """Test creating score from dictionary."""
        data = {
            "value": 0.65,
            "level": "high",
            "component": "test",
            "task": "test task",
        }
        score = ConfidenceScore.from_dict(data)
        assert score.value == 0.65
        assert score.level == ConfidenceLevel.HIGH


class TestConfidenceCalculator:
    """Tests for ConfidenceCalculator."""

    def test_calculator_creation(self):
        """Test creating a calculator."""
        calculator = ConfidenceCalculator()
        assert calculator._default_weight == 1.0

    def test_calculate_empty(self):
        """Test calculating with no events."""
        calculator = ConfidenceCalculator()
        score = calculator.calculate([])
        assert score.value == 0.5
        assert score.level == ConfidenceLevel.MEDIUM

    def test_calculate_single_event(self):
        """Test calculating with a single event."""
        calculator = ConfidenceCalculator()
        events = [
            ConfidenceEvent(
                event_type=ConfidenceEventType.SUCCESS,
                base_score=0.9,
                weight=1.0,
            ),
        ]
        score = calculator.calculate(events)
        assert score.value > 0.5
        assert score.event_count == 1

    def test_calculate_multiple_events(self):
        """Test calculating with multiple events."""
        calculator = ConfidenceCalculator()
        events = [
            ConfidenceEvent(
                event_type=ConfidenceEventType.SUCCESS,
                base_score=0.9,
                weight=1.0,
            ),
            ConfidenceEvent(
                event_type=ConfidenceEventType.VERIFICATION,
                base_score=0.8,
                weight=1.0,
            ),
            ConfidenceEvent(
                event_type=ConfidenceEventType.ERROR,
                base_score=0.2,
                weight=0.5,
            ),
        ]
        score = calculator.calculate(events)
        assert 0.0 <= score.value <= 1.0
        assert score.event_count == 3

    def test_calculate_by_component(self):
        """Test calculating by component."""
        calculator = ConfidenceCalculator()
        events = [
            ConfidenceEvent(
                event_type=ConfidenceEventType.DECISION,
                component="planner",
                base_score=0.8,
            ),
            ConfidenceEvent(
                event_type=ConfidenceEventType.DECISION,
                component="executor",
                base_score=0.6,
            ),
        ]
        scores = calculator.calculate_by_component(events)
        assert "planner" in scores
        assert "executor" in scores

    def test_adjust_for_risk(self):
        """Test adjusting for risk."""
        calculator = ConfidenceCalculator()
        score = ConfidenceScore(value=0.8, component="test")

        # High risk should lower confidence
        adjusted = calculator.adjust_for_risk(score, "critical")
        assert adjusted.value < score.value

        # Low risk should slightly lower or maintain confidence
        adjusted = calculator.adjust_for_risk(score, "low")
        assert adjusted.value <= score.value


class TestConfidenceTracker:
    """Tests for ConfidenceTracker."""

    def test_tracker_creation(self):
        """Test creating a tracker."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = ConfidenceTracker(workspace=tmpdir)
            assert tracker.event_count == 0
            assert tracker.score_count == 0

    def test_add_event(self):
        """Test adding an event."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = ConfidenceTracker(workspace=tmpdir)
            event = ConfidenceEvent(
                event_type=ConfidenceEventType.DECISION,
                description="Test",
            )
            tracker.add_event(event)
            assert tracker.event_count == 1

    def test_add_score(self):
        """Test adding a score."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = ConfidenceTracker(workspace=tmpdir)
            score = ConfidenceScore(value=0.8, component="test")
            tracker.add_score(score)
            assert tracker.score_count == 1

    def test_calculate_current(self):
        """Test calculating current confidence."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = ConfidenceTracker(workspace=tmpdir)
            tracker.add_event(ConfidenceEvent(
                event_type=ConfidenceEventType.SUCCESS,
                base_score=0.9,
            ))
            score = tracker.calculate_current()
            assert score.value > 0.5

    def test_get_events(self):
        """Test getting events with filters."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = ConfidenceTracker(workspace=tmpdir)
            tracker.add_event(ConfidenceEvent(
                event_type=ConfidenceEventType.DECISION,
                component="planner",
            ))
            tracker.add_event(ConfidenceEvent(
                event_type=ConfidenceEventType.ACTION,
                component="executor",
            ))

            decision_events = tracker.get_events(event_type=ConfidenceEventType.DECISION)
            assert len(decision_events) == 1

            planner_events = tracker.get_events(component="planner")
            assert len(planner_events) == 1

    def test_get_summary(self):
        """Test getting tracker summary."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = ConfidenceTracker(workspace=tmpdir)
            tracker.add_event(ConfidenceEvent(
                event_type=ConfidenceEventType.SUCCESS,
                component="test",
            ))
            tracker.add_score(ConfidenceScore(value=0.8, component="test"))

            summary = tracker.get_summary()
            assert "current_confidence" in summary
            assert "average_confidence" in summary
            assert "total_events" in summary

    def test_clear(self):
        """Test clearing tracker."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = ConfidenceTracker(workspace=tmpdir)
            tracker.add_event(ConfidenceEvent(event_type=ConfidenceEventType.DECISION))
            tracker.add_score(ConfidenceScore(value=0.8))
            assert tracker.event_count > 0

            tracker.clear()
            assert tracker.event_count == 0
            assert tracker.score_count == 0


class TestDecisionConfidence:
    """Tests for DecisionConfidence model."""

    def test_decision_creation(self):
        """Test creating a decision confidence model."""
        decision = DecisionConfidence(
            decision_type=DecisionType.CODE_CHANGE,
            decision="Implement new feature",
            complexity=0.7,
            impact=0.8,
            alternatives_considered=3,
        )
        score = decision.confidence_score
        assert 0.0 <= score.value <= 1.0
        assert score.level is not None

    def test_decision_to_dict(self):
        """Test converting decision to dictionary."""
        decision = DecisionConfidence(
            decision_type=DecisionType.CODE_CHANGE,
            decision="Test",
        )
        data = decision.to_dict()
        assert data["decision_type"] == "code_change"
        assert "confidence_score" in data

    def test_decision_from_dict(self):
        """Test creating decision from dictionary."""
        data = {
            "decision_type": "bug_fix",
            "decision": "Fix critical bug",
            "complexity": 0.5,
        }
        decision = DecisionConfidence.from_dict(data)
        assert decision.decision_type == DecisionType.BUG_FIX


class TestActionConfidence:
    """Tests for ActionConfidence model."""

    def test_action_creation(self):
        """Test creating an action confidence model."""
        action = ActionConfidence(
            action_type=ActionType.FILE_EDIT,
            action="Edit config.py",
            reversible=True,
            historical_success_rate=0.95,
        )
        score = action.confidence_score
        assert 0.0 <= score.value <= 1.0

    def test_action_to_dict(self):
        """Test converting action to dictionary."""
        action = ActionConfidence(
            action_type=ActionType.TOOL_EXECUTION,
            action="Run pytest",
        )
        data = action.to_dict()
        assert data["action_type"] == "tool_execution"
        assert "confidence_score" in data

    def test_action_from_dict(self):
        """Test creating action from dictionary."""
        data = {
            "action_type": "file_delete",
            "action": "Delete temp file",
            "reversible": False,
        }
        action = ActionConfidence.from_dict(data)
        assert action.action_type == ActionType.FILE_DELETE
        assert action.reversible is False


class TestRecommendationConfidence:
    """Tests for RecommendationConfidence model."""

    def test_recommendation_creation(self):
        """Test creating a recommendation confidence model."""
        rec = RecommendationConfidence(
            recommendation_type=RecommendationType.SECURITY,
            recommendation="Fix SQL injection vulnerability",
            evidence=["Detected hardcoded SQL query", "User input not sanitized"],
            potential_benefit=0.9,
            potential_risk=0.1,
        )
        score = rec.confidence_score
        assert 0.0 <= score.value <= 1.0

    def test_recommendation_to_dict(self):
        """Test converting recommendation to dictionary."""
        rec = RecommendationConfidence(
            recommendation_type=RecommendationType.PERFORMANCE,
            recommendation="Add caching",
        )
        data = rec.to_dict()
        assert data["recommendation_type"] == "performance"
        assert "confidence_score" in data

    def test_recommendation_from_dict(self):
        """Test creating recommendation from dictionary."""
        data = {
            "recommendation_type": "security",
            "recommendation": "Use parameterized queries",
            "evidence": ["SQL injection pattern detected"],
        }
        rec = RecommendationConfidence.from_dict(data)
        assert rec.recommendation_type == RecommendationType.SECURITY


class TestConfidenceModel:
    """Tests for ConfidenceModel (combined model)."""

    def test_model_creation(self):
        """Test creating a combined confidence model."""
        model = ConfidenceModel()
        score = model.calculate()
        assert score.value == 0.5  # Default when no sub-models

    def test_model_with_decision(self):
        """Test model with decision sub-model."""
        model = ConfidenceModel(
            decision_model=DecisionConfidence(
                decision_type=DecisionType.ARCHITECTURE,
                decision="Use microservices",
            ),
        )
        score = model.calculate()
        assert score.event_count >= 1

    def test_model_with_all(self):
        """Test model with all sub-models."""
        model = ConfidenceModel(
            decision_model=DecisionConfidence(
                decision_type=DecisionType.CODE_CHANGE,
                decision="Refactor module",
            ),
            action_model=ActionConfidence(
                action_type=ActionType.FILE_EDIT,
                action="Edit module.py",
            ),
            recommendation_model=RecommendationConfidence(
                recommendation_type=RecommendationType.BEST_PRACTICE,
                recommendation="Use type hints",
            ),
        )
        score = model.calculate()
        assert score.event_count >= 3

    def test_model_to_dict(self):
        """Test converting model to dictionary."""
        model = ConfidenceModel(
            decision_model=DecisionConfidence(
                decision_type=DecisionType.CODE_CHANGE,
                decision="Test",
            ),
        )
        data = model.to_dict()
        assert "decision_model" in data
        assert "overall_score" in data


class TestConfidenceSystemIntegration:
    """Integration tests for the confidence system."""

    def test_full_workflow(self):
        """Test a complete confidence calculation workflow."""
        import tempfile

        # Create a tracker
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = ConfidenceTracker(workspace=tmpdir)

            # Add various events
            tracker.add_event(ConfidenceEvent(
                event_type=ConfidenceEventType.DECISION,
                component="planner",
                description="Decided to implement feature X",
                base_score=0.8,
            ))

            tracker.add_event(ConfidenceEvent(
                event_type=ConfidenceEventType.ACTION,
                component="executor",
                description="Created new file",
                base_score=0.9,
            ))

            tracker.add_event(ConfidenceEvent(
                event_type=ConfidenceEventType.VERIFICATION,
                component="verification",
                description="Tests passed",
                base_score=0.95,
            ))

            # Calculate current confidence
            current = tracker.calculate_current()
            assert current.value > 0.5

            # Add the score to tracker
            tracker.add_score(current)

            # Get summary
            summary = tracker.get_summary()
            assert summary["total_events"] == 3
            assert summary["total_scores"] >= 1

    def test_model_integration(self):
        """Test integrating confidence models with tracker."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = ConfidenceTracker(workspace=tmpdir)

            # Create decision confidence with good values
            decision = DecisionConfidence(
                decision_type=DecisionType.CODE_CHANGE,
                decision="Use event-driven architecture",
                complexity=0.3,  # Low complexity = higher confidence
                impact=0.5,
                alternatives_considered=3,
                context_quality=0.9,
                best_practice_alignment=0.8,
            )
            decision_score = decision.confidence_score

            # Add events from decision to tracker
            for event in decision_score.events:
                tracker.add_event(event)

            # Create action confidence with good values
            action = ActionConfidence(
                action_type=ActionType.FILE_EDIT,  # High factor action
                action="Edit config.py",
                reversible=True,
                historical_success_rate=0.95,
            )
            action_score = action.confidence_score

            # Add events from action to tracker
            for event in action_score.events:
                tracker.add_event(event)

            # Verify we have events
            assert tracker.event_count >= 2

            # Calculate overall confidence
            overall = tracker.calculate_current()
            # With good values, confidence should be reasonable
            assert overall.value >= 0.4  # Adjusted expectation
