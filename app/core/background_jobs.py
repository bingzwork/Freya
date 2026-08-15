"""
BackgroundJobService - Unified background execution service for Freya.

Consolidates scheduling and background execution from:
- app/planner/scheduler.py (task scheduling)
- app/autonomous_learning/scheduler.py (periodic learning)
- app/long_term_autonomy/scheduler.py (general background jobs)

Provides a single service for:
- Background jobs (one-time, recurring, delayed)
- Scheduled jobs with cron-like expressions
- Job lifecycle management (pause, resume, cancel)
- Retry support with exponential backoff
- Graceful shutdown
- Status tracking and monitoring
- Thread-safe operations
- Chat-aware scheduling (yields to chat/conversation)
"""

import asyncio
import threading
import time
import heapq
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
from uuid import uuid4
from collections import defaultdict

from app.core.logger import logger
from app.core.events import EventBus, get_event_bus, Event, EventPriority
from pathlib import Path
import json


class ChatActivityProvider:
    """
    Interface for checking chat activity status.
    Allows BackgroundJobService to yield to chat without tight coupling.
    """
    def is_chat_active(self) -> bool:
        """Check if chat is currently active."""
        return False

    def wait_for_chat_idle(self, timeout: float = 0.1) -> bool:
        """Wait for chat to become idle. Returns True if idle, False if timeout."""
        return True


class JobStatus(Enum):
    """Status of a background job."""
    PENDING = "pending"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"
    RETRYING = "retrying"


class JobType(Enum):
    """Type of job."""
    ONE_TIME = "one_time"
    RECURRING = "recurring"
    DELAYED = "delayed"
    CRON = "cron"


@dataclass
class JobResult:
    """Result of a job execution."""
    success: bool
    result: Any = None
    error: Optional[str] = None
    duration_seconds: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class RetryConfig:
    """Configuration for job retry behavior."""
    max_retries: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0
    exponential_base: float = 2.0
    retry_on: tuple = (Exception,)


class JobTriggerType(Enum):
    """Type of job trigger."""
    ONE_TIME = "one_time"
    RECURRING = "recurring"
    DELAYED = "delayed"
    CRON = "cron"


class JobPriority(Enum):
    """Priority level for job execution."""
    LOW = 0
    NORMAL = 50
    HIGH = 100
    CRITICAL = 200


@dataclass
class JobTriggerConfig:
    """Configuration for job trigger."""
    type: JobTriggerType = JobTriggerType.ONE_TIME
    interval_seconds: float = 0.0
    cron_expression: str = ""
    delay_seconds: float = 0.0
    max_runs: Optional[int] = None


def _cron_field_matches(value: int, field: str, minimum: int, maximum: int) -> bool:
    """Evaluate one standard cron field without adding a second scheduler."""
    for part in field.split(","):
        if part == "*":
            return True
        if "/" in part:
            base, step_text = part.split("/", 1)
            try:
                step = int(step_text)
            except ValueError:
                continue
            if step <= 0:
                continue
            start = minimum if base == "*" else int(base)
            if start <= value <= maximum and (value - start) % step == 0:
                return True
            continue
        if "-" in part:
            try:
                start_text, end_text = part.split("-", 1)
                if int(start_text) <= value <= int(end_text):
                    return True
            except ValueError:
                continue
            continue
        try:
            if int(part) == value:
                return True
        except ValueError:
            continue
    return False


def _next_cron_time(expression: str, after_timestamp: float) -> Optional[float]:
    """Return the next matching minute for a five-field cron expression."""
    fields = expression.split()
    if len(fields) != 5:
        return None
    candidate = datetime.fromtimestamp(after_timestamp, timezone.utc).replace(
        second=0, microsecond=0
    ) + timedelta(minutes=1)
    for _ in range(366 * 24 * 60):
        if (
            _cron_field_matches(candidate.minute, fields[0], 0, 59)
            and _cron_field_matches(candidate.hour, fields[1], 0, 23)
            and _cron_field_matches(candidate.day, fields[2], 1, 31)
            and _cron_field_matches(candidate.month, fields[3], 1, 12)
            and _cron_field_matches((candidate.weekday() + 1) % 7, fields[4], 0, 7)
        ):
            return candidate.timestamp()
        candidate += timedelta(minutes=1)
    return None


