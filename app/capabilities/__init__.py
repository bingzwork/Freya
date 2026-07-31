"""Capability Routing System.

This module provides a routing system for handling user queries that can be
answered directly by Freya without invoking the LLM. The LLM becomes a
fallback for questions that cannot be answered through local capabilities.

The routing flow is:
    User Query
        ↓
    Intent Classification
        ↓
    Capability Router  --(if capability exists)--> Execute Capability --> Return Result
        ↓
    (no capability)
        ↓
    LLM (fallback)
"""

from app.capabilities.router import CapabilityRouter, NoCapabilityError
from app.capabilities.handlers import (
    RuntimeCapabilityHandler,
    OllamaCapabilityHandler,
    GitCapabilityHandler,
    SystemCapabilityHandler,
)
from app.capabilities.plain_english import (
    PlainEnglishFormatter,
    get_plain_english_formatter,
    plain_english,
    clarify,
    acknowledge_control,
    low_confidence,
    enforce_plain_english,
    to_plain_english,
    format_clarifying_question,
    format_control_acknowledgement,
    format_low_confidence_message,
    detect_jargon,
    detect_forbidden_fields,
)

__all__ = [
    "CapabilityRouter",
    "NoCapabilityError",
    "RuntimeCapabilityHandler",
    "OllamaCapabilityHandler",
    "GitCapabilityHandler",
    "SystemCapabilityHandler",
    # Plain English enforcement
    "PlainEnglishFormatter",
    "get_plain_english_formatter",
    "plain_english",
    "clarify",
    "acknowledge_control",
    "low_confidence",
    "enforce_plain_english",
    "to_plain_english",
    "format_clarifying_question",
    "format_control_acknowledgement",
    "format_low_confidence_message",
    "detect_jargon",
    "detect_forbidden_fields",
]
