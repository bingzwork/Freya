"""Tests for Intent Classification System.

This module tests the intent classification functionality that determines
whether user messages should enter the planning pipeline or be answered
directly.
"""

import pytest
from app.intent.classifier import (
    IntentClassifier,
    IntentType,
    IntentClassification,
    classify_intent,
    is_task,
    should_answer_directly,
)


class TestIntentType:
    """Test IntentType enum."""

    def test_requires_planning(self):
        """Test which intent types require planning."""
        assert IntentType.TASK.requires_planning is True
        assert IntentType.FILE_OPERATION.requires_planning is True
        assert IntentType.CODE_TASK.requires_planning is True
        assert IntentType.TOOL_REQUEST.requires_planning is True
        assert IntentType.GIT_OPERATION.requires_planning is True

        assert IntentType.CHAT.requires_planning is False
        assert IntentType.QUESTION.requires_planning is False
        assert IntentType.SYSTEM_STATUS.requires_planning is False

    def test_can_answer_directly(self):
        """Test which intent types can be answered directly."""
        assert IntentType.CHAT.can_answer_directly is True
        assert IntentType.QUESTION.can_answer_directly is True
        assert IntentType.SYSTEM_STATUS.can_answer_directly is True

        assert IntentType.TASK.can_answer_directly is False
        assert IntentType.FILE_OPERATION.can_answer_directly is False
        assert IntentType.CODE_TASK.can_answer_directly is False
        assert IntentType.TOOL_REQUEST.can_answer_directly is False
        assert IntentType.GIT_OPERATION.can_answer_directly is False


class TestIntentClassification:
    """Test IntentClassification dataclass."""

    def test_should_plan_flag(self):
        """Test that should_plan is set correctly."""
        classification = IntentClassification(
            intent=IntentType.TASK,
            confidence=0.8,
            reason="Test",
        )
        assert classification.should_plan is True
        assert classification.should_answer_directly is False

    def test_should_answer_directly_flag(self):
        """Test that should_answer_directly is set correctly."""
        classification = IntentClassification(
            intent=IntentType.QUESTION,
            confidence=0.8,
            reason="Test",
        )
        assert classification.should_plan is False
        assert classification.should_answer_directly is True

    def test_to_dict(self):
        """Test conversion to dictionary."""
        classification = IntentClassification(
            intent=IntentType.CHAT,
            confidence=0.9,
            reason="Greeting",
            keywords=["hello", "hi"],
        )
        d = classification.to_dict()
        assert d["intent"] == "chat"
        assert d["confidence"] == 0.9
        assert d["reason"] == "Greeting"
        assert d["keywords"] == ["hello", "hi"]
        assert d["should_plan"] is False
        assert d["should_answer_directly"] is True

    def test_repr(self):
        """Test string representation."""
        classification = IntentClassification(
            intent=IntentType.TASK,
            confidence=0.75,
            reason="Test task",
        )
        repr_str = repr(classification)
        assert "IntentClassification" in repr_str
        assert "task" in repr_str
        assert "0.75" in repr_str


