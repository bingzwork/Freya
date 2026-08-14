"""Shared contracts for Freya LLM providers.

Concrete providers expose a common request, health, and model-discovery interface so
callers can route inference without embedding provider-specific assumptions.
"""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ProviderFailureKind(str, Enum):
    """The failure categories used by provider selection and fallback."""

    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    CONNECTION = "connection"
    AUTHENTICATION = "authentication"
    CONFIGURATION = "configuration"
    MODEL_NOT_FOUND = "model_not_found"
    RATE_LIMITED = "rate_limited"
    RESPONSE = "response"
    INTERNAL = "internal"


class ProviderHealthState(str, Enum):
    """The latest known health state for a provider instance."""

    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"


class ProviderError(Exception):
    """Base exception for all provider errors."""

    failure_kind = ProviderFailureKind.INTERNAL
    recoverable = True

    def __init__(self, message: str, provider_name: str = "unknown", details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.provider_name = provider_name
        self.details = details or {}
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        return f"[{self.provider_name}] {self.message}"


class ProviderConnectionError(ProviderError):
    """Raised when the provider cannot be contacted."""

    failure_kind = ProviderFailureKind.CONNECTION


class ProviderUnavailableError(ProviderError):
    """Raised when a provider is known to be unavailable for a request."""

    failure_kind = ProviderFailureKind.UNAVAILABLE


class ProviderTimeoutError(ProviderError):
    """Raised when a provider request exceeds its bounded timeout."""

    failure_kind = ProviderFailureKind.TIMEOUT

    def __init__(self, message: str, provider_name: str = "unknown", timeout_seconds: float = 0, details: Optional[Dict[str, Any]] = None):
        self.timeout_seconds = timeout_seconds
        super().__init__(message, provider_name, details)

    def _format_message(self) -> str:
        return f"[{self.provider_name}] {self.message} (timeout: {self.timeout_seconds}s)"


class ProviderAuthenticationError(ProviderError):
    """Raised when provider credentials are invalid or unavailable."""

    failure_kind = ProviderFailureKind.AUTHENTICATION
    recoverable = False


class ProviderModelNotFoundError(ProviderError):
    """Raised when the requested model is not available from a provider."""

    failure_kind = ProviderFailureKind.MODEL_NOT_FOUND
    recoverable = False

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
    """Raised when a provider rate limit is exceeded."""

    failure_kind = ProviderFailureKind.RATE_LIMITED


class ProviderConfigurationError(ProviderError):
    """Raised when provider configuration is invalid."""

    failure_kind = ProviderFailureKind.CONFIGURATION
    recoverable = False


class ProviderResponseError(ProviderError):
    """Raised when a provider returns an unusable response."""

    failure_kind = ProviderFailureKind.RESPONSE


class NoProviderConfiguredError(ProviderError):
    """Raised when inference is requested without configured providers."""

    failure_kind = ProviderFailureKind.CONFIGURATION
    recoverable = False


class ProvidersExhaustedError(ProviderError):
    """Raised after every eligible provider has failed or been skipped."""

    failure_kind = ProviderFailureKind.UNAVAILABLE

    def __init__(self, message: str, attempts: Optional[List[Dict[str, Any]]] = None):
        self.attempts = attempts or []
        super().__init__(message, provider_name="router", details={"attempts": self.attempts})


def classify_provider_error(error: BaseException) -> ProviderFailureKind:
    """Return a stable failure classification without flattening provider errors."""

    if isinstance(error, ProviderError):
        return error.failure_kind
    if isinstance(error, TimeoutError):
        return ProviderFailureKind.TIMEOUT
    if isinstance(error, (ConnectionError, OSError)):
        return ProviderFailureKind.CONNECTION
    return ProviderFailureKind.INTERNAL


def is_recoverable_provider_error(error: BaseException) -> bool:
    """Return whether another configured provider may safely be attempted."""

    if isinstance(error, ProviderError):
        return error.recoverable
    return classify_provider_error(error) in {
        ProviderFailureKind.TIMEOUT,
        ProviderFailureKind.CONNECTION,
        ProviderFailureKind.UNAVAILABLE,
        ProviderFailureKind.RESPONSE,
        ProviderFailureKind.INTERNAL,
    }


@dataclass
class ProviderConfig:
    """Configuration for a single LLM provider."""

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

    role: str
    content: str


@dataclass
class ProviderHealthStatus:
    """The latest health observation for a provider."""

    provider_name: str
    is_healthy: bool
    is_reachable: bool
    model_available: bool
    model_name: Optional[str] = None
    error_message: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    state: ProviderHealthState = ProviderHealthState.UNKNOWN
    checked_at: Optional[float] = None

    def __post_init__(self) -> None:
        if self.state == ProviderHealthState.UNKNOWN:
            self.state = ProviderHealthState.HEALTHY if self.is_healthy else ProviderHealthState.UNHEALTHY
        if self.checked_at is None:
            self.checked_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider_name": self.provider_name,
            "is_healthy": self.is_healthy,
            "is_reachable": self.is_reachable,
            "model_available": self.model_available,
            "model_name": self.model_name,
            "error_message": self.error_message,
            "details": self.details,
            "state": self.state.value,
            "checked_at": self.checked_at,
        }


class BaseLLMProvider(ABC):
    """Abstract base class for replaceable, inference-only LLM providers."""

    provider_name: str = "base"

    def __init__(self, config: Optional[ProviderConfig] = None):
        self.config = config or ProviderConfig(provider_name=self.provider_name)
        self._last_request_duration: float = 0.0
        self._last_response_duration: float = 0.0

    @property
    def name(self) -> str:
        """Get the provider identity."""
        return self.provider_name

    @property
    def model(self) -> str:
        """Get the configured model identity."""
        return self.config.model

    @model.setter
    def model(self, value: str) -> None:
        self.config.model = value

    @property
    def timeout(self) -> float:
        """Get the bounded request timeout in seconds."""
        return self.config.timeout

    @timeout.setter
    def timeout(self, value: float) -> None:
        self.config.timeout = value

    @abstractmethod
    def ask(
        self,
        prompt: str,
        system: Optional[str] = None,
        messages: Optional[List[Message]] = None,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> ProviderResponse:
        """Perform one inference-only request or raise a classified ProviderError."""

    @abstractmethod
    def check_health(self) -> ProviderHealthStatus:
        """Perform a bounded health check and return an observable status."""

    @abstractmethod
    def list_models(self) -> List[str]:
        """List models currently available from this provider."""

    def is_healthy(self) -> bool:
        """Return health without allowing a failed check to crash selection."""
        try:
            return self.check_health().is_healthy
        except Exception:
            return False

    def get_last_request_duration(self) -> float:
        return self._last_request_duration

    def get_last_response_duration(self) -> float:
        return self._last_response_duration

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(model={self.model}, timeout={self.timeout})"
