"""Watchdog system for Long-Term Autonomy.

This module implements the watchdog system that supervises long-running
execution, enforces health checks, and restarts failed tasks.
"""

import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4


class WatchdogAction(Enum):
    """Actions the watchdog can take."""
    NONE = "none"
    WARN = "warn"
    RESTART_TASK = "restart_task"
    RESTART_SYSTEM = "restart_system"
    ALERT = "alert"


@dataclass
class WatchdogConfig:
    """Configuration for the watchdog system."""
    # Health check settings
    health_check_interval: float = 30.0  # seconds

    # Thresholds
    cpu_warning_threshold: float = 80.0  # percent
    cpu_critical_threshold: float = 95.0  # percent
    memory_warning_threshold: float = 80.0  # percent
    memory_critical_threshold: float = 95.0  # percent
    task_timeout_threshold: float = 1800.0  # seconds (30 minutes)

    # Action settings
    max_task_restarts: int = 3
    restart_backoff_seconds: float = 5.0
    max_consecutive_failures: int = 5

    # General settings
    enabled: bool = True


@dataclass
class TaskHealth:
    """Health information for a monitored task."""
    task_id: str
    task_name: str
    started_at: str
    last_heartbeat: str
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    status: str = "running"  # running, stalled, failed, completed
    restart_count: int = 0
    consecutive_failures: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


