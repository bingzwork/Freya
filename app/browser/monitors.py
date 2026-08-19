from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Dict, Optional

from app.core.events import EventBus, get_event_bus


@dataclass(frozen=True)
class BrowserStateEvent:
    """Safe browser operational event; never contains hidden reasoning."""

    event_type: str
    timestamp: float
    session_id: str = ""
    tab_id: str = ""
    url: str = ""
    severity: str = "info"
    recoverable: bool = False
    recovered: bool = False
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "tab_id": self.tab_id,
            "url": self.url,
            "severity": self.severity,
            "recoverable": self.recoverable,
            "recovered": self.recovered,
            "data": dict(self.data),
        }


class BrowserMonitorCoordinator:
    """Browser-owned observers attached to the canonical Playwright owner.

    The coordinator deliberately does not call Playwright. It consumes the
    owner-thread's safe observation snapshots and invokes only the adapter's
    explicit recovery boundary when a session failure is classified.
    """

    CHALLENGE_MARKERS = (
        "captcha", "cloudflare", "verify you are human", "checking your browser",
        "access denied", "sign in to continue", "log in to continue", "login required",
        "age verification", "permission denied",
    )
    SESSION_FAILURE_MARKERS = (
        "browser has been closed", "browser context has been closed", "target page",
        "connection closed", "disconnected", "target closed", "session is closed",
        "transport closed", "playwright", "browser closed",
    )

    def __init__(self, adapter: Any, event_bus: Optional[EventBus] = None, *, session_id: str = "", max_tabs: int = 12) -> None:
        self._adapter = adapter
        self._event_bus = event_bus or get_event_bus()
        self._session_id = session_id
        self._max_tabs = max(2, int(max_tabs))
        self._lock = RLock()
        self._started = False
        self._previous: Dict[str, Any] = {}
        self._events: list[BrowserStateEvent] = []
        self._recovery_attempts = 0
        self._max_recovery_attempts = 1

    @property
    def started(self) -> bool:
        return self._started

    @property
    def recovery_attempts(self) -> int:
        return self._recovery_attempts

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            self._previous = {}
            self._recovery_attempts = 0
            self._emit("BROWSER_MONITORS_STARTED", severity="info")

    def stop(self) -> None:
        with self._lock:
            if not self._started:
                return
            self._started = False
            self._previous = {}
            self._emit("BROWSER_MONITORS_STOPPED", severity="info")

    def observe(self, action: str, result: Dict[str, Any]) -> Dict[str, Any]:
        """Classify one owner-thread observation and return safe monitor metadata."""
        with self._lock:
            if not self._started:
                self.start()
            if hasattr(result, "to_dict") and callable(result.to_dict):
                safe = dict(result.to_dict())
            else:
                safe = dict(result or {})
            data = dict(safe.get("data") or {})
            url = str(safe.get("url") or data.get("url") or "")
            text = " ".join(str(value) for value in (safe.get("text"), safe.get("title"), data.get("body_preview")) if value).lower()
            events: list[BrowserStateEvent] = []
            if action in {"open_url", "navigate", "back", "forward", "reload"}:
                events.append(self._navigation_event(action, safe, url)) if not safe.get("success") else None
            if not safe.get("success"):
                events.extend(self._failure_events(action, safe, url))
            if any(marker in text for marker in self.CHALLENGE_MARKERS):
                events.append(self._emit("BLOCKED_BY_CHALLENGE", url=url, severity="warning", recoverable=False, data={"action": action, "markers": [marker for marker in self.CHALLENGE_MARKERS if marker in text][:3]}))
            events.extend(self._page_state_events(action, data, url))
            if action == "download_file":
                events.append(self._emit("DOWNLOAD_COMPLETED" if safe.get("success") else "DOWNLOAD_FAILED", url=url, severity="info" if safe.get("success") else "warning", data={"action": action, "path": data.get("path", ""), "error": safe.get("error")}))
            if action in {"open_url", "navigate", "back", "forward", "reload", "click", "open_tab", "switch_tab", "close_tab"}:
                if data.get("page_count") is not None and int(data.get("page_count") or 0) > self._max_tabs:
                    events.append(self._emit("RESOURCE_PRESSURE", url=url, severity="warning", recoverable=True, data={"page_count": data.get("page_count"), "max_tabs": self._max_tabs}))
            if safe.get("success") and action == "download_file":
                self._emit("DOWNLOAD_VERIFIED", url=url, data={"path": data.get("path", "")})
            classified_events = [event for event in events if event.event_type not in {"NAVIGATION_FAILED", "BROWSER_ACTION_FAILED"}]
            if classified_events:
                safe["monitor_events"] = [event.to_dict() for event in classified_events]
                safe["browser_state"] = classified_events[-1].to_dict()
            return safe

    def _failure_events(self, action: str, result: Dict[str, Any], url: str) -> list[BrowserStateEvent]:
        error = str(result.get("error") or "").lower()
        if any(marker in error for marker in self.SESSION_FAILURE_MARKERS):
            recovered = False
            recovery_error = ""
            if self._recovery_attempts < self._max_recovery_attempts and hasattr(self._adapter, "recover"):
                self._recovery_attempts += 1
                self._emit("SESSION_RECOVERING", url=url, severity="warning", recoverable=True, data={"action": action})
                try:
                    recovered = bool(self._adapter.recover())
                except Exception as exc:
                    recovery_error = str(exc)
                event_type = "SESSION_RECOVERED" if recovered else "SESSION_RECOVERY_FAILED"
                return [self._emit(event_type, url=url, severity="warning" if not recovered else "info", recoverable=True, recovered=recovered, data={"action": action, "error": recovery_error or error})]
            return [self._emit("SESSION_LOST", url=url, severity="error", recoverable=hasattr(self._adapter, "recover"), data={"action": action, "error": error})]
        if action in {"open_url", "navigate", "back", "forward", "reload"}:
            return [self._navigation_event(action, result, url)]
        return [self._emit("BROWSER_ACTION_FAILED", url=url, severity="warning", data={"action": action, "error": error})]

    def _navigation_event(self, action: str, result: Dict[str, Any], url: str) -> BrowserStateEvent:
        error = str(result.get("error") or "").lower()
        if "timeout" in error:
            event_type = "NAVIGATION_TIMEOUT"
        elif "redirect" in error:
            event_type = "REDIRECT_LOOP"
        elif result.get("success"):
            event_type = "NAVIGATION_COMPLETED"
        else:
            event_type = "NAVIGATION_FAILED"
        return self._emit(event_type, url=url, severity="info" if result.get("success") else "warning", recoverable=not result.get("success"), data={"action": action, "error": result.get("error")})

    def _page_state_events(self, action: str, data: Dict[str, Any], url: str) -> list[BrowserStateEvent]:
        events: list[BrowserStateEvent] = []
        current_token = data.get("state_token")
        previous_token = self._previous.get("state_token")
        previous_count = self._previous.get("page_count")
        current_count = data.get("page_count")
        if previous_token and current_token and previous_token != current_token and action not in {"open_url", "navigate", "back", "forward", "reload"}:
            events.append(self._emit("DOM_INVALIDATED", url=url, severity="info", recoverable=True, data={"action": action, "refresh_required": True}))
        if previous_count is not None and current_count is not None and int(current_count) > int(previous_count):
            events.append(self._emit("POPUP_OPENED", url=url, severity="info", recoverable=False, data={"previous_tab_count": previous_count, "current_tab_count": current_count, "active_index": data.get("active_index")}))
        elif previous_count is not None and current_count is not None and int(current_count) < int(previous_count):
            events.append(self._emit("TAB_CLOSED", url=url, severity="info", recoverable=False, data={"previous_tab_count": previous_count, "current_tab_count": current_count, "active_index": data.get("active_index")}))
        if current_token:
            self._previous.update({"state_token": current_token, "page_count": current_count, "active_index": data.get("active_index"), "url": url})
        return events

    def _emit(self, event_type: str, *, url: str = "", severity: str = "info", recoverable: bool = False, recovered: bool = False, data: Optional[Dict[str, Any]] = None) -> BrowserStateEvent:
        event = BrowserStateEvent(event_type=event_type, timestamp=time.time(), session_id=self._session_id, url=url, severity=severity, recoverable=recoverable, recovered=recovered, data=data or {})
        self._events.append(event)
        try:
            self._event_bus.emit(f"browser.monitor.{event_type.lower()}", event.to_dict(), source="browser_subsystem")
        except Exception:
            pass
        return event

    def recent_events(self, limit: int = 50) -> list[Dict[str, Any]]:
        with self._lock:
            return [event.to_dict() for event in self._events[-max(1, limit):]]


__all__ = ["BrowserStateEvent", "BrowserMonitorCoordinator"]