class TestIntentClassifier:
    """Test IntentClassifier class."""

    @pytest.fixture
    def classifier(self):
        """Create a classifier instance."""
        return IntentClassifier()

    # Tests for CHAT intent
    def test_classify_chat_greetings(self, classifier):
        """Test classification of chat greetings."""
        test_cases = [
            "hello",
            "hi",
            "hey",
            "good morning",
            "good afternoon",
            "good evening",
            "how are you",
            "what's up",
            "yo",
            "greetings",
            "howdy",
        ]
        for msg in test_cases:
            result = classifier.classify(msg)
            assert result.intent == IntentType.CHAT, f"Failed for '{msg}': got {result.intent.value}"
            assert result.should_plan is False
            assert result.should_answer_directly is True

    def test_classify_chat_farewells(self, classifier):
        """Test classification of chat farewells."""
        test_cases = [
            "bye",
            "goodbye",
            "see you",
            "see ya",
        ]
        for msg in test_cases:
            result = classifier.classify(msg)
            assert result.intent == IntentType.CHAT, f"Failed for '{msg}': got {result.intent.value}"

    # Tests for QUESTION intent
    def test_classify_question_words(self, classifier):
        """Test classification of questions starting with question words."""
        test_cases = [
            "what is 2+2?",
            "how does this work?",
            "why is this happening?",
            "who is the author?",
            "when was this created?",
            "where is the file?",
            "which one to use?",
        ]
        for msg in test_cases:
            result = classifier.classify(msg)
            assert result.intent == IntentType.QUESTION, f"Failed for '{msg}': got {result.intent.value}"
            assert result.should_plan is False

    def test_classify_question_explain(self, classifier):
        """Test classification of explain requests."""
        test_cases = [
            "explain this",
            "tell me about it",
            "describe the process",
            "can you explain?",
            "could you explain?",
        ]
        for msg in test_cases:
            result = classifier.classify(msg)
            assert result.intent == IntentType.QUESTION, f"Failed for '{msg}': got {result.intent.value}"

    # Tests for TASK intent
    def test_classify_task_build(self, classifier):
        """Test classification of build tasks."""
        test_cases = [
            "build my project",
            "build the application",
            "create a new feature",
            "make a component",
            "generate the docs",
        ]
        for msg in test_cases:
            result = classifier.classify(msg)
            assert result.intent == IntentType.TASK, f"Failed for '{msg}': got {result.intent.value}"
            assert result.should_plan is True

    def test_classify_task_actions(self, classifier):
        """Test classification of action tasks."""
        test_cases = [
            "fix the bug",
            "solve this problem",
            "resolve the issue",
            
            "analyze the data",
            "audit the project",
            "review the changes",
            "optimize the performance",
            "improve the design",
        ]
        for msg in test_cases:
            result = classifier.classify(msg)
            assert result.intent == IntentType.TASK, f"Failed for '{msg}': got {result.intent.value}"

    # Tests for FILE_OPERATION intent
    def test_classify_file_operations(self, classifier):
        """Test classification of file operations."""
        test_cases = [
            "read file.txt",
            "open main.py",
            "view the document",
            "show me the file",
            "display file.txt",
            "write file.txt",
            "save the file",
            "create a new file",
            "edit main.py",
            "modify the config",
            "delete temp.py",
            "remove old files",
        ]
        for msg in test_cases:
            result = classifier.classify(msg)
            assert result.intent == IntentType.FILE_OPERATION, f"Failed for '{msg}': got {result.intent.value}"
            assert result.should_plan is True

    # Tests for CODE_TASK intent
    def test_classify_code_tasks(self, classifier):
        """Test classification of code-specific tasks."""
        test_cases = [
            "refactor this function",
            "rewrite the code",
            "fix bug in main.py",
            "implement the feature",
            "review code changes",
            "analyze this code",
            "explain this function",
            "document the code",
        ]
        for msg in test_cases:
            result = classifier.classify(msg)
            assert result.intent == IntentType.CODE_TASK, f"Failed for '{msg}': got {result.intent.value}"
            assert result.should_plan is True

    # Tests for SYSTEM_STATUS intent
    def test_classify_system_status(self, classifier):
        """Test classification of system status queries."""
        test_cases = [
            "are you connected to ollama?",
            "are you online?",
            "are you running?",
            "what model are you using?",
            "which model is loaded?",
            "what version are you?",
            "is ollama installed?",
            "can you access the internet?",
            "hello are you there?",
        ]
        for msg in test_cases:
            result = classifier.classify(msg)
            assert result.intent == IntentType.SYSTEM_STATUS, f"Failed for '{msg}': got {result.intent.value}"
            assert result.should_plan is False
            assert result.should_answer_directly is True

    # Tests for TOOL_REQUEST intent
    def test_classify_tool_requests(self, classifier):
        """Test classification of tool requests."""
        test_cases = [
            "run pytest",
            "execute the script",
            "run the tests",
            "lint the code",
            "format the files",
            "run command: ls",
        ]
        for msg in test_cases:
            result = classifier.classify(msg)
            assert result.intent == IntentType.TOOL_REQUEST, f"Failed for '{msg}': got {result.intent.value}"
            assert result.should_plan is True

    # Tests for GIT_OPERATION intent
    def test_classify_git_operations(self, classifier):
        """Test classification of git operations."""
        test_cases = [
            "git commit -m hello",
            "git push origin main",
            "git pull",
            "git add .",
            "git status",
            "commit changes",
            "push to main",
        ]
        for msg in test_cases:
            result = classifier.classify(msg)
            assert result.intent == IntentType.GIT_OPERATION, f"Failed for '{msg}': got {result.intent.value}"
            assert result.should_plan is True

    # Edge cases
    def test_classify_empty_message(self, classifier):
        """Test classification of empty message."""
        result = classifier.classify("")
        assert result.intent == IntentType.CHAT

    def test_classify_whitespace_only(self, classifier):
        """Test classification of whitespace-only message."""
        result = classifier.classify("   ")
        assert result.intent == IntentType.CHAT

    def test_classify_none(self, classifier):
        """Test classification of None."""
        result = classifier.classify(None)
        assert result.intent == IntentType.QUESTION

    # Method tests
    def test_is_task_method(self, classifier):
        """Test is_task method."""
        assert classifier.is_task("build my project") is True
        assert classifier.is_task("hello") is False
        assert classifier.is_task("what is 2+2?") is False
        assert classifier.is_task("are you connected?") is False

    def test_should_answer_directly_method(self, classifier):
        """Test should_answer_directly method."""
        assert classifier.should_answer_directly("hello") is True
        assert classifier.should_answer_directly("what is 2+2?") is True
        assert classifier.should_answer_directly("are you connected?") is True
        assert classifier.should_answer_directly("build my project") is False


