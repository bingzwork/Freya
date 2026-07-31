"""Multi-Intent Detection.

Detects when a single user message contains multiple distinct intents
that should be handled as separate tasks.
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from app.intent.classifier import IntentClassifier, IntentType, classify_intent
from app.core.logger import logger


class SplitStrategy(Enum):
    """How to split a multi-intent message."""

    CONJUNCTION = "conjunction"  # Split by "and", "then", "also", ","
    SEMICOLON = "semicolon"  # Split by semicolons
    SENTENCE = "sentence"  # Split by sentence boundaries
    KEYWORD = "keyword"  # Split by task keywords


@dataclass
class DetectedIntent:
    """A single intent detected within a multi-intent message."""

    intent: IntentType
    text_segment: str
    start: int
    end: int
    confidence: float
    entities: List[Dict[str, Any]] = field(default_factory=list)
    strategy: SplitStrategy = SplitStrategy.CONJUNCTION
    order: int = 0

    @property
    def requires_planning(self) -> bool:
        return self.intent.requires_planning

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent.value,
            "text_segment": self.text_segment,
            "start": self.start,
            "end": self.end,
            "confidence": self.confidence,
            "entities": self.entities,
            "strategy": self.strategy.value,
            "order": self.order,
            "requires_planning": self.requires_planning,
        }


@dataclass
class MultiIntentResult:
    """Result of multi-intent detection."""

    original_message: str
    detected_intents: List[DetectedIntent]
    is_multi_intent: bool
    primary_intent: Optional[IntentType] = None
    execution_order: List[int] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_message": self.original_message,
            "detected_intents": [i.to_dict() for i in self.detected_intents],
            "is_multi_intent": self.is_multi_intent,
            "primary_intent": self.primary_intent.value if self.primary_intent else None,
            "execution_order": self.execution_order,
        }


class MultiIntentDetector:
    """Detects multiple intents in a single user message."""

    # Conjunctions that often separate intents
    CONJUNCTIONS = [
        r'\band\b',
        r'\bthen\b',
        r'\balso\b',
        r'\bplus\b',
        r'\badditionally\b',
        r'\bafter\s+that\b',
        r'\bnext\b',
        r'\bfollowed\s+by\b',
        r',\s*',  # commas
        r';\s*',  # semicolons
    ]

    # Task-starting keywords that indicate a new intent
    TASK_START_KEYWORDS = [
        "open", "read", "write", "create", "edit", "modify", "delete",
        "fix", "debug", "refactor", "implement", "add", "remove", "update",
        "run", "execute", "test", "build", "deploy", "commit", "push", "pull",
        "search", "find", "analyze", "review", "explain", "document",
        "schedule", "remind", "create", "make", "generate", "produce",
        "install", "configure", "setup", "migrate", "convert", "transform",
        "process", "optimize", "improve", "check", "inspect", "examine",
        "investigate", "locate", "discover", "identify",
    ]

    def __init__(self, classifier: Optional[IntentClassifier] = None):
        self.classifier = classifier or IntentClassifier()
        # Compile conjunction patterns
        self._conjunction_pattern = re.compile(
            '|'.join(f'({c})' for c in self.CONJUNCTIONS),
            re.IGNORECASE
        )
        # Compile task keyword pattern
        self._task_keyword_pattern = re.compile(
            r'\b(' + '|'.join(re.escape(kw) for kw in self.TASK_START_KEYWORDS) + r')\b',
            re.IGNORECASE
        )

    def detect(self, message: str, context: Optional[Dict[str, Any]] = None) -> MultiIntentResult:
        """Detect multiple intents in a message.

        Args:
            message: The user message to analyze.
            context: Optional context for classification.

        Returns:
            MultiIntentResult with detected intents and execution order.
        """
        if not message or not message.strip():
            return MultiIntentResult(
                original_message=message,
                detected_intents=[],
                is_multi_intent=False,
            )

        # First, try to split by strong delimiters
        segments = self._split_message(message)

        # If only one segment, check if it contains implicit multiple intents
        if len(segments) == 1:
            # Check for multiple task keywords in a single sentence
            segments = self._split_by_task_keywords(message)

        # Classify each segment
        detected = []
        for i, (segment, start, end, strategy) in enumerate(segments):
            classification = self.classifier.classify(segment, context)
            intent = DetectedIntent(
                intent=classification.intent,
                text_segment=segment,
                start=start,
                end=end,
                confidence=classification.confidence,
                strategy=strategy,
                order=i,
            )
            detected.append(intent)

        # Determine if multi-intent
        is_multi = len(detected) > 1

        # Determine primary intent (highest confidence planning intent)
        planning_intents = [d for d in detected if d.requires_planning]
        if planning_intents:
            primary = max(planning_intents, key=lambda d: d.confidence).intent
        elif detected:
            primary = max(detected, key=lambda d: d.confidence).intent
        else:
            primary = None

        # Determine execution order
        execution_order = self._determine_execution_order(detected)

        logger.info(f"[MultiIntent] Detected {len(detected)} intents in: '{message[:80]}...'")

        return MultiIntentResult(
            original_message=message,
            detected_intents=detected,
            is_multi_intent=is_multi,
            primary_intent=primary,
            execution_order=execution_order,
        )

    def _split_message(self, message: str) -> List[Tuple[str, int, int, SplitStrategy]]:
        """Split message by conjunctions and punctuation."""
        segments = []
        last_end = 0

        for match in self._conjunction_pattern.finditer(message):
            start = match.start()
            end = match.end()

            # Skip if this is at the very beginning
            if start == 0:
                continue

            # Extract segment before the conjunction
            segment = message[last_end:start].strip()
            if segment and len(segment) > 3:  # Minimum meaningful length
                # Determine strategy based on what delimiter was matched
                matched = match.group(0).lower()
                if ';' in matched:
                    strategy = SplitStrategy.SEMICOLON
                elif any(c in matched for c in ['and', 'then', 'also', 'plus', 'additionally', 'next', 'followed', 'after that']):
                    strategy = SplitStrategy.CONJUNCTION
                elif ',' in matched:
                    strategy = SplitStrategy.CONJUNCTION
                else:
                    strategy = SplitStrategy.CONJUNCTION
                segments.append((segment, last_end, start, strategy))

            last_end = end

        # Add final segment
        if last_end < len(message):
            segment = message[last_end:].strip()
            if segment and len(segment) > 3:
                segments.append((segment, last_end, len(message), SplitStrategy.CONJUNCTION))

        # If no splits found, return whole message
        if not segments:
            return [(message.strip(), 0, len(message), SplitStrategy.CONJUNCTION)]

        return segments

    def _split_by_task_keywords(self, message: str) -> List[Tuple[str, int, int, SplitStrategy]]:
        """Split a message by detecting multiple task keywords."""
        segments = []
        matches = list(self._task_keyword_pattern.finditer(message))

        if len(matches) <= 1:
            return [(message.strip(), 0, len(message), SplitStrategy.KEYWORD)]

        # Split at each task keyword
        last_pos = 0
        for i, match in enumerate(matches):
            keyword_pos = match.start()

            # If this is not the first keyword, create a segment
            if i > 0:
                segment = message[last_pos:keyword_pos].strip()
                if segment and len(segment) > 3:
                    segments.append((segment, last_pos, keyword_pos, SplitStrategy.KEYWORD))

            last_pos = keyword_pos

        # Add final segment
        if last_pos < len(message):
            segment = message[last_pos:].strip()
            if segment and len(segment) > 3:
                segments.append((segment, last_pos, len(message), SplitStrategy.KEYWORD))

        # If we got good segments, return them; otherwise return original
        if len(segments) >= 2:
            return segments

        return [(message.strip(), 0, len(message), SplitStrategy.KEYWORD)]

    def _identify_strategy(self, segment: str, full_message: str) -> SplitStrategy:
        """Identify which splitting strategy was used."""
        segment_lower = segment.lower()

        # Check for semicolon
        if ';' in segment:
            return SplitStrategy.SEMICOLON

        # Check for conjunctions at start of segment
        for conj in ['and', 'then', 'also', 'plus']:
            if segment_lower.startswith(conj + ' '):
                return SplitStrategy.CONJUNCTION

        # Check if segment starts with a task keyword
        if self._task_keyword_pattern.match(segment_lower):
            return SplitStrategy.KEYWORD

        # Check for sentence boundary
        if re.match(r'^[A-Z]', segment.strip()):
            return SplitStrategy.SENTENCE

        return SplitStrategy.CONJUNCTION

    def _determine_execution_order(self, intents: List[DetectedIntent]) -> List[int]:
        """Determine the order in which intents should be executed.

        Uses dependencies implied by the text order and intent types.
        Returns list of intent indices in execution order.
        """
        if not intents:
            return []

        # Simple strategy: execute in text order, but group by planning vs non-planning
        # Planning intents generally need to come first if they set up context
        order = list(range(len(intents)))

        # Check for explicit ordering keywords
        # "first X then Y" -> X before Y
        # "after X do Y" -> Y after X

        return order

    def get_planning_intents(self, result: MultiIntentResult) -> List[DetectedIntent]:
        """Get only the intents that require planning."""
        return [i for i in result.detected_intents if i.requires_planning]

    def get_direct_answer_intents(self, result: MultiIntentResult) -> List[DetectedIntent]:
        """Get intents that can be answered directly."""
        return [i for i in result.detected_intents if not i.requires_planning]

    def merge_with_classification(self, classification, message: str) -> MultiIntentResult:
        """Merge a single classification with multi-intent detection.

        If multi-intent detector finds multiple intents, use those.
        Otherwise, wrap the single classification in a MultiIntentResult.
        """
        result = self.detect(message)

        if result.is_multi_intent:
            return result

        # Single intent - wrap it
        intent = DetectedIntent(
            intent=classification.intent,
            text_segment=message,
            start=0,
            end=len(message),
            confidence=classification.confidence,
            order=0,
        )
        return MultiIntentResult(
            original_message=message,
            detected_intents=[intent],
            is_multi_intent=False,
            primary_intent=classification.intent,
            execution_order=[0],
        )


# Global detector instance
_detector = MultiIntentDetector()


def detect_multi_intent(message: str, context: Optional[Dict[str, Any]] = None) -> MultiIntentResult:
    """Convenience function to detect multiple intents."""
    return _detector.detect(message, context)


def get_planning_intents(result: MultiIntentResult) -> List[DetectedIntent]:
    """Get only the intents that require planning."""
    return _detector.get_planning_intents(result)


def get_direct_answer_intents(result: MultiIntentResult) -> List[DetectedIntent]:
    """Get intents that can be answered directly."""
    return _detector.get_direct_answer_intents(result)