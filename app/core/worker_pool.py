"""
WorkerPool - Reusable worker execution system for Freya.

Provides a standardized worker pool for background task execution with:
- Task queue with priority support
- Worker management and lifecycle
- Background execution with configurable concurrency
- Job submission with futures/promises
- Graceful shutdown with drain support
- Error isolation and retry hooks
- Progress reporting and callbacks
- Resource monitoring and backpressure
"""

import asyncio
import threading
import time
import queue
import weakref
from abc import ABC, abstractmethod
from collections import defaultdict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, Generic, List, Optional, Set, TypeVar, Union
from uuid import uuid4

from app.core.logger import logger
from app.core.events import EventBus, get_event_bus, Event, EventPriority
from app.core.observability import get_observability_hub, MetricPoint


T = TypeVar("T")


class WorkerStatus(Enum):
    """Status of a worker."""
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


class TaskStatus(Enum):
    """Status of a task."""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


class TaskPriority(Enum):
    """Task priority levels."""
    LOW = 0
    NORMAL = 50
    HIGH = 100
    CRITICAL = 200


@dataclass
class RetryPolicy:
    """Configuration for task retry behavior."""
    max_retries: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0
    exponential_base: float = 2.0
    retry_on: tuple = (Exception,)

    def calculate_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt number."""
        delay = self.base_delay_seconds * (self.exponential_base ** attempt)
        return min(delay, self.max_delay_seconds)


@dataclass
class Task(Generic[T]):
    """Represents a unit of work."""
    func: Callable[..., T]
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)
    priority: TaskPriority = TaskPriority.NORMAL
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    timeout_seconds: Optional[float] = None
    tags: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Internal state
    task_id: str = field(default_factory=lambda: f"task_{uuid4().hex[:12]}")
    status: TaskStatus = TaskStatus.PENDING
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    attempt: int = 0
    result: Optional[T] = None
    error: Optional[str] = None
    progress: float = 0.0
    progress_message: str = ""
    future: Optional[Future] = None
    _cancel_event: threading.Event = field(default_factory=threading.Event, init=False)

    def __post_init__(self):
        if self._cancel_event is None:
            self._cancel_event = threading.Event()

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def cancel(self) -> bool:
        """Cancel the task if not yet running."""
        if self.status in (TaskStatus.PENDING, TaskStatus.QUEUED):
            self._cancel_event.set()
            self.status = TaskStatus.CANCELLED
            if self.future and not self.future.done():
                self.future.cancel()
            return True
        return False

    def update_progress(self, progress: float, message: str = "") -> None:
        """Update task progress (0.0 to 1.0)."""
        self.progress = max(0.0, min(1.0, progress))
        self.progress_message = message

    def get_summary(self) -> Dict[str, Any]:
        """Get task summary."""
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "priority": self.priority.value,
            "attempt": self.attempt,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "progress": self.progress,
            "progress_message": self.progress_message,
            "tags": self.tags,
            "has_result": self.result is not None,
            "has_error": self.error is not None,
        }


@dataclass
class Worker:
    """Represents a worker in the pool."""
    worker_id: str
    name: str
    status: WorkerStatus = WorkerStatus.IDLE
    current_task: Optional[Task] = None
    tasks_completed: int = 0
    tasks_failed: int = 0
    started_at: Optional[str] = None
    last_activity: Optional[str] = None
    thread: Optional[threading.Thread] = None

    def get_summary(self) -> Dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "name": self.name,
            "status": self.status.value,
            "current_task": self.current_task.task_id if self.current_task else None,
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
            "started_at": self.started_at,
            "last_activity": self.last_activity,
        }


class WorkerPool:
    """
    Thread pool for executing background tasks.

    Features:
    - Configurable worker count
    - Priority task queue
    - Task submission with futures
    - Progress callbacks
    - Graceful shutdown with drain
    - Retry with exponential backoff
    - Metrics and monitoring
    - Worker lifecycle management
    """

    def __init__(
        self,
        name: str = "WorkerPool",
        min_workers: int = 1,
        max_workers: int = 10,
        queue_size: int = 0,  # 0 = unlimited
        event_bus: Optional[EventBus] = None,
        observability: Optional[Any] = None,
    ):
        """
        Initialize the worker pool.

        Args:
            name: Pool name for identification
            min_workers: Minimum number of workers to keep alive
            max_workers: Maximum number of workers
            queue_size: Maximum queue size (0 = unlimited)
            event_bus: Optional event bus for lifecycle events
            observability: Optional observability hub for metrics
        """
        self.name = name
        self.min_workers = min_workers
        self.max_workers = max_workers
        self.queue_size = queue_size

        self._event_bus = event_bus or get_event_bus()
        self._observability = observability or get_observability_hub()

        # Task queue with priority
        if queue_size > 0:
            self._queue: queue.PriorityQueue = queue.PriorityQueue(maxsize=queue_size)
        else:
            self._queue = queue.PriorityQueue()

        # Worker management
        self._workers: Dict[str, Worker] = {}
        self._worker_counter = 0
        self._worker_lock = threading.RLock()

        # Task tracking
        self._tasks: Dict[str, Task] = {}
        self._task_lock = threading.RLock()

        # Shutdown control
        self._shutdown = False
        self._shutdown_event = threading.Event()
        self._drain_mode = False

        # Thread pool for workers
        self._executor: Optional[ThreadPoolExecutor] = None

        # Statistics
        self._stats = {
            "tasks_submitted": 0,
            "tasks_completed": 0,
            "tasks_failed": 0,
            "tasks_cancelled": 0,
            "tasks_retried": 0,
            "total_execution_time": 0.0,
        }
        self._stats_lock = threading.Lock()

        # Progress callbacks
        self._progress_callbacks: Dict[str, List[Callable[[Task], None]]] = defaultdict(list)

        # Start minimum workers
        self._start_workers(min_workers)

        logger.info(f"WorkerPool '{name}' started (workers={min_workers}/{max_workers})")
        self._emit_event("pool.started", {"name": name, "min_workers": min_workers, "max_workers": max_workers})

    def _start_workers(self, count: int) -> None:
        """Start the specified number of workers."""
        with self._worker_lock:
            for _ in range(count):
                self._start_single_worker()

    def _start_single_worker(self) -> Worker:
        """Start a single worker."""
        self._worker_counter += 1
        worker_id = f"{self.name}_worker_{self._worker_counter}"
        worker = Worker(
            worker_id=worker_id,
            name=worker_id,
            status=WorkerStatus.STARTING,
        )

        def worker_loop():
            worker.status = WorkerStatus.RUNNING
            worker.started_at = datetime.now(timezone.utc).isoformat()
            self._record_metric("workers.started", 1)

            while not self._shutdown:
                try:
                    # Get task from queue with timeout
                    try:
                        priority, task = self._queue.get(timeout=1.0)
                    except queue.Empty:
                        # Check if we should scale down
                        if self._should_scale_down():
                            break
                        continue

                    if self._shutdown or self._drain_mode:
                        self._queue.put((priority, task))
                        break

                    # Execute task
                    self._execute_task(worker, task)

                except Exception as e:
                    logger.error(f"Worker {worker.worker_id} error: {e}")
                    worker.status = WorkerStatus.ERROR
                    time.sleep(1.0)  # Brief pause before retry

            worker.status = WorkerStatus.STOPPED
            self._record_metric("workers.stopped", 1)

        worker.thread = threading.Thread(target=worker_loop, name=worker.name, daemon=True)
        worker.thread.start()

        self._workers[worker_id] = worker
        self._emit_event("worker.started", worker.get_summary())

        return worker

    def _should_scale_down(self) -> bool:
        """Check if we should scale down workers."""
        with self._worker_lock:
            if len(self._workers) <= self.min_workers:
                return False
            # Check if all workers are idle
            idle_count = sum(1 for w in self._workers.values() if w.status == WorkerStatus.IDLE)
            return idle_count > self.min_workers

    def _execute_task(self, worker: Worker, task: Task) -> None:
        """Execute a single task."""
        worker.status = WorkerStatus.RUNNING
        worker.current_task = task
        worker.last_activity = datetime.now(timezone.utc).isoformat()

        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now(timezone.utc).isoformat()
        task.attempt += 1

        self._emit_event("task.started", task.get_summary())
        self._record_metric("tasks.started", 1)

        start_time = time.time()
        error = None

        try:
            # Check cancellation
            if task.is_cancelled():
                task.status = TaskStatus.CANCELLED
                task.error = "Cancelled before execution"
                self._handle_task_complete(worker, task, success=False)
                return

            # Execute with timeout if specified
            if task.timeout_seconds:
                result = self._execute_with_timeout(task, task.timeout_seconds)
            else:
                result = task.func(*task.args, **task.kwargs)

            # Check cancellation after execution
            if task.is_cancelled():
                task.status = TaskStatus.CANCELLED
                task.error = "Cancelled during execution"
                self._handle_task_complete(worker, task, success=False)
                return

            # Success
            task.result = result
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now(timezone.utc).isoformat()
            task.progress = 1.0

            duration = time.time() - start_time
            self._handle_task_complete(worker, task, success=True, duration=duration)

        except Exception as e:
            error = str(e)
            duration = time.time() - start_time

            # Handle retry logic
            if task.attempt < task.retry_policy.max_retries and isinstance(e, task.retry_policy.retry_on):
                task.status = TaskStatus.RETRYING
                delay = task.retry_policy.calculate_delay(task.attempt)

                self._emit_event("task.retrying", {
                    **task.get_summary(),
                    "error": error,
                    "attempt": task.attempt,
                    "delay": delay,
                })
                self._record_metric("tasks.retried", 1)

                with self._stats_lock:
                    self._stats["tasks_retried"] += 1

                # Re-queue with delay
                time.sleep(delay)
                if not self._shutdown and not task.is_cancelled():
                    self._queue.put((-task.priority.value, task))
                else:
                    task.status = TaskStatus.CANCELLED
                    self._handle_task_complete(worker, task, success=False, error=error)
            else:
                # Max retries exceeded or non-retryable error
                task.error = error
                task.status = TaskStatus.FAILED
                task.completed_at = datetime.now(timezone.utc).isoformat()
                self._handle_task_complete(worker, task, success=False, error=error, duration=duration)

    def _execute_with_timeout(self, task: Task, timeout: float) -> Any:
        """Execute task with timeout using a future."""
        future = self._executor.submit(task.func, *task.args, **task.kwargs)
        task.future = future
        return future.result(timeout=timeout)

    def _handle_task_complete(
        self,
        worker: Worker,
        task: Task,
        success: bool,
        error: Optional[str] = None,
        duration: float = 0.0,
    ) -> None:
        """Handle task completion."""
        worker.tasks_completed += 1 if success else 0
        worker.tasks_failed += 0 if success else 1
        worker.current_task = None
        worker.status = WorkerStatus.IDLE
        worker.last_activity = datetime.now(timezone.utc).isoformat()

        # Update stats
        with self._stats_lock:
            if success:
                self._stats["tasks_completed"] += 1
            else:
                self._stats["tasks_failed"] += 1
            self._stats["total_execution_time"] += duration

        # Remove from tracking
        with self._task_lock:
            self._tasks.pop(task.task_id, None)

        # Emit completion event
        event_name = "task.completed" if success else "task.failed"
        self._emit_event(event_name, {
            **task.get_summary(),
            "duration": duration,
            "error": error,
        })

        # Record metrics
        self._record_metric(f"tasks.{event_name.split('.')[1]}", 1, {"duration": duration})

        # Call progress callbacks
        for callback in self._progress_callbacks.get("completed" if success else "failed", []):
            try:
                callback(task)
            except Exception as e:
                logger.warning(f"Progress callback error: {e}")

        # Resolve future
        if task.future and not task.future.done():
            if success:
                task.future.set_result(task.result)
            else:
                task.future.set_exception(Exception(error or "Task failed"))

    def submit(
        self,
        func: Callable[..., T],
        *args,
        priority: TaskPriority = TaskPriority.NORMAL,
        retry_policy: Optional[RetryPolicy] = None,
        timeout_seconds: Optional[float] = None,
        tags: Optional[Dict[str, str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Future:
        """
        Submit a task for execution.

        Args:
            func: Function to execute
            *args: Positional arguments
            priority: Task priority
            retry_policy: Retry configuration
            timeout_seconds: Execution timeout
            tags: Tags for filtering
            metadata: Additional metadata
            **kwargs: Keyword arguments

        Returns:
            Future that will contain the result
        """
        if self._shutdown:
            raise RuntimeError(f"WorkerPool '{self.name}' is shutdown")

        task = Task(
            func=func,
            args=args,
            kwargs=kwargs,
            priority=priority,
            retry_policy=retry_policy or RetryPolicy(),
            timeout_seconds=timeout_seconds,
            tags=tags or {},
            metadata=metadata or {},
        )

        future = Future()
        task.future = future

        with self._task_lock:
            self._tasks[task.task_id] = task

        # Add to queue (negative priority for max-heap behavior)
        self._queue.put((-priority.value, task))
        task.status = TaskStatus.QUEUED

        # Scale up if needed
        self._scale_up_if_needed()

        # Update stats
        with self._stats_lock:
            self._stats["tasks_submitted"] += 1

        self._emit_event("task.submitted", task.get_summary())
        self._record_metric("tasks.submitted", 1)

        logger.debug(f"Task {task.task_id} submitted to {self.name} (priority={priority.value})")
        return future

    def _scale_up_if_needed(self) -> None:
        """Scale up workers if queue is backing up."""
        with self._worker_lock:
            if len(self._workers) >= self.max_workers:
                return

            # Count idle workers
            idle = sum(1 for w in self._workers.values() if w.status == WorkerStatus.IDLE)
            queue_size = self._queue.qsize()

            # If queue has more items than idle workers, add a worker
            if queue_size > idle and len(self._workers) < self.max_workers:
                self._start_single_worker()

    def submit_batch(
        self,
        tasks: List[Callable[..., T]],
        *args_list,
        priority: TaskPriority = TaskPriority.NORMAL,
        **kwargs,
    ) -> List[Future]:
        """Submit multiple tasks at once."""
        futures = []
        for i, func in enumerate(tasks):
            task_args = args_list[i] if i < len(args_list) else ()
            future = self.submit(func, *task_args, priority=priority, **kwargs)
            futures.append(future)
        return futures

    def map(self, func: Callable[..., T], iterable, **submit_kwargs) -> List[Future]:
        """Map function over iterable, submitting each as a task."""
        return [self.submit(func, item, **submit_kwargs) for item in iterable]

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID."""
        with self._task_lock:
            return self._tasks.get(task_id)

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a pending task."""
        with self._task_lock:
            task = self._tasks.get(task_id)
            if task and task.cancel():
                self._emit_event("task.cancelled", task.get_summary())
                with self._stats_lock:
                    self._stats["tasks_cancelled"] += 1
                return True
        return False

    def add_progress_callback(self, event: str, callback: Callable[[Task], None]) -> None:
        """Add a progress callback for task events (completed, failed, started)."""
        self._progress_callbacks[event].append(callback)

    def remove_progress_callback(self, event: str, callback: Callable[[Task], None]) -> bool:
        """Remove a progress callback."""
        if callback in self._progress_callbacks.get(event, []):
            self._progress_callbacks[event].remove(callback)
            return True
        return False

    def get_workers(self) -> List[Worker]:
        """Get all workers."""
        with self._worker_lock:
            return list(self._workers.values())

    def get_active_tasks(self) -> List[Task]:
        """Get all currently active tasks."""
        with self._task_lock:
            return [t for t in self._tasks.values() if t.status in (TaskStatus.QUEUED, TaskStatus.RUNNING)]

    def get_pending_tasks(self) -> List[Task]:
        """Get all pending/queued tasks."""
        with self._task_lock:
            return [t for t in self._tasks.values() if t.status == TaskStatus.QUEUED]

    def get_stats(self) -> Dict[str, Any]:
        """Get pool statistics."""
        with self._worker_lock:
            workers = list(self._workers.values())

        with self._stats_lock:
            stats = dict(self._stats)

        with self._task_lock:
            task_status_counts = defaultdict(int)
            for task in self._tasks.values():
                task_status_counts[task.status.value] += 1

        stats.update({
            "name": self.name,
            "worker_count": len(workers),
            "min_workers": self.min_workers,
            "max_workers": self.max_workers,
            "idle_workers": sum(1 for w in workers if w.status == WorkerStatus.IDLE),
            "busy_workers": sum(1 for w in workers if w.status == WorkerStatus.RUNNING),
            "queue_size": self._queue.qsize(),
            "task_status_counts": dict(task_status_counts),
            "shutdown": self._shutdown,
            "drain_mode": self._drain_mode,
        })

        return stats

    def get_worker_stats(self) -> List[Dict[str, Any]]:
        """Get per-worker statistics."""
        with self._worker_lock:
            return [w.get_summary() for w in self._workers.values()]

    def wait_for_completion(self, timeout: Optional[float] = None) -> bool:
        """Wait for all queued tasks to complete."""
        start = time.time()
        while True:
            if self._shutdown:
                return True

            with self._task_lock:
                active = [t for t in self._tasks.values() if t.status in (TaskStatus.QUEUED, TaskStatus.RUNNING)]
                if not active and self._queue.empty():
                    return True

            if timeout and (time.time() - start) >= timeout:
                return False

            time.sleep(0.1)

    def drain(self, wait: bool = True, timeout: Optional[float] = None) -> None:
        """Stop accepting new tasks and wait for current ones to complete."""
        logger.info(f"WorkerPool '{self.name}' entering drain mode")
        self._drain_mode = True
        self._emit_event("pool.drain_started", {"name": self.name})

        if wait:
            self.wait_for_completion(timeout)

    def shutdown(self, wait: bool = True, timeout: Optional[float] = None, force: bool = False) -> None:
        """Shutdown the worker pool."""
        logger.info(f"Shutting down WorkerPool '{self.name}' (wait={wait}, force={force})")
        self._shutdown = True
        self._drain_mode = True
        self._shutdown_event.set()

        # Cancel all pending tasks
        if force:
            with self._task_lock:
                for task in self._tasks.values():
                    if task.status in (TaskStatus.PENDING, TaskStatus.QUEUED):
                        task.cancel()

        # Wait for workers to finish
        if wait:
            with self._worker_lock:
                workers = list(self._workers.values())

            for worker in workers:
                if worker.thread and worker.thread.is_alive():
                    worker.thread.join(timeout=timeout / max(len(workers), 1) if timeout else 5.0)

        # Shutdown executor
        if self._executor:
            self._executor.shutdown(wait=wait)

        self._emit_event("pool.shutdown", {"name": self.name, "forced": force})
        logger.info(f"WorkerPool '{self.name}' shutdown complete")

    def _emit_event(self, name: str, data: Dict) -> None:
        """Emit a lifecycle event."""
        self._event_bus.emit(
            name,
            data=data,
            source=f"WorkerPool:{self.name}",
            priority=EventPriority.NORMAL,
        )

    def _record_metric(self, name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Record a metric."""
        try:
            self._observability.record_metric(
                f"workerpool.{self.name}.{name}",
                value,
                labels=labels or {},
            )
        except Exception:
            pass  # Metrics are best-effort

    def __enter__(self) -> "WorkerPool":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.shutdown(wait=True)


