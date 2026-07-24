"""Benchmark runner for executing benchmarks.

This module provides functionality for running benchmarks, managing
benchmark execution, and collecting results.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Callable
import json
import time
from pathlib import Path

from app.benchmarking.benchmark import (
    Benchmark,
    BenchmarkResult,
    BenchmarkSuite,
    BenchmarkMetric,
    BenchmarkStatus,
)


@dataclass
class BenchmarkRunner:
    """Runs benchmarks and manages their execution."""

    workspace: Optional[str] = None
    max_workers: int = 4  # Maximum concurrent benchmarks
    timeout: float = 60.0  # Timeout in seconds for each benchmark
    warmup: bool = True  # Whether to run warmup iterations
    results: List[BenchmarkResult] = field(default_factory=list)

    def __post_init__(self):
        self._workspace = Path(self.workspace) if self.workspace else Path(".")
        self._results_file = self._workspace / ".benchmark_results.json"
        self._load_results()

    def _load_results(self) -> None:
        """Load previous results from disk."""
        if not self._results_file.exists():
            return
        try:
            with open(self._results_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.results = [BenchmarkResult.from_dict(r) for r in data.get("results", [])]
        except Exception as e:
            print(f"Error loading benchmark results: {e}")

    def _save_results(self) -> None:
        """Save results to disk."""
        self._workspace.mkdir(parents=True, exist_ok=True)
        data = {
            "results": [r.to_dict() for r in self.results],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            with open(self._results_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving benchmark results: {e}")

    def run_benchmark(self, benchmark: Benchmark, **kwargs) -> BenchmarkResult:
        """Run a single benchmark.

        Args:
            benchmark: The benchmark to run
            **kwargs: Additional arguments for the benchmark

        Returns:
            BenchmarkResult with the results
        """
        result = benchmark.run(**kwargs)
        self.results.append(result)
        self._save_results()
        return result

    def run_suite(self, suite: BenchmarkSuite, **kwargs) -> List[BenchmarkResult]:
        """Run all benchmarks in a suite.

        Args:
            suite: The benchmark suite to run
            **kwargs: Additional arguments for the benchmarks

        Returns:
            List of BenchmarkResult objects
        """
        results: List[BenchmarkResult] = []
        for benchmark in suite.benchmarks:
            if benchmark.enabled:
                result = self.run_benchmark(benchmark, **kwargs)
                results.append(result)
        return results

    def run_multiple(self, benchmarks: List[Benchmark], **kwargs) -> List[BenchmarkResult]:
        """Run multiple benchmarks.

        Args:
            benchmarks: List of benchmarks to run
            **kwargs: Additional arguments for the benchmarks

        Returns:
            List of BenchmarkResult objects
        """
        results: List[BenchmarkResult] = []
        for benchmark in benchmarks:
            if benchmark.enabled:
                result = self.run_benchmark(benchmark, **kwargs)
                results.append(result)
        return results

    def get_results(
        self,
        benchmark_id: Optional[str] = None,
        name: Optional[str] = None,
        status: Optional[BenchmarkStatus] = None,
        since: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[BenchmarkResult]:
        """Get benchmark results with optional filters.

        Args:
            benchmark_id: Filter by benchmark ID
            name: Filter by benchmark name
            status: Filter by status
            since: Filter by start time
            limit: Maximum number of results

        Returns:
            List of matching BenchmarkResult objects
        """
        results = list(self.results)

        if benchmark_id:
            results = [r for r in results if r.benchmark_id == benchmark_id]
        if name:
            results = [r for r in results if r.name == name]
        if status:
            results = [r for r in results if r.status == status]
        if since:
            results = [r for r in results if r.start_time >= since]

        # Sort by start time (newest first)
        results.sort(key=lambda r: r.start_time, reverse=True)

        if limit:
            results = results[:limit]

        return results

    def get_latest_results(self, limit: int = 10) -> List[BenchmarkResult]:
        """Get the most recent benchmark results.

        Args:
            limit: Maximum number of results

        Returns:
            List of recent BenchmarkResult objects
        """
        return self.get_results(limit=limit)

    def get_successful_results(self) -> List[BenchmarkResult]:
        """Get all successful benchmark results.

        Returns:
            List of successful BenchmarkResult objects
        """
        return self.get_results(status=BenchmarkStatus.COMPLETED)

    def get_failed_results(self) -> List[BenchmarkResult]:
        """Get all failed benchmark results.

        Returns:
            List of failed BenchmarkResult objects
        """
        return self.get_results(status=BenchmarkStatus.FAILED)

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of all benchmark results.

        Returns:
            Summary dictionary
        """
        total = len(self.results)
        successful = len(self.get_successful_results())
        failed = len(self.get_failed_results())

        # Count by benchmark
        by_benchmark: Dict[str, int] = {}
        for result in self.results:
            name = result.name
            by_benchmark[name] = by_benchmark.get(name, 0) + 1

        # Average duration
        durations = [r.duration for r in self.results if r.duration > 0]
        avg_duration = sum(durations) / len(durations) if durations else 0.0

        # Total time
        total_time = sum(r.duration for r in self.results)

        return {
            "total_runs": total,
            "successful": successful,
            "failed": failed,
            "success_rate": successful / total if total > 0 else 0.0,
            "by_benchmark": by_benchmark,
            "average_duration": avg_duration,
            "total_time": total_time,
        }

    def compare_results(self, benchmark_name: str, limit: int = 5) -> Dict[str, Any]:
        """Compare results for a specific benchmark over time.

        Args:
            benchmark_name: Name of the benchmark to compare
            limit: Number of recent results to compare

        Returns:
            Comparison dictionary with statistics
        """
        results = self.get_results(name=benchmark_name, limit=limit)

        if not results:
            return {"error": "No results found for benchmark"}

        # Sort by date (oldest first)
        results.sort(key=lambda r: r.start_time)

        # Collect metrics
        metrics: Dict[str, List[float]] = {}
        for result in results:
            for metric, value in result.metrics.items():
                metric_name = metric.value
                if metric_name not in metrics:
                    metrics[metric_name] = []
                metrics[metric_name].append(value)

        # Calculate trends
        comparison = {
            "benchmark": benchmark_name,
            "result_count": len(results),
            "dates": [r.start_time for r in results],
            "metrics": {},
        }

        for metric_name, values in metrics.items():
            if len(values) < 2:
                comparison["metrics"][metric_name] = {
                    "values": values,
                    "trend": "insufficient_data",
                }
            else:
                # Calculate trend (positive = improving, negative = worsening)
                if metric_name in ["time", "latency"]:
                    # Lower is better
                    trend = "improving" if values[-1] < values[0] else "worsening"
                else:
                    # Higher is better
                    trend = "improving" if values[-1] > values[0] else "worsening"

                comparison["metrics"][metric_name] = {
                    "values": values,
                    "trend": trend,
                    "first": values[0],
                    "last": values[-1],
                    "min": min(values),
                    "max": max(values),
                    "mean": sum(values) / len(values) if values else 0,
                }

        return comparison

    def clear_results(self) -> None:
        """Clear all benchmark results."""
        self.results = []
        try:
            self._results_file.unlink()
        except FileNotFoundError:
            pass

    def export_results(self) -> Dict[str, Any]:
        """Export all results to a dictionary."""
        return {
            "results": [r.to_dict() for r in self.results],
            "summary": self.get_summary(),
        }

    def import_results(self, data: Dict[str, Any]) -> None:
        """Import results from a dictionary."""
        self.results = [BenchmarkResult.from_dict(r) for r in data.get("results", [])]
        self._save_results()

    def get_report(self) -> str:
        """Generate a human-readable report of benchmark results.

        Returns:
            Formatted report string
        """
        summary = self.get_summary()
        lines = [
            "=" * 70,
            "BENCHMARK REPORT",
            "=" * 70,
            "",
            f"Total Runs: {summary['total_runs']}",
            f"Successful: {summary['successful']}",
            f"Failed: {summary['failed']}",
            f"Success Rate: {summary['success_rate'] * 100:.1f}%",
            f"Average Duration: {summary['average_duration']:.3f}s",
            f"Total Time: {summary['total_time']:.2f}s",
            "",
            "-" * 70,
            "RECENT RESULTS",
            "-" * 70,
        ]

        recent = self.get_latest_results(limit=10)
        for result in recent:
            status = result.status.value.upper()
            duration = f"{result.duration:.3f}s" if result.duration else "N/A"
            lines.append(f"  [{status}] {result.name} - {duration}")

        lines.append("")
        lines.append("=" * 70)

        return "\n".join(lines)
