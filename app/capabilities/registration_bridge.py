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
        "audio": ["audio file", "sound file", "audio recording", "convert this recording", "trim audio", "trim the beginning from this sound file", "split audio", "split this recording", "join audio", "extract audio"],
        "automation": ["remind me", "set a reminder", "schedule a reminder", "scheduled reminder", "pause the reminder", "resume the reminder", "cancel the reminder", "scheduled automation", "every day", "every week"],
        "browser_capability": ["open website", "browse website", "open web page", "read this url", "read the contents of this url", "reload the page", "find the login link", "find the link on this web page", "take a screenshot of this page", "open another tab", "go back to the page", "go back", "close the tab", "switch tab"],
        "calendar": ["calendar", "appointments", "what appointments", "next meeting", "find my next meeting", "meeting availability", "do i have availability", "schedule appointment"],
        "capability_introspection": ["available capabilities", "capability list", "what capabilities are available", "what functions are supported", "what can freya help me with"],
        "code_execution": ["python", "code", "run python", "run code", "execute code", "execute python", "execute this command", "run the script", "safe local command", "test this code"],
        "communication_hub": ["send message", "send a message", "publish message", "publish this announcement", "shared channel", "post this update", "message history", "messages sent through the hub"],
        "computer": ["computer control", "open application", "open calculator", "open the calculator", "launch application", "desktop control", "type this text into the current window", "click the button on the open application", "keyboard shortcut on the computer"],
        "contacts": ["address book", "my contacts", "contact details", "new contact entry", "create a new contact", "search my address book", "find in my contacts"],
        "data_analysis": ["analyze csv", "analyze this csv", "analyze data", "analyze spreadsheet", "spreadsheet columns", "summarize the columns", "correlation in this dataset", "chart from these data", "data analysis"],
        "database": ["database", "sqlite", "sql query", "database table", "database records", "database schema", "columns in this table", "inspect the columns", "show records", "show all records", "show me all records", "records in"],
        "debugging": ["debug", "debug this", "traceback", "diagnose error", "diagnose the error", "inspect why this program failed", "run diagnostics", "validate whether this fix", "resolves the error"],
        "decision_engine": ["decision", "compare options", "compare choices", "recommend one", "choose between", "evaluate the alternatives", "which choice should i make", "compare the advantages", "decide which is better"],
        "dependency_management": ["check dependencies", "installed packages", "verify environment", "local python environment", "project dependencies", "required tools are available", "check which required tools"],
        "document_editing": ["edit document", "modify document", "modify the contents of this file", "rewrite this document", "format the report", "export the edited document", "update document"],
        "file_input": ["read file", "load file", "open local file", "read the document i attached", "attached file", "import the file"],
        "file_output": ["save file", "write file", "write the result to the requested path", "export this content as a file", "store the report on disk", "export to file"],
        "iot": ["smart home", "iot device", "home automation", "temperature sensor state", "connected iot devices", "living room smart light", "smart light"],
        "knowledge_base": ["knowledge base", "search stored knowledge", "stored knowledge", "saved project information", "look up the saved project", "retrieve relevant stored knowledge"],
        "learning_pipeline": ["learn from this", "learn this durable correction", "record lesson", "consolidate the validated lesson", "extract a lesson", "verified learning result", "learning pipeline"],
        "memory_management": ["save memory", "store memory", "remember this", "retrieve memory", "retrieve what i told you earlier", "consolidate memories", "consolidate the relevant memories", "store this information for later"],
        "orchestration_core": ["run workflow", "run this workflow", "execute workflow", "execute the existing workflow", "check the status of the workflow", "workflow status", "composed sequence of steps", "orchestrate these tasks", "workflow orchestration"],
        "planning_engine": ["create a plan", "create a project plan", "make a plan", "break this objective into steps", "replan the work", "current plan", "plan this"],
        "reasoning_engine": ["reason about", "reason through", "reason through this problem step by step", "analyze why", "explain why", "explain why this result happened", "analyze the causes", "think through the tradeoffs", "synthesize an answer"],
        "research_capability": ["search_web", "read_page", "research_topic", "compare_sources", "verify_claim", "learn_finding", "archive_search", "advanced_search", "cross_site_research", "reverse_image_search", "image_intelligence", "read the relevant pages", "find current information", "public sources", "current information", "latest news", "current news", "find current news", "current processor news", "processor news", "Intel processor news", "latest processor", "newest processor", "latest desktop processor", "newest desktop processor", "latest cpu", "newest cpu", "current cpu", "current price", "latest price", "cheapest", "cheap products", "find a cheap", "cheap RAM", "lowest price", "compare prices", "price comparison", "product discovery", "shopping research", "find products", "product availability", "product specifications", "find reviews", "search reviews", "what are people saying", "look up the current", "search the web"],
        "safety_guard": ["check whether safe", "check whether this action is safe", "safety check", "is this safe", "is this operation allowed", "assess the risk", "should freya block", "dangerous operation"],
        "show_goals": ["show goals", "my goals", "current objectives", "display the goals i created"],
        "show_identity": ["who are you", "what is your name and role", "which assistant am i speaking with", "describe who you are"],
        "show_capabilities": ["what can you do", "show me the supported actions", "what functions are enabled", "give me the capability summary"],
        "show_memory": ["what do you remember", "show the memories you have stored", "what facts have you retained", "review our saved conversation memory", "tell me what is in memory"],
        "show_tasks": ["show tasks", "active tasks", "planned tasks", "list my pending work", "which jobs are active"],
        "simulation_capability": ["simulate failure", "simulate what happens", "possible scenarios", "compare these possible scenarios", "run a failure simulation", "run a simulation"],
        "system_monitoring": ["system monitoring", "system metrics", "system health", "check system health", "monitor performance", "monitor the performance of the computer", "current cpu and memory metrics", "component unhealthy"],
        "system_status": ["system status", "freya ready and healthy", "backend status", "service running normally", "status report"],
        "tool_dispatch": ["execute tool", "run tool", "run registered tool", "dispatch tool", "execute this tool action", "selected tool", "tool manager"],
        "tool_registry": ["tool registry", "available tools", "registered tools", "tool metadata", "list tools", "what tools are installed", "which tools can be dispatched"],
        "video": ["video file", "inspect video", "trim video", "cut video", "extract audio from this movie", "extract the audio from this movie", "resize the video", "concatenate video", "split video", "crop video", "export video"],
        "vision": ["inspect image", "inspect this image", "inspect what is in this image", "read the text in this picture", "visual contents of the screenshot", "extract fields from this image", "describe what you see in the image", "image contents", "visual inspection"],
        "voice": ["speak aloud", "speak this response", "speak this response aloud", "read aloud", "read this text out loud", "text to speech", "say this aloud", "say this message aloud", "transcribe this voice recording"],
        "decision_engine": ["decision", "compare options", "compare choices", "recommend one", "choose between", "evaluate the alternatives", "which choice should i make", "compare the advantages", "decide which is better"],
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
        patterns = [rf"\b{re.escape(str(phrase).strip())}\b" for phrase in dict.fromkeys(phrases) if str(phrase).strip()]
        if metadata.name == "browser_capability":
            patterns.extend([r"https?://[^\s<>\"']+", r"\b(?:open|visit|navigate\s+to)\s+(?:the\s+)?(?:website|web\s+page|url)\b"])
        return patterns

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
