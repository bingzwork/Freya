"""Factory and configuration helpers for concrete LLM providers."""

import os
from typing import Any, Dict, Iterable, List, Optional, Sequence, Type

from app.core.logger import logger
from app.providers.base import BaseLLMProvider, ProviderConfig, ProviderConfigurationError, ProviderError
from app.providers.ollama import OllamaProvider


class ProviderFactory:
    """Register and construct concrete providers without coupling callers to one vendor."""

    _providers: Dict[str, Type[BaseLLMProvider]] = {}
    _aliases: Dict[str, str] = {}
    _default_provider: str = "ollama"

    @classmethod
    def register_provider(cls, name: str, provider_class: Type[BaseLLMProvider]) -> None:
        """Register a concrete provider implementation under a stable identity."""
        normalized = name.strip().lower()
        if not normalized:
            raise ProviderConfigurationError("Provider name cannot be empty", provider_name="factory")
        if not issubclass(provider_class, BaseLLMProvider):
            raise ProviderConfigurationError(
                f"Provider '{normalized}' must implement BaseLLMProvider",
                provider_name="factory",
            )
        cls._providers[normalized] = provider_class
        logger.info(f"[ProviderFactory] Registered provider: {normalized}")

    @classmethod
    def register_alias(cls, alias: str, provider_name: str) -> None:
        """Register a compatibility alias without treating it as another provider."""
        normalized_alias = alias.strip().lower()
        canonical = cls.resolve_provider_name(provider_name)
        if not normalized_alias:
            raise ProviderConfigurationError("Provider alias cannot be empty", provider_name="factory")
        if canonical not in cls._providers:
            raise ProviderConfigurationError(
                f"Cannot alias unknown provider '{provider_name}'",
                provider_name="factory",
            )
        cls._aliases[normalized_alias] = canonical
        logger.info(f"[ProviderFactory] Registered provider alias: {normalized_alias} -> {canonical}")

    @classmethod
    def unregister_provider(cls, name: str) -> None:
        """Remove a concrete provider and aliases that target it."""
        normalized = name.lower()
        canonical = cls.resolve_provider_name(normalized)
        if canonical in cls._providers:
            del cls._providers[canonical]
            cls._aliases = {alias: target for alias, target in cls._aliases.items() if target != canonical}
            logger.info(f"[ProviderFactory] Unregistered provider: {canonical}")

    @classmethod
    def resolve_provider_name(cls, name: str) -> str:
        """Resolve a provider name through compatibility aliases."""
        normalized = name.strip().lower()
        return cls._aliases.get(normalized, normalized)

    @classmethod
    def get_registered_providers(cls) -> List[str]:
        """Return registered concrete providers in deterministic registration order."""
        return list(cls._providers.keys())

    @classmethod
    def get_provider_aliases(cls) -> Dict[str, str]:
        """Return a copy of compatibility aliases for diagnostics."""
        return dict(cls._aliases)

    @classmethod
    def set_default_provider(cls, name: str) -> None:
        """Set the process default provider, resolving compatibility aliases."""
        cls._default_provider = cls.resolve_provider_name(name)
        logger.info(f"[ProviderFactory] Default provider set to: {cls._default_provider}")

    @classmethod
    def get_default_provider(cls) -> str:
        """Return the configured default provider, with ``DEFAULT_PROVIDER`` support."""
        configured = os.getenv("DEFAULT_PROVIDER")
        return cls.resolve_provider_name(configured) if configured else cls._default_provider

    @classmethod
    def get_configured_provider_order(
        cls,
        provider_names: Optional[Sequence[str]] = None,
    ) -> List[str]:
        """Return the single deterministic priority order for provider routing.

        Explicit ``provider_names`` take precedence.  Otherwise ``PROVIDER_ORDER``
        is used when present; legacy single-provider configuration remains supported
        through ``DEFAULT_PROVIDER`` followed by optional ``FALLBACK_PROVIDERS``.
        Aliases are canonicalized and duplicates are removed without changing order.
        """
        if provider_names is not None:
            candidates: Iterable[str] = provider_names
        else:
            configured_order = os.getenv("PROVIDER_ORDER", "").strip()
            if configured_order:
                candidates = configured_order.split(",")
            else:
                fallback = os.getenv("FALLBACK_PROVIDERS", "").split(",")
                candidates = [cls.get_default_provider(), *fallback]

        ordered: List[str] = []
        for name in candidates:
            if not name or not name.strip():
                continue
            canonical = cls.resolve_provider_name(name)
            if canonical not in ordered:
                ordered.append(canonical)
        return ordered

    @classmethod
    def create(
        cls,
        provider_name: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> BaseLLMProvider:
        """Construct one concrete provider from explicit or environment configuration."""
        requested_name = provider_name or cls.get_default_provider()
        effective_provider = cls.resolve_provider_name(requested_name)

        if effective_provider not in cls._providers:
            available = ", ".join(cls._providers.keys()) or "none"
            raise ProviderConfigurationError(
                message=f"Unknown provider: '{requested_name}'. Available providers: {available}",
                provider_name="factory",
                details={"available_providers": list(cls._providers.keys())},
            )

        config = cls._build_config(
            provider_name=effective_provider,
            model=model,
            base_url=base_url,
            timeout=timeout,
            **kwargs,
        )
        logger.info(
            f"[ProviderFactory] Creating provider={effective_provider} "
            f"model={config.model or 'default'}"
        )

        try:
            return cls._providers[effective_provider](config)
        except ProviderError:
            raise
        except Exception as exc:
            logger.error(
                f"[ProviderFactory] Provider initialization failed for {effective_provider}: {exc}"
            )
            raise ProviderConfigurationError(
                message=f"Failed to create provider '{effective_provider}': {exc}",
                provider_name=effective_provider,
                details={"error_type": type(exc).__name__},
            ) from exc

    @classmethod
    def create_from_config(cls, config: Dict[str, Any]) -> BaseLLMProvider:
        """Construct one concrete provider from a configuration mapping."""
        provider_name = config.get("provider", cls.get_default_provider())
        known_keys = {"provider", "model", "base_url", "timeout"}
        return cls.create(
            provider_name=provider_name,
            model=config.get("model"),
            base_url=config.get("base_url"),
            timeout=config.get("timeout"),
            **{key: value for key, value in config.items() if key not in known_keys},
        )

    @classmethod
    def _build_config(
        cls,
        provider_name: str,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> ProviderConfig:
        """Build normalized provider configuration from arguments and environment."""
        env_prefix = f"{provider_name.upper()}_"
        effective_model = model or os.getenv(f"{env_prefix}MODEL") or kwargs.get("model") or ""
        effective_base_url = base_url or os.getenv(f"{env_prefix}BASE_URL") or kwargs.get("base_url")
        raw_timeout: Any = timeout if timeout is not None else os.getenv(f"{env_prefix}TIMEOUT", "120")
        try:
            effective_timeout = float(raw_timeout)
        except (TypeError, ValueError) as exc:
            raise ProviderConfigurationError(
                f"Invalid timeout for provider '{provider_name}'",
                provider_name=provider_name,
            ) from exc
        if effective_timeout <= 0:
            raise ProviderConfigurationError(
                f"Timeout for provider '{provider_name}' must be positive",
                provider_name=provider_name,
            )

        if provider_name == "ollama" and effective_base_url is None:
            effective_base_url = "http://localhost:11434"

        extra = {key: value for key, value in kwargs.items() if key not in {"model", "base_url", "timeout"}}
        return ProviderConfig(
            provider_name=provider_name,
            model=effective_model,
            base_url=effective_base_url,
            api_key=kwargs.get("api_key") or os.getenv(f"{env_prefix}API_KEY"),
            timeout=effective_timeout,
            extra=extra,
        )


ProviderFactory.register_provider("ollama", OllamaProvider)
ProviderFactory.register_alias("local", "ollama")


def get_provider(provider_name: Optional[str] = None, **kwargs: Any) -> BaseLLMProvider:
    """Convenience function for constructing a concrete provider."""
    return ProviderFactory.create(provider_name=provider_name, **kwargs)
