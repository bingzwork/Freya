"""Metric Collector for gathering and storing time-series metrics.

This module provides a flexible framework for collecting, storing,
and querying time-series metrics from various sources.
"""

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, List, Any, Optional, Union
from collections import defaultdict


class MetricType(Enum):
    """Types of metrics."""
    GAUGE = "gauge"      # Single numerical value
    COUNTER = "counter"  # Incremental counter
    RATE = "rate"        # Rate of change
    HISTOGRAM = "histogram"  # Distribution of values
    BOOLEAN = "boolean"  # True/False value


@dataclass
class MetricValue:
    """A single metric value at a point in time."""
    timestamp: float  # Unix timestamp
    value: Union[float, int, bool]
    labels: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def now(cls, value: Union[float, int, bool], labels: Optional[Dict[str, str]] = None) -> "MetricValue":
        """Create a metric value with current timestamp."""
        return cls(
            timestamp=time.time(),
            value=value,
            labels=labels or {},
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp,
            "value": self.value,
            "labels": self.labels,
        }


@dataclass
class Metric:
    """Definition of a metric."""
    name: str
    metric_type: MetricType
    description: str = ""
    unit: str = ""
    labels: List[str] = field(default_factory=list)

    def __post_init__(self):
        if isinstance(self.metric_type, str):
            self.metric_type = MetricType(self.metric_type)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "type": self.metric_type.value,
            "description": self.description,
            "unit": self.unit,
            "labels": self.labels,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Metric":
        """Create from dictionary."""
        return cls(
            name=data["name"],
            metric_type=MetricType(data.get("type", "gauge")),
            description=data.get("description", ""),
            unit=data.get("unit", ""),
            labels=data.get("labels", []),
        )


