"""Canonical BrowserCapability exposed through Freya's capability registry."""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.core.events import get_event_bus
from app.orchestrator.capabilities import BaseCapability
from app.orchestrator.capability_registry import CapabilityCategory, CapabilityMetadata
from app.browser.adapter import BrowserAdapter, BrowserObservation, PlaywrightBrowserAdapter


_BROWSER_ACTIONS = [
    "open_url", "navigate", "back", "forward", "reload", "click", "type", "fill",
    "select", "scroll", "read_page", "find_element", "wait_for_element", "upload_file",
    "download_file", "extract_links", "extract_media", "open_tab", "close_tab", "switch_tab", "get_current_url",

    "get_page_title", "take_screenshot",
]
_CONSEQUENTIAL_TERMS = {
    "purchase", "buy", "pay", "delete", "remove", "send", "submit", "publish",
    "post", "message", "email", "transfer", "checkout", "change password", "settings",
    "financial", "irreversible",
}


class BrowserCapability(BaseCapability):
    """Structured browser interaction capability backed by a replaceable adapter."""

    def __init__(self, adapter: Optional[BrowserAdapter] = None, profile_dir: Optional[str] = None) -> None:
        super().__init__(CapabilityMetadata(
            name="browser_capability",
            version="1.0.0",
            description="Navigate and interact with websites through a safety-gated browser session",
            category=CapabilityCategory.EXECUTION,
            is_singleton=True,
            auto_discoverable=True,
            default_action="open_url",
            supported_actions=list(_BROWSER_ACTIONS),
            tags=["browser", "website", "navigate", "click", "form"],
            safe_query=False,
        ))
        self._adapter: BrowserAdapter = adapter or PlaywrightBrowserAdapter(profile_dir=profile_dir)
        self._safety_gate = None
        self._profile_dir = profile_dir
        self._started_event_sent = False

    def set_adapter(self, adapter: BrowserAdapter) -> None:
        self._adapter = adapter

    def set_safety_gate(self, safety_gate: Any) -> None:
        self._safety_gate = safety_gate

    def set_profile_dir(self, profile_dir: str) -> None:
        self._profile_dir = profile_dir
        if isinstance(self._adapter, PlaywrightBrowserAdapter):
            self._adapter.close()
            self._adapter = PlaywrightBrowserAdapter(profile_dir=profile_dir)

    def _deactivate(self) -> bool:
        self.close()
        return super()._deactivate()

    def close(self) -> None:
        self._adapter.close()
        self._started_event_sent = False

    @staticmethod
    def _requires_consequential_review(action: str, inputs: Dict[str, Any]) -> bool:
        if bool(inputs.get("safe_read_only", False)):
            return False
        haystack = " ".join(str(inputs.get(key, "")) for key in ("selector", "text", "url", "label", "value")).lower()
        if action in {"type", "fill", "select", "upload_file", "click"} and any(term in haystack for term in _CONSEQUENTIAL_TERMS):
            return True
        return bool(inputs.get("consequential", False))

    def _safety_check(self, action: str, inputs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self._requires_consequential_review(action, inputs):
            return None
        if self._safety_gate is None:
            return {"success": False, "action": action, "requires_approval": True, "error": "Consequential browser action requires the existing SafetyGate"}
        assessment = self._safety_gate.check_and_enforce(
            operation=f"Browser action '{action}' on {inputs.get('url') or inputs.get('selector') or 'current page'}",
            operation_type="external_api_call",
            context={"capability": self.name, "action": action, "inputs": {k: v for k, v in inputs.items() if k not in {"password", "token", "secret"}}},
        )
        if not assessment.allowed:
            return {
                "success": False,
                "action": action,
                "requires_approval": assessment.requires_approval,
                "approval_request_id": assessment.approval_request_id,
                "error": assessment.reason or f"Browser action blocked by SafetyGate: {assessment.action.value}",
                "safety": {"action": assessment.action.value, "risk_level": assessment.risk_level.value},
            }
        return None

    def execute(self, action: str, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(inputs, dict):
            return {"success": False, "action": action, "error": "Browser action inputs must be an object"}
        if not self.supports_action(action):
            return {"success": False, "action": action, "error": f"Unsupported browser action: {action}"}
        safety_failure = self._safety_check(action, inputs)
        if safety_failure:
            self._publish_event("browser.failed", safety_failure)
            return safety_failure
        if not self._started_event_sent:
            self._publish_event("browser.started", {"profile_dir": self._profile_dir, "persistent": bool(self._profile_dir)})
            self._started_event_sent = True
        self._publish_event("browser.action", {"action": action})
        if action in {"open_url", "navigate", "back", "forward", "reload"}:
            self._publish_event("browser.navigation", {"action": action, "url": inputs.get("url")})
        observation = self._adapter.execute(action, inputs)
        result = observation.to_dict() if isinstance(observation, BrowserObservation) else dict(observation)
        result.setdefault("action", action)
        self._publish_event("browser.observation", result)
        self._publish_event("browser.completed" if result.get("success") else "browser.failed", result)
        return result

    def __getattr__(self, name: str):
        if name.startswith("action_"):
            action = name.removeprefix("action_")
            if action in _BROWSER_ACTIONS:
                return lambda inputs: self.execute(action, inputs)
        raise AttributeError(name)


__all__ = ["BrowserCapability"]
