"""
Priority LLM Provider - Ensures chat/conversation has absolute priority over autonomy.

This module provides a wrapper around the LLM that implements:
1. Priority-based request queue (CHAT > SAFETY > AUTONOMY_THINK > BACKGROUND)
2. Preemption - autonomy LLM work yields when chat requests arrive
3. Resource protection - reserves capacity for chat path
4. No duplicate LLM implementation - wraps existing provider architecture
"""

import asyncio
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from app.core.logger import logger
from app.core.llm import LLM, ENHANCED_SYSTEM_PROMPT


def _priority_trace(step: str, detail: str = ""):
    """Trace PriorityLLM flow with timestamp, thread ID, and asyncio task info. Only outputs if FREYA_TRACE=true."""
    import asyncio
    import threading
    thread = threading.current_thread()
    task = None
    try:
        task = asyncio.current_task()
    except RuntimeError:
        pass
    task_id = id(task) if task else "no-loop"
    ts = time.time()
    logger.trace(f"[CHAT] {step} thread={thread.name} thread_id={thread.ident} task_id={task_id} {detail}")


class LLMPriority(Enum):
    """Priority levels for LLM requests."""
    CHAT = 1000      # Highest - user conversation
    SAFETY = 800     # Safety/critical system events
    AUTONOMY_THINK = 500  # Autonomous reasoning
    BACKGROUND = 100 # Background maintenance/learning

    @classmethod
    def from_string(cls, s: str) -> 'LLMPriority':
        return {
            'chat': cls.CHAT,
            'safety': cls.SAFETY,
            'autonomy': cls.AUTONOMY_THINK,
            'background': cls.BACKGROUND,
        }.get(s.lower(), cls.BACKGROUND)


@dataclass
class LLMRequest:
    """A request for LLM inference."""
    request_id: str = field(default_factory=lambda: str(uuid4()))
    prompt: str = ""
    system_prompt: str = ""
    priority: LLMPriority = LLMPriority.BACKGROUND
    callback: Optional[Callable[[str], None]] = None
    future: Optional[asyncio.Future] = None
    loop: Optional[asyncio.AbstractEventLoop] = None  # Event loop that owns the future
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __lt__(self, other: 'LLMRequest') -> bool:
        # Higher priority first, then FIFO within same priority
        if self.priority.value != other.priority.value:
            return self.priority.value > other.priority.value
        return self.created_at < other.created_at


