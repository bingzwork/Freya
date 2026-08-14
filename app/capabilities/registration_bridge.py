"""Shared capability registration bridge for the target runtime graph.

The bridge deliberately keeps ``CapabilityRegistry`` as the canonical owner of
capability registrations.  It projects each registered capability into the
query-time ``CapabilityRouter`` and exposes its declared action through
``ToolManager``.  This makes the runtime path explicit and testable:

    CapabilityRegistry -> CapabilityRouter -> Capability Handlers -> ToolManager

No second registry is introduced and callers continue to use the existing
registry, router, capability objects, and tool manager APIs.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Optional
import re

from app.capabilities.router import CapabilityResult, CapabilityRouter
from app.core.tool_manager import ToolManager
from app.orchestrator.capability_registry import (
    Capability as RegisteredCapability,
    CapabilityMetadata,
    CapabilityRegistry,
    CapabilityState,
)


class CapabilityRegistrationBridge:
    """Expose canonical registry entries through the capability router.

    A routed capability is represented by a lightweight router handler.  The
    handler delegates to a tool registered with the existing ``ToolManager``;
    that tool invokes the registered capability's declared action.  The
    adapter therefore preserves the registered action implementation while
    ensuring every routed call crosses the declared ToolManager boundary.
    """

    _TOOL_PREFIX = "capability::"

    def __init__(
        self,
        *,
        registry: CapabilityRegistry,
        router: CapabilityRouter,
        tool_manager: ToolManager,
    ) -> None:
        self._registry = registry
        self._router = router
        self._tool_manager = tool_manager

    def sync(self) -> None:
        """Project all canonical registry entries into the supplied router."""
        for capability in self._registry.get_all().values():
            self.register_registered_capability(capability)

    def register_query_capability(
        self,
        *,
        name: str,
        description: str,
        handler: Callable[[dict[str, Any]], Any],
        patterns: Optional[Iterable[str]] = None,
        keywords: Optional[Iterable[str]] = None,
        intent_types: Optional[Iterable[str]] = None,
        tags: Optional[Iterable[str]] = None,
    ) -> RegisteredCapability:
        """Register a query capability through the canonical registry first."""
        existing = self._registry.get_capability(name)
        if existing is None:
            metadata = CapabilityMetadata(
                name=name,
                description=description,
                default_action="execute",
                supported_actions=["execute"],
                tags=list(tags or keywords or []),
                safe_query=True,
            )
            existing = RegisteredCapability(metadata=metadata, handler=handler)
            if not self._registry.register(existing, registered_by="SystemInitializer"):
                raise RuntimeError(f"Unable to register capability '{name}'")

        self.register_registered_capability(
            existing,
            patterns=patterns,
            keywords=keywords,
            intent_types=intent_types,
        )
        return existing

    def register_registered_capability(
        self,
        capability: RegisteredCapability,
        *,
        patterns: Optional[Iterable[str]] = None,
        keywords: Optional[Iterable[str]] = None,
        intent_types: Optional[Iterable[str]] = None,
    ) -> None:
        """Expose one existing canonical registration through the router."""
        if not capability.is_executable():
            raise ValueError(
                f"Capability '{capability.name}' cannot be routed without a declared callable action"
            )

        metadata = capability.metadata
        derived_keywords = list(keywords or self._keywords_for(metadata))
        derived_patterns = list(patterns or self._patterns_for(metadata))
        tool_name = self._tool_name(capability.name)

        def tool_handler(*, context: dict[str, Any]) -> Any:
            action = context.get("capability_action") or capability.metadata.default_action
            if not capability.supports_action(action):
                raise ValueError(
                    f"Capability '{capability.name}' does not support requested action '{action}'"
                )
            return capability.execute(action, context)

        # Registering the same adapter name is intentional: it refreshes the
        # callable if the registry capability has been late-bound or replaced
        # during a controlled test/runtime setup.
        self._tool_manager.register(tool_name, tool_handler)

        def routed_handler(context: dict[str, Any]) -> CapabilityResult:
            tool_result = self._tool_manager.execute(tool_name, context=context)
            if not tool_result.success:
                return CapabilityResult(
                    success=False,
                    message=tool_result.error,
                    capability_name=capability.name,
                )
            return self._normalize_result(capability.name, tool_result.output)

        self._router.register_capability(
            name=capability.name,
            handler=routed_handler,
            description=metadata.description,
            patterns=derived_patterns,
            keywords=derived_keywords,
            intent_types=list(intent_types or []),
        )

    @staticmethod
    def _tool_name(capability_name: str) -> str:
        return f"{CapabilityRegistrationBridge._TOOL_PREFIX}{capability_name}"

    @staticmethod
    def _keywords_for(metadata: CapabilityMetadata) -> list[str]:
        """Derive conservative discovery keywords from declared metadata only."""
        if not metadata.auto_discoverable:
            return []
        name_words = metadata.name.replace("_", " ").split()
        return list(dict.fromkeys([metadata.name, *name_words, *metadata.tags]))

    @staticmethod
    def _patterns_for(metadata: CapabilityMetadata) -> list[str]:
        if not metadata.auto_discoverable:
            return []
        phrase = re.escape(metadata.name.replace("_", " "))
        return [rf"\b{phrase}\b"] if phrase else []

    @staticmethod
    def _normalize_result(capability_name: str, result: Any) -> CapabilityResult:
        if isinstance(result, CapabilityResult):
            result.capability_name = result.capability_name or capability_name
            return result
        if isinstance(result, dict):
            success = bool(result.get("success", True))
            message = str(result.get("message") or result.get("error") or "")
            return CapabilityResult(
                success=success,
                data=result,
                message=message,
                capability_name=capability_name,
            )
        return CapabilityResult(
            success=True,
            data=result,
            message=str(result) if result is not None else "",
            capability_name=capability_name,
        )


__all__ = ["CapabilityRegistrationBridge"]
