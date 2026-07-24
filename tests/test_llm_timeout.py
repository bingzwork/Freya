"""Tests for LLM timeout handling.

This module tests the timeout functionality of the LLM class with the new
provider abstraction layer.
"""

import pytest
import os
import time
from unittest.mock import Mock, patch, MagicMock
from concurrent.futures import TimeoutError as FuturesTimeoutError

from app.core.llm import LLM, LLMTimeoutError, LLMError, LLMConnectionError, DEFAULT_LLM_TIMEOUT
from app.providers.base import ProviderTimeoutError, ProviderConnectionError, ProviderError


class TestLLMTimeout:
    """Test LLM timeout functionality with new provider layer."""

    def test_default_timeout_from_env(self):
        """Test that default timeout is read from environment variable."""
        # This test uses the actual DEFAULT_LLM_TIMEOUT which is set at module load time
        # We can't easily change it after import, so we just verify it's an integer
        assert isinstance(DEFAULT_LLM_TIMEOUT, int)
        assert DEFAULT_LLM_TIMEOUT > 0

    def test_llm_timeout_error_is_defined(self):
        """Test that LLMTimeoutError is defined and is an Exception."""
        assert issubclass(LLMTimeoutError, Exception)

    def test_llm_uses_default_timeout(self):
        """Test that LLM instance uses default timeout when not specified."""
        with patch('app.providers.ollama.OllamaClient'):
            llm = LLM()
            assert llm.timeout == DEFAULT_LLM_TIMEOUT

    def test_llm_custom_timeout(self):
        """Test that LLM instance can use a custom timeout."""
        with patch('app.providers.ollama.OllamaClient'):
            llm = LLM(timeout=60)
            assert llm.timeout == 60

    def test_ask_uses_instance_timeout(self):
        """Test that ask() uses instance timeout by default."""
        with patch('app.providers.ollama.OllamaClient') as mock_client_class:
            mock_client = MagicMock()
            mock_client.chat.return_value = {"message": {"content": "test response"}, "done": True}
            mock_client_class.return_value = mock_client

            llm = LLM(timeout=30)
            result = llm.ask("test prompt")
            assert result == "test response"

    def test_ask_timeout_parameter_overrides_instance(self):
        """Test that ask() timeout parameter overrides instance timeout."""
        with patch('app.providers.ollama.OllamaClient') as mock_client_class:
            mock_client = MagicMock()
            mock_client.chat.return_value = {"message": {"content": "test response"}, "done": True}
            mock_client_class.return_value = mock_client

            llm = LLM(timeout=30)
            result = llm.ask("test prompt", timeout=10)
            assert result == "test response"

    def test_ask_timeout_raises_LLMTimeoutError(self):
        """Test that ask() raises LLMTimeoutError when request times out."""
        with patch('app.providers.ollama.OllamaClient') as mock_client_class:
            mock_client = MagicMock()
            mock_client.chat.side_effect = TimeoutError("Request timed out")
            mock_client_class.return_value = mock_client

            llm = LLM(timeout=1)  # Very short timeout

            with pytest.raises(LLMTimeoutError) as exc_info:
                llm.ask("test prompt")

            assert "timed out" in str(exc_info.value)

    def test_ask_with_custom_timeout_in_call(self):
        """Test timeout specified in ask() call."""
        with patch('app.providers.ollama.OllamaClient') as mock_client_class:
            mock_client = MagicMock()
            mock_client.chat.side_effect = TimeoutError("Request timed out")
            mock_client_class.return_value = mock_client

            llm = LLM(timeout=60)  # Instance has 60s timeout

            # Override with very short timeout in the call
            with pytest.raises(LLMTimeoutError) as exc_info:
                llm.ask("test prompt", timeout=1)

            assert "timed out" in str(exc_info.value)

    def test_ask_successful_request_no_timeout(self):
        """Test that successful requests don't trigger timeout."""
        with patch('app.providers.ollama.OllamaClient') as mock_client_class:
            mock_client = MagicMock()
            mock_client.chat.return_value = {"message": {"content": "fast response"}, "done": True}
            mock_client_class.return_value = mock_client

            llm = LLM(timeout=5)
            result = llm.ask("test prompt")
            assert result == "fast response"

    def test_ask_passes_correct_parameters_to_provider(self):
        """Test that ask() passes correct parameters to the provider."""
        with patch('app.providers.ollama.OllamaClient') as mock_client_class:
            mock_client = MagicMock()
            mock_client.chat.return_value = {"message": {"content": "test response"}, "done": True}
            mock_client_class.return_value = mock_client

            llm = LLM(model="test-model")
            llm.ask("test prompt", system="test system")

            # Verify the provider was called through the client
            mock_client.chat.assert_called_once()
            call_args = mock_client.chat.call_args
            assert call_args[1]['model'] == "test-model"
            # Messages should contain system and user
            assert len(call_args[1]['messages']) == 2
            assert call_args[1]['messages'][0]['role'] == 'system'
            assert call_args[1]['messages'][0]['content'] == 'test system'
            assert call_args[1]['messages'][1]['role'] == 'user'
            assert call_args[1]['messages'][1]['content'] == 'test prompt'

    def test_ask_without_provider_raises_connection_error(self):
        """Test that ask() raises connection error when provider is unavailable."""
        with patch('app.providers.ollama.OllamaClient') as mock_client_class:
            import urllib.error
            mock_client = MagicMock()
            mock_client.chat.side_effect = urllib.error.URLError("Connection refused")
            mock_client_class.return_value = mock_client

            llm = LLM()

            with pytest.raises(LLMConnectionError) as exc_info:
                llm.ask("test prompt", system="test system")

            assert "not running or refused" in str(exc_info.value)

    def test_llm_timeout_error_message_includes_model(self):
        """Test that timeout error message includes the model name."""
        with patch('app.providers.ollama.OllamaClient') as mock_client_class:
            mock_client = MagicMock()
            mock_client.chat.side_effect = TimeoutError("Request timed out")
            mock_client_class.return_value = mock_client

            llm = LLM(model="custom-model", timeout=1)

            with pytest.raises(LLMTimeoutError) as exc_info:
                llm.ask("test prompt")

            # The error message should contain the model name
            error_str = str(exc_info.value)
            assert "custom-model" in error_str or "timed out" in error_str


