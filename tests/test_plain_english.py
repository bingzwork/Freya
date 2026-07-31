"""Tests for Plain English Response Enforcement."""
import pytest
from app.capabilities.plain_english import (
    PlainEnglishFormatter,
    get_plain_english_formatter,
    plain_english,
    clarify,
    acknowledge_control,
    low_confidence,
    enforce_plain_english,
    to_plain_english,
    format_clarifying_question,
    format_control_acknowledgement,
    format_low_confidence_message,
    detect_jargon,
    detect_forbidden_fields,
)


class TestJargonDetection:
    """Test jargon detection."""

    def test_detect_routing_jargon(self):
        """Test detection of routing-related jargon."""
        text = "The intent classification confidence score is low. The routing decision was to use the engineering planner pipeline."
        jargon = detect_jargon(text)
        assert "intent classification" in jargon
        assert "confidence score" in jargon
        assert "routing decision" in jargon
        assert "engineering planner" in jargon
        assert "pipeline" in jargon

    def test_detect_system_jargon(self):
        """Test detection of system/architecture jargon."""
        text = "The LLM handler invoked the subprocess with a capability pipeline."
        jargon = detect_jargon(text)
        assert "llm" in jargon or "LLM" in text.lower()
        assert "handler" in jargon
        assert "subprocess" in jargon
        assert "pipeline" in jargon

    def test_detect_error_jargon(self):
        """Test detection of error-related jargon."""
        text = "An exception occurred with traceback showing the error in the stack trace."
        jargon = detect_jargon(text)
        assert "exception" in jargon
        assert "traceback" in jargon
        assert "error" in jargon
        assert "stack trace" in jargon

    def test_detect_forbidden_fields(self):
        """Test detection of forbidden internal field names."""
        text = 'The control_command was "stop" and the intent_type is TASK with confidence 0.9'
        fields = detect_forbidden_fields(text)
        assert "control_command" in fields
        assert "intent_type" in fields
        assert "confidence" in fields

    def test_no_jargon_in_plain_text(self):
        """Test that plain text doesn't trigger false positives."""
        text = "I'm working on your request now."
        jargon = detect_jargon(text)
        assert len(jargon) == 0


class TestToPlainEnglish:
    """Test to_plain_english function."""

    def test_basic_replacement(self):
        """Test basic jargon replacement."""
        text = "The intent classification confidence score is low."
        result = to_plain_english(text)
        assert "understanding what you're asking" in result

    def test_routing_replacement(self):
        """Test routing decision replacement."""
        text = "The routing decision was to use the engineering planner pipeline."
        result = to_plain_english(text)
        assert "how I'm handling this" in result
        assert "planning your request" in result

    def test_system_replacement(self):
        """Test system/architecture replacement."""
        text = "The LLM handler invoked the subprocess."
        result = to_plain_english(text)
        assert "AI model" in result
        assert "function" in result
        assert "command" in result

    def test_error_replacement(self):
        """Test error-related replacement."""
        text = "An exception occurred with traceback."
        result = to_plain_english(text)
        assert "problem" in result
        assert "details" in result

    def test_forbidden_field_hiding(self):
        """Test that forbidden fields are hidden."""
        text = 'The control_command is "stop" and intent_type is TASK.'
        result = to_plain_english(text)
        assert "control_command" not in result
        assert "intent_type" not in result
        assert "[internal]" in result

    def test_case_insensitive(self):
        """Test case-insensitive replacement."""
        text = "INTENT CLASSIFICATION and ROUTING DECISION."
        result = to_plain_english(text)
        assert "understanding what you're asking" in result.lower()
        assert "how i'm handling this" in result.lower()

    def test_less_aggressive_mode(self):
        """Test less aggressive replacement mode."""
        text = "The intent classification confidence score is low."
        result = to_plain_english(text, aggressive=False)
        # Should only replace most objectionable terms
        assert "understanding what you're asking" in result or "intent classification" in result.lower()


class TestEnforcePlainEnglish:
    """Test enforce_plain_english function."""

    def test_basic_enforcement(self):
        """Test basic plain English enforcement."""
        response = "The intent classification confidence score is low."
        result = enforce_plain_english(response)
        assert "understanding what you're asking" in result

    def test_debug_mode_preserves_jargon(self):
        """Test that debug mode preserves technical details."""
        response = "The intent classification confidence score is low."
        result = enforce_plain_english(response, debug_mode=True)
        assert "intent classification" in result
        assert "confidence score" in result

    def test_removes_excessive_apologies(self):
        """Test removal of excessive apologies."""
        response = "I am sorry, I apologize for the confusion. Here is the answer."
        result = enforce_plain_english(response)
        assert "sorry" not in result.lower()
        assert "apologize" not in result.lower()

    def test_ends_with_punctuation(self):
        """Test that response ends with punctuation."""
        response = "Here is the answer"
        result = enforce_plain_english(response)
        assert result[-1] in ".!?"

    def test_empty_input(self):
        """Test empty input handling."""
        result = enforce_plain_english("")
        assert result == ""

    def test_none_input(self):
        """Test None input handling."""
        result = enforce_plain_english(None)
        assert result is None