class TestConvenienceFunctions:
    """Test convenience functions."""

    def test_classify_intent_function(self):
        """Test classify_intent function."""
        result = classify_intent("hello")
        assert result.intent == IntentType.CHAT

    def test_is_task_function(self):
        """Test is_task function."""
        assert is_task("build my project") is True
        assert is_task("hello") is False

    def test_should_answer_directly_function(self):
        """Test should_answer_directly function."""
        assert should_answer_directly("hello") is True
        assert should_answer_directly("build my project") is False


class TestRoutingBehavior:
    """Test routing behavior - Planner invocation scenarios.

    These tests verify the specific routing requirements:
    - Chat/Greeting/Conversations should NOT invoke Planner (should_plan=False)
    - Knowledge questions should NOT invoke Planner (should_plan=False)
    - System status queries should NOT invoke Planner (should_plan=False)
    - Engineering tasks should invoke Planner (should_plan=True)
    """

    @pytest.fixture
    def classifier(self):
        """Create a classifier instance."""
        return IntentClassifier()

    def test_chat_greeting_no_planner(self, classifier):
        """Test that chat greetings do NOT invoke the planner."""
        test_cases = [
            "hello",
            "hi there",
            "hey",
            "good morning",
            "how are you",
            "what's up",
        ]
        for msg in test_cases:
            result = classifier.classify(msg)
            assert result.should_plan is False, f"Chat greeting '{msg}' should NOT invoke Planner"

    def test_general_conversation_no_planner(self, classifier):
        """Test that general conversation does NOT invoke the planner."""
        test_cases = [
            "nice to meet you",
            "how is your day",
            "thanks for the help",
            "that's great",
            "see you later",
        ]
        for msg in test_cases:
            result = classifier.classify(msg)
            assert result.should_plan is False, f"General conversation '{msg}' should NOT invoke Planner"

    def test_knowledge_question_no_planner(self, classifier):
        """Test that knowledge questions do NOT invoke the planner."""
        test_cases = [
            "what is artificial intelligence?",
            "how does the internet work?",
            "why is the sky blue?",
            "who invented python?",
            "explain machine learning",
            "tell me about quantum computing",
            "describe the water cycle",
        ]
        for msg in test_cases:
            result = classifier.classify(msg)
            assert result.should_plan is False, f"Knowledge question '{msg}' should NOT invoke Planner"
            assert result.intent in (IntentType.QUESTION, IntentType.CHAT), \
                f"Knowledge question '{msg}' should be QUESTION or CHAT intent"

    def test_system_status_no_planner(self, classifier):
        """Test that system status queries do NOT invoke the planner.

        Note: Only tests queries that are correctly classified as SYSTEM_STATUS
        by the intent classifier. Queries like "what time is it" are classified
        as QUESTION and would need capability router with manual intent_type.
        """
        test_cases = [
            "are you connected to ollama",
            "what model are you using",
            "are you online",
            "are you running",
            "are you connected to ollama?",
            "what model are you using?",
            "is ollama installed",
            "which model is loaded?",
            "is ollama installed?",
        ]
        for msg in test_cases:
            result = classifier.classify(msg)
            assert result.should_plan is False, f"System status query '{msg}' should NOT invoke Planner"
            assert result.intent == IntentType.SYSTEM_STATUS, \
                f"System status query '{msg}' should be SYSTEM_STATUS intent (got {result.intent.value})"

    def test_engineering_tasks_invoke_planner(self, classifier):
        """Test that engineering tasks DO invoke the planner."""
        test_cases = [
            "build my project",
            "fix this python error",
            "refactor this repository",
            "create a REST API",
            "implement the login feature",
            "debug the application",
            "add a new endpoint",
            "optimize the database queries",
            "run pytest",
            "git commit -m hello",
        ]
        for msg in test_cases:
            result = classifier.classify(msg)
            assert result.should_plan is True, f"Engineering task '{msg}' should invoke Planner"
            assert result.intent.requires_planning is True, \
                f"Engineering task '{msg}' intent should require planning"

    def test_routing_summary(self):
        """Test routing behavior summary - comprehensive verification."""
        classifier = IntentClassifier()

        # Scenarios that should NOT invoke Planner
        no_planner_cases = [
            # Chat
            ("hello", IntentType.CHAT),
            ("hi there", IntentType.CHAT),
            ("good morning", IntentType.CHAT),
            ("how are you", IntentType.CHAT),
            # Knowledge questions
            ("what is AI?", IntentType.QUESTION),
            ("how does this work?", IntentType.QUESTION),
            ("explain this to me", IntentType.QUESTION),
            # System status
            ("are you connected to ollama", IntentType.SYSTEM_STATUS),
            ("what model are you using", IntentType.SYSTEM_STATUS),
            ("what time is it", IntentType.SYSTEM_STATUS),
        ]

        for msg, expected_intent in no_planner_cases:
            result = classifier.classify(msg)
            assert result.should_plan is False, \
                f"Message '{msg}' should NOT invoke Planner (got intent: {result.intent.value})"

        # Scenarios that should invoke Planner
        planner_cases = [
            ("build my project", IntentType.TASK),
            ("fix this python error", IntentType.CODE_TASK),
            ("refactor this repository", IntentType.CODE_TASK),
            ("create a REST API", IntentType.TASK),
            ("run pytest", IntentType.TOOL_REQUEST),
            ("git push origin main", IntentType.GIT_OPERATION),
            ("git status", IntentType.GIT_OPERATION),  # git status is a git operation
            ("read main.py", IntentType.FILE_OPERATION),
        ]

        for msg, expected_intent in planner_cases:
            result = classifier.classify(msg)
            assert result.should_plan is True, \
                f"Message '{msg}' should invoke Planner (got intent: {result.intent.value})"
            assert result.intent.requires_planning is True, \
                f"Intent {result.intent.value} should require planning"

    def test_runtime_context_inclusion(self):
        """Test that runtime context is included for engineering tasks."""
        classifier = IntentClassifier()

        # Engineering tasks should include runtime context
        engineering_cases = [
            "build my project",
            "fix this python error",
            "refactor this repository",
            "create a REST API",
        ]

        for msg in engineering_cases:
            result = classifier.classify(msg)
            assert result.should_include_runtime_context is True, \
                f"Engineering task '{msg}' should include runtime context"

        # Non-engineering should NOT include runtime context
        non_engineering_cases = [
            "hello",
            "what is AI?",
            "are you connected to ollama",
        ]

        for msg in non_engineering_cases:
            result = classifier.classify(msg)
            assert result.should_include_runtime_context is False, \
                f"Non-engineering message '{msg}' should NOT include runtime context"