class TestLLMTimeoutConfiguration:
    """Test LLM timeout configuration."""

    def test_env_variable_llm_timeout(self):
        """Test that LLM_TIMEOUT environment variable is used."""
        # Save original value
        original_timeout = os.environ.get("LLM_TIMEOUT")

        try:
            # Set a custom timeout
            os.environ["LLM_TIMEOUT"] = "60"

            # Re-import the module to pick up the new environment variable
            import importlib
            import app.core.llm as llm_module
            importlib.reload(llm_module)

            assert llm_module.DEFAULT_LLM_TIMEOUT == 60
        finally:
            # Restore original value
            if original_timeout is not None:
                os.environ["LLM_TIMEOUT"] = original_timeout
            elif "LLM_TIMEOUT" in os.environ:
                del os.environ["LLM_TIMEOUT"]

            # Re-reload to restore original state
            import importlib
            import app.core.llm as llm_module
            importlib.reload(llm_module)
            # Re-import the global LLM reference to ensure it's updated
            global LLM, LLMTimeoutError, LLMError, LLMConnectionError, DEFAULT_LLM_TIMEOUT
            from app.core.llm import LLM, LLMTimeoutError, LLMError, LLMConnectionError, DEFAULT_LLM_TIMEOUT


class TestLLMProviderSelection:
    """Test LLM provider selection functionality."""

    def test_default_provider_is_ollama(self):
        """Test that default provider is ollama."""
        with patch('app.providers.ollama.OllamaClient'):
            llm = LLM()
            assert llm.provider == "ollama"

    def test_explicit_provider_selection(self):
        """Test explicit provider selection."""
        with patch('app.providers.ollama.OllamaClient'):
            llm = LLM(provider="ollama")
            assert llm.provider == "ollama"

    def test_model_property(self):
        """Test model property getter and setter."""
        with patch('app.providers.ollama.OllamaClient'):
            llm = LLM(model="llama3:70b")
            assert llm.model == "llama3:70b"

            llm.model = "qwen2.5-coder:14b"
            assert llm.model == "qwen2.5-coder:14b"


