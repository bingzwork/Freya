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
    ):
        """Initialize the autonomous learning scheduler.

        Args:
            pipeline: The autonomous learning pipeline to schedule
            config: Scheduler configuration (uses pipeline config if not provided)
        """
        self.pipeline = pipeline
        self.config = config or AutonomousLearningConfig()

        # Scheduler state
        self._status = SchedulerStatus.STOPPED
        self._scheduler_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._last_run_time: Optional[datetime] = None
        self._run_count = 0

        # Callback for when pipeline completes
        self._completion_callback: Optional[Callable[[AutonomousLearningPipeline.LearningPipelineResult], None]] = None

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
        result = self.pipeline.run_pipeline()
        self._last_run_time = datetime.now(timezone.utc)
        self._run_count += 1

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
            "next_run_in_seconds": self._get_next_run_interval() if self._status == SchedulerStatus.RUNNING else None
        }

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
        try:
            logger.info("Running scheduled autonomous learning pipeline")
            start_time = time.time()

            # Run the pipeline
            result = self.pipeline.run_pipeline()

            # Update tracking
            self._last_run_time = datetime.now(timezone.utc)
            self._run_count += 1

            duration = time.time() - start_time
            logger.info(f"Scheduled pipeline completed in {duration:.2f}s")

            # Call completion callback if set
            if self._completion_callback:
                try:
                    self._completion_callback(result)
                except Exception as e:
                    logger.error(f"Error in completion callback: {e}")

        except Exception as e:
            logger.error(f"Error running scheduled pipeline: {e}")

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