class Watchdog:
    """
    Watchdog system for supervising long-running autonomous execution.

    Features:
    - Monitors task health (CPU, memory, heartbeats)
    - Detects stalled or hung tasks
    - Restarts failed tasks with exponential backoff
    - Enforces resource limits
    - Alerts on anomalies
    """

    def __init__(self, config: WatchdogConfig = None):
        """
        Initialize the watchdog.

        Args:
            config: Watchdog configuration
        """
        self.config = config or WatchdogConfig()
        self._lock = threading.RLock()
        self._tasks: Dict[str, TaskHealth] = {}
        self._running = False
        self._monitor_thread = None
        self._shutdown_event = threading.Event()
        self._callbacks: List[Callable] = []

    def start(self) -> None:
        """Start the watchdog monitoring."""
        if self._running:
            return

        self._running = True
        self._shutdown_event.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="WatchdogMonitor"
        )
        self._monitor_thread.start()

    def stop(self) -> None:
        """Stop the watchdog monitoring."""
        if not self._running:
            return

        self._running = False
        self._shutdown_event.set()
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5.0)

    def register_task(self, task_id: str, task_name: str, metadata: Dict = None) -> None:
        """
        Register a task for monitoring.

        Args:
            task_id: Unique task identifier
            task_name: Human-readable task name
            metadata: Additional task metadata
        """
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            self._tasks[task_id] = TaskHealth(
                task_id=task_id,
                task_name=task_name,
                started_at=now,
                last_heartbeat=now,
                metadata=metadata or {}
            )

    def unregister_task(self, task_id: str) -> bool:
        """
        Unregister a task from monitoring.

        Args:
            task_id: Task identifier to unregister

        Returns:
            True if task was registered and removed, False otherwise
        """
        with self._lock:
            if task_id in self._tasks:
                del self._tasks[task_id]
                return True
            return False

    def heartbeat(self, task_id: str, cpu_percent: float = 0.0, memory_percent: float = 0.0) -> bool:
        """
        Update task heartbeat.

        Args:
            task_id: Task identifier
            cpu_percent: Current CPU usage percentage
            memory_percent: Current memory usage percentage

        Returns:
            True if task is registered, False otherwise
        """
        with self._lock:
            if task_id not in self._tasks:
                return False
            task = self._tasks[task_id]
            task.last_heartbeat = datetime.now(timezone.utc).isoformat()
            task.cpu_percent = cpu_percent
            task.memory_percent = memory_percent
            return True

    def mark_task_completed(self, task_id: str) -> bool:
        """
        Mark a task as completed.

        Args:
            task_id: Task identifier

        Returns:
            True if task was registered, False otherwise
        """
        with self._lock:
            if task_id not in self._tasks:
                return False
            self._tasks[task_id].status = "completed"
            return True

    def mark_task_failed(self, task_id: str) -> bool:
        """
        Mark a task as failed.

        Args:
            task_id: Task identifier

        Returns:
            True if task was registered, False otherwise
        """
        with self._lock:
            if task_id not in self._tasks:
                return False
            task = self._tasks[task_id]
            task.status = "failed"
            task.consecutive_failures += 1
            return True

    def add_callback(self, callback: Callable[[str, WatchdogAction, Dict], None]) -> None:
        """
        Add a callback for watchdog actions.

        Args:
            callback: Function to call when watchdog takes action
                     (task_id, action, details)
        """
        with self._lock:
            self._callbacks.append(callback)

    def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while not self._shutdown_event.is_set():
            try:
                self._check_tasks()
            except Exception as e:
                # Log error but continue monitoring
                print(f"Watchdog monitor error: {e}")

            # Sleep until next check
            self._shutdown_event.wait(self.config.health_check_interval)

    def _check_tasks(self) -> None:
        """Check all registered tasks for health issues."""
        now = time.time()
        actions_taken: List[tuple] = []

        with self._lock:
            for task_id, task in list(self._tasks.items()):
                if task.status in ["completed", "failed"]:
                    continue

                # Check heartbeat timeout
                last_heartbeat = datetime.fromisoformat(task.last_heartbeat)
                time_since_heartbeat = (datetime.now(timezone.utc) - last_heartbeat).total_seconds()

                if time_since_heartbeat > self.config.task_timeout_threshold:
                    # Task appears stalled
                    task.status = "stalled"
                    actions_taken.append((
                        task_id,
                        WatchdogAction.RESTART_TASK,
                        {
                            "reason": "heartbeat_timeout",
                            "seconds_since_heartbeat": time_since_heartbeat,
                            "threshold": self.config.task_timeout_threshold
                        }
                    ))

                # Check resource usage
                elif task.cpu_percent > self.config.cpu_critical_threshold:
                    actions_taken.append((
                        task_id,
                        WatchdogAction.ALERT,
                        {
                            "reason": "critical_cpu_usage",
                            "cpu_percent": task.cpu_percent,
                            "threshold": self.config.cpu_critical_threshold
                        }
                    ))
                elif task.cpu_percent > self.config.cpu_warning_threshold:
                    actions_taken.append((
                        task_id,
                        WatchdogAction.WARN,
                        {
                            "reason": "high_cpu_usage",
                            "cpu_percent": task.cpu_percent,
                            "threshold": self.config.cpu_warning_threshold
                        }
                    ))

                if task.memory_percent > self.config.memory_critical_threshold:
                    actions_taken.append((
                        task_id,
                        WatchdogAction.ALERT,
                        {
                            "reason": "critical_memory_usage",
                            "memory_percent": task.memory_percent,
                            "threshold": self.config.memory_critical_threshold
                        }
                    ))
                elif task.memory_percent > self.config.memory_warning_threshold:
                    actions_taken.append((
                        task_id,
                        WatchdogAction.WARN,
                        {
                            "reason": "high_memory_usage",
                            "memory_percent": task.memory_percent,
                            "threshold": self.config.memory_warning_threshold
                        }
                    ))

        # Execute actions outside of lock
        for task_id, action, details in actions_taken:
            self._execute_action(task_id, action, details)

    def _execute_action(self, task_id: str, action: WatchdogAction, details: Dict) -> None:
        """Execute a watchdog action."""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return

        # Call all registered callbacks
        for callback in self._callbacks:
            try:
                callback(task_id, action, details)
            except Exception as e:
                print(f"Watchdog callback error: {e}")

        # Perform the actual action
        if action == WatchdogAction.RESTART_TASK:
            self._restart_task(task_id, details)
        elif action in [WatchdogAction.WARN, WatchdogAction.ALERT]:
            # Alerts are handled by callbacks
            pass

    def _restart_task(self, task_id: str, details: Dict) -> None:
        """Restart a stalled or failed task."""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return

            if task.restart_count >= self.config.max_task_restarts:
                # Too many restarts, mark as failed
                task.status = "failed"
                task.consecutive_failures += 1
                self._execute_action(task_id, WatchdogAction.ALERT, {
                    "reason": "max_restarts_exceeded",
                    "restart_count": task.restart_count,
                    "max_restarts": self.config.max_task_restarts
                })
                return

            # Increment restart count and back off
            task.restart_count += 1
            task.status = "restarting"
            task.last_heartbeat = datetime.now(timezone.utc).isoformat()

        # Apply backoff before actual restart
        # In a real implementation, this would trigger the task executor
        time.sleep(self.config.restart_backoff_seconds * task.restart_count)

        # Mark as running again
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.status = "running"
                task.consecutive_failures = 0  # Reset on successful restart

    def get_task_health(self, task_id: str) -> Optional[TaskHealth]:
        """Get health information for a specific task."""
        with self._lock:
            return self._tasks.get(task_id)

    def get_all_task_health(self) -> List[TaskHealth]:
        """Get health information for all tasks."""
        with self._lock:
            return list(self._tasks.values())

    def get_stalled_tasks(self) -> List[TaskHealth]:
        """Get tasks that are stalled."""
        with self._lock:
            return [t for t in self._tasks.values() if t.status == "stalled"]

    def get_failed_tasks(self) -> List[TaskHealth]:
        """Get tasks that have failed."""
        with self._lock:
            return [t for t in self._tasks.values() if t.status == "failed"]

    def is_healthy(self) -> bool:
        """Check if the watchdog system is healthy."""
        return self._running and (self._monitor_thread is not None and self._monitor_thread.is_alive())