"""Transport-neutral UI bridge for AvatarRuntime.

A host web server can expose ``snapshot`` and ``subscribe`` through its existing
HTTP/SSE or WebSocket routes.  This module does not start a server or process;
it is deliberately embedded in the normal Freya application graph.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Optional
from uuid import uuid4

from .models import AvatarSnapshot
from .runtime import AvatarRuntime


@dataclass
class AvatarStreamClient:
    client_id: str
    events: queue.Queue[dict]


class AvatarUiBridge:
    """Read-only snapshot and event stream for the primary Freya UI."""

    def __init__(self, runtime: AvatarRuntime) -> None:
        self.runtime = runtime
        self._lock = threading.RLock()
        self._clients: dict[str, AvatarStreamClient] = {}
        self._runtime_subscription = runtime.subscribe(self._on_snapshot)

    def snapshot(self) -> dict:
        return self.runtime.snapshot().to_dict()

    def subscribe(self) -> str:
        with self._lock:
            client_id = str(uuid4())
            self._clients[client_id] = AvatarStreamClient(client_id, queue.Queue(maxsize=16))
            self._put(self._clients[client_id], self.snapshot())
            return client_id

    def next_event(self, client_id: str, timeout: Optional[float] = None) -> Optional[dict]:
        with self._lock:
            client = self._clients.get(client_id)
        if client is None:
            return None
        try:
            return client.events.get(timeout=timeout)
        except queue.Empty:
            return None

    def unsubscribe(self, client_id: str) -> bool:
        with self._lock:
            return self._clients.pop(client_id, None) is not None

    def close(self) -> None:
        self.runtime.unsubscribe(self._runtime_subscription)
        with self._lock:
            self._clients.clear()

    def _on_snapshot(self, snapshot: AvatarSnapshot) -> None:
        payload = snapshot.to_dict()
        with self._lock:
            clients = tuple(self._clients.values())
        for client in clients:
            self._put(client, payload)

    @staticmethod
    def _put(client: AvatarStreamClient, payload: dict) -> None:
        try:
            client.events.put_nowait(payload)
        except queue.Full:
            try:
                client.events.get_nowait()
                client.events.put_nowait(payload)
            except queue.Empty:
                pass


__all__ = ["AvatarUiBridge", "AvatarStreamClient"]