class TestClarifyingQuestion:
    """Test clarifying question formatting."""

    def test_basic_clarify(self):
        """Test basic clarifying question."""
        question = "Could you please clarify which specific file operation you would like me to perform?"
        result = clarify(question)
        assert result.endswith("?")
        assert result[0].isupper()

    def test_strips_please(self):
        """Test stripping of 'please' from questions."""
        question = "Please could you tell me what you want?"
        result = clarify(question)
        assert not result.lower().startswith("please")

    def test_strips_could_you(self):
        """Test stripping of 'could you' from questions."""
        question = "Could you explain what you mean?"
        result = clarify(question)
        assert not result.lower().startswith("could you")

    def test_single_question_mark(self):
        """Test that only one question mark remains."""
        question = "What do you want? Can you tell me?"
        result = clarify(question)
        assert result.count("?") == 1

    def test_debug_mode_preserves(self):
        """Test debug mode preserves original."""
        question = "Could you please clarify?"
        result = clarify(question, debug_mode=True)
        assert "Could you" in result


class TestControlAcknowledgement:
    """Test control acknowledgement formatting."""

    def test_stop_acknowledgement(self):
        """Test stop acknowledgement."""
        result = acknowledge_control("stop")
        assert "Stopped" in result
        assert "What's next" in result

    def test_cancel_acknowledgement(self):
        """Test cancel acknowledgement."""
        result = acknowledge_control("cancel")
        assert "Cancelled" in result

    def test_undo_acknowledgement(self):
        """Test undo acknowledgement."""
        result = acknowledge_control("undo")
        assert "undone" in result or "Done" in result

    def test_redo_acknowledgement(self):
        """Test redo acknowledgement."""
        result = acknowledge_control("redo")
        assert "reapplied" in result or "Done" in result

    def test_status_acknowledgement(self):
        """Test status acknowledgement."""
        result = acknowledge_control("status")
        assert "ready to help" in result

    def test_case_insensitive(self):
        """Test case-insensitive matching."""
        assert acknowledge_control("STOP") == acknowledge_control("stop")
        assert acknowledge_control("Cancel") == acknowledge_control("cancel")

    def test_unknown_command(self):
        """Test unknown command fallback."""
        result = acknowledge_control("unknown_command")
        assert "Understood" in result

    def test_debug_mode(self):
        """Test debug mode includes technical details."""
        result = acknowledge_control("stop", debug_mode=True)
        assert "Control command received" in result
        assert "stop" in result


class TestLowConfidenceMessage:
    """Test low-confidence message formatting."""

    def test_task_low_confidence(self):
        """Test low confidence for task intent."""
        result = low_confidence("task")
        assert "not entirely sure" in result
        assert "clarify" in result

    def test_chat_low_confidence(self):
        """Test low confidence for chat intent."""
        result = low_confidence("chat")
        assert "not sure" in result
        assert "chat" in result.lower() or "tell me more" in result

    def test_question_low_confidence(self):
        """Test low confidence for question intent."""
        result = low_confidence("question")
        assert "not completely sure" in result
        assert "rephrase" in result

    def test_unknown_type(self):
        """Test unknown classification type."""
        result = low_confidence("unknown_type")
        assert "not completely sure" in result
        assert "clarify" in result

    def test_debug_mode(self):
        """Test debug mode preserves technical details."""
        result = low_confidence("task", debug_mode=True)
        assert "Low confidence" in result
        assert "task" in result


class TestPlainEnglishFormatter:
    """Test PlainEnglishFormatter class."""

    def test_format_response(self):
        """Test formatting a general response."""
        formatter = PlainEnglishFormatter()
        response = "The intent classification confidence score is low."
        result = formatter.format_response(response)
        assert "understanding what you're asking" in result

    def test_format_error(self):
        """Test formatting an error message."""
        formatter = PlainEnglishFormatter()
        error = "Exception occurred in handler: FileNotFoundError"
        result = formatter.format_error(error)
        assert "problem" in result.lower()
        assert "exception" not in result.lower()

    def test_format_debug(self):
        """Test formatting debug info."""
        formatter = PlainEnglishFormatter()
        debug_info = "capability=test, execution_time=0.1s"
        # Default (non-debug) mode
        result = formatter.format_debug(debug_info)
        assert result == ""

        # Debug mode
        formatter_debug = PlainEnglishFormatter(debug_mode=True)
        result = formatter_debug.format_debug(debug_info)
        assert "Debug" in result
        assert "capability=test" in result

    def test_debug_mode_preserves_all(self):
        """Test debug mode preserves all technical details."""
        formatter = PlainEnglishFormatter(debug_mode=True)
        response = "The LLM handler invoked subprocess with traceback error."
        result = formatter.format_response(response)
        assert "LLM" in result
        assert "handler" in result
        assert "subprocess" in result
        assert "traceback" in result


class TestConvenienceFunctions:
    """Test module-level convenience functions."""

    def test_get_formatter(self):
        """Test getting the global formatter."""
        formatter = get_plain_english_formatter()
        assert isinstance(formatter, PlainEnglishFormatter)

    def test_plain_english_function(self):
        """Test plain_english wrapper function."""
        result = plain_english("The pipeline routing decision.")
        assert "how I'm handling this" in result

    def test_clarify_function(self):
        """Test clarify wrapper function."""
        result = clarify("Could you clarify?")
        assert result.endswith("?")

    def test_acknowledge_control_function(self):
        """Test acknowledge_control wrapper function."""
        result = acknowledge_control("stop")
        assert "Stopped" in result

    def test_low_confidence_function(self):
        """Test low_confidence wrapper function."""
        result = low_confidence("task")
        assert "not entirely sure" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])