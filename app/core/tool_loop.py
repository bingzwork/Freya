"""Bounded Jan-style tool loop for local chat models."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.core.priority_llm import LLMPriority, LLMOutcomeKind
from app.research.native_web_tools import NativeWebTools

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolLoopLimits:
    max_consecutive_calls: int = 8
    max_search_calls: int = 4
    max_fetch_calls: int = 6


@dataclass
class ToolLoopResult:
    success: bool
    content: str = ""
    error: Optional[Dict[str, Any]] = None
    tool_calls: int = 0
    search_calls: int = 0
    fetch_calls: int = 0
    messages: List[Dict[str, Any]] = field(default_factory=list)


class NativeWebToolAgent:
    """Let a tool-capable local model control search/fetch decisions."""

    def __init__(self, priority_llm: Any, native_tools: Optional[NativeWebTools] = None, limits: Optional[ToolLoopLimits] = None):
        self.priority_llm = priority_llm
        self.native_tools = native_tools or NativeWebTools()
        self.limits = limits or ToolLoopLimits()

    def run(self, prompt: str, *, system: Optional[str] = None, timeout: Optional[float] = None) -> ToolLoopResult:
        supports = getattr(self.priority_llm, "supports_tool_calling", None)
        if not callable(supports) or not bool(supports()):
            return ToolLoopResult(False, error={"error": "tools_unsupported", "message": "The selected local model does not advertise tool-calling support."})

        messages: List[Dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": str(prompt or "").strip()})
        search_calls = 0
        fetch_calls = 0
        total_calls = 0

        for _ in range(max(1, self.limits.max_consecutive_calls + 1)):
            outcome = self._ask(messages, timeout=timeout)
            if outcome.kind is not LLMOutcomeKind.SUCCESS:
                return ToolLoopResult(False, error={"error": "model_failed", "message": outcome.reason or "The local model did not return a usable response."}, tool_calls=total_calls, search_calls=search_calls, fetch_calls=fetch_calls, messages=messages)
            assistant = self._assistant_message(outcome, outcome.content or "")
            messages.append(assistant)
            calls = self._extract_tool_calls(assistant)
            if not calls:
                content = str(assistant.get("content") or "").strip()
                if not content:
                    return ToolLoopResult(False, error={"error": "empty_model_response", "message": "The local model returned no final answer."}, tool_calls=total_calls, search_calls=search_calls, fetch_calls=fetch_calls, messages=messages)
                return ToolLoopResult(True, content=content, tool_calls=total_calls, search_calls=search_calls, fetch_calls=fetch_calls, messages=messages)

            if total_calls + len(calls) > self.limits.max_consecutive_calls:
                messages.append({"role": "user", "content": "Tool-call limit reached. Answer using the evidence already returned."})
                outcome = self._ask(messages, timeout=timeout)
                return ToolLoopResult(bool(outcome.is_success), content=str(outcome.content or "").strip(), error=None if outcome.is_success else {"error": "tool_loop_limit", "message": "The web-tool call limit was reached before the model produced a final answer."}, tool_calls=total_calls, search_calls=search_calls, fetch_calls=fetch_calls, messages=messages)

            for call in calls:
                name = call["name"]
                arguments = call["arguments"]
                if name == "web_search":
                    if search_calls >= self.limits.max_search_calls:
                        result: Any = {"error": "search_limit_reached", "message": "The maximum number of web searches for this request has been reached."}
                    else:
                        search_calls += 1
                        result = self.native_tools.search(arguments.get("query"), arguments.get("count", 5))
                elif name == "web_fetch":
                    if fetch_calls >= self.limits.max_fetch_calls:
                        result = {"error": "fetch_limit_reached", "message": "The maximum number of web pages for this request has been reached."}
                    else:
                        fetch_calls += 1
                        result = self.native_tools.fetch(arguments.get("url"))
                else:
                    result = {"error": "unknown_tool", "message": f"Unknown tool '{name}'."}
                total_calls += 1
                messages.append({"role": "tool", "content": json.dumps(result, ensure_ascii=False), "name": name})

        return ToolLoopResult(False, error={"error": "tool_loop_limit", "message": "The model exceeded the bounded web-tool loop."}, tool_calls=total_calls, search_calls=search_calls, fetch_calls=fetch_calls, messages=messages)

    def _ask(self, messages: List[Dict[str, Any]], *, timeout: Optional[float]) -> Any:
        ask = getattr(self.priority_llm, "ask_outcome_with_tools", None)
        if not callable(ask):
            return type("Outcome", (), {"kind": LLMOutcomeKind.UNAVAILABLE, "reason": "Tool-capable chat is not available.", "content": "", "is_success": False, "raw_response": None})()
        return ask(messages=messages, tools=self.native_tools.schemas(), priority=LLMPriority.CHAT, timeout=timeout)

    @staticmethod
    def _assistant_message(response: Any, fallback_content: str) -> Dict[str, Any]:
        raw = getattr(response, "raw_response", None) if response is not None else None
        if isinstance(response, dict):
            raw = response
        if isinstance(raw, dict):
            message = raw.get("message")
            if isinstance(message, dict):
                clean = dict(message)
                clean.setdefault("role", "assistant")
                clean.setdefault("content", fallback_content)
                return clean
        return {"role": "assistant", "content": fallback_content}

    @staticmethod
    def _extract_tool_calls(message: Dict[str, Any]) -> List[Dict[str, Any]]:
        raw_calls = message.get("tool_calls") or []
        if not isinstance(raw_calls, list):
            raw_calls = [raw_calls]
        calls: List[Dict[str, Any]] = []
        for raw in raw_calls:
            if not isinstance(raw, dict):
                continue
            function = raw.get("function") if isinstance(raw.get("function"), dict) else raw
            name = str(function.get("name") or raw.get("name") or "").strip()
            arguments = function.get("arguments", raw.get("arguments", {}))
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {}
            if name and isinstance(arguments, dict):
                calls.append({"name": name, "arguments": arguments})
        return calls


__all__ = ["NativeWebToolAgent", "ToolLoopLimits", "ToolLoopResult"]
