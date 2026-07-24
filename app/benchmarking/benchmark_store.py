"""Benchmark store for managing benchmark definitions.

This module provides a registry for storing and retrieving benchmark
definitions, including built-in benchmarks and custom benchmarks.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Callable, Tuple
import json
from pathlib import Path
import uuid

from app.benchmarking.benchmark import (
    Benchmark,
    BenchmarkSuite,
    BenchmarkResult,
    TimingBenchmark,
    AccuracyBenchmark,
    MultiMetricBenchmark,
)


@dataclass
class BenchmarkStore:
    """Stores and manages benchmark definitions."""

    workspace: Optional[str] = None
    benchmarks: Dict[str, Benchmark] = field(default_factory=dict)
    suites: Dict[str, BenchmarkSuite] = field(default_factory=dict)

    def __post_init__(self):
        self._workspace = Path(self.workspace) if self.workspace else Path(".")
        self._benchmarks_file = self._workspace / ".benchmarks.json"
        self._initialize_builtins()
        self._load_benchmarks()

    def _initialize_builtins(self) -> None:
        """Initialize built-in benchmarks."""
        # These would be populated with actual benchmark implementations
        # For now, we'll add placeholder benchmarks
        pass

    def _load_benchmarks(self) -> None:
        """Load benchmarks from disk."""
        if not self._benchmarks_file.exists():
            return
        try:
            with open(self._benchmarks_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                for bm_data in data.get("benchmarks", []):
                    try:
                        benchmark = Benchmark.from_dict(bm_data)
                        self.benchmarks[benchmark.benchmark_id] = benchmark
                    except Exception as e:
                        print(f"Error loading benchmark {bm_data.get('name')}: {e}")
                for suite_data in data.get("suites", []):
                    try:
                        suite = BenchmarkSuite.from_dict(suite_data)
                        self.suites[suite.suite_id] = suite
                    except Exception as e:
                        print(f"Error loading suite {suite_data.get('name')}: {e}")
        except Exception as e:
            print(f"Error loading benchmarks: {e}")

    def _save_benchmarks(self) -> None:
        """Save benchmarks to disk."""
        self._workspace.mkdir(parents=True, exist_ok=True)
        data = {
            "benchmarks": [b.to_dict() for b in self.benchmarks.values()],
            "suites": [s.to_dict() for s in self.suites.values()],
            "updated_at": str(self._workspace / ".benchmarks.json"),
        }
        try:
            with open(self._benchmarks_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving benchmarks: {e}")

    def add_benchmark(self, benchmark: Benchmark) -> None:
        """Add a benchmark to the store.

        Args:
            benchmark: The benchmark to add
        """
        self.benchmarks[benchmark.benchmark_id] = benchmark
        self._save_benchmarks()

    def remove_benchmark(self, benchmark_id: str) -> bool:
        """Remove a benchmark from the store.

        Args:
            benchmark_id: The ID of the benchmark to remove

        Returns:
            True if the benchmark was found and removed, False otherwise
        """
        if benchmark_id in self.benchmarks:
            del self.benchmarks[benchmark_id]
            self._save_benchmarks()
            return True
        return False

    def get_benchmark(self, benchmark_id: str) -> Optional[Benchmark]:
        """Get a benchmark by ID.

        Args:
            benchmark_id: The ID of the benchmark

        Returns:
            The Benchmark if found, None otherwise
        """
        return self.benchmarks.get(benchmark_id)

    def get_benchmark_by_name(self, name: str) -> Optional[Benchmark]:
        """Get a benchmark by name.

        Args:
            name: The name of the benchmark

        Returns:
            The Benchmark if found, None otherwise
        """
        for benchmark in self.benchmarks.values():
            if benchmark.name == name:
                return benchmark
        return None

    def list_benchmarks(
        self,
        category: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> List[Benchmark]:
        """List benchmarks with optional filters.

        Args:
            category: Filter by category
            enabled: Filter by enabled status

        Returns:
            List of Benchmark objects
        """
        benchmarks = list(self.benchmarks.values())

        if category:
            benchmarks = [b for b in benchmarks if b.category == category]
        if enabled is not None:
            benchmarks = [b for b in benchmarks if b.enabled == enabled]

        return benchmarks

    def add_suite(self, suite: BenchmarkSuite) -> None:
        """Add a benchmark suite to the store.

        Args:
            suite: The suite to add
        """
        self.suites[suite.suite_id] = suite
        self._save_benchmarks()

    def remove_suite(self, suite_id: str) -> bool:
        """Remove a benchmark suite from the store.

        Args:
            suite_id: The ID of the suite to remove

        Returns:
            True if the suite was found and removed, False otherwise
        """
        if suite_id in self.suites:
            del self.suites[suite_id]
            self._save_benchmarks()
            return True
        return False

    def get_suite(self, suite_id: str) -> Optional[BenchmarkSuite]:
        """Get a suite by ID.

        Args:
            suite_id: The ID of the suite

        Returns:
            The BenchmarkSuite if found, None otherwise
        """
        return self.suites.get(suite_id)

    def list_suites(self) -> List[BenchmarkSuite]:
        """List all benchmark suites.

        Returns:
            List of BenchmarkSuite objects
        """
        return list(self.suites.values())

    def create_timing_benchmark(
        self,
        name: str,
        func: Callable,
        description: str = "",
        category: str = "performance",
        warmup_runs: int = 1,
        iterations: int = 10,
        enabled: bool = True,
    ) -> TimingBenchmark:
        """Create and add a timing benchmark.

        Args:
            name: Name of the benchmark
            func: Function to benchmark
            description: Description of the benchmark
            category: Category of the benchmark
            warmup_runs: Number of warmup runs
            iterations: Number of measurement iterations
            enabled: Whether the benchmark is enabled

        Returns:
            The created TimingBenchmark
        """
        benchmark = TimingBenchmark(
            name=name,
            func=func,
            description=description,
            category=category,
            warmup_runs=warmup_runs,
            iterations=iterations,
        )
        benchmark.enabled = enabled
        self.add_benchmark(benchmark)
        return benchmark

    def create_accuracy_benchmark(
        self,
        name: str,
        func: Callable[[Any], Tuple[bool, Any]],
        description: str = "",
        category: str = "accuracy",
        test_cases: Optional[List[Any]] = None,
        enabled: bool = True,
    ) -> AccuracyBenchmark:
        """Create and add an accuracy benchmark.

        Args:
            name: Name of the benchmark
            func: Function that returns (success, result) for a test case
            description: Description of the benchmark
            category: Category of the benchmark
            test_cases: List of test cases
            enabled: Whether the benchmark is enabled

        Returns:
            The created AccuracyBenchmark
        """
        benchmark = AccuracyBenchmark(
            name=name,
            func=func,
            description=description,
            category=category,
            test_cases=test_cases or [],
        )
        benchmark.enabled = enabled
        self.add_benchmark(benchmark)
        return benchmark

    def create_multimetric_benchmark(
        self,
        name: str,
        func: Callable[[Any], Dict[str, float]],
        description: str = "",
        category: str = "custom",
        enabled: bool = True,
    ) -> MultiMetricBenchmark:
        """Create and add a multi-metric benchmark.

        Args:
            name: Name of the benchmark
            func: Function that returns a dictionary of metric names to values
            description: Description of the benchmark
            category: Category of the benchmark
            enabled: Whether the benchmark is enabled

        Returns:
            The created MultiMetricBenchmark
        """
        benchmark = MultiMetricBenchmark(
            name=name,
            func=func,
            description=description,
            category=category,
        )
        benchmark.enabled = enabled
        self.add_benchmark(benchmark)
        return benchmark

    @property
    def count(self) -> int:
        """Get the total number of benchmarks."""
        return len(self.benchmarks)

    @property
    def suite_count(self) -> int:
        """Get the total number of suites."""
        return len(self.suites)

    def clear(self) -> None:
        """Clear all benchmarks and suites."""
        self.benchmarks = {}
        self.suites = {}
        try:
            self._benchmarks_file.unlink()
        except FileNotFoundError:
            pass

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the benchmark store.

        Returns:
            Summary dictionary
        """
        categories: Dict[str, int] = {}
        for benchmark in self.benchmarks.values():
            category = benchmark.category
            categories[category] = categories.get(category, 0) + 1

        enabled = len([b for b in self.benchmarks.values() if b.enabled])

        return {
            "total_benchmarks": self.count,
            "enabled_benchmarks": enabled,
            "total_suites": self.suite_count,
            "categories": categories,
        }

    def export_to_dict(self) -> Dict[str, Any]:
        """Export all data to a dictionary."""
        return {
            "benchmarks": [b.to_dict() for b in self.benchmarks.values()],
            "suites": [s.to_dict() for s in self.suites.values()],
            "summary": self.get_summary(),
        }

    def import_from_dict(self, data: Dict[str, Any]) -> None:
        """Import data from a dictionary."""
        self.benchmarks = {}
        self.suites = {}

        for bm_data in data.get("benchmarks", []):
            try:
                benchmark = Benchmark.from_dict(bm_data)
                self.benchmarks[benchmark.benchmark_id] = benchmark
            except Exception as e:
                print(f"Error importing benchmark: {e}")

        for suite_data in data.get("suites", []):
            try:
                suite = BenchmarkSuite.from_dict(suite_data)
                self.suites[suite.suite_id] = suite
            except Exception as e:
                print(f"Error importing suite: {e}")

        self._save_benchmarks()
