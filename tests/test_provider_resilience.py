"""Focused deterministic tests for production provider routing resilience."""

from typing import Any, List, Optional

import pytest

from app.core.llm import LLM
from app.providers.base import (
    BaseLLMProvider,
    NoProviderConfiguredError,
    ProviderConfig,
    ProviderConnectionError,
    ProviderHealthStatus,
    ProviderResponse,
    ProviderTimeoutError,
    ProvidersExhaustedError,
)
from app.providers.factory import ProviderFactory
from app.providers.ollama import OllamaProvider
from app.providers.resilient import ResilientLLMProvider


class FakeProvider(BaseLLMProvider):
    """Deterministic external-provider boundary for router tests."""

    provider_name = "fake"

    def __init__(
        self,
        name: str,
        *,
        healthy: bool = True,
        outcomes: Optional[List[Any]] = None,
    ) -> None:
        super().__init__(ProviderConfig(provider_name=name, model=f"{name}-model", timeout=2.0))
        self.provider_name = name
        self.healthy = healthy
        self.outcomes = list(outcomes or [f"{name} response"])
        self.health_checks = 0
        self.calls: List[dict[str, Any]] = []

    def ask(self, prompt, system=None, messages=None, timeout=None, **kwargs):
        self.calls.append({"prompt": prompt, "system": system, "messages": messages, "timeout": timeout})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return ProviderResponse(content=outcome, model=self.model, provider=self.provider_name)

    def check_health(self):
        self.health_checks += 1
        return ProviderHealthStatus(
            provider_name=self.provider_name,
            is_healthy=self.healthy,
            is_reachable=self.healthy,
            model_available=self.healthy,
            model_name=self.model,
            error_message=None if self.healthy else "offline",
        )

    def list_models(self):
        return [self.model]


def router(*providers: FakeProvider) -> ResilientLLMProvider:
    return ResilientLLMProvider(
        [provider.provider_name for provider in providers],
        providers={provider.provider_name: provider for provider in providers},
        health_cache_ttl=60.0,
    )


def test_healthy_preferred_provider_is_selected_without_using_fallback():
    first, second = FakeProvider("first"), FakeProvider("second")

    response = router(first, second).ask("hello", system="system")

    assert response.content == "first response"
    assert len(first.calls) == 1
    assert second.calls == []


def test_unhealthy_preferred_provider_is_skipped_for_healthy_fallback():
    first, second = FakeProvider("first", healthy=False), FakeProvider("second")

    response = router(first, second).ask("hello")

    assert response.provider == "second"
    assert first.calls == []
    assert len(second.calls) == 1


def test_timeout_is_classified_and_falls_back_with_request_context_preserved():
    first = FakeProvider("first", outcomes=[ProviderTimeoutError("timed out", "first", timeout_seconds=2)])
    second = FakeProvider("second")
    resilient = router(first, second)

    response = resilient.ask("keep prompt", system="keep system", timeout=7.0)

    assert response.provider == "second"
    assert first.calls[0]["prompt"] == "keep prompt"
    assert second.calls[0]["prompt"] == "keep prompt"
    assert second.calls[0]["system"] == "keep system"
    assert second.calls[0]["timeout"] == 7.0
    assert [attempt.outcome for attempt in resilient.last_attempts] == ["failed", "succeeded"]
    assert resilient.last_attempts[0].failure_kind.value == "timeout"


def test_recoverable_connection_failure_falls_back():
    first = FakeProvider("first", outcomes=[ProviderConnectionError("offline", "first")])
    second = FakeProvider("second", outcomes=["fallback response"])

    response = router(first, second).ask("hello")

    assert response.content == "fallback response"
    assert len(first.calls) == 1
    assert len(second.calls) == 1