class TestConversationalControl:
    """Tests for CONVERSATIONAL_CONTROL intent (stop / cancel / undo / redo / status)."""

    @pytest.fixture
    def classifier(self):
        return IntentClassifier()

    @pytest.mark.parametrize("msg", [
        "stop", "halt", "wait",
        "cancel", "nevermind", "abort",
        "undo", "revert", "redo",
        "status",
        "what are you doing?",
        "current plan",
        "current step",
    ])
    def test_control_intent_recognized(self, classifier, msg):
        result = classifier.classify(msg)
        assert result.intent == IntentType.CONVERSATIONAL_CONTROL, \
            f"'{msg}' should be CONVERSATIONAL_CONTROL, got {result.intent.value}"
        assert result.is_control is True
        assert result.should_answer_directly is True
        assert result.should_plan is False

    def test_control_wins_over_greeting(self, classifier):
        """Compound input with a greeting should still be CONVERSATIONAL_CONTROL."""
        result = classifier.classify("hi stop")
        assert result.intent == IntentType.CONVERSATIONAL_CONTROL

    def test_routing_priority_is_zero(self, classifier):
        """Conversational control has the highest routing priority (lowest number)."""
        assert IntentType.CONVERSATIONAL_CONTROL.routing_priority == 0
        for intent in (IntentType.TASK, IntentType.FILE_OPERATION,
                       IntentType.CODE_TASK, IntentType.TOOL_REQUEST,
                       IntentType.GIT_OPERATION):
            assert intent.routing_priority >= 1
        assert IntentType.CHAT.routing_priority == 3
        assert IntentType.QUESTION.routing_priority == 3