# === Specialized pools ===

class AsyncWorkerPool:
    """
    Async-friendly worker pool for I/O-bound tasks.
    Uses asyncio for task management.
    """

    def __init__(
        self,
        name: str = "AsyncWorkerPool",
        max_workers: int = 100,
        event_bus: Optional[EventBus] = None,
    ):
        self.name = name
        self.max_workers = max_workers
        self._event_bus = event_bus or get_event_bus()
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._running = False
        self._tasks: Dict[str, asyncio.Task] = {}

    async def start(self) -> None:
        """Start the async pool."""
        if self._running:
            return
        self._running = True
        self._semaphore = asyncio.Semaphore(self.max_workers)
        logger.info(f"AsyncWorkerPool '{self.name}' started (max_workers={self.max_workers})")

    async def submit(self, coro, *args, **kwargs) -> Any:
        """Submit a coroutine for execution."""
        if not self._running:
            await self.start()

        async with self._semaphore:
            return await coro(*args, **kwargs)

    async def map(self, coro, iterable, **kwargs) -> List[Any]:
        """Map coroutine over iterable."""
        tasks = [self.submit(coro, item, **kwargs) for item in iterable]
        return await asyncio.gather(*tasks)

    async def shutdown(self, wait: bool = True) -> None:
        """Shutdown the async pool."""
        self._running = False
        if wait and self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
        logger.info(f"AsyncWorkerPool '{self.name}' shutdown complete")