def test_fallback_order_stops_after_first_success():
    first = FakeProvider("first", outcomes=[ProviderConnectionError("offline", "first")])
    second, third = FakeProvider("second"), FakeProvider("third")

    response = router(first, second, third).ask("hello")

    assert response.provider == "second"
    assert len(first.calls) == 1
    assert len(second.calls) == 1
    assert third.calls == []


def test_all_unhealthy_providers_raise_safe_exhaustion_error():
    first, second = FakeProvider("first", healthy=False), FakeProvider("second", healthy=False)
    resilient = router(first, second)

    with pytest.raises(ProvidersExhaustedError) as error:
        resilient.ask("hello")

    assert first.calls == []
    assert second.calls == []
    assert [attempt["outcome"] for attempt in error.value.attempts] == ["skipped_unhealthy", "skipped_unhealthy"]


def test_all_provider_timeouts_raise_safe_exhaustion_error():
    first = FakeProvider("first", outcomes=[ProviderTimeoutError("timed out", "first", timeout_seconds=1)])
    second = FakeProvider("second", outcomes=[ProviderTimeoutError("timed out", "second", timeout_seconds=1)])

    with pytest.raises(ProvidersExhaustedError) as error:
        router(first, second).ask("hello", timeout=1.0)

    assert [attempt["failure_kind"] for attempt in error.value.attempts] == ["timeout", "timeout"]


def test_no_configured_provider_raises_explicit_safe_failure():
    with pytest.raises(NoProviderConfiguredError):
        ResilientLLMProvider([]).ask("hello")


def test_alias_resolves_to_one_concrete_ollama_provider():
    provider = ProviderFactory.create("local", model="qwen3:8b")

    assert isinstance(provider, OllamaProvider)
    assert provider.config.provider_name == "ollama"
    assert ProviderFactory.resolve_provider_name("local") == "ollama"
    assert "local" not in ProviderFactory.get_registered_providers()


def test_single_provider_remains_compatible_with_resilient_router():
    only = FakeProvider("only", outcomes=["single provider response"])

    response = router(only).ask("hello")

    assert response.content == "single provider response"
    assert len(only.calls) == 1


def test_runtime_llm_uses_the_resilient_provider_contract():
    provider = FakeProvider("only", outcomes=["runtime response"])
    llm = LLM(model="only-model", provider_router=router(provider))

    assert llm.ask("hello", system="system") == "runtime response"
    assert provider.calls[0]["system"] == "system"


def test_environment_provider_order_is_deterministic_and_aliases_are_not_duplicates(monkeypatch):
    monkeypatch.setenv("PROVIDER_ORDER", "local,ollama,first,first,second")

    assert ProviderFactory.get_configured_provider_order() == ["ollama", "first", "second"]


def test_legacy_default_and_fallback_configuration_produces_order(monkeypatch):
    monkeypatch.delenv("PROVIDER_ORDER", raising=False)
    monkeypatch.setenv("DEFAULT_PROVIDER", "local")
    monkeypatch.setenv("FALLBACK_PROVIDERS", "first,second,first")

    assert ProviderFactory.get_configured_provider_order() == ["ollama", "first", "second"]


class RegisteredStubProvider(BaseLLMProvider):
    provider_name = "registered-stub"

    def ask(self, prompt, system=None, messages=None, timeout=None, **kwargs):
        return ProviderResponse(content="registered", model=self.model, provider=self.provider_name)

    def check_health(self):
        return ProviderHealthStatus(
            provider_name=self.provider_name,
            is_healthy=True,
            is_reachable=True,
            model_available=True,
            model_name=self.model,
        )

    def list_models(self):
        return [self.model]


def test_factory_accepts_a_second_concrete_provider_implementation():
    ProviderFactory.register_provider("registered-stub", RegisteredStubProvider)
    try:
        provider = ProviderFactory.create("registered-stub", model="registered-model")
    finally:
        ProviderFactory.unregister_provider("registered-stub")

    assert isinstance(provider, RegisteredStubProvider)
    assert provider.model == "registered-model"
