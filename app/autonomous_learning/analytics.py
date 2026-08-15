"""Learning Analytics for Autonomous Learning System.

This module tracks and analyzes learning metrics to provide insights into
the effectiveness of the autonomous learning system over time.
"""

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict, deque
import time

from app.core.logger import logger
from app.autonomous_learning.models import (
    LearningPipelineResult,
    KnowledgeGap,
    LearningEvent,
    LearningEventType,
    ResearchTask,
    ResearchStatus
)
from dataclasses import dataclass


@dataclass
class LearningMetrics:
    """Container for learning metrics over a time period."""
    timestamp: str
    period_type: str  # "hourly", "daily", "weekly", "cumulative"

    # Pipeline metrics
    pipelines_run: int = 0
    experiences_processed: int = 0
    experiences_analyzed: int = 0

    # Knowledge extraction metrics
    knowledge_extracted: int = 0
    knowledge_validated: int = 0
    knowledge_stored: int = 0
    knowledge_rejected: int = 0

    # Gap detection metrics
    gaps_detected: int = 0
    gaps_resolved: int = 0

    # Research metrics
    research_tasks_started: int = 0
    research_tasks_completed: int = 0
    research_tasks_failed: int = 0

    # Performance metrics
    avg_pipeline_duration: float = 0.0
    avg_extraction_time: float = 0.0
    avg_validation_time: float = 0.0
    avg_storage_time: float = 0.0

    # Quality metrics
    validation_success_rate: float = 0.0  # validated / extracted
    storage_success_rate: float = 0.0     # stored / validated
    research_success_rate: float = 0.0    # completed / started
    gap_resolution_rate: float = 0.0      # resolved / detected

    # Knowledge quality
    avg_knowledge_confidence: float = 0.0
    high_confidence_knowledge_ratio: float = 0.0  # % of knowledge with confidence > 0.8

    # Error tracking
    pipeline_errors: int = 0
    validation_errors: int = 0
    storage_errors: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "period_type": self.period_type,
            "pipelines_run": self.pipelines_run,
            "experiences_processed": self.experiences_processed,
            "experiences_analyzed": self.experiences_analyzed,
            "knowledge_extracted": self.knowledge_extracted,
            "knowledge_validated": self.knowledge_validated,
            "knowledge_stored": self.knowledge_stored,
            "knowledge_rejected": self.knowledge_rejected,
            "gaps_detected": self.gaps_detected,
            "gaps_resolved": self.gaps_resolved,
            "research_tasks_started": self.research_tasks_started,
            "research_tasks_completed": self.research_tasks_completed,
            "research_tasks_failed": self.research_tasks_failed,
            "avg_pipeline_duration": self.avg_pipeline_duration,
            "avg_extraction_time": self.avg_extraction_time,
            "avg_validation_time": self.avg_validation_time,
            "avg_storage_time": self.avg_storage_time,
            "validation_success_rate": self.validation_success_rate,
            "storage_success_rate": self.storage_success_rate,
            "research_success_rate": self.research_success_rate,
            "gap_resolution_rate": self.gap_resolution_rate,
            "avg_knowledge_confidence": self.avg_knowledge_confidence,
            "high_confidence_knowledge_ratio": self.high_confidence_knowledge_ratio,
            "pipeline_errors": self.pipeline_errors,
            "validation_errors": self.validation_errors,
            "storage_errors": self.storage_errors
        }


@dataclass
class LearningTrend:
    """Represents a trend in learning metrics over time."""
    metric_name: str
    values: List[float]  # Values over time
    timestamps: List[str]  # Corresponding timestamps
    direction: str  # "improving", "declining", "stable"
    change_rate: float  # Rate of change per unit time


