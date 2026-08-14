"""Tests for the Provider Abstraction Layer.

This module contains comprehensive tests for the provider system,
including the base provider, Ollama provider, and provider factory.
"""

import json
import time
import pytest
import os
from unittest.mock import Mock, patch, MagicMock, PropertyMock
from concurrent.futures import TimeoutError as FuturesTimeoutError

# Import the provider layer
from app.providers.base import (
    BaseLLMProvider,
    ProviderConfig,
    ProviderError,
    ProviderConnectionError,
    ProviderTimeoutError,
    ProviderAuthenticationError,
    ProviderModelNotFoundError,
    ProviderRateLimitError,
    ProviderConfigurationError,
    Message,
    ProviderResponse,
    ProviderHealthStatus,
)
from app.providers.ollama import OllamaProvider
from app.providers.factory import ProviderFactory
from app.providers.health import ProviderHealthChecker, HealthCheckResult, AggregateHealthStatus
from app.core.logger import logger


class TestProviderConfig:
    """Test ProviderConfig dataclass."""

    def test_default_config(self):
        """Test default provider configuration."""
        config = ProviderConfig(provider_name="test")
        assert config.provider_name == "test"
        assert config.model == ""
        assert config.base_url is None
        assert config.api_key is None
        assert config.timeout == 120.0
        assert config.max_retries == 3
        assert config.retry_delay == 1.0
        assert config.extra == {}

    def test_custom_config(self):
        """Test custom provider configuration."""
        config = ProviderConfig(
            provider_name="ollama",
            model="llama3:70b",
            base_url="http://localhost:11434",
            timeout=60.0,
            max_retries=5,
            extra={"temperature": 0.7},
        )
        assert config.provider_name == "ollama"
        assert config.model == "llama3:70b"
        assert config.base_url == "http://localhost:11434"
        assert config.timeout == 60.0
        assert config.max_retries == 5
        assert config.extra == {"temperature": 0.7}


class TestMessage:
    """Test Message dataclass."""

    def test_system_message(self):
        """Test system message creation."""
        msg = Message(role="system", content="You are a helpful assistant.")
        assert msg.role == "system"
        assert msg.content == "You are a helpful assistant."

    def test_user_message(self):
        """Test user message creation."""
        msg = Message(role="user", content="Hello, world!")
        assert msg.role == "user"
        assert msg.content == "Hello, world!"


