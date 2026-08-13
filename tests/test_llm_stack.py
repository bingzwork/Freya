"""Tests for the LLMStack module."""

import pytest
from unittest.mock import patch, MagicMock

from app.core.llm_stack import LLMStack
from app.core.priority_llm import LLMPriority


class MockOllama:
    """Mock ollama module for testing."""
    def __init__(self):
        self.calls = []

    def chat(self, model, messages):
        self.calls.append({"model": model, "messages": messages})
        return {"message": {"content": "Test response"}}


class TestLLMStack:
    """Test the LLMStack class."""

    def test_llm_stack_init_default_model(self):
        """Test LLMStack initialization with default model."""
        with patch("app.core.llm.OLLAMA_AVAILABLE", True):
            with patch("app.core.llm.ollama", MockOllama()):
                stack = LLMStack()
                assert stack.model == "qwen3:8b"

    def test_llm_stack_init_custom_model(self):
        """Test LLMStack initialization with custom model."""
        with patch("app.core.llm.OLLAMA_AVAILABLE", True):
            with patch("app.core.llm.ollama", MockOllama()):
                stack = LLMStack(model="llama3:8b")
                assert stack.model == "llama3:8b"

    def test_llm_stack_has_priority_llm(self):
        """Test LLMStack has priority_llm property."""
        with patch("app.core.llm.OLLAMA_AVAILABLE", True):
            with patch("app.core.llm.ollama", MockOllama()):
                stack = LLMStack()
                assert hasattr(stack, "priority_llm")
                assert stack.priority_llm is not None

    def test_llm_stack_has_chat_activity(self):
        """Test LLMStack has chat_activity property."""
        with patch("app.core.llm.OLLAMA_AVAILABLE", True):
            with patch("app.core.llm.ollama", MockOllama()):
                stack = LLMStack()
                assert hasattr(stack, "chat_activity")
                assert stack.chat_activity is not None

    def test_ask_without_ollama(self):
        """Test ask() when ollama is not available."""
        with patch("app.core.llm.OLLAMA_AVAILABLE", False):
            stack = LLMStack()
            response = stack.ask("Hello", system="Test")
            assert "[LLM response not available - ollama not installed]" in response
            assert "Hello" in response
            assert "Test" in response

    def test_ask_with_ollama(self):
        """Test ask() with mocked ollama."""
        mock_ollama = MockOllama()
        with patch("app.core.llm.ollama", mock_ollama):
            with patch("app.core.llm.OLLAMA_AVAILABLE", True):
                stack = LLMStack(model="test-model")
                response = stack.ask("Test prompt", system="Test system")

                assert response == "Test response"
                assert len(mock_ollama.calls) == 1
                call = mock_ollama.calls[0]
                assert call["model"] == "test-model"
                assert len(call["messages"]) == 2
                assert call["messages"][0]["role"] == "system"
                assert call["messages"][0]["content"] == "Test system"
                assert call["messages"][1]["role"] == "user"
                assert call["messages"][1]["content"] == "Test prompt"

    def test_ask_with_custom_system(self):
        """Test ask() with custom system prompt."""
        mock_ollama = MockOllama()
        with patch("app.core.llm.ollama", mock_ollama):
            with patch("app.core.llm.OLLAMA_AVAILABLE", True):
                stack = LLMStack()
                response = stack.ask("User message", system="Custom system")

                assert response == "Test response"
                call = mock_ollama.calls[0]
                assert call["messages"][0]["content"] == "Custom system"

    def test_ask_priority_chat(self):
        """Test ask() with CHAT priority."""
        mock_ollama = MockOllama()
        with patch("app.core.llm.ollama", mock_ollama):
            with patch("app.core.llm.OLLAMA_AVAILABLE", True):
                stack = LLMStack()
                response = stack.ask("Chat message", priority=LLMPriority.CHAT)

                assert response == "Test response"

    def test_chat_activity_delegation(self):
        """Test chat activity methods delegate correctly."""
        with patch("app.core.llm.OLLAMA_AVAILABLE", True):
            with patch("app.core.llm.ollama", MockOllama()):
                stack = LLMStack()

                # These should not raise
                stack.chat_started()
                assert stack.is_chat_active() is True

                stack.chat_ended()
                assert stack.is_chat_active() is False

                stack.chat_activity_heartbeat()
                assert stack.is_chat_active() is True

    def test_get_stats(self):
        """Test get_stats returns combined stats."""
        with patch("app.core.llm.OLLAMA_AVAILABLE", True):
            with patch("app.core.llm.ollama", MockOllama()):
                stack = LLMStack()
                stats = stack.get_stats()

                assert "model" in stats
                assert stats["model"] == "qwen3:8b"
                assert "chat_active" in stats
                assert "total_requests" in stats

    def test_shutdown(self):
        """Test shutdown calls priority_llm shutdown."""
        with patch("app.core.llm.OLLAMA_AVAILABLE", True):
            with patch("app.core.llm.ollama", MockOllama()):
                stack = LLMStack()
                # Should not raise
                stack.shutdown()


class TestLLMStackGlobal:
    """Test global LLMStack functions."""

    def test_get_llm_stack_singleton(self):
        """Test get_llm_stack returns singleton."""
        with patch("app.core.llm.OLLAMA_AVAILABLE", True):
            with patch("app.core.llm.ollama", MockOllama()):
                from app.core.llm_stack import get_llm_stack, set_llm_stack

                # Reset global
                set_llm_stack(None)

                stack1 = get_llm_stack()
                stack2 = get_llm_stack()

                assert stack1 is stack2

    def test_set_llm_stack(self):
        """Test set_llm_stack overrides global."""
        with patch("app.core.llm.OLLAMA_AVAILABLE", True):
            with patch("app.core.llm.ollama", MockOllama()):
                from app.core.llm_stack import get_llm_stack, set_llm_stack

                # Reset global
                set_llm_stack(None)

                stack1 = get_llm_stack()
                custom_stack = LLMStack(model="custom-model")
                set_llm_stack(custom_stack)
                stack2 = get_llm_stack()

                assert stack2 is custom_stack
                assert stack2.model == "custom-model"
                assert stack1 is not stack2