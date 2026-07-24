"""Provider Health Checker.

This module provides health checking functionality for LLM providers,
including startup verification and periodic health monitoring.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable

from app.providers.base import BaseLLMProvider, ProviderHealthStatus, ProviderError
from app.providers.factory import ProviderFactory
from app.core.logger import logger


@dataclass
class HealthCheckResult:
    """Result of a health check operation."""
    provider_name: str
    is_healthy: bool
    is_reachable: bool
    model_available: bool
    error_message: Optional[str] = None
    duration: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "provider_name": self.provider_name,
            "is_healthy": self.is_healthy,
            "is_reachable": self.is_reachable,
            "model_available": self.model_available,
            "error_message": self.error_message,
            "duration": self.duration,
            "details": self.details,
        }


@dataclass
class AggregateHealthStatus:
    """Aggregate health status for all providers."""
    all_providers_healthy: bool
    healthy_providers: List[str] = field(default_factory=list)
    unhealthy_providers: List[str] = field(default_factory=list)
    results: Dict[str, HealthCheckResult] = field(default_factory=dict)
    default_provider_healthy: bool = True
    default_provider: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "all_providers_healthy": self.all_providers_healthy,
            "healthy_providers": self.healthy_providers,
            "unhealthy_providers": self.unhealthy_providers,
            "results": {name: result.to_dict() for name, result in self.results.items()},
            "default_provider_healthy": self.default_provider_healthy,
            "default_provider": self.default_provider,
        }

    def get_summary(self) -> str:
        """Get a human-readable summary of the health status."""
        if self.all_providers_healthy:
            return f"All {len(self.results)} providers are healthy."

        lines = []
        if self.healthy_providers:
            lines.append(f"Healthy: {', '.join(self.healthy_providers)}")
        if self.unhealthy_providers:
            lines.append(f"Unhealthy: {', '.join(self.unhealthy_providers)}")
        return " | ".join(lines)


class ProviderHealthChecker:
    """Health checker for LLM providers.

    Performs startup health checks and provides methods for verifying
    provider availability.
    """

    def __init__(self, factory: Optional[Any] = None):
        """Initialize the health checker.

        Args:
            factory: The provider factory to use. If None, uses ProviderFactory.
        """
        self.factory = factory or ProviderFactory
        self._last_check_time: float = 0.0
        self._last_check_result: Optional[AggregateHealthStatus] = None
        self._check_interval: float = 60.0  # Minimum seconds between automatic checks

    def check_provider(
        self,
        provider_name: Optional[str] = None,
        provider: Optional[Any] = None,
        **kwargs
    ) -> HealthCheckResult:
        """Check the health of a specific provider.

        Args:
            provider_name: The name of the provider to check. If None, uses default.
            provider: An existing provider instance to reuse. If provided, provider_name
                     is ignored and no new provider is created.
            **kwargs: Additional arguments passed to provider creation (only used if
                     provider is not provided).

        Returns:
            HealthCheckResult with the check results.
        """
        effective_provider = provider_name or self.factory.get_default_provider()
        start_time = time.time()

        try:
            logger.info(f"[HealthChecker] Checking provider: {effective_provider}")

            # Reuse existing provider if provided, otherwise create a new one
            if provider is not None:
                provider_instance = provider
            else:
                provider_instance = self.factory.create(provider_name=effective_provider, **kwargs)
            status = provider_instance.check_health()

            duration = time.time() - start_time

            result = HealthCheckResult(
                provider_name=effective_provider,
                is_healthy=status.is_healthy,
                is_reachable=status.is_reachable,
                model_available=status.model_available,
                error_message=status.error_message,
                duration=duration,
                details=status.details,
            )

            if result.is_healthy:
                logger.info(
                    f"[HealthChecker] {effective_provider} is healthy "
                    f"(reachable: {result.is_reachable}, model: {result.model_available})"
                )
            else:
                logger.warning(
                    f"[HealthChecker] {effective_provider} is unhealthy: {result.error_message}"
                )

            return result

        except Exception as e:
            duration = time.time() - start_time
            error_msg = str(e) or "Unknown error"
            logger.error(f"[HealthChecker] Failed to check {effective_provider}: {error_msg}")

            return HealthCheckResult(
                provider_name=effective_provider,
                is_healthy=False,
                is_reachable=False,
                model_available=False,
                error_message=error_msg,
                duration=duration,
                details={"error": str(e), "type": type(e).__name__},
            )

    def check_all_providers(self) -> AggregateHealthStatus:
        """Check the health of all registered providers.

        Returns:
            AggregateHealthStatus with results for all providers.
        """
        start_time = time.time()
        logger.info("[HealthChecker] Checking all providers")

        provider_names = self.factory.get_registered_providers()
        results: Dict[str, HealthCheckResult] = {}
        healthy = []
        unhealthy = []

        default_provider = self.factory.get_default_provider()

        for name in provider_names:
            result = self.check_provider(provider_name=name)
            results[name] = result

            if result.is_healthy:
                healthy.append(name)
            else:
                unhealthy.append(name)

        default_healthy = results.get(default_provider, HealthCheckResult(
            provider_name=default_provider,
            is_healthy=False,
            is_reachable=False,
            model_available=False,
            error_message="Provider not found",
        )).is_healthy

        all_healthy = len(unhealthy) == 0

        aggregate = AggregateHealthStatus(
            all_providers_healthy=all_healthy,
            healthy_providers=healthy,
            unhealthy_providers=unhealthy,
            results=results,
            default_provider_healthy=default_healthy,
            default_provider=default_provider,
        )

        self._last_check_result = aggregate
        self._last_check_time = time.time()

        logger.info(
            f"[HealthChecker] All providers check completed in {time.time() - start_time:.2f}s: "
            f"{len(healthy)} healthy, {len(unhealthy)} unhealthy"
        )

        return aggregate

    def check_default_provider(
        self, provider: Optional[Any] = None, **kwargs
    ) -> HealthCheckResult:
        """Check the health of the default provider.

        Args:
            provider: An existing provider instance to reuse. If None, creates a new one.
            **kwargs: Additional arguments passed to provider creation (only used if
                     provider is not provided).

        Returns:
            HealthCheckResult with the check results.
        """
        default = self.factory.get_default_provider()
        return self.check_provider(provider_name=default, provider=provider, **kwargs)

    def verify_startup(
        self,
        provider_name: Optional[str] = None,
        provider: Optional[Any] = None,
        model: Optional[str] = None,
        raise_on_failure: bool = False,
        **kwargs
    ) -> HealthCheckResult:
        """Perform startup health verification.

        This method is designed to be called during application startup
        to ensure the primary provider is available.

        Args:
            provider_name: The provider to verify. If None, uses default.
            provider: An existing provider instance to reuse. If provided, provider_name
                     is ignored and no new provider is created.
            model: The model to verify. If None, uses provider's default.
            raise_on_failure: If True, raises an exception if health check fails.
            **kwargs: Additional arguments passed to provider creation (only used if
                     provider is not provided).

        Returns:
            HealthCheckResult with the verification results.

        Raises:
            ProviderError: If raise_on_failure is True and health check fails.
        """
        effective_provider = provider_name or self.factory.get_default_provider()
        logger.info(f"[HealthChecker] Startup verification for provider: {effective_provider}")

        if model:
            kwargs["model"] = model

        result = self.check_provider(
            provider_name=effective_provider, provider=provider, **kwargs
        )

        if raise_on_failure and not result.is_healthy:
            error_msg = result.error_message or "Provider health check failed"
            raise ProviderError(
                message=f"Startup health check failed for {effective_provider}: {error_msg}",
                provider_name=effective_provider,
                details=result.details,
            )

        return result

    def get_last_check_result(self) -> Optional[AggregateHealthStatus]:
        """Get the result of the last aggregate health check.

        Returns:
            The last AggregateHealthStatus, or None if no check has been performed.
        """
        return self._last_check_result

    def get_last_check_time(self) -> float:
        """Get the timestamp of the last aggregate health check.

        Returns:
            The timestamp of the last check, or 0.0 if no check has been performed.
        """
        return self._last_check_time

    def should_check_again(self) -> bool:
        """Check if enough time has passed to perform another automatic check.

        Returns:
            True if it's time to check again, False otherwise.
        """
        if self._last_check_time == 0.0:
            return True
        return (time.time() - self._last_check_time) >= self._check_interval

    @property
    def default_provider_healthy(self) -> bool:
        """Check if the default provider is currently healthy.

        Performs a check if no recent check has been performed.

        Returns:
            True if the default provider is healthy, False otherwise.
        """
        if self._last_check_result is None:
            result = self.check_default_provider()
            return result.is_healthy
        return self._last_check_result.default_provider_healthy

    @property
    def any_provider_healthy(self) -> bool:
        """Check if any provider is currently healthy.

        Returns:
            True if at least one provider is healthy, False otherwise.
        """
        if self._last_check_result is None:
            result = self.check_all_providers()
            return result.all_providers_healthy or len(result.healthy_providers) > 0
        return len(self._last_check_result.healthy_providers) > 0


def perform_startup_health_check(
    provider_name: Optional[str] = None,
    provider: Optional[Any] = None,
    model: Optional[str] = None,
    raise_on_failure: bool = False,
) -> HealthCheckResult:
    """Convenience function to perform a startup health check.

    Args:
        provider_name: The provider to verify. If None, uses default.
        provider: An existing provider instance to reuse. If provided, provider_name
                 is ignored and no new provider is created.
        model: The model to verify. If None, uses provider's default.
        raise_on_failure: If True, raises an exception if health check fails.

    Returns:
        HealthCheckResult with the verification results.

    Raises:
        ProviderError: If raise_on_failure is True and health check fails.
    """
    checker = ProviderHealthChecker()
    return checker.verify_startup(
        provider_name=provider_name,
        provider=provider,
        model=model,
        raise_on_failure=raise_on_failure,
    )
