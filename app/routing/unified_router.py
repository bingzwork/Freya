
"""
UnifiedRouter - Single Intent/Control/Capability Router.

Consolidates: IntentClassifier, CapabilityRouter, ConversationalControlHandler (routing part)
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Tuple

from app.intent import (
    IntentType,
    classify_intent,
    should_answer_directly,
    should_clarify,
    should_clarify_engineering,
    is_control_intent,
)
from app.capabilities.router import CapabilityRouter, CapabilityResult, NoCapabilityError
from app.conversational_control import ControlCommand
from app.core.protocols import MemoryProvider, ToolProvider, RouterProtocol
from app.core.priority_llm import PriorityLLMProvider
from app.core.protocols import ChatActivityProvider
from app.routing.knowledge_first_resolver import KnowledgeFirstResolver, ResolutionResult
from app.memory.unified_retrieval import UnifiedRetrieval
from app.intelligence.intelligence import Intelligence
from app.core.correlation import correlation_scope
from app.core.llm_stack import LLMStack
from app.core.logger import logger
from app.capabilities.registration_bridge import CapabilityRegistrationBridge
from app.orchestrator.capability_registry import CapabilityRegistry


@dataclass
class RouteResult:
    # Classification
    intent: IntentType
    confidence: float
    reason: str

    # Routing decision
    is_direct_answer: bool = False
    is_clarification: bool = False
    is_control: bool = False
    is_engineering: bool = False
    control_command: Optional[ControlCommand] = None

    # Capability match (if any)
    capability_name: Optional[str] = None
    capability_confidence: float = 0.0
    capability_result: Any = None

    # Knowledge-first answer and verified local-LLM fallback handoff
    answer: Optional[str] = None
    llm_prompt: Optional[str] = None
    llm_priority: Any = None
    llm_context: Optional[Dict[str, Any]] = None
    routing_metadata: Optional[Dict[str, Any]] = None


class ControlCommandParser:
    """Extract control commands from user input."""

    CONTROL_PATTERNS = {
        ControlCommand.STOP: [r'\bstop\b', r'\bhalt\b', r'\bwait\b'],
        ControlCommand.CANCEL: [r'\bcancel\b', r'\bnevermind\b', r'\babort\b'],
        ControlCommand.PAUSE: [r'\bpause\b'],
        ControlCommand.RESUME: [r'\bresume\b', r'\bcontinue\b'],
        ControlCommand.UNDO: [r'\bundo\b'],
        ControlCommand.REDO: [r'\bredo\b'],
        ControlCommand.STATUS: [r'\bstatus\b', r'what are you doing', r'current plan', r'current step'],
    }

    def parse(self, user_input: str) -> Optional[ControlCommand]:
        """Parse user input for control commands. Returns the matched command or None."""
        import re
        user_lower = user_input.lower().strip()

        for cmd, patterns in self.CONTROL_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, user_lower):
                    return cmd
        return None


class UnifiedRouter:
    """
    Single route() call returns complete routing decision; no multi-stage classification in callers.
    Delegates to KnowledgeFirstResolver for knowledge-first routing.
    """

    def __init__(
        self,
        memory: MemoryProvider,
        tools: ToolProvider,
        llm: PriorityLLMProvider,
        chat_activity: ChatActivityProvider,
        unified_retrieval: UnifiedRetrieval,
        intelligence: Intelligence,
        llm_stack: LLMStack,
        capability_registry: Optional[CapabilityRegistry] = None,
    ):
        self._memory = memory
        self._tools = tools
        self._llm = llm
        self._chat_activity = chat_activity

        # Reuse existing logic for control command parsing and capability registration
        from app.intent.classifier import IntentClassifier
        self._intent_classifier = IntentClassifier()
        self._capability_router = CapabilityRouter()
        self._capability_registry = capability_registry
        self._capability_bridge = (
            CapabilityRegistrationBridge(
                registry=capability_registry,
                router=self._capability_router,
                tool_manager=tools,
            )
            if capability_registry is not None
            else None
        )
        self._control_parser = ControlCommandParser()

        # KnowledgeFirstResolver is the sole production routing path. The
        # initializer supplies every dependency explicitly so routing cannot
        # silently fall back to a parallel legacy graph.
        self._knowledge_first_resolver = KnowledgeFirstResolver(
            unified_retrieval=unified_retrieval,
            intelligence=intelligence,
            capability_router=self._capability_router,
            llm_stack=llm_stack,
        )

        # CapabilityRegistry remains the single source of registrations.
        # Project pre-registered workflow capabilities before adding the
        # query-facing built-ins through the same bridge.
        if self._capability_bridge is not None:
            self._capability_bridge.sync()
        self._register_builtin_capabilities()

    def _register_builtin_capabilities(self) -> None:
        """Register query-facing built-ins through the canonical registry."""
        from app.capabilities.handlers import (
            handle_system_status,
            handle_show_identity,
            handle_show_capabilities,
            handle_show_memory,
            handle_show_goals,
            handle_show_tasks,
        )

        definitions = (
            ("system_status", handle_system_status, "Show system status and health", ["status", "health", "system"], ["system_status", "question"]),
            ("show_identity", handle_show_identity, "Answer questions about Freya identity", ["name", "creator", "created", "made", "identity", "role", "what are you", "who are you"], ["question", "chat", "system_status"]),
            ("show_capabilities", handle_show_capabilities, "List available capabilities", ["capabilities", "what can you do", "features", "tools"], ["question", "chat", "system_status"]),
            ("show_memory", handle_show_memory, "Show memory contents", ["memory", "what do you remember", "recall"], ["question", "system_status"]),
            ("show_goals", handle_show_goals, "Show current goals", ["goals", "objectives", "targets"], ["question", "system_status"]),
            ("show_tasks", handle_show_tasks, "Show active/planned tasks", ["tasks", "plan", "steps", "progress"], ["question", "system_status"]),
        )
        for name, handler, description, keywords, intent_types in definitions:
            def bound_handler(context, handler=handler):
                bound_context = dict(context or {})
                bound_context.setdefault("capability_registry", self._capability_registry)
                bound_context.setdefault("capability_router", self._capability_router)
                return handler(bound_context)

            if self._capability_bridge is not None:
                self._capability_bridge.register_query_capability(
                    name=name,
                    handler=bound_handler,
                    description=description,
                    keywords=keywords,
                    intent_types=intent_types,
                )
            else:
                # Direct construction remains supported for focused unit tests,
                # while production initialization always supplies the bridge.
                self._capability_router.register_capability(
                    name=name,
                    handler=handler,
                    description=description,
                    keywords=keywords,
                    intent_types=intent_types,
                )

    def route(self, user_input: str, context: Optional[Dict[str, Any]] = None) -> RouteResult:
        """
        Route user input to the appropriate handler.

        Returns a complete routing decision in a single call.
        Uses KnowledgeFirstResolver for knowledge-first routing when available.
        """
        route_context = dict(context or {})
        with correlation_scope(route_context.get("correlation_id"), prefix="request") as correlation_id:
            route_context.setdefault("correlation_id", correlation_id)
            route_context.setdefault("request_id", correlation_id)

            # 1. Check conversational control FIRST (short-circuits everything)
            control_cmd = self._control_parser.parse(user_input)
            if control_cmd:
                return RouteResult(
                    intent=IntentType.CONVERSATIONAL_CONTROL,
                    confidence=1.0,
                    reason="Control command",
                    is_control=True,
                    control_command=control_cmd,
                )

            # 2. Knowledge-first routing is authoritative. Resolver failures are
            # surfaced to the caller rather than silently selecting a conflicting
            # legacy path.
            classification = self._intent_classifier.classify(user_input, route_context)
            route_context["intent_type"] = classification.intent.value

            # Engineering intents preserve the classifier planning contract.
            # Knowledge-first answerability is for questions, not project changes.
            if classification.intent.requires_planning:
                routing_metadata = dict(intent_classification=classification.to_dict())
                if classification.should_clarify_engineering:
                    return RouteResult(
                        intent=classification.intent,
                        confidence=classification.confidence,
                        reason=classification.reason,
                        is_clarification=True,
                        routing_metadata=routing_metadata,
                    )
                return RouteResult(
                    intent=classification.intent,
                    confidence=classification.confidence,
                    reason=classification.reason,
                    is_engineering=True,
                    routing_metadata=routing_metadata,
                )
            resolution = self._knowledge_first_resolver.resolve(
                query=user_input,
                context=route_context,
                intent_type=classification.intent,
            )

            # Convert ResolutionResult to RouteResult.
            if resolution.action == "answer":
                return RouteResult(
                    intent=IntentType.QUESTION,
                    confidence=resolution.confidence,
                    reason=f"Knowledge-first answer: {', '.join(resolution.sources)}",
                    is_direct_answer=True,
                    answer=resolution.answer,
                    routing_metadata=resolution.routing_metadata,
                )
            if resolution.action == "capability":
                return RouteResult(
                    intent=IntentType.QUESTION,
                    confidence=resolution.capability_confidence,
                    reason=f"Capability: {resolution.capability_name}",
                    is_direct_answer=True,
                    capability_name=resolution.capability_name,
                    capability_confidence=resolution.capability_confidence,
                    capability_result=resolution.capability_result,
                    routing_metadata=resolution.routing_metadata,
                )
            if resolution.action == "llm_fallback":
                llm_context = dict(resolution.llm_context or {})
                llm_context.setdefault("correlation_id", correlation_id)
                llm_context.setdefault("request_id", correlation_id)
                return RouteResult(
                    intent=IntentType.QUESTION,
                    confidence=resolution.confidence,
                    reason="LLM fallback required",
                    is_direct_answer=True,
                    llm_prompt=resolution.llm_prompt,
                    llm_priority=resolution.llm_priority,
                    llm_context=llm_context,
                    routing_metadata=resolution.routing_metadata,
                )

            # Resolver implementations must return one of the above actions.
            raise RuntimeError(f"Unsupported knowledge-first routing action: {resolution.action}")

    def execute_capability(self, capability_name: str, query: str, **context) -> CapabilityResult:
        """Execute a specific capability by name through the shared router path."""
        return self._capability_router.execute_named(capability_name, query, **context)

    def get_planning_context(self, task: str) -> Dict[str, Any]:
        """Return knowledge and available capability context for UnifiedPlanner."""
        return {
            "knowledge": self._memory.retrieve_for_planning(task),
            "capabilities": self.find_matching_capabilities(task),
        }

    def find_matching_capabilities(self, query: str, intent_type: Optional[str] = None) -> List[Tuple[str, float]]:
        """Find all capabilities matching a query."""
        return self._capability_router.find_matching(query, intent_type)

    def get_capabilities(self) -> List[str]:
        """Get list of registered capability names."""
        return self._capability_router.get_capabilities()

    def get_capability(self, name: str):
        """Get a capability by name."""
        return self._capability_router.get_capability(name)