class TestProviderResponse:
    """Test ProviderResponse dataclass."""

    def test_basic_response(self):
        """Test basic response creation."""
        response = ProviderResponse(
            content="Hello!",
            model="qwen3:8b",
            provider="ollama",
        )
        assert response.content == "Hello!"
        assert response.model == "qwen3:8b"
        assert response.provider == "ollama"
        assert response.finish_reason is None
        assert response.usage is None
        assert response.raw_response is None
        assert response.request_duration == 0.0
        assert response.response_duration == 0.0

    def test_full_response(self):
        """Test response with all fields."""
        response = ProviderResponse(
            content="Hello!",
            model="llama3:70b",
            provider="ollama",
            finish_reason="stop",
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            raw_response={"message": {"content": "Hello!"}},
            request_duration=1.5,
            response_duration=0.5,
        )
        assert response.finish_reason == "stop"
        assert response.usage == {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
        assert response.raw_response == {"message": {"content": "Hello!"}}
        assert response.request_duration == 1.5
        assert response.response_duration == 0.5


class TestProviderHealthStatus:
    """Test ProviderHealthStatus dataclass."""

    def test_healthy_status(self):
        """Test healthy status creation."""
        status = ProviderHealthStatus(
            provider_name="ollama",
            is_healthy=True,
            is_reachable=True,
            model_available=True,
            model_name="qwen3:8b",
        )
        assert status.is_healthy is True
        assert status.is_reachable is True
        assert status.model_available is True
        assert status.model_name == "qwen3:8b"
        assert status.error_message is None

    def test_unhealthy_status(self):
        """Test unhealthy status creation."""
        status = ProviderHealthStatus(
            provider_name="ollama",
            is_healthy=False,
            is_reachable=False,
            model_available=False,
            error_message="Connection refused",
        )
        assert status.is_healthy is False
        assert status.is_reachable is False
        assert status.model_available is False
        assert status.error_message == "Connection refused"

    def test_to_dict(self):
        """Test conversion to dictionary."""
        status = ProviderHealthStatus(
            provider_name="ollama",
            is_healthy=True,
            is_reachable=True,
            model_available=True,
            model_name="llama3:70b",
            details={"available_models": ["llama3:70b", "qwen3:8b"]},
        )
        result = status.to_dict()
        assert result["provider_name"] == "ollama"
        assert result["is_healthy"] is True
        assert result["is_reachable"] is True
        assert result["model_available"] is True
        assert result["model_name"] == "llama3:70b"
        assert result["details"] == {"available_models": ["llama3:70b", "qwen3:8b"]}


class TestProviderErrorHierarchy:
    """Test provider error class hierarchy."""

    def test_provider_error_base(self):
        """Test ProviderError base class."""
        error = ProviderError(message="Test error", provider_name="test")
        assert str(error) == "[test] Test error"
        assert error.message == "Test error"
        assert error.provider_name == "test"
        assert error.details == {}

    def test_provider_error_with_details(self):
        """Test ProviderError with details."""
        error = ProviderError(
            message="Connection failed",
            provider_name="ollama",
            details={"url": "http://localhost:11434", "error": "Connection refused"},
        )
        assert error.details == {"url": "http://localhost:11434", "error": "Connection refused"}

    def test_provider_connection_error(self):
        """Test ProviderConnectionError."""
        error = ProviderConnectionError(
            message="Server not reachable",
            provider_name="ollama",
        )
        assert isinstance(error, ProviderError)
        assert str(error) == "[ollama] Server not reachable"

    def test_provider_timeout_error(self):
        """Test ProviderTimeoutError."""
        error = ProviderTimeoutError(
            message="Request timed out",
            provider_name="ollama",
            timeout_seconds=30.0,
        )
        assert isinstance(error, ProviderError)
        assert "30.0s" in str(error)

    def test_provider_model_not_found_error(self):
        """Test ProviderModelNotFoundError."""
        error = ProviderModelNotFoundError(
            message="Model not available",
            provider_name="ollama",
            model_name="nonexistent:model",
            available_models=["llama3:70b", "qwen3:8b"],
        )
        assert isinstance(error, ProviderError)
        error_str = str(error)
        assert "nonexistent:model" in error_str
        assert "llama3:70b" in error_str

    def test_provider_authentication_error(self):
        """Test ProviderAuthenticationError."""
        error = ProviderAuthenticationError(
            message="Invalid API key",
            provider_name="claude",
        )
        assert isinstance(error, ProviderError)
        assert "Invalid API key" in str(error)

    def test_provider_rate_limit_error(self):
        """Test ProviderRateLimitError."""
        error = ProviderRateLimitError(
            message="Rate limit exceeded",
            provider_name="openai",
        )
        assert isinstance(error, ProviderError)
        assert "Rate limit exceeded" in str(error)

    def test_provider_configuration_error(self):
        """Test ProviderConfigurationError."""
        error = ProviderConfigurationError(
            message="Invalid configuration",
            provider_name="gemini",
        )
        assert isinstance(error, ProviderError)
        assert "Invalid configuration" in str(error)


class TestBaseLLMProvider:
    """Test BaseLLMProvider abstract class."""

    def test_provider_name(self):
        """Test provider name property."""
        config = ProviderConfig(provider_name="test")
        # We need a concrete implementation to test
        class TestProvider(BaseLLMProvider):
            provider_name = "test"
            def ask(self, *args, **kwargs):
                pass
            def check_health(self):
                pass
            def list_models(self):
                pass

        provider = TestProvider(config)
        assert provider.name == "test"

    def test_model_property(self):
        """Test model property."""
        config = ProviderConfig(provider_name="test", model="test-model")

        class TestProvider(BaseLLMProvider):
            provider_name = "test"
            def ask(self, *args, **kwargs):
                pass
            def check_health(self):
                pass
            def list_models(self):
                pass

        provider = TestProvider(config)
        assert provider.model == "test-model"
        provider.model = "new-model"
        assert provider.model == "new-model"

    def test_timeout_property(self):
        """Test timeout property."""
        config = ProviderConfig(provider_name="test", timeout=60.0)

        class TestProvider(BaseLLMProvider):
            provider_name = "test"
            def ask(self, *args, **kwargs):
                pass
            def check_health(self):
                pass
            def list_models(self):
                pass

        provider = TestProvider(config)
        assert provider.timeout == 60.0
        provider.timeout = 120.0
        assert provider.timeout == 120.0


class TestOllamaProvider:
    """Test OllamaProvider implementation."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock Ollama client."""
        with patch('app.providers.ollama.OllamaClient') as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            yield mock_client

    def test_initialization_with_default_config(self, mock_client):
        """Test OllamaProvider initialization with default config."""
        provider = OllamaProvider()
        assert provider.provider_name == "ollama"
        assert provider.model == "qwen3:8b"
        assert provider.base_url == "http://localhost:11434"
        assert provider.timeout == 120.0

    def test_initialization_with_custom_config(self, mock_client):
        """Test OllamaProvider initialization with custom config."""
        config = ProviderConfig(
            provider_name="ollama",
            model="llama3:70b",
            base_url="http://localhost:8080",
            timeout=60.0,
        )
        provider = OllamaProvider(config)
        assert provider.model == "llama3:70b"
        assert provider.base_url == "http://localhost:8080"
        assert provider.timeout == 60.0

    def test_ask_success(self, mock_client):
        """Test successful ask() call."""
        mock_client.chat.return_value = {
            "message": {"content": "Hello!"},
            "done": True,
        }

        provider = OllamaProvider()
        response = provider.ask("Hello, world!")

        assert isinstance(response, ProviderResponse)
        assert response.content == "Hello!"
        assert response.model == "qwen3:8b"
        assert response.provider == "ollama"
        assert response.finish_reason is True

    def test_ask_with_system_prompt(self, mock_client):
        """Test ask() with system prompt."""
        mock_client.chat.return_value = {
            "message": {"content": "I am helpful"},
            "done": True,
        }

        provider = OllamaProvider()
        response = provider.ask("Hello", system="You are helpful")

        assert response.content == "I am helpful"
        # Verify system message was included
        call_kwargs = mock_client.chat.call_args[1]
        assert call_kwargs["model"] == "qwen3:8b"
        assert len(call_kwargs["messages"]) == 2
        assert call_kwargs["messages"][0]["role"] == "system"
        assert call_kwargs["messages"][0]["content"] == "You are helpful"

    def test_ask_with_messages(self, mock_client):
        """Test ask() with existing messages."""
        mock_client.chat.return_value = {
            "message": {"content": "Response"},
            "done": True,
        }

        messages = [
            Message(role="system", content="System"),
            Message(role="user", content="First message"),
            Message(role="assistant", content="First response"),
        ]

        provider = OllamaProvider()
        response = provider.ask("Second message", messages=messages)

        call_kwargs = mock_client.chat.call_args[1]
        # Should have existing messages + system + user prompt
        assert len(call_kwargs["messages"]) >= len(messages)

    def test_ask_timeout(self, mock_client):
        """Test ask() with custom timeout."""
        mock_client.chat.return_value = {
            "message": {"content": "Response"},
            "done": True,
        }

        provider = OllamaProvider()
        provider.ask("Hello", timeout=30.0)

        call_kwargs = mock_client.chat.call_args[1]
        assert call_kwargs["timeout"] == 30.0

    def test_ask_connection_error(self, mock_client):
        """Test ask() with connection error."""
        import urllib.error
        mock_client.chat.side_effect = urllib.error.URLError("Connection refused")

        provider = OllamaProvider()

        with pytest.raises(ProviderConnectionError) as exc_info:
            provider.ask("Hello")

        assert "not running or refused" in str(exc_info.value)

    def test_ask_timeout_error(self, mock_client):
        """Test ask() with timeout error."""
        mock_client.chat.side_effect = TimeoutError("Request timed out")

        config = ProviderConfig(
            provider_name="ollama",
            timeout=5.0,
        )
        provider = OllamaProvider(config)

        with pytest.raises(ProviderTimeoutError) as exc_info:
            provider.ask("Hello")

        assert "timed out" in str(exc_info.value)
        assert exc_info.value.timeout_seconds == 5.0

    def test_check_health_success(self, mock_client):
        """Test successful health check."""
        mock_client.get.return_value = {
            "models": [
                {"name": "qwen3:8b"},
                {"name": "llama3:70b"},
            ]
        }

        provider = OllamaProvider()
        status = provider.check_health()

        assert status.is_healthy is True
        assert status.is_reachable is True
        assert status.model_available is True
        assert status.provider_name == "ollama"

    def test_check_health_server_unreachable(self, mock_client):
        """Test health check when server is unreachable."""
        import urllib.error
        mock_client.get.side_effect = urllib.error.URLError("Connection refused")

        provider = OllamaProvider()
        status = provider.check_health()

        assert status.is_healthy is False
        assert status.is_reachable is False
        assert status.model_available is False
        assert status.error_message is not None

    def test_check_health_model_not_found(self, mock_client):
        """Test health check when model is not found."""
        mock_client.get.return_value = {
            "models": [
                {"name": "llama3:70b"},
                {"name": "mistral:7b"},
            ]
        }

        config = ProviderConfig(
            provider_name="ollama",
            model="nonexistent:model",
        )
        provider = OllamaProvider(config)
        status = provider.check_health()

        assert status.is_healthy is False
        assert status.is_reachable is True
        assert status.model_available is False
        assert "nonexistent:model" in status.error_message

    def test_list_models_success(self, mock_client):
        """Test successful model listing."""
        mock_client.get.return_value = {
            "models": [
                {"name": "qwen3:8b"},
                {"name": "llama3:70b"},
                {"name": "mistral:7b"},
            ]
        }

        provider = OllamaProvider()
        models = provider.list_models()

        assert len(models) == 3
        assert "qwen3:8b" in models
        assert "llama3:70b" in models
        assert "mistral:7b" in models

    def test_list_models_connection_error(self, mock_client):
        """Test model listing with connection error."""
        import urllib.error
        mock_client.get.side_effect = urllib.error.URLError("Connection refused")

        provider = OllamaProvider()

        with pytest.raises(ProviderConnectionError):
            provider.list_models()

    def test_repr(self, mock_client):
        """Test provider string representation."""
        provider = OllamaProvider()
        repr_str = repr(provider)
        assert "OllamaProvider" in repr_str
        assert "qwen3:8b" in repr_str


class TestProviderFactory:
    """Test ProviderFactory."""

    def test_register_provider(self):
        """Test provider registration."""
        ProviderFactory.register_provider("test", OllamaProvider)
        providers = ProviderFactory.get_registered_providers()
        assert "test" in providers
        # Clean up
        ProviderFactory.unregister_provider("test")

    def test_unregister_provider(self):
        """Test provider unregistration."""
        ProviderFactory.register_provider("test", OllamaProvider)
        assert "test" in ProviderFactory.get_registered_providers()

        ProviderFactory.unregister_provider("test")
        assert "test" not in ProviderFactory.get_registered_providers()

    def test_set_get_default_provider(self):
        """Test default provider setting."""
        original = ProviderFactory.get_default_provider()
        try:
            ProviderFactory.set_default_provider("ollama")
            assert ProviderFactory.get_default_provider() == "ollama"
        finally:
            ProviderFactory.set_default_provider(original)

    def test_create_ollama_provider(self):
        """Test creating an Ollama provider."""
        with patch('app.providers.ollama.OllamaClient'):
            provider = ProviderFactory.create("ollama")
            assert isinstance(provider, OllamaProvider)
            assert provider.provider_name == "ollama"

    def test_create_with_model(self):
        """Test creating a provider with specific model."""
        with patch('app.providers.ollama.OllamaClient'):
            provider = ProviderFactory.create("ollama", model="llama3:70b")
            assert provider.model == "llama3:70b"

    def test_create_with_base_url(self):
        """Test creating a provider with custom base URL."""
        with patch('app.providers.ollama.OllamaClient'):
            provider = ProviderFactory.create("ollama", base_url="http://localhost:8080")
            assert provider.base_url == "http://localhost:8080"

    def test_create_with_timeout(self):
        """Test creating a provider with custom timeout."""
        with patch('app.providers.ollama.OllamaClient'):
            provider = ProviderFactory.create("ollama", timeout=60.0)
            assert provider.timeout == 60.0

    def test_create_unknown_provider(self):
        """Test creating an unknown provider raises error."""
        with pytest.raises(ProviderError) as exc_info:
            ProviderFactory.create("nonexistent")

        assert "Unknown provider" in str(exc_info.value)
        assert "nonexistent" in str(exc_info.value)

    def test_create_from_config(self):
        """Test creating provider from config dictionary."""
        with patch('app.providers.ollama.OllamaClient'):
            config = {
                "provider": "ollama",
                "model": "llama3:70b",
                "base_url": "http://localhost:8080",
                "timeout": 60.0,
            }
            provider = ProviderFactory.create_from_config(config)
            assert isinstance(provider, OllamaProvider)
            assert provider.model == "llama3:70b"

    def test_alias_local_to_ollama(self):
        """Test that 'local' is an alias for 'ollama'."""
        with patch('app.providers.ollama.OllamaClient'):
            provider = ProviderFactory.create("local")
            assert isinstance(provider, OllamaProvider)


class TestProviderHealthChecker:
    """Test ProviderHealthChecker."""

    def test_check_provider_success(self):
        """Test successful provider check."""
        with patch('app.providers.ollama.OllamaClient') as mock_client_class:
            mock_client = MagicMock()
            mock_client.get.return_value = {
                "models": [{"name": "qwen3:8b"}]
            }
            mock_client_class.return_value = mock_client

            checker = ProviderHealthChecker()
            result = checker.check_provider("ollama", model="qwen3:8b")

            assert isinstance(result, HealthCheckResult)
            assert result.is_healthy is True

    def test_check_provider_failure(self):
        """Test provider check failure."""
        with patch('app.providers.ollama.OllamaClient') as mock_client_class:
            import urllib.error
            mock_client = MagicMock()
            mock_client.get.side_effect = urllib.error.URLError("Connection refused")
            mock_client_class.return_value = mock_client

            checker = ProviderHealthChecker()
            result = checker.check_provider("ollama")

            assert result.is_healthy is False
            assert result.is_reachable is False

    def test_check_all_providers(self):
        """Test checking all providers."""
        with patch('app.providers.ollama.OllamaClient') as mock_client_class:
            mock_client = MagicMock()
            mock_client.get.return_value = {
                "models": [{"name": "qwen3:8b"}]
            }
            mock_client_class.return_value = mock_client

            checker = ProviderHealthChecker()
            result = checker.check_all_providers()

            assert isinstance(result, AggregateHealthStatus)
            assert "ollama" in result.results
            assert "local" not in result.results

    def test_check_default_provider(self):
        """Test checking the default provider."""
        with patch('app.providers.ollama.OllamaClient') as mock_client_class:
            mock_client = MagicMock()
            mock_client.get.return_value = {
                "models": [{"name": "qwen3:8b"}]
            }
            mock_client_class.return_value = mock_client

            checker = ProviderHealthChecker()
            result = checker.check_default_provider()

            assert isinstance(result, HealthCheckResult)
            assert result.provider_name == "ollama"

    def test_verify_startup_success(self):
        """Test successful startup verification."""
        with patch('app.providers.ollama.OllamaClient') as mock_client_class:
            mock_client = MagicMock()
            mock_client.get.return_value = {
                "models": [{"name": "qwen3:8b"}]
            }
            mock_client_class.return_value = mock_client

            checker = ProviderHealthChecker()
            result = checker.verify_startup(model="qwen3:8b")

            assert result.is_healthy is True

    def test_verify_startup_failure_no_raise(self):
        """Test startup verification failure without raising."""
        with patch('app.providers.ollama.OllamaClient') as mock_client_class:
            import urllib.error
            mock_client = MagicMock()
            mock_client.get.side_effect = urllib.error.URLError("Connection refused")
            mock_client_class.return_value = mock_client

            checker = ProviderHealthChecker()
            result = checker.verify_startup(raise_on_failure=False)

            assert result.is_healthy is False

    def test_verify_startup_failure_raise(self):
        """Test startup verification failure with raising."""
        with patch('app.providers.ollama.OllamaClient') as mock_client_class:
            import urllib.error
            mock_client = MagicMock()
            mock_client.get.side_effect = urllib.error.URLError("Connection refused")
            mock_client_class.return_value = mock_client

            checker = ProviderHealthChecker()

            with pytest.raises(ProviderError):
                checker.verify_startup(raise_on_failure=True)


class TestHealthCheckResult:
    """Test HealthCheckResult dataclass."""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        result = HealthCheckResult(
            provider_name="ollama",
            is_healthy=True,
            is_reachable=True,
            model_available=True,
            error_message=None,
            duration=1.5,
            details={"test": "value"},
        )
        d = result.to_dict()
        assert d["provider_name"] == "ollama"
        assert d["is_healthy"] is True
        assert d["duration"] == 1.5
        assert d["details"] == {"test": "value"}


class TestAggregateHealthStatus:
    """Test AggregateHealthStatus dataclass."""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        status = AggregateHealthStatus(
            all_providers_healthy=True,
            healthy_providers=["ollama"],
            unhealthy_providers=[],
            default_provider_healthy=True,
            default_provider="ollama",
        )
        d = status.to_dict()
        assert d["all_providers_healthy"] is True
        assert d["healthy_providers"] == ["ollama"]
        assert d["default_provider"] == "ollama"

    def test_get_summary_all_healthy(self):
        """Test summary when all providers are healthy."""
        status = AggregateHealthStatus(
            all_providers_healthy=True,
            healthy_providers=["ollama", "claude"],
            unhealthy_providers=[],
        )
        summary = status.get_summary()
        assert "All" in summary
        assert "healthy" in summary

    def test_get_summary_some_unhealthy(self):
        """Test summary when some providers are unhealthy."""
        status = AggregateHealthStatus(
            all_providers_healthy=False,
            healthy_providers=["ollama"],
            unhealthy_providers=["claude"],
        )
        summary = status.get_summary()
        assert "Healthy" in summary
        assert "Unhealthy" in summary
        assert "ollama" in summary
        assert "claude" in summary


class TestStartupHealthCheckBug:
    """Tests for the startup health check bug fix.

    These tests verify that the HealthChecker properly reuses existing
    provider instances instead of creating new ones with incomplete configuration.
    """

    def test_health_checker_reuses_provider(self):
        """Test that HealthChecker can reuse an existing provider instance."""
        with patch('app.providers.ollama.OllamaClient') as mock_client:
            # Create a provider with full configuration
            config = ProviderConfig(
                provider_name="ollama",
                model="qwen3:8b",
                base_url="http://localhost:11434",
                timeout=120.0,
            )
            provider = OllamaProvider(config)

            # Create health checker and check with existing provider
            checker = ProviderHealthChecker()
            
            # Mock the check_health method to avoid actual network calls
            provider.check_health = Mock(return_value=ProviderHealthStatus(
                provider_name="ollama",
                is_healthy=True,
                is_reachable=True,
                model_available=True,
                model_name="qwen3:8b",
            ))

            # Call check_provider with the existing provider
            result = checker.check_provider(provider_name="ollama", provider=provider)

            # Verify the result
            assert result.provider_name == "ollama"
            assert result.is_healthy is True
            # Verify that the existing provider's check_health was called
            provider.check_health.assert_called_once()

    def test_verify_startup_with_provider_reuse(self):
        """Test that verify_startup can reuse an existing provider."""
        with patch('app.providers.ollama.OllamaClient') as mock_client:
            # Create a provider with full configuration
            config = ProviderConfig(
                provider_name="ollama",
                model="qwen3:8b",
                base_url="http://localhost:11434",
                timeout=120.0,
            )
            provider = OllamaProvider(config)

            # Mock the check_health method
            provider.check_health = Mock(return_value=ProviderHealthStatus(
                provider_name="ollama",
                is_healthy=True,
                is_reachable=True,
                model_available=True,
                model_name="qwen3:8b",
            ))

            # Create health checker and verify startup with existing provider
            checker = ProviderHealthChecker()
            result = checker.verify_startup(
                provider_name="ollama",
                provider=provider,
                raise_on_failure=False,
            )

            # Verify the result
            assert result.provider_name == "ollama"
            assert result.is_healthy is True
            provider.check_health.assert_called_once()

    def test_check_default_provider_with_provider_reuse(self):
        """Test that check_default_provider can reuse an existing provider."""
        with patch('app.providers.ollama.OllamaClient') as mock_client:
            # Create a provider with full configuration
            config = ProviderConfig(
                provider_name="ollama",
                model="qwen3:8b",
                base_url="http://localhost:11434",
                timeout=120.0,
            )
            provider = OllamaProvider(config)

            # Mock the check_health method
            provider.check_health = Mock(return_value=ProviderHealthStatus(
                provider_name="ollama",
                is_healthy=True,
                is_reachable=True,
                model_available=True,
                model_name="qwen3:8b",
            ))

            # Create health checker and check default provider with existing provider
            checker = ProviderHealthChecker()
            result = checker.check_default_provider(provider=provider)

            # Verify the result
            assert result.provider_name == "ollama"
            assert result.is_healthy is True
            provider.check_health.assert_called_once()
