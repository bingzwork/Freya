"""Tests for Multi-Intent Detection."""
import pytest
from app.intent.multi_intent import (
    MultiIntentDetector,
    SplitStrategy,
    DetectedIntent,
    MultiIntentResult,
    detect_multi_intent,
    get_planning_intents,
    get_direct_answer_intents,
)
from app.intent.classifier import IntentType


class TestSplitStrategy:
    """Test SplitStrategy enum."""

    def test_all_strategies_exist(self):
        """Verify all expected strategies exist."""
        assert SplitStrategy.CONJUNCTION
        assert SplitStrategy.SEMICOLON
        assert SplitStrategy.SENTENCE
        assert SplitStrategy.KEYWORD


class TestDetectedIntent:
    """Test DetectedIntent dataclass."""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        intent = DetectedIntent(
            intent=IntentType.TASK,
            text_segment="build my project",
            start=0,
            end=15,
            confidence=0.9,
            entities=[],
            strategy=SplitStrategy.CONJUNCTION,
            order=0,
        )
        d = intent.to_dict()
        assert d["intent"] == "task"
        assert d["text_segment"] == "build my project"
        assert d["start"] == 0
        assert d["end"] == 15
        assert d["confidence"] == 0.9
        assert d["strategy"] == "conjunction"
        assert d["order"] == 0
        assert d["requires_planning"] is True

    def test_requires_planning_property(self):
        """Test requires_planning property."""
        task_intent = DetectedIntent(
            intent=IntentType.TASK,
            text_segment="build",
            start=0,
            end=5,
            confidence=0.9,
        )
        assert task_intent.requires_planning is True

        chat_intent = DetectedIntent(
            intent=IntentType.CHAT,
            text_segment="hello",
            start=0,
            end=5,
            confidence=0.9,
        )
        assert chat_intent.requires_planning is False


class TestMultiIntentResult:
    """Test MultiIntentResult dataclass."""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        intent = DetectedIntent(
            intent=IntentType.TASK,
            text_segment="build",
            start=0,
            end=5,
            confidence=0.9,
            order=0,
        )
        result = MultiIntentResult(
            original_message="build and test",
            detected_intents=[intent],
            is_multi_intent=False,
            primary_intent=IntentType.TASK,
            execution_order=[0],
        )
        d = result.to_dict()
        assert d["original_message"] == "build and test"
        assert len(d["detected_intents"]) == 1
        assert d["is_multi_intent"] is False
        assert d["primary_intent"] == "task"
        assert d["execution_order"] == [0]


