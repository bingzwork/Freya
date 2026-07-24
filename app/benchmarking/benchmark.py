"""Core benchmarking classes.

This module defines the fundamental classes for creating and running
benchmarks in the Freya AI system.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Dict, List, Any, Optional, Callable, Tuple
import json
from pathlib import Path
import time
import uuid
import statistics


class BenchmarkStatus(Enum):
    """Status of a benchmark run."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BenchmarkMetric(Enum):
    """Types of metrics that can be collected."""
    TIME = "time"  # Execution time in seconds
    ACCURACY = "accuracy"  # Accuracy score (0.0-1.0)
    PRECISION = "precision"  # Precision score (0.0-1.0)
    RECALL = "recall"  # Recall score (0.0-1.0)
    F1_SCORE = "f1_score"  # F1 score (0.0-1.0)
    MEMORY = "memory"  # Memory usage in MB
    TOKENS = "tokens"  # Token count
    COST = "cost"  # Cost in dollars
    THROUGHPUT = "throughput"  # Items per second
    LATENCY = "latency"  # Latency in milliseconds
    SUCCESS_RATE = "success_rate"  # Success rate (0.0-1.0)
    ERROR_RATE = "error_rate"  # Error rate (0.0-1.0)


@dataclass
class BenchmarkResult:
    """Result of a single benchmark run."""
    benchmark_id: str
    result_id: str = field(default_factory=lambda: f"result_{uuid.uuid4().hex[:8]}")
    name: str = ""
    description: str = ""
    status: BenchmarkStatus = BenchmarkStatus.PENDING
    start_time: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    end_time: str = ""
    duration: float = 0.0  # seconds
    metrics: Dict[BenchmarkMetric, float] = field(default_factory=dict)
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if isinstance(self.status, str):
            self.status = BenchmarkStatus(self.status)

    @property
    def success(self) -> bool:
        """Check if the benchmark ran successfully."""
        return self.status == BenchmarkStatus.COMPLETED

    @property
    def failed(self) -> bool:
        """Check if the benchmark failed."""
        return self.status == BenchmarkStatus.FAILED

    def set_end_time(self) -> None:
        """Set the end time and calculate duration."""
        self.end_time = datetime.now(timezone.utc).isoformat()
        if self.start_time:
            start = datetime.fromisoformat(self.start_time)
            end = datetime.fromisoformat(self.end_time)
            self.duration = (end - start).total_seconds()

    def add_metric(self, metric: BenchmarkMetric, value: float) -> None:
        """Add a metric to the result.

        Args:
            metric: The type of metric
            value: The metric value
        """
        self.metrics[metric] = value

    def get_metric(self, metric: BenchmarkMetric) -> Optional[float]:
        """Get a metric value.

        Args:
            metric: The type of metric

        Returns:
            The metric value if present, None otherwise
        """
        return self.metrics.get(metric)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "benchmark_id": self.benchmark_id,
            "result_id": self.result_id,
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "metrics": {k.value: v for k, v in self.metrics.items()},
            "error": self.error,
            "metadata": self.metadata,
            "success": self.success,
            "failed": self.failed,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BenchmarkResult":
        """Create from dictionary."""
        result = cls(
            benchmark_id=data.get("benchmark_id", ""),
            result_id=data.get("result_id", f"result_{uuid.uuid4().hex[:8]}"),
            name=data.get("name", ""),
            description=data.get("description", ""),
            status=data.get("status", "pending"),
            start_time=data.get("start_time", ""),
            end_time=data.get("end_time", ""),
            duration=data.get("duration", 0.0),
            error=data.get("error"),
            metadata=data.get("metadata", {}),
        )
        # Convert metrics back to enum keys
        result.metrics = {}
        for key, value in data.get("metrics", {}).items():
            metric = BenchmarkMetric(key)
            result.metrics[metric] = value
        return result

    def __str__(self) -> str:
        return f"BenchmarkResult(name='{self.name}', status={self.status.value}, duration={self.duration:.2f}s)"