class PriorityLLMProvider:
    """
    Priority-based LLM provider that ensures chat always gets served first.

    Architecture:
    - Single worker thread processes requests in priority order
    - Chat requests can preempt running autonomy work (by setting yield flag)
    - Logs all priority decisions for observability
    - No changes needed to existing LLM implementation
    - Uses threading.Condition for efficient wait/notify instead of polling
    """

    def __init__(self, llm: LLM):
        self._llm = llm
        self._request_queue: deque = deque()
        self._queue_lock = threading.RLock()
        self._worker_thread: Optional[threading.Thread] = None
        self._shutdown_event = threading.Event()
        self._current_request: Optional[LLMRequest] = None
        self._current_request_lock = threading.RLock()

        # Chat activity tracking with Condition for efficient wait/notify
        self._chat_active = False
        self._chat_active_lock = threading.RLock()
        self._chat_last_activity = 0.0
        self._queue_condition = threading.Condition(self._queue_lock)

        # Statistics
        self._stats = {
            'total_requests': 0,
            'chat_requests': 0,
            'autonomy_requests': 0,
            'background_requests': 0,
            'preempted_requests': 0,
            'yielded_requests': 0,
        }
        self._stats_lock = threading.RLock()

        # Start worker
        self._start_worker()

        logger.info("[PriorityLLM] Initialized with priority-based queue")

    def _start_worker(self) -> None:
        """Start the background worker thread."""
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="PriorityLLM-Worker"
        )
        self._worker_thread.start()

    def _worker_loop(self) -> None:
        """Main worker loop - processes requests in priority order."""
        while not self._shutdown_event.is_set():
            with self._queue_condition:
                # Wait for a request to be available, or for chat to end
                while not self._request_queue and not self._shutdown_event.is_set():
                    # Wait for a new request to be enqueued, or for chat to end
                    self._queue_condition.wait(timeout=1.0)

                if self._shutdown_event.is_set():
                    break

                # Check if queue is empty after wait (could be spurious wakeup or just chat ending)
                if not self._request_queue:
                    continue

                # Get the highest priority request
                request = self._request_queue.popleft()
                _priority_trace(f"4 REQUEST_WORKER_PICKED_UP priority={request.priority.name} queue_remaining={len(self._request_queue)}")

            # Check if we should yield for chat
            if self._should_yield_for_chat(request):
                # Re-queue and wait for chat to end efficiently
                with self._queue_condition:
                    # Re-insert maintaining priority order
                    inserted = False
                    for i, existing in enumerate(self._request_queue):
                        if request < existing:
                            self._request_queue.insert(i, request)
                            inserted = True
                            break
                    if not inserted:
                        self._request_queue.append(request)
                with self._stats_lock:
                    self._stats['yielded_requests'] += 1

                # Wait efficiently for chat to end (notified by chat_ended)
                with self._queue_condition:
                    self._queue_condition.wait(timeout=60.0)
                continue

            # Execute the request
            self._execute_request(request)

    def _should_yield_for_chat(self, request: LLMRequest) -> bool:
        """Check if this request should yield to chat."""
        # Only autonomy and background requests yield
        if request.priority in (LLMPriority.CHAT, LLMPriority.SAFETY):
            return False

        with self._chat_active_lock:
            if self._chat_active:
                return True

            # Also yield if chat was recently active (within 2 seconds)
            if time.time() - self._chat_last_activity < 2.0:
                return True

        return False

    def _execute_request(self, request: LLMRequest) -> None:
        """Execute a single LLM request."""
        with self._current_request_lock:
            self._current_request = request
            request.started_at = time.time()

        try:
            # Check if we should abort (preempted by chat)
            if self._should_yield_for_chat(request):
                self._requeue_request(request)
                with self._current_request_lock:
                    self._current_request = None
                return

            _priority_trace(f"5 PROVIDER_REQUEST_STARTED priority={request.priority.name} request_id={request.request_id[:8]}")

            # Execute the actual LLM call
            result = self._llm.ask(request.prompt, request.system_prompt)

            _priority_trace(f"6 PROVIDER_RESPONSE_RECEIVED priority={request.priority.name} request_id={request.request_id[:8]}")

            with self._current_request_lock:
                self._current_request = None
                request.completed_at = time.time()

            # Call callback or resolve future
            if request.callback:
                try:
                    request.callback(result)
                except Exception as e:
                    logger.error(f"[PriorityLLM] Callback error: {e}")

            if request.future and not request.future.done():
                if request.loop:
                    request.loop.call_soon_threadsafe(request.future.set_result, result)
                else:
                    request.future.set_result(result)

            _priority_trace(f"7 RESPONSE_RETURNED_TO_AGENT priority={request.priority.name} request_id={request.request_id[:8]}")

            # Update stats
            with self._stats_lock:
                self._stats['total_requests'] += 1
                if request.priority == LLMPriority.CHAT:
                    self._stats['chat_requests'] += 1
                elif request.priority == LLMPriority.AUTONOMY_THINK:
                    self._stats['autonomy_requests'] += 1
                elif request.priority == LLMPriority.BACKGROUND:
                    self._stats['background_requests'] += 1

        except Exception as e:
            logger.error(f"[PriorityLLM] Request execution error: {e}")
            with self._current_request_lock:
                self._current_request = None
                request.completed_at = time.time()

            if request.future and not request.future.done():
                if request.loop:
                    request.loop.call_soon_threadsafe(request.future.set_exception, e)
                else:
                    request.future.set_exception(e)

    def ask(
        self,
        prompt: str,
        system: Optional[str] = None,
        priority: LLMPriority = LLMPriority.BACKGROUND,
        timeout: Optional[float] = None
    ) -> str:
        """
        Synchronous LLM request with priority.

        Args:
            prompt: The prompt to send
            system: Optional system prompt
            priority: Priority level for this request
            timeout: Optional timeout in seconds

        Returns:
            LLM response
        """
        # Create future for sync wait
        loop = asyncio.new_event_loop()
        future = asyncio.Future(loop=loop)

        request = LLMRequest(
            prompt=prompt,
            system_prompt=system or ENHANCED_SYSTEM_PROMPT,
            priority=priority,
            future=future,
            loop=loop,
        )

        self._enqueue_request(request)

        # Wait for result
        try:
            return loop.run_until_complete(asyncio.wait_for(future, timeout=timeout or 300.0))
        finally:
            loop.close()

    async def ask_async(
        self,
        prompt: str,
        system: Optional[str] = None,
        priority: LLMPriority = LLMPriority.BACKGROUND,
        timeout: Optional[float] = None
    ) -> str:
        """
        Asynchronous LLM request with priority.

        Args:
            prompt: The prompt to send
            system: Optional system prompt
            priority: Priority level for this request
            timeout: Optional timeout in seconds

        Returns:
            LLM response
        """
        future = asyncio.get_event_loop().create_future()

        request = LLMRequest(
            prompt=prompt,
            system_prompt=system or ENHANCED_SYSTEM_PROMPT,
            priority=priority,
            future=future,
        )

        self._enqueue_request(request)

        return await asyncio.wait_for(future, timeout=timeout or 300.0)

    def _enqueue_request(self, request: LLMRequest) -> None:
        """Add request to priority queue."""
        with self._queue_condition:
            # Insert maintaining priority order (highest first)
            inserted = False
            for i, existing in enumerate(self._request_queue):
                if request < existing:
                    self._request_queue.insert(i, request)
                    inserted = True
                    break
            if not inserted:
                self._request_queue.append(request)
            # Notify worker thread that a request is available
            self._queue_condition.notify()

        _priority_trace(f"3 REQUEST_ENQUEUED priority={request.priority.name} queue={len(self._request_queue)} request_id={request.request_id[:8]}")

    def chat_started(self) -> None:
        """Signal that chat activity has started - autonomy should yield."""
        import threading
        thread = threading.current_thread()
        _priority_trace("CHAT_STARTED_INTERNAL", f"thread={thread.name}")
        with self._chat_active_lock:
            if not self._chat_active:
                self._chat_active = True
                self._chat_last_activity = time.time()
                logger.debug("[PriorityLLM] Chat started - autonomy will yield")
        # Notify waiting worker threads (they'll check should_yield and requeue if needed)
        with self._queue_condition:
            self._queue_condition.notify_all()

    def chat_ended(self) -> None:
        """Signal that chat activity has ended - autonomy may resume."""
        import threading
        thread = threading.current_thread()
        _priority_trace("CHAT_ENDED_INTERNAL", f"thread={thread.name}")
        with self._chat_active_lock:
            self._chat_active = False
            self._chat_last_activity = time.time()
            logger.debug("[PriorityLLM] Chat ended - autonomy may resume")
        # Notify all waiting worker threads that chat ended - they can resume
        with self._queue_condition:
            self._queue_condition.notify_all()

    def chat_activity(self) -> None:
        """Record chat activity (heartbeat to keep priority)."""
        with self._chat_active_lock:
            self._chat_last_activity = time.time()
            if not self._chat_active:
                self._chat_active = True

    def is_chat_active(self) -> bool:
        """Check if chat is currently active."""
        with self._chat_active_lock:
            return self._chat_active

    def get_stats(self) -> Dict[str, Any]:
        """Get provider statistics."""
        with self._stats_lock:
            stats = dict(self._stats)
        stats['queue_size'] = len(self._request_queue)
        stats['chat_active'] = self.is_chat_active()
        return stats

    def shutdown(self) -> None:
        """Shutdown the provider."""
        self._shutdown_event.set()
        # Notify the worker thread to wake up from wait and check shutdown
        with self._queue_condition:
            self._queue_condition.notify_all()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5.0)
        logger.info("[PriorityLLM] Shutdown complete")


# Global instance
_priority_llm: Optional[PriorityLLMProvider] = None
_priority_llm_lock = threading.Lock()


def get_priority_llm(llm: Optional[LLM] = None) -> PriorityLLMProvider:
    """Get or create the global priority LLM provider."""
    global _priority_llm
    with _priority_llm_lock:
        if _priority_llm is None:
            if llm is None:
                llm = LLM()
            _priority_llm = PriorityLLMProvider(llm)
        return _priority_llm


def set_priority_llm(provider: PriorityLLMProvider) -> None:
    """Set the global priority LLM provider."""
    global _priority_llm
    with _priority_llm_lock:
        _priority_llm = provider