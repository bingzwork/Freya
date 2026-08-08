
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
from app.core.logger import logger


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
    """

    def __init__(
        self,
        memory: MemoryProvider,
        tools: ToolProvider,
        llm: PriorityLLMProvider,
        chat_activity: ChatActivityProvider,
    ):
        self._memory = memory
        self._tools = tools
        self._llm = llm
        self._chat_activity = chat_activity

        # Reuse existing logic
        from app.intent.classifier import IntentClassifier
        self._intent_classifier = IntentClassifier()
        self._capability_router = CapabilityRouter()
        self._control_parser = ControlCommandParser()

        # Register built-in capabilities
        self._register_builtin_capabilities()

    def _register_builtin_capabilities(self) -> None:
        """Register built-in capabilities that can answer directly."""
        from app.capabilities.handlers import (
            handle_system_status,
            handle_show_capabilities,
            handle_show_memory,
            handle_show_goals,
            handle_show_tasks,
        )

        # System status capability
        self._capability_router.register_capability(
            name="system_status",
            handler=handle_system_status,
            description="Show system status and health",
            keywords=["status", "health", "system"],
            intent_types=["system_status", "question"],
        )

        # Show capabilities
        self._capability_router.register_capability(
            name="show_capabilities",
            handler=handle_show_capabilities,
            description="List available capabilities",
            keywords=["capabilities", "what can you do", "features"],
            intent_types=["question", "system_status"],
        )

        # Show memory
        self._capability_router.register_capability(
            name="show_memory",
            handler=handle_show_memory,
            description="Show memory contents",
            keywords=["memory", "what do you remember", "recall"],
            intent_types=["question", "system_status"],
        )

        # Show goals
        self._capability_router.register_capability(
            name="show_goals",
            handler=handle_show_goals,
            description="Show current goals",
            keywords=["goals", "objectives", "targets"],
            intent_types=["question", "system_status"],
        )

        # Show tasks
        self._capability_router.register_capability(
            name="show_tasks",
            handler=handle_show_tasks,
            description="Show active/planned tasks",
            keywords=["tasks", "plan", "steps", "progress"],
            intent_types=["question", "system_status"],
        )

    def route(self, user_input: str, context: Optional[Dict[str, Any]] = None) -> RouteResult:
        """
        Route user input to the appropriate handler.

        Returns a complete routing decision in a single call.
        """
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

        # 2. Classify intent
        classification = self._intent_classifier.classify(user_input, context)

        # 3. Check capability match for SYSTEM_STATUS and other direct routes
        if classification.intent in (IntentType.SYSTEM_STATUS, IntentType.CHAT, IntentType.QUESTION):
            cap_match = self._capability_router.find_matching(user_input, classification.intent.value)
            if cap_match:
                best_name, best_conf = cap_match[0]
                return RouteResult(
                    intent=classification.intent,
                    confidence=max(classification.confidence, best_conf),
                    reason=f"Capability: {best_name}",
                    is_direct_answer=True,
                    capability_name=best_name,
                    capability_confidence=best_conf,
                )

        # 4. Check clarification thresholds
        if classification.is_ambiguous or getattr(classification, 'should_clarify_engineering', False):
            return RouteResult(
                intent=classification.intent,
                confidence=classification.confidence,
                reason=classification.reason,
                is_clarification=True,
            )

        # 5. Direct answer for non-engineering
        if classification.should_answer_directly:
            return RouteResult(
                intent=classification.intent,
                confidence=classification.confidence,
                reason=classification.reason,
                is_direct_answer=True,
            )

        # 6. Engineering task
        return RouteResult(
            intent=classification.intent,
            confidence=classification.confidence,
            reason=classification.reason,
            is_engineering=True,
        )

    def execute_capability(self, capability_name: str, query: str, **context) -> CapabilityResult:
        """Execute a specific capability by name."""
        return self._capability_router.route(query, capability_name=capability_name, **context)

    def find_matching_capabilities(self, query: str, intent_type: Optional[str] = None) -> List[Tuple[str, float]]:
        """Find all capabilities matching a query."""
        return self._capability_router.find_matching(query, intent_type)

    def get_capabilities(self) -> List[str]:
        """Get list of registered capability names."""
        return self._capability_router.get_capabilities()

    def get_capability(self, name: str):
        """Get a capability by name."""
        return self._capability_router.get_capability(name)