# === Global pool management ===

_default_pool: Optional[WorkerPool] = None
_pool_lock = threading.Lock()


def get_worker_pool(
    name: str = "default",
    min_workers: int = 2,
    max_workers: int = 10,
) -> WorkerPool:
    """Get or create the global default worker pool."""
    global _default_pool
    with _pool_lock:
        if _default_pool is None:
            _default_pool = WorkerPool(
                name=name,
                min_workers=min_workers,
                max_workers=max_workers,
            )
        return _default_pool


def set_worker_pool(pool: WorkerPool) -> None:
    """Set the global default worker pool."""
    global _default_pool
    with _pool_lock:
        if _default_pool:
            _default_pool.shutdown(wait=False)
        _default_pool = pool


def shutdown_worker_pool(wait: bool = True) -> None:
    """Shutdown the global default worker pool."""
    global _default_pool
    with _pool_lock:
        if _default_pool:
            _default_pool.shutdown(wait=wait)
            _default_pool = None


# === Convenience functions ===

def run_in_pool(
    func: Callable[..., T],
    *args,
    pool: Optional[WorkerPool] = None,
    **kwargs,
) -> Future:
    """Submit a task to a worker pool (default if not specified)."""
    p = pool or get_worker_pool()
    return p.submit(func, *args, **kwargs)


def run_in_pool_async(
    coro,
    *args,
    pool: Optional[AsyncWorkerPool] = None,
    **kwargs,
) -> Any:
    """Submit a coroutine to an async worker pool."""
    p = pool or AsyncWorkerPool()
    return p.submit(coro, *args, **kwargs)