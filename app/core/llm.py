"""Primary runtime adapter for provider-backed Freya inference."""

import os
from typing import Mapping, Optional, Sequence

from app.core.logger import logger
from app.identity import create_enhanced_system_prompt
from app.providers.factory import ProviderFactory
from app.providers.resilient import ResilientLLMProvider


FREYA_SYSTEM_PROMPT = (
    "You are Freya, an autonomous AI software engineer.\n"
    "Engine focus: Windows-first, Python-first, PowerShell-first.\n"
    "Aware of: the current Git state, the active model, and the configured LLM provider.\n"
    "Behave like an engineer: think briefly, act deliberately, and produce well-formed plans and clean, minimal code. "
    "Reason from the context in front of you. Prefer the smallest correct change. "
    "Skip hedging, filler, invented tools, and any step you cannot justify."
)

ENHANCED_SYSTEM_PROMPT = create_enhanced_system_prompt(FREYA_SYSTEM_PROMPT)


class LLM:
    """Return text responses from the configured resilient provider path.

    ``LLM`` remains the compatibility surface consumed by the legacy agent,
    priority scheduler, and LLM stack.  The provider router owns health-aware
    ordering, bounded concrete-provider requests, and fallback decisions.
    """

    def __init__(
        self,
        model: Optional[str] = None,
        *,
        provider_names: Optional[Sequence[str]] = None,
        provider_options: Optional[Mapping[str, Mapping[str, object]]] = None,
        provider_router: Optional[ResilientLLMProvider] = None,
    ) -> None:
        self._model = model or os.getenv("MODEL") or "qwen3:8b"
        if provider_router is None:
            options = {name: dict(values) for name, values in (provider_options or {}).items()}
            if model is not None:
                for name in ProviderFactory.get_configured_provider_order(provider_names):
                    options.setdefault(name, {})["model"] = model
            provider_router = ResilientLLMProvider(
                provider_names,
                provider_options=options,
            )
        self._provider_router = provider_router
        logger.info(
            f"[LLM] Initialized provider order={','.join(self._provider_router.provider_order) or 'none'} "
            f"model={self._model}"
        )

    @property
    def model(self) -> str:
        """Return the configured model until a provider response identifies the active model."""
        return self._model

    @model.setter
    def model(self, value: str) -> None:
        self._model = value

    @property
    def provider_order(self) -> list[str]:
        """Expose canonical provider order for diagnostics without vendor coupling."""
        return self._provider_router.provider_order

    @property
    def last_provider_attempts(self):
        """Expose the last non-sensitive routing decisions for observability."""
        return self._provider_router.last_attempts

    def get_provider_health(self) -> dict:
        """Return current provider observations through the active provider router."""
        return {
            name: self._provider_router.get_health_status(name)
            for name in self._provider_router.provider_order
        }

    def ask(
        self,
        prompt: str,
        system: str = ENHANCED_SYSTEM_PROMPT,
        timeout: Optional[float] = None,
    ) -> str:
        """Perform one inference request or propagate the safe provider failure."""
        response = self._provider_router.ask(
            prompt,
            system=system,
            timeout=timeout,
        )
        self._model = response.model
        return response.content
