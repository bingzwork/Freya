
"""
Chat Activity Provider - Coordinates chat activity across subsystems.

This provider signals chat activity to all subsystems so they yield to conversation.
Uses threading.Condition for efficient wait/notify instead of polling.
"""

import threading
from typing import Callable, List

from app.core.priority_llm import PriorityLLMProvider


class FreyaChatActivityProvider:
    """
    Unified chat activity provider that coordinates between PriorityLLMProvider,
    AutonomyManager, and BackgroundJobService.

    This provider signals chat activity to all subsystems so they yield to conversation.
    Uses threading.Condition for efficient wait/notify instead of polling.
    """

    def __init__(self, priority_llm: PriorityLLMProvider):
        self._priority_llm = priority_llm
        self._chat_active = False
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._chat_ended_callbacks: List[Callable[[], None]] = []

    def is_chat_active(self) -> bool:
        with self._lock:
            return self._chat_active

    def wait_for_chat_idle(self, timeout: float = 0.1) -> bool:
        with self._condition:
            if not self._chat_active:
                return True
            return self._condition.wait_for(lambda: not self._chat_active, timeout=timeout)

    def register_chat_ended_callback(self, callback: Callable[[], None]) -> None:
        with self._lock:
            self._chat_ended_callbacks.append(callback)

    def unregister_chat_ended_callback(self, callback: Callable[[], None]) -> None:
        with self._lock:
            if callback in self._chat_ended_callbacks:
                self._chat_ended_callbacks.remove(callback)

    def _notify_chat_ended(self) -> None:
        with self._condition:
            self._condition.notify_all()
        for callback in self._chat_ended_callbacks:
            try:
                callback()
            except Exception:
                pass

    def chat_started(self) -> None:
        with self._lock:
            self._chat_active = True
        if self._priority_llm:
            self._priority_llm.chat_started()

    def chat_ended(self) -> None:
        with self._lock:
            self._chat_active = False
        self._notify_chat_ended()
        if self._priority_llm:
            self._priority_llm.chat_ended()

    def chat_activity(self) -> None:
        with self._lock:
            self._chat_active = True
        if self._priority_llm:
            self._priority_llm.chat_activity()