@dataclass
class Job:
    """Represents a background job."""
    id: str = field(default_factory=lambda: f"job_{uuid4().hex[:12]}")
    name: str = ""
    func: Callable = None
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)

    # Job type and scheduling
    job_type: JobType = JobType.ONE_TIME
    trigger_time: Optional[float] = None  # Unix timestamp
    interval_seconds: float = 0.0  # For recurring jobs
    cron_expression: str = ""  # For cron jobs (future)

    # Retry configuration
    retry_config: RetryConfig = field(default_factory=RetryConfig)
    current_retry: int = 0

    # Lifecycle
    max_runs: Optional[int] = None  # None = unlimited for recurring
    run_count: int = 0
    status: JobStatus = JobStatus.PENDING

    # Metadata
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    last_error: Optional[str] = None
    tags: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Result history (limited)
    result_history: List[JobResult] = field(default_factory=list)
    max_result_history: int = 10

    # Internal
    _cancel_event: threading.Event = field(default_factory=threading.Event, init=False)
    _pause_event: threading.Event = field(default_factory=threading.Event, init=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False)

    def __post_init__(self):
        if self._cancel_event is None:
            self._cancel_event = threading.Event()
        if self._pause_event is None:
            self._pause_event = threading.Event()
            self._pause_event.clear()  # Not paused by default
        if self._lock is None:
            self._lock = threading.RLock()

        # Default trigger time to now if not set
        if self.trigger_time is None and self.job_type != JobType.CRON:
            self.trigger_time = time.time()

        # Set default name if not provided
        if not self.name and self.func:
            self.name = getattr(self.func, '__name__', 'anonymous_job')

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def is_paused(self) -> bool:
        return self._pause_event.is_set()

    def cancel(self) -> None:
        """Cancel the job."""
        with self._lock:
            self._cancel_event.set()
            self._pause_event.set()  # Unblock if waiting
            self.status = JobStatus.CANCELLED

    def pause(self) -> None:
        """Pause the job."""
        with self._lock:
            self._pause_event.set()
            if self.status == JobStatus.SCHEDULED or self.status == JobStatus.PENDING:
                self.status = JobStatus.PAUSED

    def resume(self) -> None:
        """Resume the job."""
        with self._lock:
            self._pause_event.clear()
            if self.status == JobStatus.PAUSED:
                self.status = JobStatus.SCHEDULED

    def next_run_time(self) -> Optional[float]:
        """Calculate the next run time."""
        if self.job_type == JobType.ONE_TIME:
            return self.trigger_time if self.run_count == 0 else None
        elif self.job_type == JobType.RECURRING:
            if self.interval_seconds <= 0:
                return None
            return self.trigger_time + (self.run_count * self.interval_seconds)
        elif self.job_type == JobType.DELAYED:
            return self.trigger_time
        elif self.job_type == JobType.CRON:
            if not self.cron_expression:
                return None
            candidate = self.trigger_time or time.time()
            for _ in range(self.run_count + 1):
                next_candidate = _next_cron_time(self.cron_expression, candidate)
                if next_candidate is None:
                    return None
                candidate = next_candidate
            return candidate
        return None

    def is_ready(self, current_time: float) -> bool:
        """Check if the job is ready to run."""
        with self._lock:
            if self.is_cancelled():
                return False
            if self.is_paused():
                return False
            if self.status == JobStatus.COMPLETED:
                return False
            if self.max_runs is not None and self.run_count >= self.max_runs:
                self.status = JobStatus.COMPLETED
                return False

            next_run = self.next_run_time()
            if next_run is None:
                return False
            return current_time >= next_run

    def should_retry(self) -> bool:
        """Check if job should be retried."""
        return (
            self.current_retry < self.retry_config.max_retries and
            self.last_error is not None
        )

    def calculate_retry_delay(self) -> float:
        """Calculate delay before next retry."""
        delay = self.retry_config.base_delay_seconds * (
            self.retry_config.exponential_base ** self.current_retry
        )
        return min(delay, self.retry_config.max_delay_seconds)

    def add_result(self, result: JobResult) -> None:
        """Add execution result to history."""
        with self._lock:
            self.result_history.append(result)
            if len(self.result_history) > self.max_result_history:
                self.result_history = self.result_history[-self.max_result_history:]

    def get_summary(self) -> Dict[str, Any]:
        """Get job summary."""
        with self._lock:
            return {
                "id": self.id,
                "name": self.name,
                "type": self.job_type.value,
                "status": self.status.value,
                "run_count": self.run_count,
                "max_runs": self.max_runs,
                "current_retry": self.current_retry,
                "created_at": self.created_at,
                "started_at": self.started_at,
                "completed_at": self.completed_at,
                "last_error": self.last_error,
                "tags": self.tags,
                "next_run": self.next_run_time(),
            }


