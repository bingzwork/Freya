"""Plain English Response Enforcement.

This module provides utilities to enforce plain English responses across
all user-facing outputs. It detects and replaces technical jargon with
user-friendly alternatives.
"""

import re
from typing import Any, Dict, List, Optional, Set

from app.core.logger import logger


# Technical terms that should be replaced with plain English equivalents
JARGON_REPLACEMENTS: Dict[str, str] = {
    # Routing / Classification
    "intent classification": "understanding what you're asking",
    "intent classifier": "my understanding",
    "routing decision": "how I'm handling this",
    "capability routing": "how I'm handling this",
    "direct answer routing": "answering directly",
    "engineering planner": "planning your request",
    "planning pipeline": "planning your request",
    "execution pipeline": "working on your request",
    "should_plan": "needs planning",
    "should_answer_directly": "can be answered directly",
    "runtime context": "context about your environment",
    "confidence score": "how sure I am",
    "low confidence": "not completely sure",
    "high confidence": "very sure",

    # System / Architecture
    "capability": "function",
    "handler": "function",
    "handler": "function",
    "dispatcher": "system",
    "short-circuit": "handle directly",
    "pipeline": "process",
    "runtime": "system",
    "agent core": "core system",
    "core agent": "core system",

    # LLM / Model
    "llm": "AI model",
    "llms": "AI models",
    "large language model": "AI model",
    "model invocation": "calling the model",
    "prompt engineering": "crafting the prompt",
    "context window": "memory",
    "token": "text unit",
    "tokens": "text units",

    # Technical operations
    "subprocess": "command",
    "child process": "command",
    "execute": "run",
    "execution": "running",
    "invocation": "call",
    "instantiate": "create",
    "initialization": "setup",
    "deserialize": "load",
    "serialize": "save",
    "persist": "save",
    "persistence": "saving",
    "atomic write": "safe save",
    "lock": "safeguard",
    "thread-safe": "safe for concurrent use",

    # Memory / Storage
    "long-term memory": "memory",
    "episodic memory": "conversation history",
    "semantic memory": "knowledge base",
    "working memory": "current context",
    "consolidation": "organizing memories",
    "forgetting": "clearing old information",
    "retrieval": "recall",
    "embedding": "representation",
    "vector": "representation",

    # Error / Debug
    "error": "problem",
    "exception": "problem",
    "traceback": "details",
    "stack trace": "details",
    "debug": "details",
    "debug info": "details",
    "log": "record",
    "logging": "recording",

    # Control flow
    "control command": "your command",
    "control intent": "your command",
    "conversational control": "your command",
    "is_control": "is a command",
    "cancellation": "cancelling",
    "undo": "undo",

    # Git / Version control
    "git operation": "git task",
    "git status": "repository status",
    "commit hash": "commit ID",

    # File operations
    "file operation": "file task",
    "path resolution": "finding the file",

    # Configuration
    "configuration": "settings",
    "config": "settings",
    "parameter": "setting",
    "argument": "input",
    "default": "standard",

    # General
    "implementation": "how it works",
    "architecture": "structure",
    "internal": "internal",
    "metadata": "details",
    "schema": "format",
    "validation": "checking",
    "sanitization": "cleaning",
    "normalization": "standardizing",
    "deduplication": "removing duplicates",
}


# Internal field names that should never leak to users
FORBIDDEN_INTERNAL_FIELDS: Set[str] = {
    "control_command",
    "execution_plan",
    "plan_id",
    "step_number",
    "capability_name",
    "capability_result",
    "intent_type",
    "intent_classification",
    "confidence",
    "classification",
    "routing_priority",
    "should_plan",
    "should_answer_directly",
    "should_include_runtime_context",
    "is_low_confidence",
    "is_ambiguous",
    "is_control",
    "requires_planning",
    "can_answer_directly",
    "is_engineering",
    "is_conversational_control",
    "keywords",
    "reason",
    "debug",
    "debug_info",
    "debug_mode",
    "runtime_context",
    "handler_name",
    "router",
    "dispatcher",
    "pipeline",
    "task_id",
    "step_id",
    "tool_call",
    "tool_result",
    "tool_output",
    "llm_response",
    "llm_call",
    "prompt",
    "completion",
    "provider",
    "temperature",
    "max_tokens",
    "system_prompt",
    "user_prompt",
    "conversation_history",
    "memory_retrieval",
    "retrieval_query",
    "retrieval_result",
    "vector_search",
    "similarity_score",
    "chunk",
    "document",
    "index",
    "namespace",
    "collection",
}


