"""Tests for LLMStack integration with the provider-backed LLM adapter."""

from app.core.llm import LLM
from app.core.llm_stack import LLMStack, get_llm_stack, set_llm_stack
from app.core.priority_llm import LLMPriority
from app.providers.base import BaseLLMProvider, ProviderConfig, ProviderHealthStatus, ProviderResponse
from app.providers.resilient import ResilientLLMProvider


class StackStubProvider(BaseLLMProvider):
    provider_name = "stack-stub"

    def __init__(self):
        super().__init__(ProviderConfig(provider_name=self.provider_name, model="stack-model", timeout=1.0))
        self.calls = []

    def ask(self, prompt, system=None, messages=None, timeout=None, **kwargs):
        self.calls.append({"prompt": prompt, "system": system, "timeout": timeout})
        return ProviderResponse(content="Stack response", model=self.model, provider=self.provider_name)

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


def make_stack(model="stack-model"):
    provider = StackStubProvider()
    llm = LLM(
        model=model,
        provider_router=ResilientLLMProvider([provider.provider_name], providers={provider.provider_name: provider}),
    )
    return LLMStack(base_llm=llm), provider


class TestLLMStack:
    def test_llm_stack_init_default_model(self):
        stack, _ = make_stack()
        try:
            assert stack.model == "stack-model"
        finally:
            stack.shutdown()

    def test_llm_stack_init_custom_model(self):
        stack, _ = make_stack(model="custom-model")
        try:
            assert stack.model == "custom-model"
        finally:
            stack.shutdown()

    def test_llm_stack_has_priority_llm(self):
        stack, _ = make_stack()
        try:
            assert stack.priority_llm is not None
        finally:
            stack.shutdown()

    def test_llm_stack_has_chat_activity(self):
        stack, _ = make_stack()
        try:
            assert stack.chat_activity is not None
        finally:
            stack.shutdown()

    def test_ask_uses_provider_backed_runtime(self):
        stack, provider = make_stack()
        try:
            assert stack.ask("Hello", system="Test", timeout=3.0) == "Stack response"
            assert provider.calls == [{"prompt": "Hello", "system": "Test", "timeout": 3.0}]
        finally:
            stack.shutdown()

    def test_ask_priority_chat(self):
        stack, provider = make_stack()
        try:
            assert stack.ask("Chat message", priority=LLMPriority.CHAT) == "Stack response"
            assert provider.calls[0]["prompt"] == "Chat message"
        finally:
            stack.shutdown()

    def test_chat_activity_delegation(self):
        stack, _ = make_stack()
        try:
            stack.chat_started()
            assert stack.is_chat_active() is True
            stack.chat_ended()
            assert stack.is_chat_active() is False
            stack.chat_activity_heartbeat()
            assert stack.is_chat_active() is True
        finally:
            stack.shutdown()

    def test_get_stats(self):
        stack, _ = make_stack()
        try:
            stats = stack.get_stats()
            assert stats["model"] == "stack-model"
            assert "chat_active" in stats
            assert "total_requests" in stats
        finally:
            stack.shutdown()

    def test_shutdown(self):
        stack, _ = make_stack()
        stack.shutdown()


class TestLLMStackGlobal:
    def test_get_llm_stack_singleton(self):
        set_llm_stack(None)
        stack1 = get_llm_stack()
        stack2 = get_llm_stack()
        try:
            assert stack1 is stack2
        finally:
            stack1.shutdown()
            set_llm_stack(None)

    def test_set_llm_stack(self):
        set_llm_stack(None)
        stack1, _ = make_stack()
        custom_stack, _ = make_stack(model="custom-model")
        try:
            set_llm_stack(stack1)
            set_llm_stack(custom_stack)
            assert get_llm_stack() is custom_stack
            assert custom_stack.model == "custom-model"
            assert stack1 is not custom_stack
        finally:
            stack1.shutdown()
            custom_stack.shutdown()
            set_llm_stack(None)
