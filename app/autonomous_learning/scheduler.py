"""Autonomous Learning Scheduler

This module provides background scheduling for periodic autonomous learning runs.
It ensures the learning pipeline runs at regular intervals for continuous learning.
"""

import time
import threading
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Callable
from enum import Enum

from app.core.logger import logger
from app.autonomous_learning.pipeline import AutonomousLearningPipeline
from app.autonomous_learning.models import AutonomousLearningConfig, LearningPipelineResult
from app.autonomous_learning.analytics import LearningAnalytics, LearningMetrics


class SchedulerStatus(Enum):
    """Status of the scheduler."""
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"


class AutonomousLearningScheduler:
    """Background scheduler for autonomous learning pipeline.

    Runs the autonomous learning pipeline at configured intervals
    to enable continuous learning without manual intervention.
    """

    def __init__(
        self,
        pipeline: AutonomousLearningPipeline,
        config: Optional[AutonomousLearningConfig] = None,
        analytics: Optional[LearningAnalytics] = None,
    ):
        """Initialize the autonomous learning scheduler.

        Args:
            pipeline: The autonomous learning pipeline to schedule
            config: Scheduler configuration (uses pipeline config if not provided)
            analytics: Optional LearningAnalytics instance for tracking metrics
        """
        self.pipeline = pipeline
        self.config = config or AutonomousLearningConfig()
        self.analytics = analytics or LearningAnalytics()

        # Scheduler state
        self._status = SchedulerStatus.STOPPED
        self._scheduler_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._last_run_time: Optional[datetime] = None
        self._run_count = 0
        self._last_consolidation_run: Optional[datetime] = None

        # Scheduler analytics
        self._scheduler_metrics = {
            "total_runs": 0,
            "successful_runs": 0,
            "failed_runs": 0,
            "total_duration_seconds": 0.0,
            "avg_run_duration": 0.0,
            "last_run_duration": 0.0,
            "consecutive_failures": 0,
            "consecutive_successes": 0,
            "last_error": None,
            "last_error_time": None,
            "runs_by_hour": {},  # hour -> count
            "duration_history": [],  # Last 100 run durations
            "error_history": [],  # Last 50 errors
        }

        # Callback for when pipeline completes
        self._completion_callback: Optional[Callable[[LearningPipelineResult], None]] = None

    def start(self) -> None:
        """Start the background scheduler."""
        if self._status == SchedulerStatus.RUNNING:
            logger.warning("Autonomous learning scheduler is already running")
            return

        logger.info("Starting autonomous learning scheduler")
        self._status = SchedulerStatus.RUNNING
        self._stop_event.clear()
        self._pause_event.clear()
        self._pause_event.set()  # Start in unpaused state

        # Start scheduler thread
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop,
            name="AutonomousLearningScheduler",
            daemon=True
        )
        self._scheduler_thread.start()

        logger.info(f"Autonomous learning scheduler started with {self.config.run_interval_minutes} minute interval")
        if self.config.goal_driven_learning_enabled:
            logger.info("Goal-driven learning is ENABLED - scheduler will analyze active goals")
        if self.config.use_consolidation_engine:
            logger.info("Memory consolidation is ENABLED - scheduler will run consolidation periodically")

    def stop(self) -> None:
        """Stop the background scheduler."""
        if self._status == SchedulerStatus.STOPPED:
            logger.warning("Autonomous learning scheduler is already stopped")
            return

        logger.info("Stopping autonomous learning scheduler")
        self._status = SchedulerStatus.STOPPED
        self._stop_event.set()

        # Wait for thread to finish
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            self._scheduler_thread.join(timeout=5.0)

        # Persist scheduler analytics
        self._persist_scheduler_analytics()

        logger.info("Autonomous learning scheduler stopped")

    def pause(self) -> None:
        """Pause the scheduler (stop running pipeline but keep thread alive)."""
        if self._status != SchedulerStatus.RUNNING:
            logger.warning("Cannot pause scheduler - not running")
            return

        logger.info("Pausing autonomous learning scheduler")
        self._status = SchedulerStatus.PAUSED
        self._pause_event.clear()  # Block the scheduler loop

    def resume(self) -> None:
        """Resume the scheduler after pausing."""
        if self._status != SchedulerStatus.PAUSED:
            logger.warning("Cannot resume scheduler - not paused")
            return

        logger.info("Resuming autonomous learning scheduler")
        self._status = SchedulerStatus.RUNNING
        self._pause_event.set()  # Allow scheduler loop to continue

    def run_now(self) -> LearningPipelineResult:
        """Run the pipeline immediately (outside of scheduled interval).

        Returns:
            LearningPipelineResult: Result of the pipeline execution
        """
        logger.info("Running autonomous learning pipeline on demand")
        start_time = time.time()

        # Record pipeline start in analytics
        self.analytics.record_pipeline_start()

        # Run the pipeline
        result = self.pipeline()  # Pipeline uses __call__ method

        # Record pipeline result
        self.analytics.record_pipeline_result(result)
        self.analytics.record_pipeline_duration(result.duration_seconds)

        # Update tracking
        self._last_run_time = datetime.now(timezone.utc)
        self._run_count += 1

        duration = time.time() - start_time
        self._update_scheduler_metrics(duration, True, result)

        # Call completion callback if set
        if self._completion_callback:
            try:
                self._completion_callback(result)
            except Exception as e:
                logger.error(f"Error in completion callback: {e}")

        return result

    def get_status(self) -> Dict[str, Any]:
        """Get current scheduler status.

        Returns:
            Dictionary containing scheduler status information
        """
        return {
            "status": self._status.value,
            "is_running": self._status == SchedulerStatus.RUNNING,
            "is_paused": self._status == SchedulerStatus.PAUSED,
            "last_run_time": self._last_run_time.isoformat() if self._last_run_time else None,
            "run_count": self._run_count,
            "interval_minutes": self.config.run_interval_minutes,
            "goal_driven_learning_enabled": self.config.goal_driven_learning_enabled,
            "consolidation_enabled": self.config.use_consolidation_engine,
            "next_run_in_seconds": self._get_next_run_interval() if self._status == SchedulerStatus.RUNNING else None
        }

    def get_learning_progress_dashboard(self) -> Dict[str, Any]:
        """Get a comprehensive learning progress dashboard.

        Returns:
            Dictionary with learning progress metrics, trends, and statistics
        """
        pipeline_status = self.pipeline.get_pipeline_status()

        # Get analytics from pipeline
        analytics = self.pipeline.analytics if hasattr(self.pipeline, 'analytics') else None

        dashboard = {
            "scheduler": self.get_status(),
            "pipeline": pipeline_status,
            "learning_metrics": {
                "total_runs": self._run_count,
                "total_duration_seconds": pipeline_status.get("stats", {}).get("duration_seconds", 0),
                "experiences_processed": pipeline_status.get("stats", {}).get("experiences_processed", 0),
                "knowledge_extracted": pipeline_status.get("stats", {}).get("knowledge_objects_extracted", 0),
                "knowledge_validated": pipeline_status.get("stats", {}).get("knowledge_objects_validated", 0),
                "knowledge_stored": pipeline_status.get("stats", {}).get("knowledge_objects_stored", 0),
                "gaps_detected": pipeline_status.get("stats", {}).get("gaps_detected", 0),
                "goal_gaps_detected": pipeline_status.get("stats", {}).get("goal_gaps_detected", 0),
                "research_tasks_started": pipeline_status.get("stats", {}).get("research_tasks_started", 0),
                "research_tasks_completed": pipeline_status.get("stats", {}).get("research_tasks_completed", 0),
                "consolidation_runs": pipeline_status.get("stats", {}).get("consolidation_runs", 0),
                "experiences_promoted": pipeline_status.get("stats", {}).get("experiences_promoted", 0),
                "lessons_promoted": pipeline_status.get("stats", {}).get("lessons_promoted", 0),
                "entries_archived": pipeline_status.get("stats", {}).get("entries_archived", 0),
            },
            "health": {
                "error_count": len(pipeline_status.get("stats", {}).get("errors", [])),
                "warning_count": len(pipeline_status.get("stats", {}).get("warnings", [])),
                "last_errors": pipeline_status.get("stats", {}).get("errors", [])[-5:],
                "last_warnings": pipeline_status.get("stats", {}).get("warnings", [])[-5:],
            },
            "trends": {},
        }

        # Add analytics trends if available
        if analytics and hasattr(analytics, 'get_trends'):
            try:
                dashboard["trends"] = analytics.get_trends()
            except Exception:
                pass

        return dashboard

    def set_completion_callback(self, callback: Callable[[LearningPipelineResult], None]) -> None:
        """Set a callback to be called when pipeline completes.

        Args:
            callback: Function to call with pipeline result
        """
        self._completion_callback = callback

    def update_config(self, config: AutonomousLearningConfig) -> None:
        """Update scheduler configuration.

        Args:
            config: New configuration to use
        """
        logger.info("Updating autonomous learning scheduler configuration")
        self.config = config

    def _scheduler_loop(self) -> None:
        """Main scheduler loop that runs in background thread."""
        logger.debug("Scheduler loop started")

        while not self._stop_event.is_set():
            try:
                # Wait for pause event (allows pausing/resuming)
                self._pause_event.wait(timeout=1.0)

                # Check if we should stop
                if self._stop_event.is_set():
                    break

                # Check if it's time to run
                if self._should_run_now():
                    logger.debug("Scheduled time reached - running autonomous learning pipeline")
                    self._run_pipeline_scheduled()

                # Sleep for a short interval before checking again
                time.sleep(30)  # Check every 30 seconds

            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")
                time.sleep(5)  # Brief pause before continuing

        logger.debug("Scheduler loop ended")

    def _should_run_now(self) -> bool:
        """Check if it's time to run the pipeline based on interval.

        Returns:
            bool: True if pipeline should run now
        """
        try:
            if self._last_run_time is None:
                # First run - run immediately
                return True

            # Calculate time since last run
            now = datetime.now(timezone.utc)
            time_since_last_run = now - self._last_run_time
            interval_seconds = self.config.run_interval_minutes * 60

            return time_since_last_run.total_seconds() >= interval_seconds

        except Exception as e:
            logger.error(f"Error checking if should run now: {e}")
            return False

    def _run_pipeline_scheduled(self) -> None:
        """Run the pipeline as part of scheduled execution."""
        start_time = time.time()
        run_successful = False

        try:
            logger.info("Running scheduled autonomous learning pipeline")

            # Record pipeline start in analytics
            self.analytics.record_pipeline_start()

            # Run the pipeline
            result = self.pipeline()  # Pipeline uses __call__ method

            # Record pipeline result
            self.analytics.record_pipeline_result(result)
            self.analytics.record_pipeline_duration(result.duration_seconds)

            # Update tracking
            self._last_run_time = datetime.now(timezone.utc)
            self._run_count += 1

            duration = time.time() - start_time
            run_successful = True

            # Update scheduler metrics
            self._update_scheduler_metrics(duration, True, result)

            logger.info(f"Scheduled pipeline completed in {duration:.2f}s")

            # Call completion callback if set
            if self._completion_callback:
                try:
                    self._completion_callback(result)
                except Exception as e:
                    logger.error(f"Error in completion callback: {e}")

        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"Error running scheduled pipeline: {e}")

            # Update scheduler metrics for failure
            self._update_scheduler_metrics(duration, False, str(e))

            # Record error in analytics
            self.analytics.record_error("pipeline")

    def _update_scheduler_metrics(self, duration: float, success: bool, result_or_error: Any) -> None:
        """Update scheduler analytics metrics."""
        metrics = self._scheduler_metrics
        metrics["total_runs"] += 1
        metrics["total_duration_seconds"] += duration
        metrics["last_run_duration"] = duration

        # Update duration history (keep last 100)
        metrics["duration_history"].append(duration)
        if len(metrics["duration_history"]) > 100:
            metrics["duration_history"] = metrics["duration_history"][-100:]

        # Update average
        metrics["avg_run_duration"] = metrics["total_duration_seconds"] / metrics["total_runs"]

        # Track by hour
        hour = datetime.now(timezone.utc).hour
        metrics["runs_by_hour"][hour] = metrics["runs_by_hour"].get(hour, 0) + 1

        if success:
            metrics["successful_runs"] += 1
            metrics["consecutive_successes"] += 1
            metrics["consecutive_failures"] = 0

            # Record error history for successful run if there were warnings
            if hasattr(result_or_error, 'warnings') and result_or_error.warnings:
                self._record_error_history("warning", result_or_error.warnings[-1] if result_or_error.warnings else "")
        else:
            metrics["failed_runs"] += 1
            metrics["consecutive_failures"] += 1
            metrics["consecutive_successes"] = 0
            metrics["last_error"] = str(result_or_error)
            metrics["last_error_time"] = datetime.now(timezone.utc).isoformat()

            # Record error history (keep last 50)
            self._record_error_history("pipeline_error", str(result_or_error))

    def _record_error_history(self, error_type: str, message: str) -> None:
        """Record an error in the error history."""
        error_entry = {
            "type": error_type,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._scheduler_metrics["error_history"].append(error_entry)
        if len(self._scheduler_metrics["error_history"]) > 50:
            self._scheduler_metrics["error_history"] = self._scheduler_metrics["error_history"][-50:]

    def _persist_scheduler_analytics(self) -> None:
        """Persist scheduler analytics to learning analytics storage."""
        try:
            # The analytics object handles its own persistence
            pass
        except Exception as e:
            logger.warning(f"Failed to persist scheduler analytics: {e}")

    def get_scheduler_analytics(self) -> Dict[str, Any]:
        """Get scheduler analytics and performance metrics.

        Returns:
            Dictionary containing scheduler analytics
        """
        metrics = self._scheduler_metrics

        # Calculate success rate
        total_runs = metrics["total_runs"]
        success_rate = (metrics["successful_runs"] / total_runs * 100) if total_runs > 0 else 0.0

        # Calculate recovery metrics
        if metrics["consecutive_failures"] > 0:
            recovery_status = "recovering" if metrics["consecutive_successes"] > 0 else "degraded"
            estimated_recovery_time = None
            if metrics["avg_run_duration"] > 0:
                estimated_recovery_time = metrics["avg_run_duration"] * metrics["consecutive_failures"]
        else:
            recovery_status = "healthy"
            estimated_recovery_time = None

        # Calculate scheduling efficiency
        expected_runs = 0
        if self._last_run_time:
            elapsed_hours = (datetime.now(timezone.utc) - self._last_run_time).total_seconds() / 3600
            expected_runs = max(1, int(elapsed_hours * 60 / self.config.run_interval_minutes))

        scheduling_adherence = (total_runs / expected_runs * 100) if expected_runs > 0 else 100.0

        return {
            "scheduler_metrics": {
                "total_runs": total_runs,
                "successful_runs": metrics["successful_runs"],
                "failed_runs": metrics["failed_runs"],
                "success_rate_percent": round(success_rate, 2),
                "avg_run_duration_seconds": round(metrics["avg_run_duration"], 2),
                "last_run_duration_seconds": round(metrics["last_run_duration"], 2),
                "total_duration_seconds": round(metrics["total_duration_seconds"], 2),
            },
            "reliability": {
                "consecutive_successes": metrics["consecutive_successes"],
                "consecutive_failures": metrics["consecutive_failures"],
                "recovery_status": recovery_status,
                "estimated_recovery_time_seconds": round(estimated_recovery_time, 2) if estimated_recovery_time else None,
                "last_error": metrics["last_error"],
                "last_error_time": metrics["last_error_time"],
            },
            "scheduling": {
                "interval_minutes": self.config.run_interval_minutes,
                "expected_runs_last_24h": int(24 * 60 / self.config.run_interval_minutes),
                "actual_runs_last_24h": sum(metrics["runs_by_hour"].values()),
                "scheduling_adherence_percent": round(scheduling_adherence, 2),
                "runs_by_hour": metrics["runs_by_hour"],
            },
            "performance": {
                "duration_history_summary": self._get_duration_summary(),
                "recent_errors": metrics["error_history"][-10:],
            },
            "learning_analytics": self.analytics.get_learning_summary(),
        }

    def _get_duration_summary(self) -> Dict[str, Any]:
        """Get summary statistics for run durations."""
        durations = self._scheduler_metrics["duration_history"]
        if not durations:
            return {"count": 0}

        sorted_durations = sorted(durations)
        n = len(sorted_durations)

        return {
            "count": n,
            "min_seconds": round(sorted_durations[0], 2),
            "max_seconds": round(sorted_durations[-1], 2),
            "median_seconds": round(sorted_durations[n // 2], 2),
            "p95_seconds": round(sorted_durations[int(n * 0.95)], 2) if n > 20 else None,
            "avg_seconds": round(sum(durations) / n, 2),
        }

    def _get_next_run_interval(self) -> Optional[float]:
        """Get seconds until next scheduled run.

        Returns:
            float: Seconds until next run, or None if cannot calculate
        """
        try:
            if self._last_run_time is None:
                return 0.0  # Should run immediately

            now = datetime.now(timezone.utc)
            time_since_last_run = now - self._last_run_time
            interval_seconds = self.config.run_interval_minutes * 60
            elapsed_seconds = time_since_last_run.total_seconds()

            if elapsed_seconds >= interval_seconds:
                return 0.0  # Overdue - should run now
            else:
                return interval_seconds - elapsed_seconds

        except Exception as e:
            logger.error(f"Error calculating next run interval: {e}")
            return None