def detect_jargon(text: str) -> List[str]:
    """Detect technical jargon in text.

    Args:
        text: Text to analyze.

    Returns:
        List of jargon terms found.
    """
    found = []
    text_lower = text.lower()
    for jargon in JARGON_REPLACEMENTS:
        if jargon in text_lower:
            found.append(jargon)
    return found


def detect_forbidden_fields(text: str) -> List[str]:
    """Detect forbidden internal field names in text.

    Args:
        text: Text to analyze.

    Returns:
        List of forbidden fields found.
    """
    found = []
    for field in FORBIDDEN_INTERNAL_FIELDS:
        if field in text:
            found.append(field)
    return found


def to_plain_english(text: str, aggressive: bool = True) -> str:
    """Convert technical text to plain English.

    Args:
        text: Text to convert.
        aggressive: If True, replace all known jargon. If False, only replace
                   the most common/objectionable terms.

    Returns:
        Plain English version of the text.
    """
    if not text:
        return text

    result = text

    # First, replace jargon with plain English
    if aggressive:
        # Sort by length (longest first) to avoid partial replacements
        sorted_jargon = sorted(JARGON_REPLACEMENTS.items(), key=lambda x: -len(x[0]))
        for jargon, plain in sorted_jargon:
            # Case-insensitive replacement, preserving word boundaries where possible
            pattern = re.compile(re.escape(jargon), re.IGNORECASE)
            result = pattern.sub(plain, result)
    else:
        # Less aggressive: only replace the most objectionable terms
        objectionable = {
            "intent classification": "understanding what you're asking",
            "routing decision": "how I'm handling this",
            "engineering planner": "planning your request",
            "control_command": "[your command]",
            "capability": "function",
            "handler": "function",
            "pipeline": "process",
            "llm": "AI model",
            "subprocess": "command",
            "exception": "problem",
            "traceback": "details",
        }
        for jargon, plain in objectionable.items():
            pattern = re.compile(re.escape(jargon), re.IGNORECASE)
            result = pattern.sub(plain, result)

    # Then, hide forbidden internal field names
    for field in FORBIDDEN_INTERNAL_FIELDS:
        # Match field names in various formats: field_name, "field_name", field_name=value
        patterns = [
            rf'\b{re.escape(field)}\b',
            rf'"{re.escape(field)}"',
            rf"'{re.escape(field)}'",
            rf'{re.escape(field)}=',
            rf'{re.escape(field)}:',
        ]
        for pattern in patterns:
            result = re.sub(pattern, '[internal]', result)

    return result


def enforce_plain_english(response: str, debug_mode: bool = False) -> str:
    """Enforce plain English on a response.

    This is the main entry point for ensuring user-facing responses use
    plain language and omit internal implementation details.

    Args:
        response: The raw response text.
        debug_mode: If True, preserve technical details for debugging.

    Returns:
        Plain English response.
    """
    if response is None:
        return None
    if debug_mode:
        return response

    # Convert to plain English
    plain = to_plain_english(response, aggressive=True)

    # Ensure the response is concise and friendly
    # Remove excessive apologies
    plain = re.sub(r'\b(i am sorry|i apologize|sorry for|apologies for)\b', '', plain, flags=re.IGNORECASE)
    plain = re.sub(r'\s+', ' ', plain).strip()

    # Ensure it ends cleanly
    if plain and not plain[-1] in '.!?':
        plain += '.'

    return plain


def format_clarifying_question(question: str, debug_mode: bool = False) -> str:
    """Format a clarifying question in plain English.

    Args:
        question: The clarifying question.
        debug_mode: If True, preserve technical details.

    Returns:
        Formatted clarifying question.
    """
    if not question:
        return "Could you clarify what you'd like me to do?"

    if debug_mode:
        return question

    # Make it conversational and brief
    plain = to_plain_english(question, aggressive=True)

    # Ensure it's a single question
    if plain.count('?') > 1:
        # Take only the first question
        first_q = plain.split('?')[0] + '?'
        plain = first_q

    # Make it sound natural
    patterns = [
        (r'^\s*please\s+', ''),
        (r'^\s*could you please\s+', ''),
        (r'^\s*could you\s+', ''),
        (r'^\s*would you\s+', ''),
        (r'^\s*can you\s+', ''),
    ]
    for pattern, repl in patterns:
        plain = re.sub(pattern, '', plain, flags=re.IGNORECASE)

    # Capitalize first letter
    if plain:
        plain = plain[0].upper() + plain[1:]

    # Ensure question mark
    if not plain.endswith('?'):
        plain += '?'

    return plain


