"""Background scheduler for recurring and delayed tasks in Long-Term Autonomy."""

import threading
import time
import heapq
from datetime import datetime, timezone
from typing import Callable, Optional, Any
from uuid import uuid4
from dataclasses import dataclass, field
from enum import Enum


class JobStatus(Enum):
    """Status of a scheduled job."""
    SCHEDULED = "scheduled"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass
class ScheduledJob:
    """Represents a job to be executed at a specific time."""
    id: str = field(default_factory=lambda: f"job_{uuid4().hex[:8]}")
    func: Callable = None
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)
    trigger_time: float = 0.0  # timestamp when the job should run
    interval: float = 0.0      # interval in seconds for repeating jobs (0 for one-time)
    max_runs: int = 1          # maximum number of times to run (None for infinite)
    run_count: int = 0         # number of times the job has been run
    status: JobStatus = JobStatus.SCHEDULED
    metadata: dict = field(default_factory=dict)
    # Internal fields
    _cancel_event: threading.Event = field(default_factory=threading.Event, init=False)
    _pause_event: threading.Event = field(default_factory=threading.Event, init=False)

    def __post_init__(self):
        if self.pause_event is None:
            self._pause_event.clear()  # Not paused by default
        if self.cancel_event is None:
            self._cancel_event.clear()  # Not cancelled by default

    @property
    def cancel_event(self) -> threading.Event:
        return self._cancel_event

    @property
    def pause_event(self) -> threading.Event:
        return self._pause_event

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def is_paused(self) -> bool:
        return self._pause_event.is_set()

    def cancel(self) -> None:
        """Cancel the job."""
        self._cancel_event.set()
        self._pause_event.set()  # Unblock if waiting
        self.status = JobStatus.CANCELLED

    def pause(self) -> None:
        """Pause the job."""
        self._pause_event.set()
        self.status = JobStatus.PAUSED

    def resume(self) -> None:
        """Resume the job."""
        self._pause_event.clear()
        if self.status == JobStatus.PAUSED:
            self.status = JobStatus.SCHEDULED

    def next_run_time(self) -> float:
        """Calculate the next run time based on interval."""
        if self.interval <= 0:
            return float('inf')
        return self.trigger_time + (self.run_count * self.interval)

    def is_ready(self, current_time: float) -> bool:
        """Check if the job is ready to run."""
        if self.is_cancelled():
            return False
        if self.is_paused():
            return False
        if self.max_runs is not None and self.run_count >= self.max_runs:
            return False
        return current_time >= self.trigger_time


class BackgroundScheduler:
    """
    A background scheduler for executing functions at specific times or intervals.

    Features:
    - One-time and recurring jobs
    - Pause/resume/cancel individual jobs
    - Thread-safe operations
    - Persistent storage (optional)
    - Misinfiring handling
    """

    def __init__(self, tick_interval: float = 1.0):
        """
        Initialize the background scheduler.

        Args:
            tick_interval: How often the scheduler thread checks for jobs (seconds)
        """
        self._tick_interval = tick_interval
        self._jobs: dict[str, ScheduledJob] = {}
        self._lock = threading.RLock()
        self._shutdown = False
        self._scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._scheduler_thread.start()

    def _scheduler_loop(self) -> None:
        """Main scheduler loop that runs in a background thread."""
        while not self._shutdown:
            now = time.time()
            with self._lock:
                # Get jobs that are ready to run
                ready_jobs = [
                    job for job in self._jobs.values()
                    if job.is_ready(now)
                ]
                # Sort by trigger time (FIFO for same time)
                ready_jobs.sort(key=lambda j: j.trigger_time)

                for job in ready_jobs:
                    # Check again if job was cancelled/paused while we were sorting
                    if job.is_cancelled() or job.is_paused():
                        continue

                    # Execute the job in a separate thread to avoid blocking the scheduler
                    job_thread = threading.Thread(
                        target=self._run_job,
                        args=(job,),
                        daemon=True
                    )
                    job_thread.start()

                    # Update job state
                    job.run_count += 1
                    if job.max_runs is not None and job.run_count >= job.max_runs:
                        job.status = JobStatus.COMPLETED
                    elif job.interval > 0:
                        # Schedule next occurrence for repeating jobs
                        job.trigger_time = now + job.interval
                    else:
                        # One-time job is done
                        job.status = JobStatus.COMPLETED

            # Sleep until the next tick
            time.sleep(self._tick_interval)

    def _run_job(self, job: ScheduledJob) -> None:
        """Execute a single job."""
        try:
            if job.cancel_event.is_set():
                return
            if job.pause_event.is_set():
                # Wait until resumed or cancelled
                job.pause_event.wait()
                if job.cancel_event.is_set():
                    return

            # Execute the function
            job.func(*job.args, **job.kwargs)

            # Mark as completed if not rescheduled
            if job.status != JobScheduled.COMPLETED and job.interval == 0:
                job.status = JobStatus.COMPLETED

        except Exception as e:
            # Log the error and mark job as failed
            # In a real implementation, we would use a logger
            print(f"Job {job.id} failed: {e}")
            job.status = JobStatus.FAILED

    def add_job(
        self,
        func: Callable,
        trigger_time: float = None,
        interval: float = 0.0,
        args: tuple = (),
        kwargs: dict = None,
        max_runs: int = 1,
        metadata: dict = None
    ) -> str:
        """
        Add a job to the scheduler.

        Args:
            func: The function to execute
            trigger_time: When to first run the job (timestamp). If None, uses now + 1 second
            interval: How often to repeat the job in seconds (0 for one-time)
            args: Positional arguments to pass to the function
            kwargs: Keyword arguments to pass to the function
            max_runs: Maximum number of times to run the job (None for infinite)
            metadata: Additional data to store with the job

        Returns:
            The job ID
        """
        if kwargs is None:
            kwargs = {}
        if metadata is None:
            metadata = {}
        if trigger_time is None:
            trigger_time = time.time() + 1.0  # Default to 1 second from now

        job = ScheduledJob(
            func=func,
            args=args,
            kwargs=kwargs,
            trigger_time=trigger_time,
            interval=interval,
            max_runs=max_runs if max_runs is not None else 1,
            metadata=metadata
        )

        with self._lock:
            self._jobs[job.id] = job

        return job.id

    def remove_job(self, job_id: str) -> bool:
        """Remove a job from the scheduler."""
        with self._lock:
            if job_id in self._jobs:
                job = self._jobs[job_id]
                job.cancel()
                del self._jobs[job_id]
                return True
        return False

    def pause_job(self, job_id: str) -> bool:
        """Pause a job."""
        with self._lock:
            if job_id in self._jobs:
                job = self._jobs[job_id]
                job.pause()
                return True
        return False

    def resume_job(self, job_id: str) -> bool:
        """Resume a paused job."""
        with self._lock:
            if job_id in self._jobs:
                job = self._jobs[job_id]
                job.resume()
                return True
        return False

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a job (alias for remove_job)."""
        return self.remove_job(job_id)

    def get_job(self, job_id: str) -> Optional[ScheduledJob]:
        """Get a job by its ID."""
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self) -> list[ScheduledJob]:
        """List all jobs."""
        with self._lock:
            return list(self._jobs.values())

    def shutdown(self) -> None:
        """Shutdown the scheduler."""
        self._shutdown = True
        # Wait for the scheduler thread to finish (it's a daemon, so we don't wait long)
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            self._scheduler_thread.join(timeout=2.0)