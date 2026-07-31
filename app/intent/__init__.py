"""Intent Classification Module.

This module provides intent classification for user messages to determine
the appropriate processing pipeline. Not all user messages should trigger
the full autonomous execution pipeline - simple chat and questions should
be answered directly.

Intent Types:
- CONVERSATIONAL_CONTROL: Meta-commands (stop / cancel / undo); short-circuits routing.
- CHAT: Casual conversation, greetings
- QUESTION: Asking about something (how, what, why, etc.)
- TASK: Request to perform a task/action
- FILE_OPERATION: File-specific operations (read, write, delete)
- CODE_TASK: Code-specific tasks (refactor, fix, implement)
- SYSTEM_STATUS: Questions about system state (connected, version, etc.)
- TOOL_REQUEST: Direct tool requests (run command, use tool)

Only TASK, FILE_OPERATION, CODE_TASK, and TOOL_REQUEST should enter the
planning and execution pipeline. Others should be answered directly via LLM.
"""

from app.intent.classifier import (
    ACCEPT_CONFIDENCE_THRESHOLD,
    LOW_CONFIDENCE_THRESHOLD,
    IntentClassifier,
    IntentType,
    IntentClassification,
    classify_intent,
    is_task,
    should_answer_directly,
    should_clarify,
    should_include_runtime_context,
    is_control_intent,
    is_low_confidence,
)
from app.intent.runtime_context import (
    RuntimeContext,
    get_runtime_context,
    set_runtime_context,
    reset_runtime_context,
)
from app.intent.json_utils import (
    JSONValidationError,
    JSONExtractionError,
    JSONValidationResult,
    JSONSchema,
    JSONValidator,
    validate_json,
    extract_json,
    ensure_json,
)
from app.intent.entity_extractor import (
    EntityType,
    ExtractedEntity,
    SlotFillingResult,
    EntityExtractor,
    extract_entities,
    fill_slots,
    get_missing_slots_prompt,
)
from app.intent.multi_intent import (
    SplitStrategy,
    DetectedIntent,
    MultiIntentResult,
    MultiIntentDetector,
    detect_multi_intent,
    get_planning_intents,
    get_direct_answer_intents,
)

__all__ = [
    # Intent classification
    "ACCEPT_CONFIDENCE_THRESHOLD",
    "LOW_CONFIDENCE_THRESHOLD",
    "IntentClassifier",
    "IntentType",
    "IntentClassification",
    "classify_intent",
    "is_task",
    "should_answer_directly",
    "should_clarify",
    "should_include_runtime_context",
    "is_control_intent",
    "is_low_confidence",
    # Runtime context
    "RuntimeContext",
    "get_runtime_context",
    "set_runtime_context",
    "reset_runtime_context",
    # JSON utilities
    "JSONValidationError",
    "JSONExtractionError",
    "JSONValidationResult",
    "JSONSchema",
    "JSONValidator",
    "validate_json",
    "extract_json",
    "ensure_json",
    # Entity extraction
    "EntityType",
    "ExtractedEntity",
    "SlotFillingResult",
    "EntityExtractor",
    "extract_entities",
    "fill_slots",
    "get_missing_slots_prompt",
    # Multi-intent detection
    "SplitStrategy",
    "DetectedIntent",
    "MultiIntentResult",
    "MultiIntentDetector",
    "detect_multi_intent",
    "get_planning_intents",
    "get_direct_answer_intents",
]
