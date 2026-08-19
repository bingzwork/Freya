from types import SimpleNamespace

from app.ui.agent_console import _browser_component_status


class LiveThread:
    def is_alive(self):
        return True


class BrowserCapabilityStub:
    state = SimpleNamespace(value="active")
    _adapter = SimpleNamespace(_context=object(), _owner_thread=LiveThread())

    def is_executable(self):
        return True


def test_browser_dashboard_status_uses_canonical_active_browser_capability():
    system = SimpleNamespace(browser_capability=BrowserCapabilityStub())
    result = _browser_component_status(system, {"dependencies": []})
    assert result == {
        "status": "Active",
        "ready": True,
        "active": True,
        "source": "browser_capability",
    }


def test_browser_dashboard_status_is_ready_before_session_starts():
    capability = BrowserCapabilityStub()
    capability._adapter = SimpleNamespace(_context=None, _owner_thread=None)
    system = SimpleNamespace(browser_capability=capability)
    result = _browser_component_status(system, {"dependencies": []})
    assert result["status"] == "Ready"
    assert result["ready"] is True
    assert result["active"] is False
