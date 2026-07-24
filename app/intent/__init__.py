"""Intent Classification Module.

This module provides intent classification for user messages to determine
the appropriate processing pipeline. Not all user messages should trigger
the full autonomous execution pipeline - simple chat and questions should
be answered directly.

Intent Types:
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
    IntentClassifier,
    IntentType,
    IntentClassification,
    classify_intent,
    is_task,
    should_answer_directly,
    should_include_runtime_context,
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

__all__ = [
    # Intent classification
    "IntentClassifier",
    "IntentType",
    "IntentClassification",
    "classify_intent",
    "is_task",
    "should_answer_directly",
    "should_include_runtime_context",
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
]
