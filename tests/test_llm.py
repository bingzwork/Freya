"""Tests for the compatibility LLM adapter over the provider router."""

from app.core.llm import LLM
from app.providers.base import BaseLLMProvider, ProviderConfig, ProviderHealthStatus, ProviderResponse
from app.providers.resilient import ResilientLLMProvider


class StubProvider(BaseLLMProvider):
    provider_name = "stub"

    def __init__(self, content="Test response"):
        super().__init__(ProviderConfig(provider_name="stub", model="stub-model", timeout=1.0))
        self.content = content
        self.calls = []

    def ask(self, prompt, system=None, messages=None, timeout=None, **kwargs):
        self.calls.append({"prompt": prompt, "system": system, "timeout": timeout})
        return ProviderResponse(content=self.content, model=self.model, provider=self.provider_name)

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


def make_llm(provider: StubProvider) -> LLM:
    router = ResilientLLMProvider(["stub"], providers={"stub": provider})
    return LLM(model="stub-model", provider_router=router)


class TestLLM:
    def test_llm_init_default_model(self):
        llm = make_llm(StubProvider())
        assert llm.model == "stub-model"

    def test_llm_init_custom_model(self):
        llm = LLM(model="custom-model", provider_router=ResilientLLMProvider([]))
        assert llm.model == "custom-model"

    def test_ask_uses_provider_router(self):
        provider = StubProvider()
        llm = make_llm(provider)

        response = llm.ask("Test prompt", system="Test system", timeout=4.0)

        assert response == "Test response"
        assert provider.calls == [{"prompt": "Test prompt", "system": "Test system", "timeout": 4.0}]

    def test_ask_updates_active_model_from_provider_response(self):
        provider = StubProvider(content="response")
        llm = make_llm(provider)

        llm.ask("hello")

        assert llm.model == "stub-model"