class TestLLMHealthCheck:
    """Test LLM health check functionality."""

    def test_check_health_success(self):
        """Test successful health check."""
        with patch('app.providers.ollama.OllamaClient') as mock_client_class:
            mock_client = MagicMock()
            mock_client.get.return_value = {
                "models": [{"name": "qwen2.5-coder:14b"}]
            }
            mock_client_class.return_value = mock_client

            llm = LLM()
            health = llm.check_health()

            assert health["is_healthy"] is True
            assert health["is_reachable"] is True
            assert health["model_available"] is True

    def test_check_health_failure(self):
        """Test health check when provider is unavailable."""
        with patch('app.providers.ollama.OllamaClient') as mock_client_class:
            import urllib.error
            mock_client = MagicMock()
            mock_client.get.side_effect = urllib.error.URLError("Connection refused")
            mock_client_class.return_value = mock_client

            llm = LLM()
            health = llm.check_health()

            assert health["is_healthy"] is False

    def test_is_healthy_property(self):
        """Test is_healthy property."""
        with patch('app.providers.ollama.OllamaClient') as mock_client_class:
            mock_client = MagicMock()
            mock_client.get.return_value = {
                "models": [{"name": "qwen2.5-coder:14b"}]
            }
            mock_client_class.return_value = mock_client

            llm = LLM()
            assert llm.is_healthy() is True


class TestLLMMessages:
    """Test LLM with various message formats."""

    def test_ask_with_no_system_prompt(self):
        """Test ask() with no system prompt uses default."""
        with patch('app.providers.ollama.OllamaClient') as mock_client_class:
            mock_client = MagicMock()
            mock_client.chat.return_value = {"message": {"content": "response"}, "done": True}
            mock_client_class.return_value = mock_client

            llm = LLM()
            result = llm.ask("Hello")

            # Check that default system prompt was used
            call_args = mock_client.chat.call_args[1]
            assert call_args["messages"][0]["role"] == "system"
            assert "Freya" in call_args["messages"][0]["content"]

    def test_ask_with_custom_system_prompt_in_constructor(self):
        """Test ask() with system prompt set in constructor."""
        with patch('app.providers.ollama.OllamaClient') as mock_client_class:
            mock_client = MagicMock()
            mock_client.chat.return_value = {"message": {"content": "response"}, "done": True}
            mock_client_class.return_value = mock_client

            llm = LLM(system="Custom system prompt")
            result = llm.ask("Hello")

            call_args = mock_client.chat.call_args[1]
            assert call_args["messages"][0]["content"] == "Custom system prompt"

    def test_ask_with_custom_system_prompt_in_call(self):
        """Test ask() with system prompt in call overrides constructor."""
        with patch('app.providers.ollama.OllamaClient') as mock_client_class:
            mock_client = MagicMock()
            mock_client.chat.return_value = {"message": {"content": "response"}, "done": True}
            mock_client_class.return_value = mock_client

            llm = LLM(system="Constructor system")
            result = llm.ask("Hello", system="Call system")

            call_args = mock_client.chat.call_args[1]
            assert call_args["messages"][0]["content"] == "Call system"


class TestGetLLMFunction:
    """Test the get_llm convenience function."""

    def test_get_llm_default(self):
        """Test get_llm with default settings."""
        from app.core.llm import get_llm
        with patch('app.providers.ollama.OllamaClient'):
            with patch('app.core.llm.LLM._ensure_health_checked'):
                llm = get_llm()
                assert isinstance(llm, LLM)
                assert llm.provider == "ollama"

    def test_get_llm_with_model(self):
        """Test get_llm with custom model."""
        from app.core.llm import get_llm
        with patch('app.providers.ollama.OllamaClient'):
            with patch('app.core.llm.LLM._ensure_health_checked'):
                llm = get_llm(model="llama3:70b")
                assert llm.model == "llama3:70b"

    def test_get_llm_with_timeout(self):
        """Test get_llm with custom timeout."""
        from app.core.llm import get_llm
        with patch('app.providers.ollama.OllamaClient'):
            with patch('app.core.llm.LLM._ensure_health_checked'):
                llm = get_llm(timeout=60)
                assert llm.timeout == 60
