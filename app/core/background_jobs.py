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

        # Statistics
        self._stats = {
            "total_jobs_created": 0,
            "total_jobs_completed": 0,
            "total_jobs_failed": 0,
            "total_jobs_cancelled": 0,
            "total_jobs_retried": 0,
        }
        self._stats_lock = threading.Lock()

        # Start scheduler
        self._start_scheduler()

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
        while not self._shutdown:
            try:
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

                # Handle recurring vs one-time
                if job.job_type == JobType.RECURRING and job.interval_seconds > 0:
                    if job.max_runs is None or job.run_count < job.max_runs:
                        job.status = JobStatus.SCHEDULED
                    else:
                        job.status = JobStatus.COMPLETED
                else:
                    job.status = JobStatus.COMPLETED

                # Record success
                job_result = JobResult(
                    success=True,
                    result=result,
                    duration_seconds=duration,
                )
                job.add_result(job_result)
                job.last_error = None
                job.current_retry = 0

            # Emit job completed event
            self._emit_job_event("job.completed", job, {"result": result, "duration": duration})

            # Update stats
            with self._stats_lock:
                self._stats["total_jobs_completed"] += 1

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

        self._event_bus.emit(
            event_name,
            data=event_data,
            source="BackgroundJobService",
            priority=EventPriority.NORMAL,
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
            if job_id in self._jobs:
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