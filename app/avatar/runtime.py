"""In-process avatar lifecycle owned by Freya startup.

The bridge uses the existing EventBus and exposes read-only snapshots to a UI
transport.  It never owns or calls Freya intelligence, routing, memory,
capabilities, safety, or execution logic.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable, Optional

from app.core.events import EventBus

from .adapters import AvatarAdapter, NoopAvatarAdapter
from .controller import AvatarController
from .mapping import AvatarStateMapper
from .models import AvatarSnapshot


class AvatarRuntime:
    """Lifecycle-managed avatar observer created during normal startup."""

    def __init__(
        self,
        event_bus: EventBus,
        *,
        adapter: Optional[AvatarAdapter] = None,
        enabled: bool = True,
        model_path: Optional[Path] = None,
    ) -> None:
        self.event_bus = event_bus
        self.controller = AvatarController(adapter or NoopAvatarAdapter(model_status="ui_managed"))
        self.mapper = AvatarStateMapper(event_bus, self.controller)
        self.enabled = bool(enabled)
        self.model_path = model_path
        self._lock = threading.RLock()
        self._started = False
        self._listeners: dict[str, Callable[[AvatarSnapshot], None]] = {}
        self._controller_subscription: Optional[str] = None

    @property
    def started(self) -> bool:
        return self._started

    def start(self) -> None:
        with self._lock:
            if self._started or not self.enabled:
                return
            self.mapper.start()
            self._controller_subscription = self.controller.subscribe(self._on_snapshot)
            self._started = True
            self._emit_snapshot(self.controller.snapshot())

    def stop(self) -> None:
        with self._lock:
            if not self._started:
                return
            self.mapper.stop()
            if self._controller_subscription:
                self.controller.unsubscribe(self._controller_subscription)
                self._controller_subscription = None
            self.controller.dispose()
            self._started = False
            self._listeners.clear()

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            desired = bool(enabled)
            if desired == self.enabled:
                return
            self.enabled = desired
            if desired:
                self.start()
            else:
                self.stop()

    def snapshot(self) -> AvatarSnapshot:
        return self.controller.snapshot()

    def create_ui_bridge(self):
        """Return a bridge for Freya's existing HTTP/SSE/WebSocket host."""
        from .transport import AvatarUiBridge
        return AvatarUiBridge(self)

    def subscribe(self, listener: Callable[[AvatarSnapshot], None]) -> str:
        with self._lock:
            from uuid import uuid4
            subscription_id = str(uuid4())
            self._listeners[subscription_id] = listener
            listener(self.controller.snapshot())
            return subscription_id

    def unsubscribe(self, subscription_id: str) -> bool:
        with self._lock:
            return self._listeners.pop(subscription_id, None) is not None

    def _on_snapshot(self, snapshot: AvatarSnapshot) -> None:
        self._emit_snapshot(snapshot)

    def _emit_snapshot(self, snapshot: AvatarSnapshot) -> None:
        payload = snapshot.to_dict()
        try:
            self.event_bus.emit("avatar.state.changed", payload, source="AvatarRuntime")
        except Exception:
            # Avatar observation must never affect the runtime event producer.
            pass
        for listener in tuple(self._listeners.values()):
            try:
                listener(snapshot)
            except Exception:
                pass


__all__ = ["AvatarRuntime"]
