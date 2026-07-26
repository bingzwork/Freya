"""Tests for the LLM module."""
import pytest
from unittest.mock import patch, MagicMock

from app.core.llm import LLM


class MockOllama:
    """Mock ollama module for testing."""
    def __init__(self):
        self.calls = []

    def chat(self, model, messages):
        self.calls.append({"model": model, "messages": messages})
        return {"message": {"content": "Test response"}}


class TestLLM:
    """Test the LLM class."""

    def test_llm_init_default_model(self):
        """Test LLM initialization with default model."""
        llm = LLM()
        assert llm.model == "qwen2.5-coder:14b"

    def test_llm_init_custom_model(self):
        """Test LLM initialization with custom model."""
        llm = LLM(model="llama3:8b")
        assert llm.model == "llama3:8b"

    def test_ask_without_ollama(self):
        """Test ask() when ollama is not available."""
        with patch("app.core.llm.OLLAMA_AVAILABLE", False):
            llm = LLM()
            response = llm.ask("Hello", system="Test")
            assert "[LLM response not available - ollama not installed]" in response
            assert "Hello" in response
            assert "Test" in response

    def test_ask_with_ollama(self):
        """Test ask() with mocked ollama."""
        mock_ollama = MockOllama()
        with patch("app.core.llm.ollama", mock_ollama):
            with patch("app.core.llm.OLLAMA_AVAILABLE", True):
                llm = LLM(model="test-model")
                response = llm.ask("Test prompt", system="Test system")

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
                llm = LLM()
                response = llm.ask("User message", system="Custom system")

                assert response == "Test response"
                call = mock_ollama.calls[0]
                assert call["messages"][0]["content"] == "Custom system"

    def test_ask_truncates_long_prompt_in_unavailable_message(self):
        """Test that unavailable message truncates long prompts."""
        with patch("app.core.llm.OLLAMA_AVAILABLE", False):
            llm = LLM()
            long_prompt = "x" * 200
            response = llm.ask(long_prompt)
            # Should truncate to 100 chars + "..."
            assert long_prompt[:100] + "..." in response


if __name__ == "__main__":
    pytest.main([__file__, "-v"])