@dataclass
class Benchmark:
    """Represents a single benchmark.

    A benchmark is a named test that measures some aspect of system performance.
    """
    name: str
    benchmark_id: str = field(default_factory=lambda: f"benchmark_{uuid.uuid4().hex[:8]}")
    description: str = ""
    category: str = "performance"  # performance, accuracy, reliability, etc.
    author: str = "system"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.name == "":
            raise ValueError("Benchmark must have a name")

    def run(self, **kwargs) -> BenchmarkResult:
        """Run this benchmark.

        This method should be overridden by subclasses to implement
        the actual benchmark logic.

        Args:
            **kwargs: Additional arguments for the benchmark

        Returns:
            BenchmarkResult with the results of the benchmark
        """
        raise NotImplementedError("Subclasses must implement run() method")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "benchmark_id": self.benchmark_id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "author": self.author,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "enabled": self.enabled,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Benchmark":
        """Create from dictionary."""
        return cls(
            name=data.get("name", ""),
            benchmark_id=data.get("benchmark_id", f"benchmark_{uuid.uuid4().hex[:8]}"),
            description=data.get("description", ""),
            category=data.get("category", "performance"),
            author=data.get("author", "system"),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            enabled=data.get("enabled", True),
            metadata=data.get("metadata", {}),
        )

    def __str__(self) -> str:
        return f"Benchmark(name='{self.name}', category='{self.category}')"