class BackgroundJobService:
    """
    Unified background job service for Freya.

    Consolidates all background execution into a single service.
    Supports one-time, recurring, delayed, and cron jobs with
    full lifecycle management, retries, and monitoring.
    """

    def __init__(
        self,
        tick_interval: float = 1.0,
        max_workers: int = 10,
        event_bus: Optional[EventBus] = None,
    ):
        """
        Initialize the background job service.

        Args:
            tick_interval: How often the scheduler checks for ready jobs (seconds)
            max_workers: Maximum concurrent job executions
            event_bus: Optional event bus for job lifecycle events
        """
        self._tick_interval = tick_interval
        self._max_workers = max_workers
        self._event_bus = event_bus or get_event_bus()

        # Job storage
        self._jobs: Dict[str, Job] = {}
        self._jobs_by_tag: Dict[str, Set[str]] = defaultdict(set)
        self._lock = threading.RLock()

        # Execution control
        self._shutdown = False
        self._worker_semaphore = threading.Semaphore(max_workers)
        self._scheduler_thread: Optional[threading.Thread] = None
        self._worker_threads: Set[threading.Thread] = set()
        self._worker_lock = threading.Lock()

        # Chat activity provider - for yielding to chat/conversation
        self._chat_activity_provider: ChatActivityProvider = ChatActivityProvider()

        # Statistics
        self._stats = {
            "total_jobs_created": 0,
            "total_jobs_completed": 0,
            "total_jobs_failed": 0,
            "total_jobs_cancelled": 0,
            "total_jobs_retried": 0,
        }
        self._stats_lock = threading.Lock()
        # Job execution history
        self._history_file = Path("data/scheduling/job_history.json")
        self._history_file.parent.mkdir(parents=True, exist_ok=True)
        self._job_history: List[Dict[str, Any]] = []
        self._max_history_size = 10000
        self._history_lock = threading.RLock()
        self._load_history()

    def _load_history(self) -> None:
        """Load job execution history from disk."""
        try:
            if self._history_file.exists():
                with self._history_file.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self._job_history = data
                        # Trim to max size
                        if len(self._job_history) > self._max_history_size:
                            self._job_history = self._job_history[-self._max_history_size:]
                    else:
                        self._job_history = []
        except Exception as e:
            logger.warning(f"Failed to load job history: {e}")
            self._job_history = []

    def _save_history(self) -> None:
        """Save job execution history to disk."""
        try:
            with self._history_file.parent.joinpath("job_history.json.tmp").open("w", encoding="utf-8") as f:
                json.dump(self._job_history, f, indent=2)
            # Atomic replace
            temp_file = self._history_file.parent.joinpath("job_history.json.tmp")
            temp_file.replace(self._history_file)
        except Exception as e:
            logger.error(f"Failed to save job history: {e}")

    def _record_job_execution(self, job: Job, job_result: JobResult) -> None:
        """Record job execution to history."""
        record = {
            "job_id": job.id,
            "job_name": job.name,
            "success": job_result.success,
            "duration_seconds": job_result.duration_seconds,
            "timestamp": job_result.timestamp,
            "error": job_result.error,
            "retry_count": job.current_retry,
        }
        with self._history_lock:
            self._job_history.append(record)
            if len(self._job_history) > self._max_history_size:
                self._job_history = self._job_history[-self._max_history_size:]
            self._save_history()

    def set_chat_activity_provider(self, provider: ChatActivityProvider) -> None:
        """
        Set the chat activity provider for chat-aware yielding.

        Args:
            provider: An object implementing ChatActivityProvider interface
        """
        self._chat_activity_provider = provider
        logger.info("[BackgroundJobService] Chat activity provider set")

    def start(self) -> None:
        """Explicitly start the background scheduler thread.

        This must be called after initialization to begin processing jobs.
        """
        if self._scheduler_thread is not None and self._scheduler_thread.is_alive():
            logger.warning("BackgroundJobService already started")
            return
        self._shutdown = False
        self._start_scheduler()

    def is_running(self) -> bool:
        """Return whether the scheduler thread is alive and accepting work."""
        return bool(
            not self._shutdown
            and self._scheduler_thread
            and self._scheduler_thread.is_alive()
        )

    def _start_scheduler(self) -> None:
        """Start the background scheduler thread."""
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop,
            name="BackgroundJobScheduler",
            daemon=True,
        )
        self._scheduler_thread.start()
        logger.info(f"BackgroundJobService started (tick={self._tick_interval}s, workers={self._max_workers})")

    def _scheduler_loop(self) -> None:
        """Main scheduler loop."""
        import threading
        import asyncio
        def _bg_trace(step: str, detail: str = ""):
            thread = threading.current_thread()
            task = None
            try:
                task = asyncio.current_task()
            except RuntimeError:
                pass
            task_id = id(task) if task else "no-loop"
            logger.debug(f"[CHAT] {step} thread={thread.name} thread_id={thread.ident} task_id={task_id} {detail}")

        while not self._shutdown:
            try:
                # YIELD TO CHAT: Check if chat is active and wait efficiently for it to become idle
                # Chat has absolute priority over background jobs
                if self._chat_activity_provider.is_chat_active():
                    _bg_trace("BG_YIELD_CHAT_START", "scheduler yielding")
                    logger.debug("[BackgroundJobService] Chat active - yielding scheduler tick")
                    # Wait efficiently for chat to end (no polling - uses Condition variable)
                    # Use a long timeout to allow periodic shutdown checks
                    self._chat_activity_provider.wait_for_chat_idle(timeout=60.0)
                    _bg_trace("BG_YIELD_CHAT_END", "scheduler resuming")
                    continue  # Re-check chat status after yielding

                now = time.time()
                ready_jobs = self._get_ready_jobs(now)

                for job in ready_jobs:
                    if self._shutdown:
                        break

                    # Check if we have worker capacity
                    if not self._worker_semaphore.acquire(blocking=False):
                        # No workers available, wait for next tick
                        break

                    # Execute job in worker thread
                    worker = threading.Thread(
                        target=self._execute_job,
                        args=(job,),
                        name=f"JobWorker-{job.id[:8]}",
                        daemon=True,
                    )
                    with self._worker_lock:
                        self._worker_threads.add(worker)
                    worker.start()

            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")
                time.sleep(1.0)  # Brief pause before continuing

            # Sleep until next tick
            time.sleep(self._tick_interval)

    def _get_ready_jobs(self, current_time: float) -> List[Job]:
        """Get jobs ready to run."""
        ready = []
        with self._lock:
            for job in self._jobs.values():
                if job.is_ready(current_time):
                    ready.append(job)
        # Sort by trigger time (FIFO)
        ready.sort(key=lambda j: j.next_run_time() or 0)
        return ready

    def _execute_job(self, job: Job) -> None:
        """Execute a single job."""
        try:
            # Check cancellation/pause before starting
            if job.is_cancelled() or job.is_paused():
                return

            # Update job status
            with job._lock:
                job.status = JobStatus.RUNNING
                job.started_at = datetime.now(timezone.utc).isoformat()

            # Emit job started event
            self._emit_job_event("job.started", job)

            # Execute the function
            start_time = time.time()
            result = job.func(*job.args, **job.kwargs)
            duration = time.time() - start_time

            # Check if cancelled during execution
            if job.is_cancelled():
                return

            # Update job status
            with job._lock:
                job.run_count += 1
                job.completed_at = datetime.now(timezone.utc).isoformat()

                # Handle recurring/cron vs one-time without replacing the scheduler.
                is_recurring = (
                    job.job_type == JobType.RECURRING and job.interval_seconds > 0
                ) or job.job_type == JobType.CRON
                if is_recurring and (job.max_runs is None or job.run_count < job.max_runs):
                    job.status = JobStatus.SCHEDULED
                else:
                    job.status = JobStatus.COMPLETED

                # Record success
                job_result = JobResult(
                    success=True,
                    result=result,
                    duration_seconds=duration,
                )
                job.add_result(job_result)
                self._record_job_execution(job, job_result)
                job.last_error = None
                job.current_retry = 0

            # Emit job completed event
            self._emit_job_event("job.completed", job, {"result": result, "duration": duration})

            # Update stats
            with self._stats_lock:
                self._stats["total_jobs_completed"] += 1

            # Only log job completion for state changes: first run, after retry, or final completion
            # (not for recurring jobs that complete successfully and are rescheduled)
            is_recurring_rescheduled = (
                ((job.job_type == JobType.RECURRING and job.interval_seconds > 0) or job.job_type == JobType.CRON)
                and (job.max_runs is None or job.run_count < job.max_runs)
            )
            if not is_recurring_rescheduled or job.run_count == 1 or job.current_retry > 0:
                logger.debug(f"Job '{job.name}' ({job.id[:8]}) completed in {duration:.3f}s")

        except Exception as e:
            self._handle_job_error(job, e)
        finally:
            # Release worker semaphore
            self._worker_semaphore.release()
            with self._worker_lock:
                # Clean up finished worker threads
                current_thread = threading.current_thread()
                if current_thread in self._worker_threads:
                    self._worker_threads.discard(current_thread)

    def _handle_job_error(self, job: Job, error: Exception) -> None:
        """Handle job execution error."""
        error_msg = str(error)
        duration = 0.0

        if job.started_at:
            try:
                start = datetime.fromisoformat(job.started_at.replace('Z', '+00:00'))
                duration = (datetime.now(timezone.utc) - start).total_seconds()
            except Exception:
                pass

        with job._lock:
            job.last_error = error_msg

            # Check if should retry
            if job.should_retry() and isinstance(error, job.retry_config.retry_on):
                job.current_retry += 1
                job.status = JobStatus.RETRYING
                delay = job.calculate_retry_delay()

                # Schedule retry
                job.trigger_time = time.time() + delay

                job_result = JobResult(
                    success=False,
                    error=f"Retry {job.current_retry}/{job.retry_config.max_retries}: {error_msg}",
                    duration_seconds=duration,
                )
                job.add_result(job_result)
                self._record_job_execution(job, job_result)

                # Emit retry event
                self._emit_job_event("job.retrying", job, {
                    "error": error_msg,
                    "retry": job.current_retry,
                    "delay": delay,
                })

                with self._stats_lock:
                    self._stats["total_jobs_retried"] += 1

                logger.warning(f"Job '{job.name}' ({job.id[:8]}) failed, retry {job.current_retry}/{job.retry_config.max_retries} in {delay:.1f}s: {error_msg}")
            else:
                # Max retries exceeded or non-retryable error
                job.status = JobStatus.FAILED
                job.completed_at = datetime.now(timezone.utc).isoformat()

                job_result = JobResult(
                    success=False,
                    error=error_msg,
                    duration_seconds=duration,
                )
                job.add_result(job_result)
                self._record_job_execution(job, job_result)

                # Emit job failed event
                self._emit_job_event("job.failed", job, {"error": error_msg, "duration": duration})

                with self._stats_lock:
                    self._stats["total_jobs_failed"] += 1

                logger.error(f"Job '{job.name}' ({job.id[:8]}) failed: {error_msg}")

    def _emit_job_event(self, event_name: str, job: Job, data: Optional[Dict] = None) -> None:
        """Emit a job lifecycle event."""
        event_data = {
            "job_id": job.id,
            "job_name": job.name,
            "job_type": job.job_type.value,
            "status": job.status.value,
            "run_count": job.run_count,
            "tags": job.tags,
        }
        if data:
            event_data.update(data)
        correlation_id = job.metadata.get("correlation_id") or job.metadata.get("request_id")
        if correlation_id:
            event_data.setdefault("correlation_id", correlation_id)

        self._event_bus.emit(
            event_name,
            data=event_data,
            source="BackgroundJobService",
            priority=EventPriority.NORMAL,
            metadata={"correlation_id": correlation_id} if correlation_id else {},
        )

    # Public API

    def add_job(
        self,
        func: Callable,
        *,
        name: str = "",
        args: tuple = (),
        kwargs: dict = None,
        trigger_time: Optional[float] = None,
        delay_seconds: float = 0.0,
        interval_seconds: float = 0.0,
        max_runs: Optional[int] = None,
        retry_config: Optional[RetryConfig] = None,
        tags: Optional[Dict[str, str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Add a job to the service.

        Args:
            func: Function to execute
            name: Optional job name
            args: Positional arguments
            kwargs: Keyword arguments
            trigger_time: Absolute timestamp to run (Unix time)
            delay_seconds: Delay from now (alternative to trigger_time)
            interval_seconds: Interval for recurring jobs (0 = one-time)
            max_runs: Maximum runs for recurring jobs (None = unlimited)
            retry_config: Retry configuration
            tags: Tags for filtering
            metadata: Additional metadata

        Returns:
            Job ID
        """
        if kwargs is None:
            kwargs = {}
        if tags is None:
            tags = {}
        if metadata is None:
            metadata = {}

        # Determine job type
        if interval_seconds > 0:
            job_type = JobType.RECURRING
        elif delay_seconds > 0 or trigger_time is not None:
            job_type = JobType.DELAYED
        else:
            job_type = JobType.ONE_TIME

        # Calculate trigger time
        if trigger_time is None:
            trigger_time = time.time() + delay_seconds

        job = Job(
            name=name or getattr(func, '__name__', 'anonymous_job'),
            func=func,
            args=args,
            kwargs=kwargs,
            job_type=job_type,
            trigger_time=trigger_time,
            interval_seconds=interval_seconds,
            max_runs=max_runs,
            retry_config=retry_config or RetryConfig(),
            tags=tags,
            metadata=metadata,
        )

        with self._lock:
            self._jobs[job.id] = job
            for tag_key, tag_value in tags.items():
                tag = f"{tag_key}:{tag_value}"
                self._jobs_by_tag[tag].add(job.id)

            with self._stats_lock:
                self._stats["total_jobs_created"] += 1

        logger.info(f"Added job '{job.name}' ({job.id[:8]}) type={job_type.value}")
        self._emit_job_event("job.created", job)
        return job.id

    def schedule(
        self,
        job_id: str,
        func: Callable,
        trigger: JobTriggerConfig,
        *,
        priority: JobPriority = JobPriority.NORMAL,
        max_retries: int = 3,
        name: str = "",
        args: tuple = (),
        kwargs: Optional[dict] = None,
        replace_existing: bool = False,
        **job_kwargs,
    ) -> str:
        """Schedule a job with trigger configuration.

        Args:
            job_id: Unique identifier for the job
            func: Function to execute
            trigger: JobTriggerConfig with scheduling details
            priority: Job priority (not yet fully implemented, stored in metadata)
            max_retries: Maximum retry attempts
            name: Optional human-readable name
            args: Positional arguments for func
            kwargs: Keyword arguments for func
            replace_existing: Whether to replace existing job with same ID
            **job_kwargs: Additional job metadata

        Returns:
            Job ID
        """
        # Ensure kwargs is never None
        if kwargs is None:
            kwargs = {}
        with self._lock:
            is_replacement = job_id in self._jobs
            if is_replacement:
                if replace_existing:
                    self._jobs[job_id].cancel()
                else:
                    raise ValueError(f"Job with ID '{job_id}' already exists")

        # Map trigger config to job parameters
        job_type = JobType.ONE_TIME
        interval_seconds = 0.0
        delay_seconds = 0.0
        max_runs = None
        cron_expression = ""

        if trigger.type == JobTriggerType.ONE_TIME:
            job_type = JobType.ONE_TIME
            delay_seconds = trigger.delay_seconds
        elif trigger.type == JobTriggerType.RECURRING:
            job_type = JobType.RECURRING
            interval_seconds = trigger.interval_seconds
            max_runs = trigger.max_runs
            delay_seconds = trigger.delay_seconds
        elif trigger.type == JobTriggerType.DELAYED:
            job_type = JobType.DELAYED
            delay_seconds = trigger.delay_seconds
        elif trigger.type == JobTriggerType.CRON:
            job_type = JobType.CRON
            cron_expression = trigger.cron_expression
            max_runs = trigger.max_runs

        retry_config = RetryConfig(max_retries=max_retries)

        # Add priority and trigger info to metadata
        metadata = {**job_kwargs, "priority": priority.value, "trigger_config": trigger.__dict__}

        job = Job(
            id=job_id,
            name=name or getattr(func, '__name__', 'anonymous_job'),
            func=func,
            args=args,
            kwargs=kwargs,
            job_type=job_type,
            trigger_time=time.time() + delay_seconds,
            interval_seconds=interval_seconds,
            cron_expression=cron_expression,
            max_runs=max_runs,
            retry_config=retry_config,
            metadata=metadata,
        )

        with self._lock:
            self._jobs[job_id] = job

            with self._stats_lock:
                self._stats["total_jobs_created"] += 1

        if is_replacement:
            logger.debug(f"Replaced job '{job.name}' ({job_id[:8]}) type={trigger.type.value}")
        else:
            logger.info(f"Scheduled job '{job.name}' ({job_id[:8]}) type={trigger.type.value}")
        self._emit_job_event("job.created", job)
        return job_id

    def add_recurring_job(
        self,
        func: Callable,
        interval_seconds: float,
        *,
        name: str = "",
        args: tuple = (),
        kwargs: dict = None,
        max_runs: Optional[int] = None,
        start_delay: float = 0.0,
        **job_kwargs,
    ) -> str:
        """Add a recurring job."""
        return self.add_job(
            func,
            name=name,
            args=args,
            kwargs=kwargs,
            interval_seconds=interval_seconds,
            max_runs=max_runs,
            delay_seconds=start_delay,
            **job_kwargs,
        )

    def add_delayed_job(
        self,
        func: Callable,
        delay_seconds: float,
        *,
        name: str = "",
        args: tuple = (),
        kwargs: dict = None,
        **job_kwargs,
    ) -> str:
        """Add a delayed one-time job."""
        return self.add_job(
            func,
            name=name,
            args=args,
            kwargs=kwargs,
            delay_seconds=delay_seconds,
            **job_kwargs,
        )

    def remove_job(self, job_id: str) -> bool:
        """Remove a job from the service."""
        with self._lock:
            job = self._jobs.pop(job_id, None)
            if job:
                job.cancel()
                # Remove from tag index
                for tag_key, tag_value in job.tags.items():
                    tag = f"{tag_key}:{tag_value}"
                    self._jobs_by_tag[tag].discard(job_id)
                    if not self._jobs_by_tag[tag]:
                        del self._jobs_by_tag[tag]

                with self._stats_lock:
                    self._stats["total_jobs_cancelled"] += 1

                logger.info(f"Removed job '{job.name}' ({job_id[:8]})")
                self._emit_job_event("job.cancelled", job)
                return True
        return False

    def pause_job(self, job_id: str) -> bool:
        """Pause a job."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.pause()
                logger.info(f"Paused job '{job.name}' ({job_id[:8]})")
                self._emit_job_event("job.paused", job)
                return True
        return False

    def resume_job(self, job_id: str) -> bool:
        """Resume a paused job."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.resume()
                logger.info(f"Resumed job '{job.name}' ({job_id[:8]})")
                self._emit_job_event("job.resumed", job)
                return True
        return False

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a job (alias for remove_job)."""
        return self.remove_job(job_id)

    def get_job(self, job_id: str) -> Optional[Job]:
        """Get a job by ID."""
        with self._lock:
            return self._jobs.get(job_id)

    def get_job_summary(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get job summary by ID."""
        job = self.get_job(job_id)
        return job.get_summary() if job else None

    def list_jobs(
        self,
        status: Optional[JobStatus] = None,
        tag: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """List jobs with optional filters."""
        with self._lock:
            jobs = list(self._jobs.values())

        if status:
            jobs = [j for j in jobs if j.status == status]

        if tag:
            tag_job_ids = self._jobs_by_tag.get(tag, set())
            jobs = [j for j in jobs if j.id in tag_job_ids]

        # Sort by creation time (newest first)
        jobs.sort(key=lambda j: j.created_at, reverse=True)

        if limit:
            jobs = jobs[:limit]

        return [j.get_summary() for j in jobs]

    def get_jobs_by_tag(self, tag_key: str, tag_value: str) -> List[Dict[str, Any]]:
        """Get jobs by tag."""
        tag = f"{tag_key}:{tag_value}"
        with self._lock:
            job_ids = self._jobs_by_tag.get(tag, set())
            jobs = [self._jobs[jid] for jid in job_ids if jid in self._jobs]
        return [j.get_summary() for j in jobs]

    def get_stats(self) -> Dict[str, Any]:
        """Get service statistics."""
        with self._lock:
            status_counts = defaultdict(int)
            for job in self._jobs.values():
                status_counts[job.status.value] += 1

        with self._stats_lock:
            stats = dict(self._stats)

        stats.update({
            "active_jobs": len(self._jobs),
            "status_counts": dict(status_counts),
            "worker_capacity": self._max_workers,
            "workers_available": self._worker_semaphore._value,
        })
        return stats

    def get_job_history(self, job_id: Optional[str] = None, limit: int = 100, success: Optional[bool] = None) -> List[Dict[str, Any]]:
        """Get job execution history with optional filtering."""
        with self._history_lock:
            history = self._job_history
        if job_id:
            history = [record for record in history if record.get("job_id") == job_id]
        if success is not None:
            history = [record for record in history if record.get("success") == success]
        # Return most recent first
        history = list(reversed(history))
        if limit:
            history = history[:limit]
        return history

    def get_success_rate_trend(self, job_id: Optional[str] = None, window_hours: int = 24) -> List[Dict[str, Any]]:
        """Get success rate trend over time.

        Args:
            job_id: Optional job ID to filter by. If None, considers all jobs.
            window_hours: Number of hours to look back from now.

        Returns:
            List of dictionaries, each representing a time bucket with keys:
                start_time, end_time, success_rate, total_jobs, successful_jobs
        """
        now = datetime.now(timezone.utc)
        start_time = now - timedelta(hours=window_hours)

        # Get history for the job (if specified) in chronological order (oldest first)
        history = self.get_job_history(job_id=job_id, limit=None)
        chronological_history = list(reversed(history))

        # Filter to records within the time window
        filtered_history = []
        for record in chronological_history:
            try:
                record_time = datetime.fromisoformat(record["timestamp"])
            except ValueError:
                # If timestamp format is invalid, skip
                continue
            if start_time <= record_time <= now:
                filtered_history.append(record)

        # If no data, return empty list
        if not filtered_history:
            return []

        # Create time buckets of 1 hour each
        bucket_size = timedelta(hours=1)
        # Calculate number of buckets needed to cover the window
        num_buckets = int((now - start_time).total_seconds() // bucket_size.total_seconds()) + 1

        # Initialize buckets
        buckets = []
        for i in range(num_buckets):
            bucket_start = start_time + i * bucket_size
            bucket_end = bucket_start + bucket_size
            buckets.append({
                "start": bucket_start,
                "end": bucket_end,
                "success_count": 0,
                "total_count": 0
            })

        # Assign each record to a bucket
        for record in filtered_history:
            record_time = datetime.fromisoformat(record["timestamp"])
            delta = record_time - start_time
            if delta.total_seconds() < 0:
                # Should not happen due to filtering, but just in case
                continue
            index = int(delta.total_seconds() // bucket_size.total_seconds())
            if index >= num_buckets:
                index = num_buckets - 1
            bucket = buckets[index]
            bucket["total_count"] += 1
            if record.get("success", False):
                bucket["success_count"] += 1

        # Build result
        result = []
        for bucket in buckets:
            if bucket["total_count"] > 0:
                success_rate = bucket["success_count"] / bucket["total_count"]
            else:
                success_rate = 0.0
            result.append({
                "start_time": bucket["start"].isoformat(),
                "end_time": bucket["end"].isoformat(),
                "success_rate": success_rate,
                "total_jobs": bucket["total_count"],
                "successful_jobs": bucket["success_count"]
            })

        return result

    def get_retry_statistics(self, job_id: Optional[str] = None) -> Dict[str, Any]:
        """Get retry statistics.

        Args:
            job_id: Optional job ID to filter by. If None, considers all jobs.

        Returns:
            Dictionary with retry statistics:
                total_retries: total number of retries across all executions
                executions_with_retries: number of executions that had at least one retry
                average_retries_per_execution: average retries per execution (across all executions)
                average_retries_per_retry_execution: average retries per execution that had retries
                max_retries_per_execution: maximum retries in a single execution
                success_after_retry_rate: percentage of retried executions that eventually succeeded
        """
        # Get history for the job (if specified) in chronological order (oldest first)
        history = self.get_job_history(job_id=job_id, limit=None)
        chronological_history = list(reversed(history))

        total_executions = len(chronological_history)
        if total_executions == 0:
            return {
                "total_retries": 0,
                "executions_with_retries": 0,
                "average_retries_per_execution": 0.0,
                "average_retries_per_retry_execution": 0.0,
                "max_retries_per_execution": 0,
                "success_after_retry_rate": 0.0
            }

        retries = [record.get("retry_count", 0) for record in chronological_history]
        total_retries = sum(retries)
        executions_with_retries = sum(1 for r in retries if r > 0)
        avg_retries_per_execution = total_retries / total_executions if total_executions > 0 else 0.0
        avg_retries_per_retry_execution = total_retries / executions_with_retries if executions_with_retries > 0 else 0.0
        max_retries = max(retries) if retries else 0

        # Count executions that had retries and eventually succeeded
        success_after_retry = 0
        for record in chronological_history:
            if record.get("retry_count", 0) > 0 and record.get("success", False):
                success_after_retry += 1
        success_after_retry_rate = (
            success_after_retry / executions_with_retries
            if executions_with_retries > 0
            else 0.0
        )

        return {
            "total_retries": total_retries,
            "executions_with_retries": executions_with_retries,
            "average_retries_per_execution": avg_retries_per_execution,
            "average_retries_per_retry_execution": avg_retries_per_retry_execution,
            "max_retries_per_execution": max_retries,
            "success_after_retry_rate": success_after_retry_rate
        }

    def get_job_statistics(self, job_id: Optional[str] = None) -> Dict[str, Any]:
        """Get job execution statistics.

        Args:
            job_id: Optional job ID to filter by. If None, considers all jobs.

        Returns:
            Dictionary with job statistics:
                total_executions: total number of executions
                successful_executions: number of successful executions
                failed_executions: number of failed executions
                success_rate: success rate (successful/total)
                average_duration_seconds: average execution duration
                min_duration_seconds: minimum execution duration
                max_duration_seconds: maximum execution duration
                total_retries: total number of retries across all executions
        """
        # Get history for the job (if specified) in chronological order (oldest first)
        history = self.get_job_history(job_id=job_id, limit=None)
        chronological_history = list(reversed(history))

        total_executions = len(chronological_history)
        if total_executions == 0:
            return {
                "total_executions": 0,
                "successful_executions": 0,
                "failed_executions": 0,
                "success_rate": 0.0,
                "average_duration_seconds": 0.0,
                "min_duration_seconds": 0.0,
                "max_duration_seconds": 0.0,
                "total_retries": 0
            }

        success_count = sum(1 for record in chronological_history if record.get("success", False))
        fail_count = total_executions - success_count
        success_rate = success_count / total_executions if total_executions > 0 else 0.0

        durations = [record.get("duration_seconds", 0.0) for record in chronological_history]
        avg_duration = sum(durations) / len(durations) if durations else 0.0
        min_duration = min(durations) if durations else 0.0
        max_duration = max(durations) if durations else 0.0

        total_retries = sum(record.get("retry_count", 0) for record in chronological_history)

        return {
            "total_executions": total_executions,
            "successful_executions": success_count,
            "failed_executions": fail_count,
            "success_rate": success_rate,
            "average_duration_seconds": avg_duration,
            "min_duration_seconds": min_duration,
            "max_duration_seconds": max_duration,
            "total_retries": total_retries
        }


    def shutdown(self, wait: bool = True, timeout: float = 30.0) -> None:
        """Shutdown the job service."""
        logger.info("Shutting down BackgroundJobService...")
        self._shutdown = True

        # Cancel all pending jobs
        with self._lock:
            for job in self._jobs.values():
                if job.status in (JobStatus.PENDING, JobStatus.SCHEDULED, JobStatus.PAUSED):
                    job.cancel()

        # Wait for scheduler thread
        if self._scheduler_thread and self._scheduler_thread.is_alive() and wait:
            self._scheduler_thread.join(timeout=timeout)

        # Wait for worker threads
        if wait:
            with self._worker_lock:
                for worker in list(self._worker_threads):
                    worker.join(timeout=timeout / max(len(self._worker_threads), 1))

        logger.info("BackgroundJobService shutdown complete")


# Global instance
_job_service: Optional[BackgroundJobService] = None


def get_job_service() -> BackgroundJobService:
    """Get the global background job service instance."""
    global _job_service
    if _job_service is None:
        _job_service = BackgroundJobService()
    return _job_service


def set_job_service(service: BackgroundJobService) -> None:
    """Set the global background job service instance."""
    global _job_service
    _job_service = service


# Convenience functions
def schedule_job(
    func: Callable,
    delay_seconds: float = 0,
    *,
    name: str = "",
    **kwargs
) -> str:
    """Schedule a one-time job."""
    return get_job_service().add_delayed_job(func, delay_seconds, name=name, **kwargs)


def schedule_recurring_job(
    func: Callable,
    interval_seconds: float,
    *,
    name: str = "",
    **kwargs
) -> str:
    """Schedule a recurring job."""
    return get_job_service().add_recurring_job(func, interval_seconds, name=name, **kwargs)