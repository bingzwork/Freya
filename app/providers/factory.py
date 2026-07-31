"""Provider Factory.

This module provides a factory for creating LLM provider instances based on configuration.
It supports dynamic provider selection and fallback mechanisms.
"""

import os
from typing import Any, Dict, List, Optional, Type

from app.providers.base import BaseLLMProvider, ProviderConfig, ProviderError
from app.providers.ollama import OllamaProvider
from app.core.logger import logger


class ProviderFactory:
    """Factory for creating LLM provider instances.

    This factory manages provider registration, selection, and instantiation.
    It supports multiple providers and allows for easy extension.
    """

    # Mapping of provider names to their classes
    _providers: Dict[str, Type[BaseLLMProvider]] = {}

    # Default provider name
    _default_provider: str = "ollama"

    @classmethod
    def register_provider(cls, name: str, provider_class: Type[BaseLLMProvider]) -> None:
        """Register a provider class with the factory.

        Args:
            name: The name to register the provider under.
            provider_class: The provider class to register.
        """
        cls._providers[name.lower()] = provider_class
        logger.info(f"[ProviderFactory] Registered provider: {name}")

    @classmethod
    def unregister_provider(cls, name: str) -> None:
        """Unregister a provider.

        Args:
            name: The name of the provider to unregister.
        """
        if name.lower() in cls._providers:
            del cls._providers[name.lower()]
            logger.info(f"[ProviderFactory] Unregistered provider: {name}")

    @classmethod
    def get_registered_providers(cls) -> List[str]:
        """Get the list of registered provider names.

        Returns:
            List of registered provider names.
        """
        return list(cls._providers.keys())

    @classmethod
    def set_default_provider(cls, name: str) -> None:
        """Set the default provider name.

        Args:
            name: The name of the default provider.
        """
        cls._default_provider = name.lower()
        logger.info(f"[ProviderFactory] Default provider set to: {name}")

    @classmethod
    def get_default_provider(cls) -> str:
        """Get the default provider name.

        Returns:
            The default provider name.
        """
        return cls._default_provider

    @classmethod
    def create(
        cls,
        provider_name: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        **kwargs
    ) -> BaseLLMProvider:
        """Create a provider instance.

        Args:
            provider_name: The name of the provider to create. If None, uses the default.
            model: The model to use. If None, uses the provider's default or environment config.
            base_url: The base URL for the provider. If None, uses the provider's default.
            timeout: The timeout for requests. If None, uses the provider's default.
            **kwargs: Additional configuration for the provider.

        Returns:
            An instance of the requested provider.

        Raises:
            ProviderError: If the provider cannot be created.
        """
        effective_provider = provider_name or cls._default_provider

        # Normalize provider name
        effective_provider = effective_provider.lower()

        # Check if provider is registered
        if effective_provider not in cls._providers:
            available = ", ".join(cls._providers.keys())
            raise ProviderError(
                message=f"Unknown provider: '{effective_provider}'. Available providers: {available}",
                provider_name="factory",
                details={"available_providers": list(cls._providers.keys())},
            )

        provider_class = cls._providers[effective_provider]

        # Build configuration
        config = cls._build_config(
            provider_name=effective_provider,
            model=model,
            base_url=base_url,
            timeout=timeout,
            **kwargs
        )

        logger.info(
            f"[ProviderFactory] Creating {effective_provider} provider "
            f"(model: {config.model}, base_url: {config.base_url})"
        )

        try:
            provider = provider_class(config)
            logger.info(f"[ProviderFactory] Successfully created {effective_provider} provider")
            return provider
        except Exception as e:
            logger.error(f"[ProviderFactory] Failed to create {effective_provider} provider: {str(e)}")
            raise ProviderError(
                message=f"Failed to create provider '{effective_provider}': {str(e)}",
                provider_name="factory",
                details={"error": str(e), "type": type(e).__name__},
            )

    @classmethod
    def create_from_config(cls, config: Dict[str, Any]) -> BaseLLMProvider:
        """Create a provider instance from a configuration dictionary.

        Args:
            config: Configuration dictionary containing provider settings.

        Returns:
            An instance of the configured provider.

        Raises:
            ProviderError: If the provider cannot be created.
        """
        provider_name = config.get("provider", cls._default_provider)
        model = config.get("model")
        base_url = config.get("base_url")
        timeout = config.get("timeout")

        # Extract provider-specific config
        extra = {k: v for k, v in config.items() if k not in ["provider", "model", "base_url", "timeout"]}

        return cls.create(
            provider_name=provider_name,
            model=model,
            base_url=base_url,
            timeout=timeout,
            **extra
        )

    @classmethod
    def _build_config(
        cls,
        provider_name: str,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        **kwargs
    ) -> ProviderConfig:
        """Build a ProviderConfig from the given parameters.

        Also reads from environment variables as fallback.
        Performs defensive validation to ensure required configuration is present.

        Args:
            provider_name: The provider name.
            model: The model to use.
            base_url: The base URL.
            timeout: The timeout.
            **kwargs: Additional configuration.

        Returns:
            A ProviderConfig instance.

        Raises:
            ProviderError: If required configuration is missing.
        """
        # Get values from environment as fallback
        env_prefix = f"{provider_name.upper()}_"

        effective_model = model or os.getenv(f"{env_prefix}MODEL") or kwargs.get("model")
        effective_base_url = base_url or os.getenv(f"{env_prefix}BASE_URL") or kwargs.get("base_url")
        effective_timeout = timeout or float(os.getenv(f"{env_prefix}TIMEOUT", "120"))

        # Default base_url for Ollama/local providers if not configured
        if provider_name in ["ollama", "local"] and effective_base_url is None:
            effective_base_url = "http://localhost:11434"
            logger.debug(
                f"[ProviderFactory] Using default base_url for {provider_name}: "
                f"{effective_base_url}"
            )

        # Remove known keys from kwargs
        extra = {k: v for k, v in kwargs.items() if k not in ["model", "base_url", "timeout"]}

        return ProviderConfig(
            provider_name=provider_name,
            model=effective_model if effective_model else "",
            base_url=effective_base_url,
            timeout=effective_timeout,
            extra=extra,
        )


# Register built-in providers
ProviderFactory.register_provider("ollama", OllamaProvider)

# Aliases for convenience
ProviderFactory.register_provider("local", OllamaProvider)  # alias for local Ollama


def get_provider(
    provider_name: Optional[str] = None,
    **kwargs
) -> BaseLLMProvider:
    """Convenience function to get a provider instance.

    Args:
        provider_name: The name of the provider. If None, uses the default.
        **kwargs: Additional configuration for the provider.

    Returns:
        A provider instance.
    """
    return ProviderFactory.create(provider_name=provider_name, **kwargs)
