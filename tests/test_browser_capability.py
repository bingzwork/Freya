from __future__ import annotations

from dataclasses import dataclass

from app.browser.capability import BrowserCapability
from app.browser.adapter import BrowserObservation
from app.capabilities.registration_bridge import CapabilityRegistrationBridge
from app.capabilities.router import CapabilityRouter
from app.core.tool_manager import ToolManager
from app.orchestrator.capability_registry import CapabilityRegistry, reset_capability_registry
from app.orchestrator.capabilities import create_all_capabilities


class FakeBrowserAdapter:
    def __init__(self):
        self.calls = []
        self.closed = False

    def execute(self, action, inputs):
        self.calls.append((action, inputs))
        if action == "fail":
            return BrowserObservation(False, action, error="synthetic failure")
        return BrowserObservation(True, action, url="https://example.test/next", title="Example", text="Visible content", data={"observed": True})

    def close(self):
        self.closed = True


@dataclass
class Assessment:
    allowed: bool = False
    requires_approval: bool = True
    approval_request_id: str = "approval_test"
    reason: str = "Approval required"
    action: object = type("Action", (), {"value": "require_approval"})()
    risk_level: object = type("Risk", (), {"value": "high"})()


class FakeSafetyGate:
    def __init__(self, assessment=None):
        self.assessment = assessment or Assessment()
        self.calls = []

    def check_and_enforce(self, **kwargs):
        self.calls.append(kwargs)
        return self.assessment


def test_browser_capability_is_registered_by_production_factory():
    capability = next(cap for cap in create_all_capabilities() if cap.name == "browser_capability")
    assert capability.metadata.auto_discoverable is False
    assert capability.is_executable() is True
    assert "navigate" in capability.metadata.supported_actions
    assert "take_screenshot" in capability.metadata.supported_actions


def test_browser_capability_dispatches_structured_actions_and_closes_session():
    adapter = FakeBrowserAdapter()
    capability = BrowserCapability(adapter=adapter, profile_dir="/tmp/freya-browser-test")

    result = capability.execute("read_page", {"selector": "body"})

    assert result["success"] is True
    assert result["url"] == "https://example.test/next"
    assert result["text"] == "Visible content"
    assert adapter.calls == [("read_page", {"selector": "body"})]
    capability.close()
    assert adapter.closed is True


def test_browser_capability_returns_structured_failure_for_adapter_error():
    class FailingAdapter(FakeBrowserAdapter):
        def execute(self, action, inputs):
            return BrowserObservation(False, action, error="network unavailable")

    result = BrowserCapability(adapter=FailingAdapter()).execute("navigate", {"url": "https://example.test"})
    assert result == {
        "success": False,
        "action": "navigate",
        "url": "",
        "title": "",
        "text": "",
        "data": {},
        "error": "network unavailable",
    }


def test_consequential_browser_action_uses_existing_safety_gate():
    gate = FakeSafetyGate()
    capability = BrowserCapability(adapter=FakeBrowserAdapter())
    capability.set_safety_gate(gate)

    result = capability.execute("click", {"selector": "button", "consequential": True})

    assert result["success"] is False
    assert result["requires_approval"] is True
    assert result["approval_request_id"] == "approval_test"
    assert gate.calls[0]["context"]["capability"] == "browser_capability"


def test_browser_capability_registers_and_routes_through_canonical_bridge(tmp_path):
    reset_capability_registry()
    registry = CapabilityRegistry()
    capability = BrowserCapability(adapter=FakeBrowserAdapter())
    assert registry.register(capability, registered_by="test") is True
    registry.start()

    router = CapabilityRouter()
    bridge = CapabilityRegistrationBridge(registry=registry, router=router, tool_manager=ToolManager(str(tmp_path)))
    bridge.register_registered_capability(capability, patterns=[r"\bbrowser\b"], keywords=["browser"])

    result = router.route("browser", capability_action="read_page", selector="body")

    assert result.success is True
    assert result.capability_name == "browser_capability"
    assert result.data["text"] == "Visible content"
    registry.stop()
    reset_capability_registry()