class LearningAnalytics:
    """Tracks and analyzes learning metrics for the autonomous learning system."""

    def __init__(
        self,
        storage_path: Optional[Path] = None,
        max_metrics_history: int = 1000,
    ):
        """Initialize the learning analytics system.

        Args:
            storage_path: Path to store analytics data
            max_metrics_history: Maximum number of historical metrics to keep
        """
        if isinstance(storage_path, str):
            storage_path = Path(storage_path)
        self.storage_path = storage_path or Path("data/autonomous_learning/analytics.json")
        self.max_metrics_history = max_metrics_history

        # In-memory storage for recent metrics
        self._metrics_history: deque = deque(maxlen=max_metrics_history)
        self._events_buffer: List[LearningEvent] = []
        self._pipeline_results: List[LearningPipelineResult] = []

        # Running counters for current period
        self._reset_counters()

        # Thread safety
        self._lock = threading.RLock()

        # Load existing data
        self._load()

        # Start background aggregation thread
        self._stop_event = threading.Event()
        self._aggregation_thread = threading.Thread(
            target=self._aggregation_loop,
            daemon=True
        )
        self._aggregation_thread.start()

    def _reset_counters(self):
        """Reset counters for a new measurement period."""
        self._current_metrics = LearningMetrics(
            timestamp=datetime.now(timezone.utc).isoformat(),
            period_type="realtime"
        )
        self._period_start_time = time.time()

    def record_pipeline_start(self):
        """Record the start of a pipeline execution."""
        with self._lock:
            self._current_metrics.pipelines_run += 1

    def record_experience_processed(self, count: int = 1):
        """Record experiences processed."""
        with self._lock:
            self._current_metrics.experiences_processed += count

    def record_experience_analyzed(self, count: int = 1):
        """Record experiences analyzed."""
        with self._lock:
            self._current_metrics.experiences_analyzed += count

    def record_knowledge_extracted(self, count: int = 1):
        """Record knowledge objects extracted."""
        with self._lock:
            self._current_metrics.knowledge_extracted += count

    def record_knowledge_validated(self, count: int = 1):
        """Record knowledge objects validated."""
        with self._lock:
            self._current_metrics.knowledge_validated += count

    def record_knowledge_stored(self, count: int = 1):
        """Record knowledge objects stored."""
        with self._lock:
            self._current_metrics.knowledge_stored += count

    def record_knowledge_rejected(self, count: int = 1):
        """Record knowledge objects rejected."""
        with self._lock:
            self._current_metrics.knowledge_rejected += count

    def record_gap_detected(self, count: int = 1):
        """Record knowledge gaps detected."""
        with self._lock:
            self._current_metrics.gaps_detected += count

    def record_gap_resolved(self, count: int = 1):
        """Record knowledge gaps resolved."""
        with self._lock:
            self._current_metrics.gaps_resolved += count

    def record_research_started(self, count: int = 1):
        """Record research tasks started."""
        with self._lock:
            self._current_metrics.research_tasks_started += count

    def record_research_completed(self, count: int = 1):
        """Record research tasks completed."""
        with self._lock:
            self._current_metrics.research_tasks_completed += count

    def record_research_failed(self, count: int = 1):
        """Record research tasks failed."""
        with self._lock:
            self._current_metrics.research_tasks_failed += count

    def record_pipeline_duration(self, duration_seconds: float):
        """Record pipeline execution duration."""
        with self._lock:
            # Update rolling average
            if self._current_metrics.pipelines_run == 1:
                self._current_metrics.avg_pipeline_duration = duration_seconds
            else:
                # Exponential moving average
                alpha = 0.1
                self._current_metrics.avg_pipeline_duration = (
                    alpha * duration_seconds +
                    (1 - alpha) * self._current_metrics.avg_pipeline_duration
                )

    def record_knowledge_quality(self, avg_confidence: float, high_confidence_ratio: float):
        """Record knowledge quality metrics."""
        with self._lock:
            self._current_metrics.avg_knowledge_confidence = avg_confidence
            self._current_metrics.high_confidence_knowledge_ratio = high_confidence_ratio

    def record_error(self, error_type: str):
        """Record an error occurrence."""
        with self._lock:
            if error_type == "pipeline":
                self._current_metrics.pipeline_errors += 1
            elif error_type == "validation":
                self._current_metrics.validation_errors += 1
            elif error_type == "storage":
                self._current_metrics.storage_errors += 1

    def record_event(self, event: LearningEvent):
        """Record a learning event for analytics."""
        with self._lock:
            self._events_buffer.append(event)

            # Update metrics based on event type
            if event.event_type == LearningEventType.EXPERIENCE_COLLECTED:
                count = len(event.related_experience_ids) if event.related_experience_ids else 1
                self.record_experience_processed(count)
            elif event.event_type == LearningEventType.KNOWLEDGE_EXTRACTED:
                count = len(event.related_knowledge_ids) if event.related_knowledge_ids else 1
                self.record_knowledge_extracted(count)
            elif event.event_type == LearningEventType.KNOWLEDGE_VALIDATED:
                count = len(event.related_knowledge_ids) if event.related_knowledge_ids else 1
                self.record_knowledge_validated(count)
            elif event.event_type == LearningEventType.KNOWLEDGE_STORED:
                count = len(event.related_knowledge_ids) if event.related_knowledge_ids else 1
                self.record_knowledge_stored(count)
            elif event.event_type == LearningEventType.KNOWLEDGE_REJECTED:
                count = len(event.related_knowledge_ids) if event.related_knowledge_ids else 1
                self.record_knowledge_rejected(count)
            elif event.event_type == LearningEventType.GAP_DETECTED:
                count = len(event.related_gap_ids) if event.related_gap_ids else 1
                self.record_gap_detected(count)
            elif event.event_type == LearningEventType.RESEARCH_STARTED:
                count = 1  # Each event represents one research task started
                self.record_research_started(count)
            elif event.event_type == LearningEventType.RESEARCH_COMPLETED:
                count = 1
                self.record_research_completed(count)
            elif event.event_type == LearningEventType.RESEARCH_FAILED:
                count = 1
                self.record_research_failed(count)

    def record_pipeline_result(self, result: LearningPipelineResult):
        """Record a complete pipeline execution result."""
        with self._lock:
            self._pipeline_results.append(result)

            # Update base counters
            self._current_metrics.pipelines_run += 1
            self._current_metrics.experiences_processed += result.experiences_processed
            self._current_metrics.experiences_analyzed += result.experiences_analyzed
            self._current_metrics.knowledge_extracted += result.knowledge_objects_extracted
            self._current_metrics.knowledge_validated += result.knowledge_objects_validated
            self._current_metrics.knowledge_stored += result.knowledge_objects_stored
            self._current_metrics.knowledge_rejected += result.knowledge_objects_rejected
            self._current_metrics.gaps_detected += result.gaps_detected
            self._current_metrics.gaps_resolved += result.gaps_resolved
            self._current_metrics.research_tasks_started += result.research_tasks_started
            self._current_metrics.research_tasks_completed += result.research_tasks_completed
            self._current_metrics.research_tasks_failed += result.research_tasks_failed

            # Update pipeline duration
            self._current_metrics.avg_pipeline_duration = (
                0.1 * result.duration_seconds + 0.9 * self._current_metrics.avg_pipeline_duration
            ) if self._current_metrics.avg_pipeline_duration > 0 else result.duration_seconds

            # Update derived metrics
            if result.knowledge_objects_extracted > 0:
                validation_rate = result.knowledge_objects_validated / result.knowledge_objects_extracted
                alpha = 0.1
                current_rate = self._current_metrics.validation_success_rate
                self._current_metrics.validation_success_rate = (
                    alpha * validation_rate + (1 - alpha) * current_rate
                )

            if result.knowledge_objects_validated > 0:
                storage_rate = result.knowledge_objects_stored / result.knowledge_objects_validated
                alpha = 0.1
                current_rate = self._current_metrics.storage_success_rate
                self._current_metrics.storage_success_rate = (
                    alpha * storage_rate + (1 - alpha) * current_rate
                )

            if result.research_tasks_started > 0:
                research_rate = result.research_tasks_completed / result.research_tasks_started
                alpha = 0.1
                current_rate = self._current_metrics.research_success_rate
                self._current_metrics.research_success_rate = (
                    alpha * research_rate + (1 - alpha) * current_rate
                )

            if result.gaps_detected > 0:
                gap_rate = result.gaps_resolved / result.gaps_detected
                alpha = 0.1
                current_rate = self._current_metrics.gap_resolution_rate
                self._current_metrics.gap_resolution_rate = (
                    alpha * gap_rate + (1 - alpha) * current_rate
                )

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the background aggregation thread."""
        self._stop_event.set()
        if self._aggregation_thread and self._aggregation_thread.is_alive():
            self._aggregation_thread.join(timeout=timeout)

    def _aggregation_loop(self):
        """Background thread to periodically aggregate metrics."""
        while not self._stop_event.wait(60.0):
            self._aggregate_metrics()

    def _aggregate_metrics(self):
        """Aggregate current metrics and store in history."""
        with self._lock:
            # Calculate completion percentage for the period
            period_duration = time.time() - self._period_start_time

            # Create a snapshot of current metrics
            metrics_snapshot = LearningMetrics(
                timestamp=datetime.now(timezone.utc).isoformat(),
                period_type="minute",
                pipelines_run=self._current_metrics.pipelines_run,
                experiences_processed=self._current_metrics.experiences_processed,
                experiences_analyzed=self._current_metrics.experiences_analyzed,
                knowledge_extracted=self._current_metrics.knowledge_extracted,
                knowledge_validated=self._current_metrics.knowledge_validated,
                knowledge_stored=self._current_metrics.knowledge_stored,
                knowledge_rejected=self._current_metrics.knowledge_rejected,
                gaps_detected=self._current_metrics.gaps_detected,
                gaps_resolved=self._current_metrics.gaps_resolved,
                research_tasks_started=self._current_metrics.research_tasks_started,
                research_tasks_completed=self._current_metrics.research_tasks_completed,
                research_tasks_failed=self._current_metrics.research_tasks_failed,
                avg_pipeline_duration=self._current_metrics.avg_pipeline_duration,
                validation_success_rate=self._current_metrics.validation_success_rate,
                storage_success_rate=self._current_metrics.storage_success_rate,
                research_success_rate=self._current_metrics.research_success_rate,
                gap_resolution_rate=self._current_metrics.gap_resolution_rate,
                avg_knowledge_confidence=self._current_metrics.avg_knowledge_confidence,
                high_confidence_knowledge_ratio=self._current_metrics.high_confidence_knowledge_ratio,
                pipeline_errors=self._current_metrics.pipeline_errors,
                validation_errors=self._current_metrics.validation_errors,
                storage_errors=self._current_metrics.storage_errors
            )

            # Add to history
            self._metrics_history.append(metrics_snapshot)

            # Reset counters for next period
            self._reset_counters()

            # Persist periodically
            if len(self._metrics_history) % 10 == 0:  # Every 10 minutes
                self._save()

    def get_current_metrics(self) -> Dict[str, Any]:
        """Get current real-time metrics."""
        with self._lock:
            return self._current_metrics.to_dict()

    def get_historical_metrics(self, limit: int = 60) -> List[Dict[str, Any]]:
        """Get historical metrics from the last N time periods.

        Args:
            limit: Maximum number of historical periods to return

        Returns:
            List of metric dictionaries, oldest first
        """
        with self._lock:
            if len(self._metrics_history) <= limit:
                return [m.to_dict() for m in self._metrics_history]
            else:
                # Return the most recent 'limit' entries
                start_idx = len(self._metrics_history) - limit
                return [self._metrics_history[i].to_dict()
                       for i in range(start_idx, len(self._metrics_history))]

    def get_trends(self, metric_name: str, hours: int = 24) -> Optional[LearningTrend]:
        """Calculate trends for a specific metric over time.

        Args:
            metric_name: Name of the metric to analyze
            hours: Number of hours to look back

        Returns:
            LearningTrend object or None if insufficient data
        """
        with self._lock:
            cutoff_time = time.time() - (hours * 3600)

            # Filter recent metrics
            recent_metrics = [
                m for m in self._metrics_history
                if datetime.fromisoformat(m.timestamp.replace("Z", "+00:00")).timestamp() > cutoff_time
            ]

            if len(recent_metrics) < 2:
                return None

            # Extract values and timestamps
            values = []
            timestamps = []

            for metric in recent_metrics:
                if hasattr(metric, metric_name):
                    values.append(getattr(metric, metric_name))
                    timestamps.append(metric.timestamp)

            if len(values) < 2:
                return None

            # Calculate trend
            # Simple linear regression to determine direction and rate
            n = len(values)
            x_vals = list(range(n))
            y_vals = values

            # Calculate slope (rate of change)
            sum_x = sum(x_vals)
            sum_y = sum(y_vals)
            sum_xy = sum(x * y for x, y in zip(x_vals, y_vals))
            sum_x2 = sum(x * x for x in x_vals)

            if n * sum_x2 - sum_x * sum_x == 0:
                slope = 0
            else:
                slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x * sum_x)

            # Determine direction
            if slope > 0.01:
                direction = "improving"
            elif slope < -0.01:
                direction = "declining"
            else:
                direction = "stable"

            return LearningTrend(
                metric_name=metric_name,
                values=values,
                timestamps=timestamps,
                direction=direction,
                change_rate=slope
            )

    def get_learning_summary(self) -> Dict[str, Any]:
        """Get a comprehensive summary of learning performance.

        Returns:
            Dictionary containing key learning metrics and insights
        """
        with self._lock:
            # Get recent metrics (last hour)
            recent_metrics = self.get_historical_metrics(limit=60)  # Last 60 minutes

            if not recent_metrics:
                return {"status": "no_data"}

            # Calculate aggregates
            total_pipelines = sum(m["pipelines_run"] for m in recent_metrics)
            total_experiences = sum(m["experiences_processed"] for m in recent_metrics)
            total_knowledge_extracted = sum(m["knowledge_extracted"] for m in recent_metrics)
            total_knowledge_stored = sum(m["knowledge_stored"] for m in recent_metrics)
            total_gaps_detected = sum(m["gaps_detected"] for m in recent_metrics)
            total_gaps_resolved = sum(m["gaps_resolved"] for m in recent_metrics)
            total_research_started = sum(m["research_tasks_started"] for m in recent_metrics)
            total_research_completed = sum(m["research_tasks_completed"] for m in recent_metrics)

            # Calculate rates
            knowledge_retention_rate = (
                total_knowledge_stored / max(total_knowledge_extracted, 1)
            )
            gap_resolution_rate = (
                total_gaps_resolved / max(total_gaps_detected, 1)
            )
            research_completion_rate = (
                total_research_completed / max(total_research_started, 1)
            )

            # Get trends for key metrics
            extraction_trend = self.get_trends("knowledge_extracted", hours=6)
            storage_trend = self.get_trends("knowledge_stored", hours=6)
            gap_resolution_trend = self.get_trends("gap_resolution_rate", hours=6)

            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "period": "last_hour",
                "activity": {
                    "pipelines_run": total_pipelines,
                    "experiences_processed": total_experiences,
                    "knowledge_extracted": total_knowledge_extracted,
                    "knowledge_stored": total_knowledge_stored,
                    "gaps_detected": total_gaps_detected,
                    "gaps_resolved": total_gaps_resolved,
                    "research_tasks_started": total_research_started,
                    "research_tasks_completed": total_research_completed
                },
                "efficiency": {
                    "knowledge_retention_rate": knowledge_retention_rate,
                    "gap_resolution_rate": gap_resolution_rate,
                    "research_completion_rate": research_completion_rate
                },
                "trends": {
                    "knowledge_extraction": {
                        "direction": extraction_trend.direction if extraction_trend else "unknown",
                        "change_rate": extraction_trend.change_rate if extraction_trend else 0
                    },
                    "knowledge_storage": {
                        "direction": storage_trend.direction if storage_trend else "unknown",
                        "change_rate": storage_trend.change_rate if storage_trend else 0
                    },
                    "gap_resolution": {
                        "direction": gap_resolution_trend.direction if gap_resolution_trend else "unknown",
                        "change_rate": gap_resolution_trend.change_rate if gap_resolution_trend else 0
                    }
                },
                "recent_metrics": recent_metrics[-5:] if len(recent_metrics) >= 5 else recent_metrics
            }

    def display_dashboard(self):
        """Display a simple console dashboard of learning metrics."""
        print("\n" + "="*60)
        print("FREYA LEARNING ANALYTICS DASHBOARD")
        print("="*60)

        summary = self.get_learning_summary()

        if summary.get("status") == "no_data":
            print("No learning data available yet.")
            print("="*60)
            return

        print(f"Last Updated: {summary['timestamp']}")
        print(f"Period: {summary['period']}")
        print()

        print("ACTIVITY (Last Hour):")
        print(f"  Pipelines Run:          {summary['activity']['pipelines_run']}")
        print(f"  Experiences Processed:  {summary['activity']['experiences_processed']}")
        print(f"  Knowledge Extracted:    {summary['activity']['knowledge_extracted']}")
        print(f"  Knowledge Stored:       {summary['activity']['knowledge_stored']}")
        print(f"  Gaps Detected:          {summary['activity']['gaps_detected']}")
        print(f"  Gaps Resolved:          {summary['activity']['gaps_resolved']}")
        print(f"  Research Started:       {summary['activity']['research_tasks_started']}")
        print(f"  Research Completed:     {summary['activity']['research_tasks_completed']}")
        print()

        print("EFFICIENCY METRICS:")
        print(f"  Knowledge Retention:    {summary['efficiency']['knowledge_retention_rate']:.1%}")
        print(f"  Gap Resolution Rate:    {summary['efficiency']['gap_resolution_rate']:.1%}")
        print(f"  Research Completion:    {summary['efficiency']['research_completion_rate']:.1%}")
        print()

        print("TRENDS (6-hour):")
        trends = summary['trends']
        for metric_name, trend_data in trends.items():
            direction_emoji = {
                "improving": "[UP]",
                "declining": "[DOWN]",
                "stable": "[->]",
                "unknown": "[?]",
            }.get(trend_data['direction'], "[?]")

            print(f"  {direction_emoji} {metric_name.replace('_', ' ').title()}: "
                  f"{trend_data['direction']} ({trend_data['change_rate']:+.4f}/period)")
        print()

        print("RECENT METRICS (Last 5 minutes):")
        for i, metrics in enumerate(summary['recent_metrics']):
            mins_ago = (len(summary['recent_metrics']) - i - 1) * 1
            print(f"  {mins_ago}min ago: "
                  f"P:{metrics['pipelines_run']} "
                  f"E:{metrics['experiences_processed']} "
                  f"K:{metrics['knowledge_stored']} "
                  f"G:{metrics['gaps_resolved']}/{metrics['gaps_detected']} "
                  f"R:{metrics['research_tasks_completed']}/{metrics['research_tasks_started']}")

        print("="*60)

    def _save(self):
        """Persist analytics data to disk."""
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)

            data = {
                "metrics_history": [m.to_dict() for m in self._metrics_history],
                "last_updated": datetime.now(timezone.utc).isoformat()
            }

            temp_path = self.storage_path.with_suffix(".tmp")
            with open(temp_path, "w") as f:
                json.dump(data, f, indent=2, default=str)
            temp_path.replace(self.storage_path)

            logger.debug(f"Saved learning analytics to {self.storage_path}")

        except Exception as e:
            logger.warning(f"Failed to save learning analytics: {e}")

    def _load(self):
        """Load analytics data from disk."""
        try:
            if not self.storage_path.exists():
                return

            with open(self.storage_path, "r") as f:
                data = json.load(f)

            # Load metrics history
            metrics_data = data.get("metrics_history", [])
            for m_dict in metrics_data:
                # Remove extra fields that aren't in the dataclass
                filtered_dict = {k: v for k, v in m_dict.items()
                               if k in LearningMetrics.__dataclass_fields__}
                metrics = LearningMetrics(**filtered_dict)
                self._metrics_history.append(metrics)

            logger.info(f"Loaded learning analytics: {len(self._metrics_history)} historical records")

        except Exception as e:
            logger.warning(f"Failed to load learning analytics: {e}")