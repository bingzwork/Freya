"""Tests for multi-turn conversation state functionality."""

import pytest
from app.brain.state import ConversationState, Message


class TestConversationState:
    """Test ConversationState class for session-level message history."""

    def test_initial_state_is_empty(self):
        """New ConversationState should start with no messages."""
        conversation = ConversationState()
        assert len(conversation) == 0
        assert conversation.is_empty()
        assert conversation.get_history() == []
        assert conversation.get_history_text() == ""

    def test_add_message(self):
        """Adding messages should store them in order."""
        conversation = ConversationState()

        msg1 = conversation.add_message("user", "Hello, Freya")
        assert isinstance(msg1, Message)
        assert msg1.role == "user"
        assert msg1.content == "Hello, Freya"
        assert msg1.timestamp is not None

        msg2 = conversation.add_message("assistant", "Hello, human!")
        assert isinstance(msg2, Message)
        assert msg2.role == "assistant"
        assert msg2.content == "Hello, human!"

        assert len(conversation) == 2
        assert not conversation.is_empty()

    def test_get_history(self):
        """get_history should return a copy of all messages."""
        conversation = ConversationState()
        conversation.add_message("user", "First message")
        conversation.add_message("assistant", "First response")
        conversation.add_message("user", "Second message")

        history = conversation.get_history()
        assert len(history) == 3
        assert history[0].role == "user"
        assert history[0].content == "First message"
        assert history[1].role == "assistant"
        assert history[1].content == "First response"
        assert history[2].role == "user"
        assert history[2].content == "Second message"

    def test_get_history_returns_copy(self):
        """get_history should return a copy, not the original list."""
        conversation = ConversationState()
        conversation.add_message("user", "Test")

        history = conversation.get_history()
        history.clear()

        # Original should still have the message
        assert len(conversation) == 1

    def test_get_history_text(self):
        """get_history_text should format messages for LLM context."""
        conversation = ConversationState()
        conversation.add_message("user", "What is 2+2?")
        conversation.add_message("assistant", "4")

        text = conversation.get_history_text()
        assert "User: What is 2+2?" in text
        assert "Freya: 4" in text

    def test_get_history_text_max_characters(self):
        """get_history_text should respect max_characters limit."""
        conversation = ConversationState()
        conversation.add_message("user", "A" * 10000)

        text = conversation.get_history_text(max_characters=100)
        assert len(text) <= 100

    def test_clear(self):
        """clear should remove all messages."""
        conversation = ConversationState()
        conversation.add_message("user", "Message 1")
        conversation.add_message("assistant", "Response 1")

        conversation.clear()

        assert len(conversation) == 0
        assert conversation.is_empty()
        assert conversation.get_history() == []

    def test_max_history_limit(self):
        """Conversation should respect max_history limit."""
        conversation = ConversationState(max_history=3)

        for i in range(5):
            conversation.add_message("user", f"Message {i}")

        # Should only have the last 3 messages
        assert len(conversation) == 3
        history = conversation.get_history()
        assert history[0].content == "Message 2"
        assert history[1].content == "Message 3"
        assert history[2].content == "Message 4"

    def test_get_last_user_message(self):
        """get_last_user_message should return the most recent user message."""
        conversation = ConversationState()
        conversation.add_message("assistant", "Hello")
        conversation.add_message("user", "First question")
        conversation.add_message("assistant", "Answer")
        conversation.add_message("user", "Second question")

        assert conversation.get_last_user_message() == "Second question"

    def test_get_last_user_message_empty(self):
        """get_last_user_message should return None when no user messages."""
        conversation = ConversationState()
        conversation.add_message("assistant", "Hello")

        assert conversation.get_last_user_message() is None

    def test_get_last_assistant_message(self):
        """get_last_assistant_message should return the most recent assistant message."""
        conversation = ConversationState()
        conversation.add_message("user", "Hello")
        conversation.add_message("assistant", "First reply")
        conversation.add_message("user", "Another question")
        conversation.add_message("assistant", "Second reply")

        assert conversation.get_last_assistant_message() == "Second reply"

    def test_get_last_assistant_message_empty(self):
        """get_last_assistant_message should return None when no assistant messages."""
        conversation = ConversationState()
        conversation.add_message("user", "Hello")

        assert conversation.get_last_assistant_message() is None


class TestMessage:
    """Test Message dataclass."""

    def test_message_creation(self):
        """Message should store role, content, and timestamp."""
        msg = Message(role="user", content="Test message")
        assert msg.role == "user"
        assert msg.content == "Test message"
        assert msg.timestamp is not None

    def test_message_with_custom_timestamp(self):
        """Message should accept custom timestamp."""
        msg = Message(role="assistant", content="Response", timestamp="2024-01-01T00:00:00")
        assert msg.timestamp == "2024-01-01T00:00:00"
