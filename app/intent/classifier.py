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


class IntentType(Enum):
    """Intent types for user messages."""

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

    def __post_init__(self):
        self.should_plan = self.intent.requires_planning
        self.should_answer_directly = self.intent.can_answer_directly
        self.should_include_runtime_context = self.intent.is_engineering

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent.value,
            "confidence": self.confidence,
            "reason": self.reason,
            "keywords": self.keywords,
            "should_plan": self.should_plan,
            "should_answer_directly": self.should_answer_directly,
            "should_include_runtime_context": self.should_include_runtime_context,
        }

    def __repr__(self) -> str:
        return f"IntentClassification(intent={self.intent.value}, confidence={self.confidence:.2f}, reason='{self.reason[:50]}...')"


class IntentClassifier:
    """Classifies user messages into intent categories."""

    INTENT_KEYWORDS: Dict[IntentType, List[str]] = {
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
        ],
        IntentType.TOOL_REQUEST: [
            "run command", "execute command", "run script", "execute script",
            "bash", "shell", "terminal", "command", "execute",
            "run tests", "pytest", "lint", "format", "run", "script", "the tests", "run test",
        ],
        IntentType.GIT_OPERATION: [
            "git add", "git commit", "git push", "git pull", "git fetch",
            "git merge", "git rebase", "git status", "git checkout", "git branch",
            "commit", "push", "pull", "status",
        ],
    }

    INTENT_PATTERNS: Dict[IntentType, List[str]] = {
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
            r"^\s*what\s+(model|mode|version|provider|llm)\s+.*\?\s*$",
            r"^\s*(is|are|do|does|can|was|were|have)\s+(ollama|claude|gpt|the model|the llm|a model|an llm|backend|the backend|server|the server|internet|network|online)\s+.*\?\s*$",
            r"^\s*which\s+(model|version|provider|llm)\s+.*\?\s*$",
            r".*(are you there|are you connected|are you running|are you online).*\?",
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

    def classify(self, message: str) -> IntentClassification:
        """Classify a user message into an intent category.

        Args:
            message: The user message to classify.

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

        # Check for exact empty message after stripping
        if not message or not message_lower:
            return IntentClassification(
                intent=IntentType.CHAT,
                confidence=0.5,
                reason="Empty message",
            )

        # Score each intent type
        scores: Dict[IntentType, Tuple[float, List[str]]] = {}
        for intent in IntentType:
            score, keywords = self._score_intent(intent, message_lower)
            scores[intent] = (score, keywords)

        # Find the best match
        best_intent = max(scores.items(), key=lambda x: x[1][0])
        best_score, best_keywords = best_intent[1]
        best_intent_type = best_intent[0]

        # Build reason
        if best_score > 0.8:
            reason = f"High confidence match for {best_intent_type.value}"
        elif best_score > 0.5:
            reason = f"Moderate confidence match for {best_intent_type.value}"
        else:
            reason = f"Best guess: {best_intent_type.value}"

        if best_keywords:
            reason += f" (keywords: {', '.join(best_keywords[:3])})"

        logger.info("[Intent]")
        logger.info(best_intent_type.value)

        return IntentClassification(
            intent=best_intent_type,
            confidence=best_score,
            reason=reason,
            keywords=best_keywords,
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
                pattern_score = 0.96 if intent in (IntentType.SYSTEM_STATUS, IntentType.CODE_TASK) else 0.95
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

        # Special case: ends with ? is likely a question
        if intent == IntentType.QUESTION and message.strip().endswith("?"):
            score = max(score, 0.85)

        # Special case: system status queries
        if intent == IntentType.SYSTEM_STATUS:
            system_keywords = ["ollama", "claude", "gpt", "llm",
                "version", "provider", "backend", "running", "installed", "configured",
                "connected", "current model", "current version", "llm provider",
                "backend status", "model version", "provider version"]
            for kw in system_keywords:
                if kw in message:
                    keywords.append(kw)
                    score = min(score + 0.08, 1.0)

        return (score, keywords)

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


def classify_intent(message: str) -> IntentClassification:
    """Convenience function to classify a message.

    Args:
        message: The message to classify.

    Returns:
        IntentClassification result.
    """
    return classifier.classify(message)


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
