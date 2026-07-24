"""LLM Provider Abstraction Layer.

This module provides a clean abstraction for different LLM providers,
allowing Freya to work with multiple AI services (Ollama, Claude, OpenAI, etc.)
through a unified interface.
"""

from app.providers.base import BaseLLMProvider, ProviderError, ProviderTimeoutError, ProviderConnectionError
from app.providers.ollama import OllamaProvider
from app.providers.factory import ProviderFactory
from app.providers.health import ProviderHealthChecker

__all__ = [
    "BaseLLMProvider",
    "ProviderError",
    "ProviderTimeoutError",
    "ProviderConnectionError",
    "OllamaProvider",
    "ProviderFactory",
    "ProviderHealthChecker",
]