@dataclass
class BenchmarkSuite:
    """A collection of related benchmarks.

    A benchmark suite groups related benchmarks together and provides
    methods for running them as a unit.
    """
    name: str
    suite_id: str = field(default_factory=lambda: f"suite_{uuid.uuid4().hex[:8]}")
    description: str = ""
    benchmarks: List[Benchmark] = field(default_factory=list)
    author: str = "system"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_benchmark(self, benchmark: Benchmark) -> None:
        """Add a benchmark to the suite.

        Args:
            benchmark: The benchmark to add
        """
        self.benchmarks.append(benchmark)
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def remove_benchmark(self, benchmark_id: str) -> bool:
        """Remove a benchmark from the suite.

        Args:
            benchmark_id: The ID of the benchmark to remove

        Returns:
            True if the benchmark was found and removed, False otherwise
        """
        for i, benchmark in enumerate(self.benchmarks):
            if benchmark.benchmark_id == benchmark_id:
                self.benchmarks.pop(i)
                self.updated_at = datetime.now(timezone.utc).isoformat()
                return True
        return False

    def run_all(self, **kwargs) -> List[BenchmarkResult]:
        """Run all benchmarks in the suite.

        Args:
            **kwargs: Additional arguments for the benchmarks

        Returns:
            List of BenchmarkResult objects
        """
        results: List[BenchmarkResult] = []
        for benchmark in self.benchmarks:
            if benchmark.enabled:
                result = benchmark.run(**kwargs)
                results.append(result)
        return results

    @property
    def total_benchmarks(self) -> int:
        """Get the total number of benchmarks."""
        return len(self.benchmarks)

    @property
    def enabled_benchmarks(self) -> int:
        """Get the number of enabled benchmarks."""
        return len([b for b in self.benchmarks if b.enabled])

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the suite.

        Returns:
            Summary dictionary
        """
        categories: Dict[str, int] = {}
        for benchmark in self.benchmarks:
            category = benchmark.category
            categories[category] = categories.get(category, 0) + 1

        return {
            "name": self.name,
            "suite_id": self.suite_id,
            "total_benchmarks": self.total_benchmarks,
            "enabled_benchmarks": self.enabled_benchmarks,
            "categories": categories,
        }

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "suite_id": self.suite_id,
            "name": self.name,
            "description": self.description,
            "benchmarks": [b.to_dict() for b in self.benchmarks],
            "author": self.author,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
            "summary": self.get_summary(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BenchmarkSuite":
        """Create from dictionary."""
        suite = cls(
            name=data.get("name", ""),
            suite_id=data.get("suite_id", f"suite_{uuid.uuid4().hex[:8]}"),
            description=data.get("description", ""),
            author=data.get("author", "system"),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            metadata=data.get("metadata", {}),
        )
        suite.benchmarks = [
            Benchmark.from_dict(b) for b in data.get("benchmarks", [])
        ]
        return suite

    def __str__(self) -> str:
        return f"BenchmarkSuite(name='{self.name}', benchmarks={self.total_benchmarks})"


# Concrete Benchmark implementations

class TimingBenchmark(Benchmark):
    """A benchmark that measures execution time."""

    def __init__(
        self,
        name: str,
        func: Callable,
        description: str = "",
        warmup_runs: int = 1,
        iterations: int = 10,
        category: str = "performance",
    ):
        super().__init__(
            name=name,
            description=description or f"Timing benchmark for {name}",
            category=category,
        )
        self.func = func
        self.warmup_runs = warmup_runs
        self.iterations = iterations

    def run(self, **kwargs) -> BenchmarkResult:
        """Run the timing benchmark."""
        result = BenchmarkResult(
            benchmark_id=self.benchmark_id,
            name=self.name,
            description=self.description,
        )

        try:
            # Warmup runs
            for _ in range(self.warmup_runs):
                self.func(**kwargs)

            # Measure iterations
            times: List[float] = []
            for _ in range(self.iterations):
                start = time.perf_counter()
                self.func(**kwargs)
                end = time.perf_counter()
                times.append(end - start)

            # Calculate statistics
            result.add_metric(BenchmarkMetric.TIME, min(times))
            result.add_metric(BenchmarkMetric.LATENCY, min(times) * 1000)  # ms

            # Additional metrics
            result.metadata["all_times"] = times
            result.metadata["mean_time"] = statistics.mean(times) if times else 0
            result.metadata["median_time"] = statistics.median(times) if times else 0
            result.metadata["std_dev"] = statistics.stdev(times) if len(times) > 1 else 0
            result.metadata["iterations"] = self.iterations

            result.status = BenchmarkStatus.COMPLETED

        except Exception as e:
            result.status = BenchmarkStatus.FAILED
            result.error = str(e)

        result.set_end_time()
        return result

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = super().to_dict()
        data["type"] = "timing"
        data["warmup_runs"] = self.warmup_runs
        data["iterations"] = self.iterations
        return data


class AccuracyBenchmark(Benchmark):
    """A benchmark that measures accuracy."""

    def __init__(
        self,
        name: str,
        func: Callable[[Any], Tuple[bool, Any]],  # Returns (success, result)
        description: str = "",
        test_cases: List[Any] = None,
        category: str = "accuracy",
    ):
        super().__init__(
            name=name,
            description=description or f"Accuracy benchmark for {name}",
            category=category,
        )
        self.func = func
        self.test_cases = test_cases or []

    def run(self, test_cases: Optional[List[Any]] = None, **kwargs) -> BenchmarkResult:
        """Run the accuracy benchmark.

        Args:
            test_cases: Optional list of test cases to use instead of default

        Returns:
            BenchmarkResult with accuracy metrics
        """
        result = BenchmarkResult(
            benchmark_id=self.benchmark_id,
            name=self.name,
            description=self.description,
        )

        cases = test_cases or self.test_cases

        try:
            if not cases:
                result.status = BenchmarkStatus.FAILED
                result.error = "No test cases provided"
                return result

            correct = 0
            total = len(cases)
            start = time.perf_counter()

            for case in cases:
                try:
                    success, _ = self.func(case, **kwargs)
                    if success:
                        correct += 1
                except Exception:
                    pass  # Count as incorrect

            end = time.perf_counter()

            # Calculate metrics
            accuracy = correct / total if total > 0 else 0.0
            result.add_metric(BenchmarkMetric.ACCURACY, accuracy)
            result.add_metric(BenchmarkMetric.SUCCESS_RATE, accuracy)
            result.add_metric(BenchmarkMetric.ERROR_RATE, 1.0 - accuracy)
            result.add_metric(BenchmarkMetric.TIME, end - start)

            result.metadata["correct"] = correct
            result.metadata["total"] = total
            result.metadata["incorrect"] = total - correct

            result.status = BenchmarkStatus.COMPLETED

        except Exception as e:
            result.status = BenchmarkStatus.FAILED
            result.error = str(e)

        result.set_end_time()
        return result

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = super().to_dict()
        data["type"] = "accuracy"
        data["test_case_count"] = len(self.test_cases)
        return data


class MultiMetricBenchmark(Benchmark):
    """A benchmark that collects multiple custom metrics."""

    def __init__(
        self,
        name: str,
        func: Callable[[Any], Dict[BenchmarkMetric, float]],
        description: str = "",
        category: str = "custom",
    ):
        super().__init__(
            name=name,
            description=description or f"Multi-metric benchmark for {name}",
            category=category,
        )
        self.func = func

    def run(self, input_data: Any = None, **kwargs) -> BenchmarkResult:
        """Run the multi-metric benchmark.

        Args:
            input_data: Input data for the benchmark function

        Returns:
            BenchmarkResult with collected metrics
        """
        result = BenchmarkResult(
            benchmark_id=self.benchmark_id,
            name=self.name,
            description=self.description,
        )

        try:
            start = time.perf_counter()
            metrics = self.func(input_data, **kwargs)
            end = time.perf_counter()

            result.add_metric(BenchmarkMetric.TIME, end - start)

            for metric, value in metrics.items():
                result.add_metric(metric, value)

            result.metadata["custom_metrics"] = list(metrics.keys())
            result.status = BenchmarkStatus.COMPLETED

        except Exception as e:
            result.status = BenchmarkStatus.FAILED
            result.error = str(e)

        result.set_end_time()
        return result
