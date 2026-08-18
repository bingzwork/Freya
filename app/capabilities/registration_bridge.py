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

    _SEMANTIC_ALIASES = {
        "decision_engine": ["decision", "compare options", "compare choices", "recommend one", "choose between"],
        "tool_registry": ["tool registry", "available tools", "registered tools", "tool metadata", "list tools"],
        "code_execution": ["python", "code", "run python", "run code", "execute code", "execute python"],
        "debugging": ["debug", "debug this", "traceback", "diagnose error"],
        "dependency_management": ["check dependencies", "installed packages", "verify environment"],
        "knowledge_base": ["knowledge base", "search stored knowledge", "stored knowledge"],
        "memory_management": ["save memory", "store memory", "remember this", "retrieve memory"],
        "learning_pipeline": ["learn from this", "record lesson", "learning pipeline"],
        "planning_engine": ["create a plan", "make a plan", "plan this"],
        "orchestration_core": ["run workflow", "run this workflow", "execute workflow", "workflow orchestration"],
        "reasoning_engine": ["reason about", "analyze why", "explain why"],
        "system_monitoring": ["system monitoring", "system metrics", "system health", "check system health", "monitor performance"],
        "file_input": ["read file", "load file", "open local file"],
        "file_output": ["save file", "write file", "export to file"],
        "document_editing": ["edit document", "modify document", "update document"],
        "browser_capability": ["open website", "browse website", "open web page"],
        "simulation_capability": ["simulate failure", "simulate what happens", "run a simulation"],
        "communication_hub": ["send message", "send a message", "publish message", "message history"],
        "show_goals": ["show goals", "my goals", "current objectives"],
        "show_tasks": ["show tasks", "active tasks", "planned tasks"],
        "tool_dispatch": ["execute tool", "run tool", "run registered tool", "dispatch tool"],
        "iot": ["smart home", "iot device", "home automation"],
        "calendar": ["calendar", "appointments", "what appointments", "schedule appointment"],
        "capability_introspection": ["available capabilities", "capability list", "what capabilities are available"],
        "computer": ["computer control", "open application", "open calculator", "open the calculator", "launch application", "desktop control"],
        "data_analysis": ["analyze csv", "analyze this csv", "analyze data", "analyze spreadsheet", "data analysis"],
        "orchestration_core": ["run workflow", "run this workflow", "execute workflow", "workflow orchestration"],
        "reasoning_engine": ["reason through", "logical reasoning", "think through problem", "reasoning"],
        "safety_guard": ["check whether safe", "check whether this action is safe", "safety check", "is this safe"],
        "vision": ["inspect image", "inspect this image", "inspect what is in this image", "image contents", "visual inspection"],
        "voice": ["speak aloud", "speak this response", "speak this response aloud", "read aloud", "text to speech", "say this aloud"],
    }

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
            return capability.execute(action, self._action_inputs(capability, context))

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
            return CapabilityRegistrationBridge._normalize_result(capability.name, tool_result.output)

        self._router.register_capability(
            name=capability.name,
            handler=routed_handler,
            description=metadata.description,
            patterns=derived_patterns,
            keywords=derived_keywords,
            intent_types=list(intent_types or []),
            safe_query=metadata.safe_query,
        )

    @staticmethod
    def _action_inputs(capability: RegisteredCapability, context: dict[str, Any]) -> dict[str, Any]:
        """Provide conversational fields and safely extract explicit local inputs."""
        inputs = dict(context or {})
        query = str(inputs.get("query") or "").strip()
        if query:
            inputs.setdefault("task", query)
            inputs.setdefault("problem", query)
            inputs.setdefault("question", query)
            inputs.setdefault("search_query", query)
        name = capability.metadata.name
        if name == "decision_engine" and "options" not in inputs:
            quoted = re.findall(r"""["']([^"']+)["']""", query)
            if len(quoted) >= 2:
                inputs["options"] = quoted
            else:
                option_text = re.search(r"""(?:options?|choices?)\s*(?:are|include|:)??\s*(.+)""", query, re.IGNORECASE)
                if option_text:
                    values = re.split(r"""\s*(?:,|;|\bor\b|\band\b)\s*""", option_text.group(1), flags=re.IGNORECASE)
                    values = [value.strip(" .") for value in values if value.strip(" .")]
                    if len(values) >= 2:
                        inputs["options"] = values
        if name in {"file_input", "data_analysis", "document_editing"} and "path" not in inputs:
            path_match = re.search(r"""(?P<path>(?:[A-Za-z]:[\\/]|/)[^"<>|?]*?\.[A-Za-z0-9]{1,12})""", query)
            if path_match:
                inputs["path"] = path_match.group("path").strip()
        return inputs

    @staticmethod
    def _tool_name(capability_name: str) -> str:
        return f"{CapabilityRegistrationBridge._TOOL_PREFIX}{capability_name}"

    @classmethod
    def _semantic_aliases(cls, metadata: CapabilityMetadata) -> list[str]:
        return list(cls._SEMANTIC_ALIASES.get(metadata.name, ()))

    @classmethod
    def _keywords_for(cls, metadata: CapabilityMetadata) -> list[str]:
        """Derive discovery keywords from metadata and semantic capability aliases."""
        if not metadata.auto_discoverable:
            return []
        name_words = metadata.name.replace("_", " ").split()
        return list(dict.fromkeys([metadata.name, *name_words, *metadata.tags, *metadata.aliases, *cls._semantic_aliases(metadata)]))

    @classmethod
    def _patterns_for(cls, metadata: CapabilityMetadata) -> list[str]:
        if not metadata.auto_discoverable:
            return []
        phrases = [metadata.name.replace("_", " "), *metadata.aliases, *cls._semantic_aliases(metadata)]
        return [rf"\b{re.escape(str(phrase).strip())}\b" for phrase in dict.fromkeys(phrases) if str(phrase).strip()]

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
