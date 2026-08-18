"""Intent Classifier.

Classifies user messages into intent categories to determine the appropriate
processing pipeline. This prevents non-task messages from entering the full
autonomous execution pipeline.
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from app.core.logger import logger


# Routing confidence thresholds used by the implemented classifier.
ACCEPT_CONFIDENCE_THRESHOLD = 0.70
LOW_CONFIDENCE_THRESHOLD = 0.40

# Engineering intent ambiguity thresholds - lower thresholds for engineering tasks
# to prevent accidental planner execution
ENGINEERING_AMBIGUOUS_THRESHOLD = 0.60  # Lower than ACCEPT for engineering intents
ENGINEERING_CONFIDENT_THRESHOLD = 0.75  # Higher threshold for confident engineering execution


class IntentType(Enum):
    """Intent types for user messages."""

    # Meta-commands (stop / cancel / undo / status) - short-circuit all routing
    CONVERSATIONAL_CONTROL = "conversational_control"

    # Direct chat/conversation - answer immediately via LLM
    CHAT = "chat"

    # Questions about knowledge/concepts - answer immediately via LLM
    QUESTION = "question"

    # Requests to perform work - enter planning pipeline
    TASK = "task"

    # File-specific operations - enter planning pipeline
    FILE_OPERATION = "file_operation"

    # Code-specific tasks - enter planning pipeline
    CODE_TASK = "code_task"

    # System state questions - answer immediately via LLM
    SYSTEM_STATUS = "system_status"

    # Direct tool requests - enter planning pipeline
    TOOL_REQUEST = "tool_request"

    # Git-specific operations - enter planning pipeline
    GIT_OPERATION = "git_operation"

    @property
    def routing_priority(self) -> int:
        """Dispatch priority for routing (lower number = higher priority).

        Conversation Control short-circuits all other tiers. Direct Answer
        runs before the engineering pipeline. General Conversation is the
        last tier.
        """
        return {
            IntentType.CONVERSATIONAL_CONTROL: 0,
            IntentType.CHAT: 3,
            IntentType.QUESTION: 3,
            IntentType.SYSTEM_STATUS: 1,
            IntentType.TASK: 2,
            IntentType.FILE_OPERATION: 2,
            IntentType.CODE_TASK: 2,
            IntentType.TOOL_REQUEST: 2,
            IntentType.GIT_OPERATION: 2,
        }.get(self, 3)

    @property
    def requires_planning(self) -> bool:
        """Check if this intent requires the planning pipeline."""
        return self in {
            IntentType.TASK,
            IntentType.FILE_OPERATION,
            IntentType.CODE_TASK,
            IntentType.TOOL_REQUEST,
            IntentType.GIT_OPERATION,
        }

    @property
    def can_answer_directly(self) -> bool:
        """Check if this intent can be answered directly via LLM."""
        return self in {
            IntentType.CONVERSATIONAL_CONTROL,
            IntentType.CHAT,
            IntentType.QUESTION,
            IntentType.SYSTEM_STATUS,
        }

    @property
    def is_engineering(self) -> bool:
        """Check if this intent is related to software engineering tasks.

        Engineering intents should receive runtime context to help with
        generating appropriate commands for the current environment.
        """
        return self in {
            IntentType.TASK,
            IntentType.FILE_OPERATION,
            IntentType.CODE_TASK,
            IntentType.TOOL_REQUEST,
            IntentType.GIT_OPERATION,
        }

    @property
    def is_conversational_control(self) -> bool:
        """Check if this intent is a meta-command (stop / cancel / undo)."""
        return self is IntentType.CONVERSATIONAL_CONTROL

@dataclass
class IntentClassification:
    """Result of intent classification."""
    intent: IntentType
    confidence: float
    reason: str
    keywords: List[str] = field(default_factory=list)
    should_plan: bool = field(default=False)
    should_answer_directly: bool = field(default=False)
    should_include_runtime_context: bool = field(default=False)
    # Additional context for ambiguity detection
    original_message: str = field(default="", repr=False)
    context: Dict[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self):
        self.should_plan = self.intent.requires_planning
        self.should_answer_directly = self.intent.can_answer_directly
        self.should_include_runtime_context = self.intent.is_engineering

    @property
    def is_low_confidence(self) -> bool:
        """Confidence below the low-confidence threshold (defaults to chat)."""
        return self.confidence < LOW_CONFIDENCE_THRESHOLD

    @property
    def is_ambiguous(self) -> bool:
        """Confidence in the mid-band ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ask a clarifying question."""
        return LOW_CONFIDENCE_THRESHOLD <= self.confidence < ACCEPT_CONFIDENCE_THRESHOLD

    @property
    def is_engineering_ambiguous(self) -> bool:
        """Check if an engineering intent has ambiguous confidence.

        Engineering intents need higher confidence to proceed to planning
        to prevent accidental execution of unclear engineering tasks.
        """
        if not self.intent.is_engineering:
            return False
        return self.confidence < ENGINEERING_CONFIDENT_THRESHOLD

    @property
    def is_engineering_uncertain(self) -> bool:
        """Check if an engineering intent is in the uncertain zone.

        This is the zone where we should ask clarifying questions rather
        than either executing or falling back to chat.
        """
        if not self.intent.is_engineering:
            return False
        return ENGINEERING_AMBIGUOUS_THRESHOLD <= self.confidence < ENGINEERING_CONFIDENT_THRESHOLD

    @property
    def should_clarify_engineering(self) -> bool:
        """Whether to ask for clarification for an engineering intent.

        Returns True for engineering intents that are uncertain but not
        so low-confidence that they should fall back to general chat.
        """
        return self.is_engineering_uncertain

    @property
    def is_control(self) -> bool:
        """Conversational control intent ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â short-circuit all other routing."""
        return self.intent.is_conversational_control

    @property
    def request_kind(self) -> str:
        if self.is_control:
            return "system_control"
        if self.intent in {IntentType.CHAT, IntentType.QUESTION, IntentType.SYSTEM_STATUS}:
            return "conversation"
        if self.intent.is_engineering:
            return "action"
        return self.intent.value

    @property
    def action_required(self) -> bool:
        return self.intent.requires_planning

    @property
    def memory_required(self) -> bool:
        return self.intent in {IntentType.QUESTION, IntentType.SYSTEM_STATUS}

    @property
    def external_information_required(self) -> bool:
        return False

    @property
    def ambiguity(self) -> str:
        if self.is_low_confidence:
            return "insufficient_context"
        if self.is_ambiguous or self.should_clarify_engineering:
            return "ambiguous"
        return "confident"

    @property
    def extracted_arguments(self) -> Dict[str, Any]:
        return dict(self.context.get("entities") or {}) if isinstance(self.context, dict) else {}

    @property
    def context_requirements(self) -> List[str]:
        requirements = []
        if self.memory_required:
            requirements.append("conversation_or_memory_context")
        if self.action_required:
            requirements.append("execution_context")
        return requirements

    @property
    def risk_hint(self) -> str:
        if self.intent.is_engineering:
            return "action_requires_safety_evaluation"
        if self.is_control:
            return "control"
        return "low"

    def to_contract(self) -> Dict[str, Any]:
        """Return the stable interpretation used by downstream foundation layers."""
        return {
            "intent": self.intent.value,
            "request_kind": self.request_kind,
            "action_required": self.action_required,
            "memory_required": self.memory_required,
            "external_information_required": self.external_information_required,
            "confidence": self.confidence,
            "ambiguity": self.ambiguity,
            "extracted_arguments": self.extracted_arguments,
            "context_requirements": self.context_requirements,
            "risk_hint": self.risk_hint,
            "reason": self.reason,
            "keywords": list(self.keywords),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            **self.to_contract(),
            "should_plan": self.should_plan,
            "should_answer_directly": self.should_answer_directly,
            "should_include_runtime_context": self.should_include_runtime_context,
            "is_low_confidence": self.is_low_confidence,
            "is_ambiguous": self.is_ambiguous,
            "is_engineering_ambiguous": self.is_engineering_ambiguous,
            "is_engineering_uncertain": self.is_engineering_uncertain,
            "should_clarify_engineering": self.should_clarify_engineering,
            "is_control": self.is_control,
        }

    def __repr__(self) -> str:
        return f"IntentClassification(intent={self.intent.value}, confidence={self.confidence:.2f}, reason='{self.reason[:50]}...')"


class IntentClassifier:
    """Classifies user messages into intent categories."""

    INTENT_KEYWORDS: Dict[IntentType, List[str]] = {
        IntentType.CONVERSATIONAL_CONTROL: [
            "stop", "halt", "wait", "cancel", "nevermind", "abort",
            "undo", "revert", "redo",
            "what are you doing", "current plan", "current step",
        ],
        IntentType.CHAT: [
            "hello", "hi", "hey", "good morning", "good afternoon", "good evening",
            "how are you", "what's up", "thanks", "thank you", "bye", "goodbye",
            "yo", "greetings", "nice to meet you", "howdy",
        ],
        IntentType.QUESTION: [
            "what is", "what are", "what was", "what were", "what will",
            "what would", "what can", "what does", "what do", "what did",
            "how is", "how are", "how was", "how were", "how do", "how does",
            "how did", "how can", "how could", "how would", "how to",
            "why is", "why are", "why was", "why were", "why do", "why does",
            "why did", "explain", "tell me", "describe", "what means",
            "who is", "who are", "when is", "when was", "where is", "where are",
            "which is", "which are", "can you explain", "could you explain",
        ],
        IntentType.TASK: [
            "build", "create", "make", "generate", "produce", "develop",
            "write", "implement", "add", "remove", "delete", "move", "copy",
            "rename", "organize", "structure", "setup", "configure", "install",
            "update", "upgrade", "migrate", "transform", "convert",
            "process", "analyze", "audit", "review", "optimize", "improve",
            "fix", "solve", "resolve", "debug", "test", "verify", "validate",
            "check", "inspect", "examine", "investigate", "find", "locate",
            "search", "discover", "identify", "fix bug", "fix error",
        ],
        IntentType.FILE_OPERATION: [
            "read file", "open file", "view file", "show file", "display file",
            "write file", "save file", "create file", "make file", "new file",
            "edit file", "modify file", "change file", "update file",
            "delete file", "remove file", "rename file", "move file", "copy file",
        ],
        IntentType.CODE_TASK: [
            "refactor", "rewrite code", "fix bug", "implement", "code review",
            "analyze code", "explain code", "document code",
            "add feature", "extend", "modify code", "change code",
            "test code", "write test", "debug code",
        ],
        IntentType.SYSTEM_STATUS: [
            "are you connected", "are you running", "are you loaded", "are you online",
            "are you available", "connected to", "running ollama", "running claude",
            "running gpt", "ollama running", "claude running", "gpt running",
            "current model", "current provider", "current mode", "current version",
            "llm provider", "backend status", "model version", "provider version",
            "what model", "what mode", "which model", "which provider", "which llm",
            "is ollama", "is claude", "is gpt", "are you installed", "are you configured",
            "are you there",
            # Follow-up keywords for system status context
            "specific model", "which variant", "which version", "model variant",
            "parameters", "param count", "param", "b model", "8b", "7b", "13b", "70b",
            "is that", "is it the", "which one", "what version", "model version",
            "provider", "llm", "ollama", "still using", "currently using", "running on",
            "ai model", "ollama model", "what provider", "which provider",
            # Version query keywords
            "what is your version", "what's your version", "whats your version",
            "your version", "model version", "which version",
            # Model query keywords
            "what is your model", "what's your model", "whats your model",
            "your model", "what model", "which model", "current model",
        ],
        IntentType.TOOL_REQUEST: [
            "run command", "execute command", "run script", "execute script",
            "bash", "shell", "terminal", "command", "execute",
            "run tests", "run the tests", "pytest", "lint", "format",
        ],
        IntentType.GIT_OPERATION: [
            "git add", "git commit", "git push", "git pull", "git fetch",
            "git merge", "git rebase", "git status", "git checkout", "git branch",
            "commit", "push", "pull", "status",
        ],
    }

    INTENT_PATTERNS: Dict[IntentType, List[str]] = {
        IntentType.CONVERSATIONAL_CONTROL: [
            r"^\s*(stop|halt|wait)\s*[!.]?\s*$",
            r"^\s*(cancel|nevermind|abort)\s*[!.]?\s*$",
            r"^\s*(undo|revert|redo)\s*[!.]?\s*$",
            r"^\s*what\s+are\s+you\s+doing\s*\?\s*$",
            r"^\s*(status|current\s+plan|current\s+step)\s*[!.]?\s*$",
        ],
        IntentType.CHAT: [
            r"^\s*(hello|hi|hey|yo|howdy|greetings)\s*[!.]?\s*$",
            r"^\s*(good\s+(morning|afternoon|evening)|bye|goodbye)\s*[!.]?\s*$",
            r"^\s*(thanks|thank you|cheers)\s*[!.]?\s*$",
        ],
        IntentType.QUESTION: [
            r"^\s*(what|how|why|who|when|where|which)\s+.*\?\s*$",
 r"^\s*(explain|tell me|describe)\s+.*\?\s*$",
            r"\bmean\b.*\?",
        ],
        IntentType.SYSTEM_STATUS: [
            r"^\s*(are you|are we|can you|do you|is it|was it|have you)\s+(connected|running|loaded|installed|available|online|access|connected to|there)\s*(\w+\s*)*\?\s*$",
            r"^\s*what\s+(model|mode|version|provider|llm)\s*[.?]*\s*$",
            r"^\s*(is|are|do|does|can|was|were|have)\s+(ollama|claude|gpt|the model|the llm|a model|an llm|backend|the backend|server|the server|internet|network|online)\s+.*\?\s*$",
            r"^\s*which\s+(model|version|provider|llm)\s*[.?]*\s*$",
            r".*(are you there|are you connected|are you running|are you online).*\?",
            # Follow-up patterns for system status context
            r"^\s*(what|which)\s+(specific|exact|particular)\s+(model|version|variant|provider|llm)\s*\?*\s*$",
            r"^\s*(what|which)\s+(specific|exact|particular)\s+\w+\s+(model|version|variant)\s*\?*\s*$",
            r"^\s*is\s+(that|it|the\s+model|the\s+llm)\s+(the\s+)?(8b|7b|13b|70b|32b|1b)(\s+version)?\s*\?*\s*$",
            r"^\s*(how\s+many\s+)?(parameters?|params?)\s*\?*\s*$",
            r"^\s*(how\s+many\s+)?(parameters?|params?)\s*(does\s+it\s+have|is\s+it)\s*\?*\s*$",
            r"^\s*which\s+(variant|version|model)\s*\?*\s*$",
            r"^\s*(what\s+)?version\s*\?*\s*$",
            r"^\s*still\s+(using|running|on)\s+.*\?*\s*$",
            r"^\s*(are|is)\s+you\s+(still\s+)?(using|running|on)\s+.*\?*\s*$",
            r"^\s*current\s+(model|version|provider|llm)\s*\?*\s*$",
            r"^\s*(whats?|what\s+is)\s+the\s+(model|version)\s*\?*\s*$",
            r"^\s*what\s+(model|version|provider|llm)\s+(am\s+i|are\s+you|do\s+i|is\s+it)\s+(using|on)\s*\?*\s*$",
            # Additional patterns for common queries
            r"^\s*what\s+(ai\s+)?model\s+(are\s+you|am\s+i)\s+(using|on)\s*\?*\s*$",
            r"^\s*(ollama|gemini|claude|gpt|openai)\s+model\s*\?*\s*$",
            r"^\s*what\s+(model|llm)\s+from\s+(ollama|openai|anthropic|google)\s*\?*\s*$",
            # Model identity queries - "what model are you", "which model are you"
            r"^\s*(what|which)\s+(ai\s+)?model\s+(are\s+you|am\s+i)\??\s*$",
            r"^\s*(what|which)\s+llm\s+(are\s+you|am\s+i)\??\s*$",
            # Model status queries - catch "which model is loaded", "what model is loaded"
            r"^\s*(what|which)\s+model\s+(is\s+|are\s+you\s+)?loaded\??\s*$",
            r"^\s*(what|which)\s+model\s+(is\s+|are\s+you\s+)?running\??\s*$",
            r"^\s*model\s+(loaded|running)\??\s*$",
            r"^\s*(what|which)\s+model\??\s*$",
            # Version queries - "what version are you", "what's your version"
            r"^\s*(what|whats|what's)\s+(version|your version)\??\s*$",
            r"^\s*(what|which)\s+version\s+(are\s+you|am\s+i)\s+(running|using|on)\s*\?*\s*$",
            r"^\s*(what|which)\s+version\s+(are\s+you|am\s+i)\??\s*$",
            r"^\s*(what|whats|what's)\s+your\s+version\??\s*$",
            r"^\s*what\s+is\s+your\s+version\??\s*$",
            r"^\s*what\s+is\s+your\s+version\??\s*$",  # duplicate for emphasis
            # Specific patterns for "what is your version" and similar
            r"^\s*what\s+is\s+your\s+(version|model|llm)\??\s*$",
            r"^\s*(whats|what's)\s+is\s+your\s+(version|model|llm)\??\s*$",
            r"^\s*what\s+is\s+the\s+(version|model|llm)\s+of\s+you\??\s*$",
        ],
        IntentType.FILE_OPERATION: [
            r"^\s*(read|open|view|show|display|write|save|create|edit|modify|delete|remove|rename|move|copy)\s+.*\.(py|txt|md|json|yaml|yml|\w+)\s*$",
            r"^\s*(read|open|view|show|display|write|save|create|edit|modify|delete|remove|rename|move|copy)\s+.*(file|document|config|text)\s*[\s\w]*$",
            r"\.(py|txt|md|json|yaml|yml)\s*$",
        ],
        IntentType.CODE_TASK: [
            r"^\s*(refactor|rewrite|fix|implement|add|modify|change|debug|test|analyze|review|explain|document)\s+.*(code|function|class|module|\.py|\.js|\.ts|\.java|bug in \w+\.\w+|feature|algorithm|library)\s*[\s\w]*$",
            r"^\s*explain\s+.*(code|function|class|module)\s*[\s\w]*$",
            r"^\s*(fix bug|debug code|analyze code|review code)\s+.*$",
        ],
    }

    def __init__(self):
        self._compiled_patterns = self._compile_patterns()

    def _compile_patterns(self) -> Dict[IntentType, List[re.Pattern]]:
        """Compile regex patterns for efficiency."""
        compiled = {}
        for intent, patterns in self.INTENT_PATTERNS.items():
            compiled[intent] = [re.compile(p, re.IGNORECASE) for p in patterns]
        return compiled

    def classify(self, message: str, context: Optional[Dict[str, Any]] = None) -> IntentClassification:
        """Classify a user message into an intent category.

        Args:
            message: The user message to classify.
            context: Optional context dictionary with keys like 'last_intent', 'last_user_message'.

        Returns:
            IntentClassification with the detected intent and confidence.
        """
        if not isinstance(message, str):
            return IntentClassification(
                intent=IntentType.QUESTION,
                confidence=0.5,
                reason="Invalid message",
            )

        message_lower = message.lower().strip()

        # Explicit public-web lookups are informational, not engineering tasks.
        web_search_markers = ("search the web", "search online", "look up online", "research online", "find online")
        if any(marker in message_lower for marker in web_search_markers):
            return IntentClassification(intent=IntentType.QUESTION, confidence=0.95, reason="Explicit web-search request", keywords=["web_search"], original_message=message, context=context or {})


        # Check for exact empty message after stripping
        if not message or not message_lower:
            return IntentClassification(
                intent=IntentType.CHAT,
                confidence=0.5,
                reason="Empty message",
            )

        # Check for follow-up system status questions
        if context and context.get('last_intent') == IntentType.SYSTEM_STATUS.value:
            # Check if this looks like a follow-up question about the system status
            follow_up_patterns = [
                r"what specific",
                r"which.*b\b",
                r"how many (parameters|params)",
                r"is that the",
                r"which variant",
                r"what version",
                r"still (using|running|on)",
            ]
            for pattern in follow_up_patterns:
                if re.search(pattern, message_lower, re.IGNORECASE):
                    # Boost SYSTEM_STATUS score for follow-ups
                    break

        # Score each intent type
        scores: Dict[IntentType, Tuple[float, List[str]]] = {}
        for intent in IntentType:
            score, keywords = self._score_intent(intent, message_lower)
            scores[intent] = (score, keywords)


        # A concrete local file request is an engineering operation even
        # when a follow-up phrase such as "tell me what it contains" looks
        # like a general question. Keep this narrow: require both an explicit
        # file action and a recognizable filename/path.
        file_action = re.search(
            r"\b(read|open|view|show|display|write|save|create|edit|modify|change|update|delete|remove|rename|move|copy)\b",
            message_lower,
        )
        has_file_path = bool(
            re.search(r"(?:[a-z]:[\\/]|file:///)[^?\n]+\.[a-z0-9]{1,10}\b", message_lower)
            or re.search(r"\b[\w.-]+\.(?:txt|md|json|yaml|yml|csv|toml|ini|cfg|py|js|ts|tsx|jsx|html|css|xml|pdf|docx|xlsx)\b", message_lower)
        )
        if file_action and has_file_path:
            current_score, current_keywords = scores[IntentType.FILE_OPERATION]
            scores[IntentType.FILE_OPERATION] = (
                max(current_score, 0.99),
                current_keywords + ["file_action", "file_path"],
            )
        # Apply follow-up boost after scoring
        if context and context.get('last_intent') == IntentType.SYSTEM_STATUS.value:
            # Check for follow-up indicators and boost SYSTEM_STATUS
            follow_up_indicators = [
                "what specific", "which", "how many", "is that", "which variant",
                "what version", "still using", "still running", "still on",
                "parameters", "params", "8b", "7b", "13b", "70b", "32b", "1b",
            ]
            if any(indicator in message_lower for indicator in follow_up_indicators):
                current_score, current_keywords = scores[IntentType.SYSTEM_STATUS]
                scores[IntentType.SYSTEM_STATUS] = (min(current_score + 0.4, 1.0), current_keywords + ["follow-up"])

        # Find the best match
        # Prefer SYSTEM_STATUS over QUESTION on ties (secondary key: prefer higher priority intent)
        def score_key(item):
            intent_type, (score, keywords) = item
            # Primary: score (higher wins)
            # Secondary: routing priority (lower number = higher priority wins)
            return (score, -intent_type.routing_priority)

        best_intent = max(scores.items(), key=score_key)
        best_score, best_keywords = best_intent[1]
        best_intent_type = best_intent[0]

        # No-signal fallback: when no pattern or keyword matched any intent,
        # default to CHAT (the General Conversation tier). Confidence stays
        # low so callers see `is_low_confidence=True` and can choose an
        # appropriate general-conversation response.
        if best_score == 0.0:
            best_intent_type = IntentType.CHAT
            best_keywords = []

        # Build reason
        if best_score > 0.8:
            reason = f"High confidence match for {best_intent_type.value}"
        elif best_score > 0.5:
            reason = f"Moderate confidence match for {best_intent_type.value}"
        else:
            reason = f"Best guess: {best_intent_type.value}"

        if best_keywords:
            reason += f" (keywords: {', '.join(best_keywords[:3])})"

        return IntentClassification(
            intent=best_intent_type,
            confidence=best_score,
            reason=reason,
            keywords=best_keywords,
            original_message=message,
            context=context or {},
        )

    def _score_intent(self, intent: IntentType, message: str) -> Tuple[float, List[str]]:
        """Score a message for a specific intent type.

        Args:
            intent: The intent type to score against.
            message: The message to score.

        Returns:
            Tuple of (score, keywords) where score is 0.0 to 1.0.
        """
        score = 0.0
        keywords: List[str] = []

        # Check patterns first (high confidence)
        for pattern in self._compiled_patterns.get(intent, []):
            if pattern.match(message):
                # SYSTEM_STATUS and CODE_TASK get a slight priority boost to win ties with QUESTION
                # CONVERSATIONAL_CONTROL gets the highest priority to short-circuit all other routing
                if intent is IntentType.CONVERSATIONAL_CONTROL:
                    pattern_score = 0.99
                elif intent is IntentType.SYSTEM_STATUS:
                    pattern_score = 0.98
                elif intent is IntentType.CODE_TASK:
                    pattern_score = 0.97
                else:
                    pattern_score = 0.95
                score = max(score, pattern_score)
                break

        # Check keywords
        for keyword in self.INTENT_KEYWORDS.get(intent, []):
            if keyword in message:
                keywords.append(keyword)
                # Add score based on keyword match
                keyword_score = 0.1 * (1 + len(keyword) / 10)  # Longer keywords = more specific
                # Don't cap below pattern match scores
                score = min(score + keyword_score, 1.0)

        # Boost engineering intent base scores to make ambiguity zone reachable
        # Without this, keyword-only matches for engineering intents are too low
        if intent in (IntentType.TASK, IntentType.FILE_OPERATION, IntentType.CODE_TASK, IntentType.TOOL_REQUEST, IntentType.GIT_OPERATION):
            # Don't boost if message contains question-type keywords
            # that indicate a query rather than a task
            question_keywords_in_message = any(kw in message for kw in [
                "explain", "tell me", "describe", "what is", "what are", "how to", "how do",
                "why is", "why are", "can you", "could you", "would you", "what means",
                "who is", "when is", "where is", "which is"
            ])
            if not question_keywords_in_message and score > 0 and score < 0.6:
                # Boost base score for engineering intents that have keywords but no pattern match
                score = min(score * 2.0, 0.60)

        # Special case: ends with ? is likely a question
        if intent == IntentType.QUESTION and message.strip().endswith("?"):
            score = max(score, 0.85)

        # Special case: system status queries
        if intent == IntentType.SYSTEM_STATUS:
            system_keywords = ["ollama", "claude", "gpt", "llm",
                "version", "provider", "backend", "running", "installed", "configured",
                "connected", "current model", "current version", "llm provider",
                "backend status", "model version", "provider version",
                "your version", "my version"]
            for kw in system_keywords:
                if kw in message:
                    keywords.append(kw)
                    score = min(score + 0.08, 1.0)

        # Engineering intent ambiguity detection
        # Reduce confidence for vague/ambiguous engineering requests
        if intent in (IntentType.TASK, IntentType.FILE_OPERATION, IntentType.CODE_TASK, IntentType.TOOL_REQUEST, IntentType.GIT_OPERATION):
            score = self._adjust_engineering_confidence(intent, message, score, keywords)

        return (score, keywords)

    def _adjust_engineering_confidence(self, intent: IntentType, message: str, base_score: float, keywords: List[str]) -> float:
        """Adjust confidence for engineering intents based on request clarity.

        This reduces confidence for vague engineering requests that lack
        specific details (file paths, code, error messages, etc.).
        """
        adjusted_score = base_score

        # Check for specific indicators that make an engineering request clear
        has_file_path = bool(re.search(r'\b\w+\.(py|js|ts|jsx|tsx|java|cpp|cc|c|h|rs|go|rb|php|cs|kt|swift|scala|r|m|pl|sh|bash|zsh|fish|ps1|bat|cmd|dockerfile|makefile|cmake|gradle|xml|json|yaml|yml|toml|ini|cfg|conf|md|txt|html|css|scss|sass|less|vue|svelte)\b', message))
        has_code_block = '```' in message
        has_colon_action = ':' in message and len(message.split(':', 1)[-1].strip()) >= 10
        has_error_traceback = bool(re.search(r'(traceback|error|exception|fail):', message, re.IGNORECASE))
        has_specific_action = bool(re.search(r'\b(fix|debug|review|explain|optimize|refactor|implement|create|build|test|delete|clean|modify|change|edit|upgrade|add|remove)\b.*\b(to|for|by)\b', message, re.IGNORECASE))

        # Git operations typically don't need additional context
        if intent == IntentType.GIT_OPERATION:
            return adjusted_score

        # Tool requests like "run pytest" are typically self-contained
        if intent == IntentType.TOOL_REQUEST:
            if any(kw in message for kw in ["pytest", "test", "lint", "format", "build", "run"]):
                return adjusted_score

        # FILE_OPERATION needs a target file for most actions
        if intent == IntentType.FILE_OPERATION:
            if not has_file_path and not has_colon_action:
                # Vague file operation - reduce confidence to engineering ambiguous zone
                adjusted_score = min(adjusted_score, 0.65)

        # CODE_TASK needs code, file path, or traceback
        elif intent == IntentType.CODE_TASK:
            if not has_file_path and not has_code_block and not has_error_traceback and not has_specific_action:
                # Vague code task - reduce confidence to engineering ambiguous zone
                adjusted_score = min(adjusted_score, 0.60)

        # General TASK needs specific action + context
        elif intent == IntentType.TASK:
            fix_debug_keywords = ['fix', 'debug', 'review', 'explain', 'optimize', 'refactor', 'analyze', 'update', 'upgrade', 'modify', 'change', 'edit']
            if any(kw in message for kw in fix_debug_keywords):
                # These need code, file, or error context with SPECIFIC ACTION
                if not has_code_block and not has_error_traceback and not has_colon_action and not has_specific_action and not has_file_path:
                    # Vague fix/debug/review request - reduce confidence to engineering ambiguous zone
                    adjusted_score = min(adjusted_score, 0.55)
            else:
                # Other TASK intents without specific context
                if not has_file_path and not has_colon_action and not has_specific_action:
                    adjusted_score = min(adjusted_score, 0.60)

        return adjusted_score

    def is_task(self, message: str) -> bool:
        """Check if a message should trigger the planning pipeline.

        Args:
            message: The user message to check.

        Returns:
            True if the message requires planning, False otherwise.
        """
        classification = self.classify(message)
        return classification.should_plan

    def should_answer_directly(self, message: str) -> bool:
        """Check if a message can be answered directly via LLM.

        Args:
            message: The user message to check.

        Returns:
            True if the message can be answered directly.
        """
        classification = self.classify(message)
        return classification.should_answer_directly


# Global classifier instance
classifier = IntentClassifier()


def classify_intent(message: str, context: Optional[Dict[str, Any]] = None) -> IntentClassification:
    """Convenience function to classify a message.

    Args:
        message: The message to classify.
        context: Optional context dictionary with keys like 'last_intent', 'last_user_message'.

    Returns:
        IntentClassification result.
    """
    return classifier.classify(message, context)


def is_task(message: str) -> bool:
    """Convenience function to check if a message is a task.

    Args:
        message: The message to check.

    Returns:
        True if the message is a task.
    """
    return classifier.is_task(message)


def should_answer_directly(message: str) -> bool:
    """Convenience function to check if a message should be answered directly.

    Args:
        message: The message to check.

    Returns:
        True if the message should be answered directly.
    """
    return classifier.should_answer_directly(message)


def should_include_runtime_context(message: str) -> bool:
    """Convenience function to check if runtime context should be included.

    Runtime context (OS, shell, Python version, working directory, etc.) is
    only included for engineering-related tasks where it helps generate
    appropriate commands.

    Args:
        message: The message to check.

    Returns:
        True if runtime context should be included for this message.
    """
    return classifier.classify(message).should_include_runtime_context


def should_clarify(classification: IntentClassification) -> bool:
    """Return True when a clarifying question should be asked instead of acting on the intent.

    This includes:
    - General ambiguous confidence (mid-band)
    - Engineering-specific uncertain confidence (engineering intents with
      insufficient clarity for planning)
    """
    return classification.is_ambiguous or classification.should_clarify_engineering


def is_low_confidence(classification: IntentClassification) -> bool:
    """Return True when confidence is below the low-confidence threshold.

    The caller should default to General Conversation and add a low-confidence
    signal to the LLM prompt.
    """
    return classification.is_low_confidence


def is_control_intent(classification: IntentClassification) -> bool:
    """Return True when the classification is a conversational control command."""
    return classification.is_control


def is_engineering_uncertain(classification: IntentClassification) -> bool:
    """Return True when an engineering intent has uncertain confidence.

    These should trigger clarification rather than execution or fallback to chat.
    """
    return classification.is_engineering_uncertain


def should_clarify_engineering(classification: IntentClassification) -> bool:
    """Return True when an engineering intent should trigger clarification.

    This is specifically for engineering intents that are uncertain but not
    low-confidence enough to fall back to general chat.
    """
    return classification.should_clarify_engineering
