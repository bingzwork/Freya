"""Unified Intent Router.

Consolidates IntentClassifier and CapabilityRouter into a single routing interface.
This replaces the need for multiple routing systems in app/routing/unified_router.py
and app/capabilities/router.py.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from app.capabilities.router import CapabilityRouter, CapabilityResult, NoCapabilityError
from app.intent.classifier import (
    IntentClassifier,
    IntentType,
    IntentClassification,
    classify_intent,
    should_answer_directly,
    should_clarify,
    should_clarify_engineering,
    is_control_intent,
    is_low_confidence,
)
from app.conversational_control import ControlCommand
from app.core.logger import logger


@dataclass
class RouteDecision:
    """Complete routing decision for a user input."""
    # Classification
    intent: IntentType
    confidence: float
    reason: str
    keywords: List[str]
    original_message: str = ""

    # Routing flags (single source of truth)
    is_direct_answer: bool = False
    is_clarification: bool = False
    is_control: bool = False
    is_engineering: bool = False
    control_command: Optional[ControlCommand] = None

    # Capability match (for system status queries)
    capability_name: Optional[str] = None
    capability_confidence: float = 0.0

    # Context flags
    should_include_runtime_context: bool = False


class ControlCommandParser:
    """Parse control commands from user input (stop, cancel, undo, etc.)."""

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
        """Parse user input for control commands."""
        import re
        user_lower = user_input.lower().strip()

        for cmd, patterns in self.CONTROL_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, user_lower):
                    return cmd
        return None


class IntentRouter:
    """
    Single unified router for all intent classification and capability routing.

    This consolidates:
    - IntentClassifier (app/intent/classifier.py)
    - CapabilityRouter (app/capabilities/router.py)
    - UnifiedRouter (app/routing/unified_router.py) -- deprecated
    """

    def __init__(
        self,
        capability_router: Optional[CapabilityRouter] = None,
        intent_classifier: Optional[IntentClassifier] = None,
    ):
        self._intent_classifier = intent_classifier or IntentClassifier()
        self._capability_router = capability_router or CapabilityRouter()
        self._control_parser = ControlCommandParser()

        # Register built-in capabilities that can answer directly
        self._register_builtin_capabilities()

    def _register_builtin_capabilities(self) -> None:
        """Register built-in capabilities for direct answers."""
        from app.capabilities.handlers import (
            handle_system_status,
            handle_show_capabilities,
            handle_show_memory,
            handle_show_goals,
            handle_show_tasks,
            handle_python_version,
            handle_os_info,
            handle_current_time,
            handle_working_directory,
            handle_current_model,
            handle_ollama_status,
            handle_git_status,
        )

        capabilities = [
            ("system_status", handle_system_status, "Show system status and health", ["status", "health", "system"], ["system_status", "question"]),
            ("show_capabilities", handle_show_capabilities, "List available capabilities", ["capabilities", "what can you do", "features"], ["question", "system_status"]),
            ("show_memory", handle_show_memory, "Show memory contents", ["memory", "what do you remember", "recall"], ["question", "system_status"]),
            ("show_goals", handle_show_goals, "Show current goals", ["goals", "objectives", "targets"], ["question", "system_status"]),
            ("show_tasks", handle_show_tasks, "Show active/planned tasks", ["tasks", "plan", "steps", "progress"], ["question", "system_status"]),
            ("python_version", handle_python_version, "Get Python version", ["python", "version"], ["system_status", "question"]),
            ("os_info", handle_os_info, "Get OS information", ["os", "operating system"], ["system_status", "question"]),
            ("current_time", handle_current_time, "Get current time", ["time", "clock", "what time"], ["system_status", "question"]),
            ("working_directory", handle_working_directory, "Get working directory", ["directory", "pwd", "folder"], ["system_status", "question"]),
            ("current_model", handle_current_model, "Get current model info", ["model", "llm", "which model"], ["system_status", "question"]),
            ("ollama_status", handle_ollama_status, "Get Ollama connection status", ["ollama", "connected"], ["system_status", "question"]),
            ("git_status", handle_git_status, "Get Git repository status", ["git", "status", "repository"], ["system_status", "git_operation", "question"]),
        ]

        for name, handler, desc, keywords, intent_types in capabilities:
            self._capability_router.register(
                name=name,
                handler=handler,
                description=desc,
                keywords=keywords,
                intent_types=intent_types,
            )

    def route(self, user_input: str, context: Optional[Dict[str, Any]] = None) -> RouteDecision:
        """
        Route user input to the appropriate handler.

        Returns a complete routing decision in a single call.
        """
        context = context or {}

        # 1. Check conversational control FIRST (short-circuits everything)
        control_cmd = self._control_parser.parse(user_input)
        if control_cmd:
            return RouteDecision(
                intent=IntentType.CONVERSATIONAL_CONTROL,
                confidence=1.0,
                reason="Control command",
                keywords=[],
                original_message=user_input,
                is_control=True,
                control_command=control_cmd,
            )

        # 2. Classify intent using IntentClassifier
        classification = self._intent_classifier.classify(user_input, context)

        # 3. Check capability match for SYSTEM_STATUS and direct-answer intents
        if classification.intent in (IntentType.SYSTEM_STATUS, IntentType.QUESTION, IntentType.CHAT):
            cap_match = self._capability_router.find_matching(user_input, classification.intent.value)
            if cap_match:
                best_name, best_conf = cap_match[0]
                return RouteDecision(
                    intent=classification.intent,
                    confidence=max(classification.confidence, best_conf),
                    reason=f"Capability: {best_name}",
                    keywords=classification.keywords,
                    original_message=user_input,
                    is_direct_answer=True,
                    capability_name=best_name,
                    capability_confidence=best_conf,
                    should_include_runtime_context=classification.should_include_runtime_context,
                )

        # 4. Check clarification thresholds
        if classification.is_ambiguous or getattr(classification, 'should_clarify_engineering', False):
            return RouteDecision(
                intent=classification.intent,
                confidence=classification.confidence,
                reason=classification.reason,
                keywords=classification.keywords,
                original_message=user_input,
                is_clarification=True,
                should_include_runtime_context=classification.should_include_runtime_context,
            )

        # 5. Direct answer for non-engineering
        if classification.should_answer_directly:
            return RouteDecision(
                intent=classification.intent,
                confidence=classification.confidence,
                reason=classification.reason,
                keywords=classification.keywords,
                original_message=user_input,
                is_direct_answer=True,
                should_include_runtime_context=classification.should_include_runtime_context,
            )

        # 6. Engineering task - requires planning
        return RouteDecision(
            intent=classification.intent,
            confidence=classification.confidence,
            reason=classification.reason,
            keywords=classification.keywords,
            original_message=user_input,
            is_engineering=True,
            should_include_runtime_context=classification.should_include_runtime_context,
        )

    def execute_capability(self, capability_name: str, query: str, **context) -> Optional[CapabilityResult]:
        """Execute a specific capability by name."""
        try:
            return self._capability_router.route(query, intent_type=None, capability_name=capability_name, **context)
        except NoCapabilityError:
            return None

    def find_matching_capabilities(self, query: str, intent_type: Optional[str] = None) -> List[Tuple[str, float]]:
        """Find all capabilities matching a query."""
        return self._capability_router.find_matching(query, intent_type)

    def get_capabilities(self) -> List[str]:
        """Get list of registered capability names."""
        return self._capability_router.get_capabilities()

    def get_capability(self, name: str):
        """Get a capability by name."""
        return self._capability_router.get_capability(name)


# Global router instance for backward compatibility
_intent_router: Optional[IntentRouter] = None


def get_intent_router() -> IntentRouter:
    """Get the global IntentRouter instance."""
    global _intent_router
    if _intent_router is None:
        _intent_router = IntentRouter()
    return _intent_router


def route_intent(user_input: str, context: Optional[Dict[str, Any]] = None) -> RouteDecision:
    """Convenience function to route user input."""
    return get_intent_router().route(user_input, context)


# Backward compatibility exports - these delegate to the consolidated router
def is_task(message: str) -> bool:
    """Check if a message should trigger planning pipeline (delegates to IntentClassifier)."""
    from app.intent.classifier import classify_intent
    return classify_intent(message).should_plan


def should_answer_directly(message: str) -> bool:
    """Check if a message can be answered directly (delegates to IntentClassifier)."""
    from app.intent.classifier import classify_intent
    return classify_intent(message).should_answer_directly


def should_clarify_intent(message: str, context: Optional[Dict[str, Any]] = None) -> bool:
    """Check if a message needs clarification."""
    decision = route_intent(message, context)
    return decision.is_clarification


def is_control_intent(message: str) -> bool:
    """Check if a message is a control command."""
    decision = route_intent(message)
    return decision.is_control


def is_engineering_task(message: str, context: Optional[Dict[str, Any]] = None) -> bool:
    """Check if a message is an engineering task requiring planning."""
    decision = route_intent(message, context)
    return decision.is_engineering