class TestMultiIntentDetector:
    """Test MultiIntentDetector class."""

    @pytest.fixture
    def detector(self):
        return MultiIntentDetector()

    # Conjunction-based splitting
    def test_split_by_and(self, detector):
        """Test splitting by 'and'."""
        message = "build my project and run tests"
        result = detector.detect(message)
        assert result.is_multi_intent is True
        assert len(result.detected_intents) == 2
        assert result.detected_intents[0].text_segment.strip() == "build my project"
        assert result.detected_intents[1].text_segment.strip() == "run tests"

    def test_split_by_then(self, detector):
        """Test splitting by 'then'."""
        message = "create the file then commit it"
        result = detector.detect(message)
        assert result.is_multi_intent is True
        assert len(result.detected_intents) == 2

    def test_split_by_also(self, detector):
        """Test splitting by 'also'."""
        message = "fix the bug also update the docs"
        result = detector.detect(message)
        assert result.is_multi_intent is True

    def test_split_by_comma(self, detector):
        """Test splitting by comma."""
        message = "read file.txt, write output.txt"
        result = detector.detect(message)
        assert result.is_multi_intent is True
        assert len(result.detected_intents) == 2

    def test_split_by_semicolon(self, detector):
        """Test splitting by semicolon."""
        message = "build project; run tests; deploy"
        result = detector.detect(message)
        assert result.is_multi_intent is True
        assert len(result.detected_intents) == 3
        # Check strategies detected
        strategies = [i.strategy for i in result.detected_intents]
        assert SplitStrategy.SEMICOLON in strategies

    # Task keyword splitting
    def test_split_by_task_keywords(self, detector):
        """Test splitting by implicit task keywords."""
        message = "open file.txt and edit main.py"
        result = detector.detect(message)
        assert result.is_multi_intent is True
        # Should detect "open file.txt" and "edit main.py"
        assert len(result.detected_intents) >= 2

    def test_single_intent_not_split(self, detector):
        """Test that single intents are not split."""
        message = "build my project"
        result = detector.detect(message)
        assert result.is_multi_intent is False
        assert len(result.detected_intents) == 1
        assert result.primary_intent == IntentType.TASK

    def test_chat_not_split(self, detector):
        """Test that simple chat is not split."""
        message = "hello how are you"
        result = detector.detect(message)
        assert result.is_multi_intent is False
        assert len(result.detected_intents) == 1

    # Execution order
    def test_execution_order_simple(self, detector):
        """Test execution order for simple cases."""
        message = "build project and run tests"
        result = detector.detect(message)
        assert result.execution_order == [0, 1]

    def test_execution_order_sequential(self, detector):
        """Test execution order with sequential keywords."""
        message = "first create file then run it"
        result = detector.detect(message)
        # "first create file" should come before "run it"
        assert result.execution_order[0] == 0 or result.execution_order[0] == 1

    # Planning vs direct answer
    def test_get_planning_intents(self, detector):
        """Test filtering for planning intents."""
        message = "build project and hello world"
        result = detector.detect(message)
        planning = get_planning_intents(result)
        assert len(planning) >= 1
        assert all(i.requires_planning for i in planning)

    def test_get_direct_answer_intents(self, detector):
        """Test filtering for direct answer intents."""
        message = "build project and hello"
        result = detector.detect(message)
        direct = get_direct_answer_intents(result)
        assert len(direct) >= 1
        assert all(not i.requires_planning for i in direct)

    # Primary intent
    def test_primary_intent_highest_confidence(self, detector):
        """Test that primary intent is highest confidence planning intent."""
        message = "build my project and run the tests"
        result = detector.detect(message)
        # Both are planning intents (TASK and TOOL_REQUEST), should pick highest confidence
        assert result.primary_intent in (IntentType.TASK, IntentType.TOOL_REQUEST)
        # TOOL_REQUEST has higher confidence for "run the tests"
        assert result.primary_intent == IntentType.TOOL_REQUEST

    def test_primary_intent_planning_over_direct(self, detector):
        """Test that planning intent wins over direct answer."""
        message = "build project and hello"
        result = detector.detect(message)
        assert result.primary_intent == IntentType.TASK

    # Edge cases
    def test_empty_message(self, detector):
        """Test empty message handling."""
        result = detector.detect("")
        assert result.is_multi_intent is False
        assert len(result.detected_intents) == 0
        assert result.primary_intent is None

    def test_whitespace_only(self, detector):
        """Test whitespace-only message."""
        result = detector.detect("   ")
        assert result.is_multi_intent is False
        assert len(result.detected_intents) == 0

    def test_short_segments_ignored(self, detector):
        """Test that very short segments are ignored."""
        message = "a and b"
        result = detector.detect(message)
        # "a" and "b" are too short to be meaningful
        assert result.is_multi_intent is False or len(result.detected_intents) <= 1

    # Strategy identification
    def test_strategy_conjunction(self, detector):
        """Test identification of conjunction strategy."""
        message = "build and test"
        result = detector.detect(message)
        strategies = [i.strategy for i in result.detected_intents]
        # First segment starts without conjunction
        # Second starts with "and"
        assert SplitStrategy.CONJUNCTION in strategies

    def test_strategy_keyword(self, detector):
        """Test identification of keyword strategy."""
        message = "open file.txt edit main.py"
        result = detector.detect(message)
        strategies = [i.strategy for i in result.detected_intents]
        assert SplitStrategy.KEYWORD in strategies


class TestConvenienceFunctions:
    """Test module-level convenience functions."""

    def test_detect_multi_intent(self):
        """Test detect_multi_intent function."""
        result = detect_multi_intent("build project and run tests")
        assert result.is_multi_intent is True

    def test_get_planning_intents_function(self):
        """Test get_planning_intents function."""
        result = detect_multi_intent("build and test")
        planning = get_planning_intents(result)
        assert all(i.requires_planning for i in planning)

    def test_get_direct_answer_intents_function(self):
        """Test get_direct_answer_intents function."""
        result = detect_multi_intent("build and hello")
        direct = get_direct_answer_intents(result)
        assert all(not i.requires_planning for i in direct)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])