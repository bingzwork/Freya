from __future__ import annotations

from threading import get_ident

from app.browser.adapter import BrowserObservation, PlaywrightBrowserAdapter
from app.browser.capability import BrowserCapability
from app.browser.monitors import BrowserMonitorCoordinator
from app.core.events import EventBus


class FakeAdapter:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.recover_calls = 0
        self.closed = False

    def execute(self, action, inputs):
        if self.results:
            value = self.results.pop(0)
            return value(action, inputs) if callable(value) else value
        return BrowserObservation(True, action, url="https://local.test", data={"page_count": 1, "active_index": 0, "state_token": "stable"})

    def recover(self):
        self.recover_calls += 1
        return True

    def close(self):
        self.closed = True


def event_types(monitor):
    return [item["event_type"] for item in monitor.recent_events()]


def test_monitor_lifecycle_is_idempotent_and_cleans_state():
    monitor = BrowserMonitorCoordinator(FakeAdapter(), EventBus(), session_id="s1")
    monitor.start()
    monitor.start()
    assert monitor.started is True
    assert event_types(monitor).count("BROWSER_MONITORS_STARTED") == 1
    monitor.stop()
    monitor.stop()
    assert monitor.started is False
    assert event_types(monitor).count("BROWSER_MONITORS_STOPPED") == 1


def test_navigation_timeout_is_classified_without_unbounded_retry():
    monitor = BrowserMonitorCoordinator(FakeAdapter(), EventBus(), session_id="s1")
    monitor.start()
    result = monitor.observe("navigate", {"success": False, "action": "navigate", "error": "Timeout 30000ms exceeded"})
    assert "NAVIGATION_TIMEOUT" in event_types(monitor)
    assert result["monitor_events"]
    assert monitor.recovery_attempts == 0


def test_dom_invalidation_and_popup_tab_transitions_are_separate_events():
    monitor = BrowserMonitorCoordinator(FakeAdapter(), EventBus(), session_id="s1")
    monitor.start()
    monitor.observe("read_page", {"success": True, "url": "https://local.test", "data": {"state_token": "a", "page_count": 1, "active_index": 0}})
    result = monitor.observe("click", {"success": True, "url": "https://local.test", "data": {"state_token": "b", "page_count": 2, "active_index": 1}})
    assert "DOM_INVALIDATED" in event_types(monitor)
    assert "POPUP_OPENED" in event_types(monitor)
    assert {event["event_type"] for event in result["monitor_events"]} >= {"DOM_INVALIDATED", "POPUP_OPENED"}
    monitor.observe("close_tab", {"success": True, "url": "https://local.test", "data": {"state_token": "c", "page_count": 1, "active_index": 0}})
    assert "TAB_CLOSED" in event_types(monitor)


def test_challenge_and_download_states_are_structured_and_not_bypassed():
    monitor = BrowserMonitorCoordinator(FakeAdapter(), EventBus(), session_id="s1")
    monitor.start()
    challenge = monitor.observe("read_page", {"success": True, "url": "https://local.test", "title": "CAPTCHA verification", "text": "Please verify you are human", "data": {"state_token": "x", "page_count": 1}})
    assert "BLOCKED_BY_CHALLENGE" in event_types(monitor)
    assert challenge["browser_state"]["event_type"] == "BLOCKED_BY_CHALLENGE"
    download = monitor.observe("download_file", {"success": True, "url": "https://local.test/file", "data": {"path": "C:/tmp/file.txt", "state_token": "x", "page_count": 1}})
    assert "DOWNLOAD_COMPLETED" in event_types(monitor)
    assert download["monitor_events"][-1]["event_type"] in {"DOWNLOAD_COMPLETED", "DOWNLOAD_VERIFIED"}


def test_resource_pressure_is_observed_without_aggressive_cleanup():
    monitor = BrowserMonitorCoordinator(FakeAdapter(), EventBus(), session_id="s1", max_tabs=2)
    monitor.start()
    result = monitor.observe("open_tab", {"success": True, "url": "https://local.test", "data": {"state_token": "x", "page_count": 3, "active_index": 2}})
    assert "RESOURCE_PRESSURE" in event_types(monitor)
    assert result["success"] is True


def test_session_failure_attempts_one_bounded_recovery_and_surfaces_result():
    adapter = FakeAdapter([BrowserObservation(False, "read_page", error="Browser context has been closed")])
    monitor = BrowserMonitorCoordinator(adapter, EventBus(), session_id="s1")
    monitor.start()
    result = monitor.observe("read_page", adapter.execute("read_page", {}))
    assert adapter.recover_calls == 1
    assert "SESSION_RECOVERED" in event_types(monitor)
    assert result["browser_state"]["recovered"] is True
    monitor.observe("read_page", {"success": False, "error": "Browser context has been closed"})
    assert adapter.recover_calls == 1


def test_browser_capability_preserves_safety_gate_before_monitor_or_adapter():
    adapter = FakeAdapter()
    capability = BrowserCapability(adapter=adapter)

    class Denied:
        def check_and_enforce(self, **kwargs):
            class Assessment:
                allowed = False
                requires_approval = False
                approval_request_id = None
                reason = "Denied by test SafetyGate"
                action = type("Action", (), {"value": "deny"})()
                risk_level = type("Risk", (), {"value": "high"})()
            return Assessment()

    capability.set_safety_gate(Denied())
    result = capability.execute("click", {"selector": "button", "consequential": True})
    assert result["success"] is False
    assert adapter.closed is False


def test_playwright_commands_remain_on_the_dedicated_owner_thread():
    class ProbeAdapter(PlaywrightBrowserAdapter):
        def _execute_local(self, action, inputs):
            return BrowserObservation(True, action, data={"thread_id": get_ident()})

    adapter = ProbeAdapter()
    caller_thread = get_ident()
    result = adapter.execute("get_current_url", {})
    assert result.success is True
    assert result.data["thread_id"] != caller_thread
    adapter.close()
    assert adapter._owner_thread is None
