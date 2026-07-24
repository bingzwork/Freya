"""Base LLM Provider Abstract Class.

This module defines the abstract base class that all LLM providers must implement,
ensuring a consistent interface across different AI services.
"""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class ProviderError(Exception):
    """Base exception for all provider errors."""

    def __init__(self, message: str, provider_name: str = "unknown", details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.provider_name = provider_name
        self.details = details or {}
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        return f"[{self.provider_name}] {self.message}"


class ProviderConnectionError(ProviderError):
    """Exception raised when unable to connect to the provider."""
    pass


class ProviderTimeoutError(ProviderError):
    """Exception raised when a provider request times out."""

    def __init__(self, message: str, provider_name: str = "unknown", timeout_seconds: float = 0, details: Optional[Dict[str, Any]] = None):
        self.timeout_seconds = timeout_seconds
        super().__init__(message, provider_name, details)

    def _format_message(self) -> str:
        return f"[{self.provider_name}] {self.message} (timeout: {self.timeout_seconds}s)"


class ProviderAuthenticationError(ProviderError):
    """Exception raised when authentication fails with the provider."""
    pass


class ProviderModelNotFoundError(ProviderError):
    """Exception raised when the requested model is not available."""

    def __init__(self, message: str, provider_name: str = "unknown", model_name: str = "unknown", available_models: Optional[List[str]] = None, details: Optional[Dict[str, Any]] = None):
        self.model_name = model_name
        self.available_models = available_models or []
        super().__init__(message, provider_name, details)

    def _format_message(self) -> str:
        msg = f"[{self.provider_name}] {self.message} (model: {self.model_name})"
        if self.available_models:
            msg += f"\nAvailable models: {', '.join(self.available_models)}"
        return msg


class ProviderRateLimitError(ProviderError):
    """Exception raised when rate limit is exceeded."""
    pass


class ProviderConfigurationError(ProviderError):
    """Exception raised when provider configuration is invalid."""
    pass


@dataclass
class ProviderConfig:
    """Configuration for an LLM provider."""
    provider_name: str
    model: str = ""
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    timeout: float = 120.0
    max_retries: int = 3
    retry_delay: float = 1.0
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderResponse:
    """Response from an LLM provider."""
    content: str
    model: str
    provider: str
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, int]] = None
    raw_response: Optional[Dict[str, Any]] = None
    request_duration: float = 0.0
    response_duration: float = 0.0


@dataclass
class Message:
    """A chat message."""
    role: str  # "system", "user", "assistant"
    content: str


@dataclass
class ProviderHealthStatus:
    """Health status of a provider."""
    provider_name: str
    is_healthy: bool
    is_reachable: bool
    model_available: bool
    model_name: Optional[str] = None
    error_message: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider_name": self.provider_name,
            "is_healthy": self.is_healthy,
            "is_reachable": self.is_reachable,
            "model_available": self.model_available,
            "model_name": self.model_name,
            "error_message": self.error_message,
            "details": self.details,
        }


class BaseLLMProvider(ABC):
    """Abstract base class for all LLM providers.

    All concrete providers (Ollama, Claude, OpenAI, etc.) must implement
    the methods defined in this class.
    """

    provider_name: str = "base"

    def __init__(self, config: Optional[ProviderConfig] = None):
        """Initialize the provider with configuration.

        Args:
            config: Provider configuration. If None, uses default values.
        """
        self.config = config or ProviderConfig(provider_name=self.provider_name)
        self._last_request_duration: float = 0.0
        self._last_response_duration: float = 0.0

    @property
    def name(self) -> str:
        """Get the provider name."""
        return self.provider_name

    @property
    def model(self) -> str:
        """Get the current model name."""
        return self.config.model

    @model.setter
    def model(self, value: str) -> None:
        """Set the model name."""
        self.config.model = value

    @property
    def timeout(self) -> float:
        """Get the request timeout in seconds."""
        return self.config.timeout

    @timeout.setter
    def timeout(self, value: float) -> None:
        """Set the request timeout in seconds."""
        self.config.timeout = value

    @abstractmethod
    def ask(
        self,
        prompt: str,
        system: Optional[str] = None,
        messages: Optional[List[Message]] = None,
        timeout: Optional[float] = None,
        **kwargs
    ) -> ProviderResponse:
        """Send a prompt to the LLM and return the response.

        Args:
            prompt: The user prompt.
            system: Optional system prompt. If provided, it will be used as a system message.
            messages: Optional list of previous messages for conversation context.
            timeout: Optional timeout override for this request.
            **kwargs: Additional provider-specific parameters.

        Returns:
            ProviderResponse containing the LLM's response.

        Raises:
            ProviderConnectionError: If unable to connect to the provider.
            ProviderTimeoutError: If the request times out.
            ProviderAuthenticationError: If authentication fails.
            ProviderModelNotFoundError: If the model is not available.
            ProviderRateLimitError: If rate limit is exceeded.
            ProviderError: For other provider-specific errors.
        """
        pass

    @abstractmethod
    def check_health(self) -> ProviderHealthStatus:
        """Check the health of the provider.

        Performs connectivity and model availability checks.

        Returns:
            ProviderHealthStatus indicating the current health of the provider.
        """
        pass

    @abstractmethod
    def list_models(self) -> List[str]:
        """List available models from this provider.

        Returns:
            List of available model names.

        Raises:
            ProviderConnectionError: If unable to connect to the provider.
            ProviderError: For other errors.
        """
        pass

    def is_healthy(self) -> bool:
        """Check if the provider is currently healthy.

        Returns:
            True if the provider is healthy, False otherwise.
        """
        try:
            status = self.check_health()
            return status.is_healthy
        except Exception:
            return False

    def get_last_request_duration(self) -> float:
        """Get the duration of the last request in seconds."""
        return self._last_request_duration

    def get_last_response_duration(self) -> float:
        """Get the duration of the last response processing in seconds."""
        return self._last_response_duration

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(model={self.model}, timeout={self.timeout})"