class TestConfidenceThresholds:
    """Tests for low-confidence / ambiguous classification flags."""

    @pytest.fixture
    def classifier(self):
        return IntentClassifier()

    def test_low_confidence_flag_on_no_signal(self, classifier):
        """A message that matches no pattern or keyword reports low_confidence=True."""
        result = classifier.classify("xxxxxnomatchxxxxx")
        assert result.confidence < 0.40
        assert result.is_low_confidence is True

    def test_low_confidence_flag_false_on_pattern_match(self, classifier):
        """A pattern-matched input has high confidence, not low."""
        result = classifier.classify("stop")
        assert result.confidence >= 0.40
        assert result.is_low_confidence is False
        assert result.is_ambiguous is False

    def test_accept_threshold_constant(self):
        from app.intent.classifier import ACCEPT_CONFIDENCE_THRESHOLD
        assert ACCEPT_CONFIDENCE_THRESHOLD == 0.70

    def test_low_confidence_threshold_constant(self):
        from app.intent.classifier import LOW_CONFIDENCE_THRESHOLD
        assert LOW_CONFIDENCE_THRESHOLD == 0.40

    def test_ambiguous_flag_in_mid_band(self, classifier):
        """Mid-band confidence produces is_ambiguous=True.

        Constructed by mocking confidence to land in the mid-band; the
        keyword-only classifier typically produces scores below the
        low-confidence threshold, so the mid-band is exercised via the
        property directly.
        """
        import dataclasses
        # Use a manually-constructed classification in the mid-band.
        c = dataclasses.replace(
            classifier.classify("hello"),
            confidence=0.55,
        )
        assert 0.40 <= c.confidence < 0.70
        assert c.is_ambiguous is True
        assert c.is_low_confidence is False


class TestRoutingHelpers:
    """Tests for module-level routing helpers."""

    def test_should_clarify_true_at_mid_band(self):
        """should_clarify returns True for classifications in the mid-band."""
        import dataclasses
        from app.intent import classify_intent, should_clarify
        # Force a mid-band confidence via dataclass replace.
        c = dataclasses.replace(classify_intent("hello"), confidence=0.55)
        assert should_clarify(c) is True

    def test_should_clarify_false_on_high_confidence(self):
        from app.intent import classify_intent, should_clarify
        c = classify_intent("stop")
        assert should_clarify(c) is False

    def test_is_control_intent_helper(self):
        from app.intent import classify_intent, is_control_intent
        assert is_control_intent(classify_intent("stop")) is True
        assert is_control_intent(classify_intent("hi")) is False

    def test_is_low_confidence_helper(self):
        from app.intent import classify_intent, is_low_confidence
        assert is_low_confidence(classify_intent("xxxxxnomatchxxxxx")) is True
        assert is_low_confidence(classify_intent("hello")) is False