class MetricCollector:
    """Collects and stores time-series metrics.

    This class provides a flexible framework for collecting metrics
    from various sources and storing them for analysis and visualization.
    """

    def __init__(
        self,
        workspace: str = ".",
        max_values_per_metric: int = 10000,
        storage_path: Optional[str] = None,
    ):
        """Initialize the metric collector.

        Args:
            workspace: The project workspace directory.
            max_values_per_metric: Maximum number of values to store per metric.
            storage_path: Path to store metrics persistently.
        """
        self.workspace = Path(workspace).resolve()
        self.max_values = max_values_per_metric
        self.storage_path = Path(storage_path or (self.workspace / ".metrics")).resolve()

        # Metric definitions: name -> Metric
        self._metrics: Dict[str, Metric] = {}

        # Metric values: metric_name -> List[MetricValue]
        self._values: Dict[str, List[MetricValue]] = defaultdict(list)

        # Aggregated values for counters and rates
        self._counters: Dict[str, float] = defaultdict(float)
        self._last_values: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))

        # Load from storage if exists
        self._load_from_storage()

    def register_metric(self, metric: Metric) -> None:
        """Register a new metric definition."""
        self._metrics[metric.name] = metric

    def unregister_metric(self, name: str) -> None:
        """Unregister a metric."""
        self._metrics.pop(name, None)
        self._values.pop(name, None)
        self._counters.pop(name, None)
        self._last_values.pop(name, None)

    def get_metric(self, name: str) -> Optional[Metric]:
        """Get a metric definition by name."""
        return self._metrics.get(name)

    def list_metrics(self) -> List[Metric]:
        """List all registered metrics."""
        return list(self._metrics.values())

    def record(self, name: str, value: Union[float, int, bool], labels: Optional[Dict[str, str]] = None) -> None:
        """Record a metric value.

        Args:
            name: Name of the metric
            value: Value to record
            labels: Optional labels for this value
        """
        metric = self._metrics.get(name)
        if metric is None:
            # Auto-register gauge metric if not exists
            metric = Metric(name=name, metric_type=MetricType.GAUGE)
            self._metrics[name] = metric

        metric_value = MetricValue.now(value, labels)
        self._values[name].append(metric_value)

        # Trim old values
        if len(self._values[name]) > self.max_values:
            self._values[name] = self._values[name][-self.max_values:]

        # Handle counter aggregation
        if metric.metric_type == MetricType.COUNTER:
            self._counters[name] += value

    def increment(self, name: str, value: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
        """Increment a counter metric.

        Args:
            name: Name of the counter
            value: Amount to increment
            labels: Optional labels
        """
        # Ensure the metric is registered as a counter
        if name not in self._metrics:
            self.register_metric(Metric(name=name, metric_type=MetricType.COUNTER))
        self._counters[name] += value
        # Record the increment event (but don't double-count in _counters)
        metric_value = MetricValue.now(value, labels)
        self._values[name].append(metric_value)
        if len(self._values[name]) > self.max_values:
            self._values[name] = self._values[name][-self.max_values:]

    def set_gauge(self, name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Set a gauge metric value.

        Args:
            name: Name of the gauge
            value: Value to set
            labels: Optional labels
        """
        self.record(name, value, labels)

    def observe(self, name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Observe a value for a histogram metric."""
        self.record(name, value, labels)

    def get_values(
        self,
        name: str,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        count: Optional[int] = None,
    ) -> List[MetricValue]:
        """Get metric values for a specific metric.

        Args:
            name: Name of the metric
            start_time: Start timestamp (Unix time)
            end_time: End timestamp (Unix time)
            count: Maximum number of values to return
        """
        values = self._values.get(name, [])

        # Filter by time
        if start_time is not None or end_time is not None:
            filtered = []
            for v in values:
                if start_time is not None and v.timestamp < start_time:
                    continue
                if end_time is not None and v.timestamp > end_time:
                    continue
                filtered.append(v)
            values = filtered

        # Limit count
        if count is not None:
            values = values[-count:]

        return values

    def get_current_value(self, name: str) -> Optional[Union[float, int, bool]]:
        """Get the most recent value for a metric."""
        values = self._values.get(name, [])
        if values:
            return values[-1].value
        return None

    def get_counter_value(self, name: str) -> float:
        """Get the current value of a counter."""
        return self._counters.get(name, 0.0)

    def reset_counter(self, name: str) -> None:
        """Reset a counter to zero."""
        self._counters[name] = 0.0

    def get_rate(self, name: str, interval_seconds: float = 60.0) -> float:
        """Calculate the rate of change for a metric.

        Args:
            name: Name of the metric
            interval_seconds: Time interval for rate calculation
        """
        values = self.get_values(name, count=2)
        if len(values) < 2:
            return 0.0

        time_diff = values[-1].timestamp - values[-2].timestamp
        if time_diff <= 0:
            return 0.0

        value_diff = values[-1].value - values[-2].value
        return value_diff / time_diff * interval_seconds

    def query(
        self,
        name_pattern: Optional[str] = None,
        metric_type: Optional[MetricType] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> Dict[str, List[MetricValue]]:
        """Query metrics matching criteria.

        Args:
            name_pattern: Pattern to match metric names (substring match)
            metric_type: Filter by metric type
            start_time: Start timestamp
            end_time: End timestamp
        """
        results = {}

        for metric_name, metric in self._metrics.items():
            # Filter by name pattern
            if name_pattern and name_pattern not in metric_name:
                continue

            # Filter by type
            if metric_type and metric.metric_type != metric_type:
                continue

            # Get values
            values = self.get_values(
                metric_name,
                start_time=start_time,
                end_time=end_time,
            )

            if values:
                results[metric_name] = values

        return results

    def aggregate(
        self,
        name: str,
        aggregation: str = "avg",
        interval_seconds: float = 60.0,
    ) -> List[Dict[str, Any]]:
        """Aggregate metric values over time intervals.

        Args:
            name: Metric name
            aggregation: Type of aggregation (avg, sum, min, max, count)
            interval_seconds: Time interval for aggregation
        """
        values = self.get_values(name)
        if not values:
            return []

        # Sort by timestamp
        values = sorted(values, key=lambda v: v.timestamp)

        aggregated = []
        current_interval_start = values[0].timestamp
        current_interval_values = []
        current_interval_label = {}

        for value in values:
            # Check if we've moved to a new interval
            interval_start = value.timestamp - (value.timestamp % interval_seconds)
            if interval_start != current_interval_start:
                # Process current interval
                if current_interval_values:
                    result = self._aggregate_values(
                        current_interval_values,
                        aggregation,
                        current_interval_start,
                        current_interval_start + interval_seconds,
                        current_interval_label,
                    )
                    aggregated.append(result)

                # Start new interval
                current_interval_start = interval_start
                current_interval_values = [value]
                current_interval_label = dict(value.labels)
            else:
                current_interval_values.append(value)

        # Process last interval
        if current_interval_values:
            result = self._aggregate_values(
                current_interval_values,
                aggregation,
                current_interval_start,
                current_interval_start + interval_seconds,
                current_interval_label,
            )
            aggregated.append(result)

        return aggregated

    def _aggregate_values(
        self,
        values: List[MetricValue],
        aggregation: str,
        start_time: float,
        end_time: float,
        labels: Dict[str, str],
    ) -> Dict[str, Any]:
        """Helper to aggregate values."""
        numeric_values = [v for v in values if isinstance(v.value, (int, float))]

        if not numeric_values:
            return {
                "start_time": start_time,
                "end_time": end_time,
                "count": len(values),
                "labels": labels,
            }

        result = {
            "start_time": start_time,
            "end_time": end_time,
            "count": len(numeric_values),
            "labels": labels,
        }

        if aggregation == "avg":
            result["value"] = sum(v.value for v in numeric_values) / len(numeric_values)
        elif aggregation == "sum":
            result["value"] = sum(v.value for v in numeric_values)
        elif aggregation == "min":
            result["value"] = min(v.value for v in numeric_values)
        elif aggregation == "max":
            result["value"] = max(v.value for v in numeric_values)
        else:
            result["value"] = len(numeric_values)

        return result

    def save_to_storage(self) -> None:
        """Save metrics to persistent storage."""
        self.storage_path.mkdir(parents=True, exist_ok=True)

        data = {
            "metrics": [m.to_dict() for m in self._metrics.values()],
            "values": {
                name: [v.to_dict() for v in values]
                for name, values in self._values.items()
            },
            "counters": dict(self._counters),
        }

        storage_file = self.storage_path / "metrics.json"
        with open(storage_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _load_from_storage(self) -> None:
        """Load metrics from persistent storage."""
        storage_file = self.storage_path / "metrics.json"
        if not storage_file.exists():
            return

        try:
            with open(storage_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            for metric_data in data.get("metrics", []):
                metric = Metric.from_dict(metric_data)
                self._metrics[metric.name] = metric

            for name, values in data.get("values", {}).items():
                for v in values:
                    self._values[name].append(MetricValue(**v))

            self._counters.update(data.get("counters", {}))
        except Exception as e:
            print(f"Error loading metrics from storage: {e}")

    def clear(self) -> None:
        """Clear all metrics and values."""
        self._metrics.clear()
        self._values.clear()
        self._counters.clear()
        self._last_values.clear()

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of collected metrics."""
        return {
            "metric_count": len(self._metrics),
            "total_values": sum(len(v) for v in self._values.values()),
            "counter_values": dict(self._counters),
        }