def format_control_acknowledgement(command: str, debug_mode: bool = False) -> str:
    """Format a conversational control acknowledgement.

    Args:
        command: The control command (stop, cancel, undo, redo, status).
        debug_mode: If True, include technical details.

    Returns:
        Brief, user-friendly acknowledgement.
    """
    if debug_mode:
        return f"Control command received: {command}"

    acknowledgements = {
        "stop": "Stopped. What's next?",
        "halt": "Stopped. What's next?",
        "wait": "Waiting. What would you like me to do?",
        "cancel": "Cancelled.",
        "nevermind": "Cancelled.",
        "abort": "Cancelled.",
        "undo": "Done. I've undone the last action.",
        "revert": "Done. I've reverted the last change.",
        "redo": "Done. I've reapplied the action.",
        "status": "I'm ready to help. What would you like me to do?",
    }

    command_lower = command.lower().strip()
    for key, response in acknowledgements.items():
        if key in command_lower:
            return response

    return "Understood."


def format_low_confidence_message(classification_type: str, debug_mode: bool = False) -> str:
    """Format a low-confidence message in plain English.

    Args:
        classification_type: The type of classification (chat, question, etc.).
        debug_mode: If True, preserve technical details.

    Returns:
        Plain English low-confidence response.
    """
    if debug_mode:
        return f"Low confidence in {classification_type} classification."

    messages = {
        "chat": "I'm not sure what you'd like to chat about. Could you tell me more?",
        "question": "I'm not completely sure what you're asking. Could you rephrase?",
        "task": "I'm not entirely sure what you'd like me to do. Could you clarify?",
        "file_operation": "I'm not sure which file operation you want. Could you be more specific?",
        "code_task": "I'm not sure what code task you need. Could you explain?",
        "system_status": "I'm not sure what system information you need. Could you clarify?",
        "tool_request": "I'm not sure which tool you want me to use. Could you specify?",
        "git_operation": "I'm not sure what git operation you need. Could you clarify?",
    }

    return messages.get(classification_type, "I'm not completely sure what you mean. Could you clarify?")


class PlainEnglishFormatter:
    """Wrapper that applies plain English enforcement to any text."""

    def __init__(self, debug_mode: bool = False):
        self.debug_mode = debug_mode

    def format(self, text: str) -> str:
        """Format text using plain English enforcement."""
        return enforce_plain_english(text, self.debug_mode)

    def format_response(self, response: str) -> str:
        """Format a general response."""
        return self.format(response)

    def format_error(self, error: str) -> str:
        """Format an error message."""
        if self.debug_mode:
            return error
        # Hide technical details
        plain = to_plain_english(error, aggressive=True)
        return plain

    def format_debug(self, debug_info: str) -> str:
        """Format debug information (only shown in debug mode)."""
        if self.debug_mode:
            return f"[Debug: {debug_info}]"
        return ""


# Global instance
_plain_english_formatter: Optional[PlainEnglishFormatter] = None


def get_plain_english_formatter(debug_mode: bool = False) -> PlainEnglishFormatter:
    """Get the global PlainEnglishFormatter instance."""
    global _plain_english_formatter
    if _plain_english_formatter is None:
        _plain_english_formatter = PlainEnglishFormatter(debug_mode)
    return _plain_english_formatter


# Convenience functions
def plain_english(text: str, debug_mode: bool = False) -> str:
    """Quick function to convert text to plain English."""
    return enforce_plain_english(text, debug_mode)

def clarify(question: str, debug_mode: bool = False) -> str:
    """Quick function to format a clarifying question."""
    return format_clarifying_question(question, debug_mode)

def acknowledge_control(command: str, debug_mode: bool = False) -> str:
    """Quick function to format a control acknowledgement."""
    return format_control_acknowledgement(command, debug_mode)

def low_confidence(classification_type: str, debug_mode: bool = False) -> str:
    """Quick function to format a low-confidence message."""
    return format_low_confidence_message(classification_type, debug_mode)