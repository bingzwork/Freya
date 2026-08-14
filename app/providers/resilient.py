"""Health-aware, deterministic routing across configured inference providers."""

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence

from app.core.logger import logger
from app.providers.base import (
    BaseLLMProvider,
    Message,
    NoProviderConfiguredError,
    ProviderConnectionError,
    ProviderError,
    ProviderFailureKind,
    ProviderHealthStatus,
    ProviderHealthState,
    ProviderResponse,
    ProviderTimeoutError,
    ProvidersExhaustedError,
    classify_provider_error,
    is_recoverable_provider_error,
)
from app.providers.factory import ProviderFactory


@dataclass(frozen=True)
class ProviderAttempt:
    """A non-sensitive record of one provider selection decision."""

    provider_name: str
    outcome: str
    failure_kind: Optional[ProviderFailureKind] = None
    detail: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider_name,
            "outcome": self.outcome,
            "failure_kind": self.failure_kind.value if self.failure_kind else None,
            "detail": self.detail,
        }


class ResilientLLMProvider:
    """Select healthy providers in configured order and fall back after safe failures.

    The class owns provider fallback only.  It never retries a concrete provider,
    which keeps it composable with the priority queue and other runtime recovery
    layers.  Provider operations are inference-only under ``BaseLLMProvider``.
    """

    def __init__(
        self,
        provider_names: Optional[Sequence[str]] = None,
        *,
        factory: type[ProviderFactory] = ProviderFactory,
        providers: Optional[Mapping[str, BaseLLMProvider]] = None,
        provider_options: Optional[Mapping[str, Mapping[str, Any]]] = None,
        health_cache_ttl: float = 30.0,
    ) -> None:
        if health_cache_ttl < 0:
            raise ValueError("health_cache_ttl must be non-negative")
        self._factory = factory
        self._provider_names = factory.get_configured_provider_order(provider_names)
        self._providers: Dict[str, BaseLLMProvider] = {
            factory.resolve_provider_name(name): provider
            for name, provider in (providers or {}).items()
        }
        self._provider_options: Dict[str, Dict[str, Any]] = {
            factory.resolve_provider_name(name): dict(options)
            for name, options in (provider_options or {}).items()
        }
        self._health_cache_ttl = health_cache_ttl
        self._health: Dict[str, ProviderHealthStatus] = {}
        self._last_attempts: List[ProviderAttempt] = []

    @property
    def provider_order(self) -> List[str]:
        """Return a defensive copy of the configured canonical provider order."""
        return list(self._provider_names)

    @property
    def last_attempts(self) -> List[ProviderAttempt]:
        """Return the last non-sensitive routing attempt trace."""
        return list(self._last_attempts)

    def get_health_status(self, provider_name: str) -> ProviderHealthStatus:
        """Return cached health or safely refresh it for a configured provider."""
        canonical = self._factory.resolve_provider_name(provider_name)
        provider = self._get_provider(canonical)
        return self._health_status(canonical, provider)

    def ask(
        self,
        prompt: str,
        system: Optional[str] = None,
        messages: Optional[List[Message]] = None,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> ProviderResponse:
        """Execute one bounded inference request with deterministic fallback."""
        if not self._provider_names:
            logger.error("[ProviderRouter] No provider is configured for inference")
            raise NoProviderConfiguredError("No provider is configured for inference", provider_name="router")

        attempts: List[ProviderAttempt] = []
        self._last_attempts = attempts
        for name in self._provider_names:
            try:
                provider = self._get_provider(name)
            except ProviderError as exc:
                attempts.append(self._attempt(name, "initialization_failed", exc))
                logger.warning(f"[ProviderRouter] Skipping provider={name}; initialization failed")
                continue

            status = self._health_status(name, provider)
            if not status.is_healthy:
                detail = status.error_message or "health check failed"
                attempts.append(ProviderAttempt(name, "skipped_unhealthy", ProviderFailureKind.UNAVAILABLE, detail))
                logger.warning(f"[ProviderRouter] Skipping unhealthy provider={name}")
                continue

            logger.info(f"[ProviderRouter] Selected provider={name}")
            try:
                response = provider.ask(
                    prompt,
                    system=system,
                    messages=messages,
                    timeout=timeout,
                    **kwargs,
                )
                if not isinstance(response, ProviderResponse):
                    raise ProviderError(
                        "Provider returned an invalid response type",
                        provider_name=name,
                        details={"response_type": type(response).__name__},
                    )
                attempts.append(ProviderAttempt(name, "succeeded"))
                return response
            except BaseException as exc:
                provider_error = self._normalize_error(exc, name, timeout)
                attempts.append(self._attempt(name, "failed", provider_error))
                if not is_recoverable_provider_error(provider_error):
                    logger.error(
                        f"[ProviderRouter] Provider={name} failed with non-recoverable "
                        f"classification={provider_error.failure_kind.value}"
                    )
                    raise provider_error

                self._mark_unhealthy(name, provider_error)
                logger.warning(
                    f"[ProviderRouter] Provider={name} failed with "
                    f"classification={provider_error.failure_kind.value}; trying fallback"
                )

        serialized_attempts = [attempt.to_dict() for attempt in attempts]
        logger.error(f"[ProviderRouter] All configured providers exhausted: {serialized_attempts}")
        raise ProvidersExhaustedError(
            "No configured provider could complete the inference request",
            attempts=serialized_attempts,
        )

    def _get_provider(self, provider_name: str) -> BaseLLMProvider:
        canonical = self._factory.resolve_provider_name(provider_name)
        provider = self._providers.get(canonical)
        if provider is None:
            provider = self._factory.create(canonical, **self._provider_options.get(canonical, {}))
            self._providers[canonical] = provider
        return provider

    def _health_status(self, name: str, provider: BaseLLMProvider) -> ProviderHealthStatus:
        cached = self._health.get(name)
        now = time.time()
        if cached and cached.checked_at is not None and now - cached.checked_at <= self._health_cache_ttl:
            return cached

        try:
            status = provider.check_health()
            if not isinstance(status, ProviderHealthStatus):
                raise ProviderError(
                    "Provider health check returned an invalid status",
                    provider_name=name,
                    details={"status_type": type(status).__name__},
                )
            if status.checked_at is None:
                status.checked_at = now
        except BaseException as exc:
            error = self._normalize_error(exc, name, None)
            status = ProviderHealthStatus(
                provider_name=name,
                is_healthy=False,
                is_reachable=False,
                model_available=False,
                error_message=error.message,
                details={"failure_kind": error.failure_kind.value},
                state=ProviderHealthState.UNHEALTHY,
                checked_at=now,
            )
            logger.warning(f"[ProviderRouter] Health check failed for provider={name}")

        self._health[name] = status
        return status

    def _mark_unhealthy(self, name: str, error: ProviderError) -> None:
        self._health[name] = ProviderHealthStatus(
            provider_name=name,
            is_healthy=False,
            is_reachable=False,
            model_available=False,
            error_message=error.message,
            details={"failure_kind": error.failure_kind.value},
            state=ProviderHealthState.UNHEALTHY,
        )

    @staticmethod
    def _normalize_error(
        error: BaseException,
        provider_name: str,
        timeout: Optional[float],
    ) -> ProviderError:
        if isinstance(error, ProviderError):
            return error
        if isinstance(error, TimeoutError):
            return ProviderTimeoutError(
                "Provider request timed out",
                provider_name=provider_name,
                timeout_seconds=timeout or 0,
            )
        if isinstance(error, (ConnectionError, OSError)):
            return ProviderConnectionError(str(error) or "Provider connection failed", provider_name=provider_name)
        return ProviderError(
            str(error) or "Provider request failed",
            provider_name=provider_name,
            details={"failure_kind": classify_provider_error(error).value, "error_type": type(error).__name__},
        )

    @staticmethod
    def _attempt(name: str, outcome: str, error: ProviderError) -> ProviderAttempt:
        return ProviderAttempt(name, outcome, error.failure_kind, error.message)
