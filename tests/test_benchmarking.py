"""Tests for the Benchmarking Framework.

This module provides comprehensive tests for all benchmarking components
including Benchmark, BenchmarkResult, BenchmarkSuite, BenchmarkRunner,
and BenchmarkStore.
"""

import json
import os
import tempfile
import time
import pytest
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable, Tuple
import uuid

from app.benchmarking.benchmark import (
    Benchmark,
    BenchmarkResult,
    BenchmarkSuite,
    BenchmarkMetric,
    BenchmarkStatus,
    TimingBenchmark,
    AccuracyBenchmark,
    MultiMetricBenchmark,
)
from app.benchmarking.benchmark_runner import BenchmarkRunner
from app.benchmarking.benchmark_store import BenchmarkStore


class TestBenchmarkMetric:
    """Tests for BenchmarkMetric enum."""

    def test_metric_enum_values(self):
        """Test that all metric enum values are strings."""
        for metric in BenchmarkMetric:
            assert isinstance(metric.value, str)

    def test_metric_enum_unique(self):
        """Test that all metric enum values are unique."""
        values = [metric.value for metric in BenchmarkMetric]
        assert len(values) == len(set(values))


class TestBenchmarkStatus:
    """Tests for BenchmarkStatus enum."""

    def test_status_enum_values(self):
        """Test that all status enum values are strings."""
        for status in BenchmarkStatus:
            assert isinstance(status.value, str)

    def test_status_enum_unique(self):
        """Test that all status enum values are unique."""
        values = [status.value for status in BenchmarkStatus]
        assert len(values) == len(set(values))


class TestBenchmarkResult:
    """Tests for BenchmarkResult class."""

    def test_create_basic_result(self):
        """Test creating a basic benchmark result."""
        result = BenchmarkResult(
            benchmark_id="test_benchmark",
            name="Test Benchmark",
            description="A test benchmark",
        )
        assert result.benchmark_id == "test_benchmark"
        assert result.name == "Test Benchmark"
        assert result.description == "A test benchmark"
        assert result.result_id.startswith("result_")
        assert result.status == BenchmarkStatus.PENDING
        assert result.duration == 0.0
        assert result.metrics == {}
        assert result.error is None
        assert result.metadata == {}

    def test_result_success_property(self):
        """Test the success property."""
        result = BenchmarkResult(
            benchmark_id="test",
            status=BenchmarkStatus.COMPLETED,
        )
        assert result.success is True
        assert result.failed is False

        result.status = BenchmarkStatus.FAILED
        assert result.success is False
        assert result.failed is True

    def test_result_string_representation(self):
        """Test the string representation of a result."""
        result = BenchmarkResult(
            benchmark_id="test",
            name="Test",
            status=BenchmarkStatus.COMPLETED,
            duration=1.5,
        )
        str_repr = str(result)
        assert "Test" in str_repr
        assert "completed" in str_repr
        assert "1.50s" in str_repr

    def test_add_metric(self):
        """Test adding metrics to a result."""
        result = BenchmarkResult(benchmark_id="test")
        result.add_metric(BenchmarkMetric.TIME, 1.5)
        result.add_metric(BenchmarkMetric.ACCURACY, 0.95)

        assert result.get_metric(BenchmarkMetric.TIME) == 1.5
        assert result.get_metric(BenchmarkMetric.ACCURACY) == 0.95
        assert result.get_metric(BenchmarkMetric.PRECISION) is None

    def test_set_end_time(self):
        """Test setting end time and calculating duration."""
        result = BenchmarkResult(
            benchmark_id="test",
            start_time=datetime.now(timezone.utc).isoformat(),
        )
        # Add a small delay
        time.sleep(0.1)
        result.set_end_time()

        assert result.end_time != ""
        assert result.duration > 0
        assert result.duration >= 0.1

    def test_to_dict(self):
        """Test converting result to dictionary."""
        result = BenchmarkResult(
            benchmark_id="test",
            result_id="result_123",
            name="Test",
            description="Desc",
            status=BenchmarkStatus.COMPLETED,
            duration=1.5,
        )
        result.add_metric(BenchmarkMetric.TIME, 1.5)

        data = result.to_dict()

        assert data["benchmark_id"] == "test"
        assert data["result_id"] == "result_123"
        assert data["name"] == "Test"
        assert data["description"] == "Desc"
        assert data["status"] == "completed"
        assert data["duration"] == 1.5
        assert data["metrics"]["time"] == 1.5
        assert data["success"] is True
        assert data["failed"] is False

    def test_from_dict(self):
        """Test creating result from dictionary."""
        data = {
            "benchmark_id": "test",
            "result_id": "result_456",
            "name": "Test From Dict",
            "status": "failed",
            "duration": 2.5,
            "metrics": {"time": 2.5, "accuracy": 0.8},
            "error": "Test error",
        }

        result = BenchmarkResult.from_dict(data)

        assert result.benchmark_id == "test"
        assert result.result_id == "result_456"
        assert result.name == "Test From Dict"
        assert result.status == BenchmarkStatus.FAILED
        assert result.duration == 2.5
        assert result.error == "Test error"
        assert len(result.metrics) == 2

    def test_from_dict_with_string_status(self):
        """Test creating result from dictionary with string status."""
        data = {
            "benchmark_id": "test",
            "status": "completed",
        }

        result = BenchmarkResult.from_dict(data)
        assert result.status == BenchmarkStatus.COMPLETED


class TestBenchmark:
    """Tests for Benchmark base class."""

    def test_create_benchmark(self):
        """Test creating a basic benchmark."""
        benchmark = Benchmark(
            name="Test Benchmark",
            description="A test benchmark",
            category="performance",
        )

        assert benchmark.name == "Test Benchmark"
        assert benchmark.description == "A test benchmark"
        assert benchmark.category == "performance"
        assert benchmark.benchmark_id.startswith("benchmark_")
        assert benchmark.enabled is True
        assert benchmark.author == "system"

    def test_benchmark_requires_name(self):
        """Test that benchmark requires a name."""
        with pytest.raises(ValueError):
            Benchmark(name="")

    def test_benchmark_string_representation(self):
        """Test the string representation of a benchmark."""
        benchmark = Benchmark(
            name="Test",
            category="performance",
        )
        str_repr = str(benchmark)
        assert "Test" in str_repr
        assert "performance" in str_repr

    def test_benchmark_to_dict(self):
        """Test converting benchmark to dictionary."""
        benchmark = Benchmark(
            name="Test",
            description="Desc",
            category="accuracy",
            enabled=False,
        )

        data = benchmark.to_dict()

        assert data["name"] == "Test"
        assert data["description"] == "Desc"
        assert data["category"] == "accuracy"
        assert data["enabled"] is False

    def test_benchmark_from_dict(self):
        """Test creating benchmark from dictionary."""
        data = {
            "benchmark_id": "bench_123",
            "name": "Test From Dict",
            "description": "Desc",
            "category": "custom",
            "enabled": False,
        }

        benchmark = Benchmark.from_dict(data)

        assert benchmark.benchmark_id == "bench_123"
        assert benchmark.name == "Test From Dict"
        assert benchmark.category == "custom"
        assert benchmark.enabled is False


class TestBenchmarkSuite:
    """Tests for BenchmarkSuite class."""

    def test_create_empty_suite(self):
        """Test creating an empty benchmark suite."""
        suite = BenchmarkSuite(
            name="Test Suite",
            description="A test suite",
        )

        assert suite.name == "Test Suite"
        assert suite.description == "A test suite"
        assert suite.suite_id.startswith("suite_")
        assert suite.benchmarks == []

    def test_add_benchmark_to_suite(self):
        """Test adding benchmarks to a suite."""
        suite = BenchmarkSuite(name="Test Suite")
        benchmark1 = Benchmark(name="Bench 1")
        benchmark2 = Benchmark(name="Bench 2")

        suite.add_benchmark(benchmark1)
        suite.add_benchmark(benchmark2)

        assert suite.total_benchmarks == 2
        assert suite.benchmarks[0].name == "Bench 1"
        assert suite.benchmarks[1].name == "Bench 2"

    def test_remove_benchmark_from_suite(self):
        """Test removing a benchmark from a suite."""
        suite = BenchmarkSuite(name="Test Suite")
        benchmark = Benchmark(name="Bench 1")

        suite.add_benchmark(benchmark)
        assert suite.total_benchmarks == 1

        removed = suite.remove_benchmark(benchmark.benchmark_id)
        assert removed is True
        assert suite.total_benchmarks == 0

        # Try removing non-existent benchmark
        removed = suite.remove_benchmark("non_existent")
        assert removed is False

    def test_enabled_benchmarks_count(self):
        """Test counting enabled benchmarks."""
        suite = BenchmarkSuite(name="Test Suite")

        bench1 = Benchmark(name="Bench 1", enabled=True)
        bench2 = Benchmark(name="Bench 2", enabled=False)
        bench3 = Benchmark(name="Bench 3", enabled=True)

        suite.add_benchmark(bench1)
        suite.add_benchmark(bench2)
        suite.add_benchmark(bench3)

        assert suite.total_benchmarks == 3
        assert suite.enabled_benchmarks == 2

    def test_suite_summary(self):
        """Test getting suite summary."""
        suite = BenchmarkSuite(name="Performance Suite")

        bench1 = Benchmark(name="Bench 1", category="performance", enabled=True)
        bench2 = Benchmark(name="Bench 2", category="accuracy", enabled=True)
        bench3 = Benchmark(name="Bench 3", category="performance", enabled=False)

        suite.add_benchmark(bench1)
        suite.add_benchmark(bench2)
        suite.add_benchmark(bench3)

        summary = suite.get_summary()

        assert summary["name"] == "Performance Suite"
        assert summary["total_benchmarks"] == 3
        assert summary["enabled_benchmarks"] == 2
        assert summary["categories"]["performance"] == 2
        assert summary["categories"]["accuracy"] == 1

    def test_suite_to_dict(self):
        """Test converting suite to dictionary."""
        suite = BenchmarkSuite(
            name="Test Suite",
            description="Desc",
        )
        suite.add_benchmark(Benchmark(name="Bench 1"))

        data = suite.to_dict()

        assert data["name"] == "Test Suite"
        assert data["description"] == "Desc"
        assert len(data["benchmarks"]) == 1
        assert data["benchmarks"][0]["name"] == "Bench 1"

    def test_suite_from_dict(self):
        """Test creating suite from dictionary."""
        data = {
            "suite_id": "suite_123",
            "name": "Test Suite",
            "benchmarks": [
                {"name": "Bench 1", "benchmark_id": "bench_1"},
                {"name": "Bench 2", "benchmark_id": "bench_2"},
            ],
        }

        suite = BenchmarkSuite.from_dict(data)

        assert suite.suite_id == "suite_123"
        assert suite.name == "Test Suite"
        assert suite.total_benchmarks == 2


class TestTimingBenchmark:
    """Tests for TimingBenchmark class."""

    def test_create_timing_benchmark(self):
        """Test creating a timing benchmark."""
        def sample_func():
            time.sleep(0.01)

        benchmark = TimingBenchmark(
            name="Timing Test",
            func=sample_func,
            warmup_runs=2,
            iterations=5,
        )

        assert benchmark.name == "Timing Test"
        assert benchmark.warmup_runs == 2
        assert benchmark.iterations == 5

    def test_timing_benchmark_run(self):
        """Test running a timing benchmark."""
        def sample_func():
            time.sleep(0.01)

        benchmark = TimingBenchmark(
            name="Timing Test",
            func=sample_func,
            warmup_runs=1,
            iterations=3,
        )

        result = benchmark.run()

        assert result.benchmark_id == benchmark.benchmark_id
        assert result.name == "Timing Test"
        assert result.status == BenchmarkStatus.COMPLETED
        assert result.duration > 0
        assert BenchmarkMetric.TIME in result.metrics
        assert BenchmarkMetric.LATENCY in result.metrics
        assert result.metadata["iterations"] == 3
        assert "all_times" in result.metadata
        assert "mean_time" in result.metadata

    def test_timing_benchmark_failure(self):
        """Test timing benchmark with failing function."""
        def failing_func():
            raise ValueError("Test error")

        benchmark = TimingBenchmark(
            name="Failing Test",
            func=failing_func,
            warmup_runs=1,
            iterations=2,
        )

        result = benchmark.run()

        assert result.status == BenchmarkStatus.FAILED
        assert result.error is not None
        assert "Test error" in result.error

    def test_timing_benchmark_to_dict(self):
        """Test converting timing benchmark to dictionary."""
        benchmark = TimingBenchmark(
            name="Test",
            func=lambda: None,
            warmup_runs=2,
            iterations=10,
        )

        data = benchmark.to_dict()

        assert data["type"] == "timing"
        assert data["warmup_runs"] == 2
        assert data["iterations"] == 10


class TestAccuracyBenchmark:
    """Tests for AccuracyBenchmark class."""

    def test_create_accuracy_benchmark(self):
        """Test creating an accuracy benchmark."""
        def sample_func(test_case):
            return (test_case > 5, test_case)

        benchmark = AccuracyBenchmark(
            name="Accuracy Test",
            func=sample_func,
            test_cases=[6, 7, 8, 4, 3],
        )

        assert benchmark.name == "Accuracy Test"
        assert len(benchmark.test_cases) == 5

    def test_accuracy_benchmark_run(self):
        """Test running an accuracy benchmark."""
        def sample_func(test_case):
            return (test_case > 5, test_case)

        benchmark = AccuracyBenchmark(
            name="Accuracy Test",
            func=sample_func,
            test_cases=[6, 7, 8, 4, 3],
        )

        result = benchmark.run()

        assert result.status == BenchmarkStatus.COMPLETED
        assert result.metadata["total"] == 5
        assert result.metadata["correct"] == 3  # 6, 7, 8 > 5
        assert result.metadata["incorrect"] == 2
        assert result.get_metric(BenchmarkMetric.ACCURACY) == 0.6
        assert result.get_metric(BenchmarkMetric.SUCCESS_RATE) == 0.6
        assert result.get_metric(BenchmarkMetric.ERROR_RATE) == 0.4

    def test_accuracy_benchmark_no_test_cases(self):
        """Test accuracy benchmark with no test cases."""
        def sample_func(test_case):
            return (True, test_case)

        benchmark = AccuracyBenchmark(
            name="No Cases Test",
            func=sample_func,
            test_cases=[],
        )

        result = benchmark.run()

        assert result.status == BenchmarkStatus.FAILED
        assert "No test cases" in result.error

    def test_accuracy_benchmark_custom_test_cases(self):
        """Test accuracy benchmark with custom test cases."""
        def sample_func(test_case):
            return (test_case % 2 == 0, test_case)

        benchmark = AccuracyBenchmark(
            name="Even Test",
            func=sample_func,
            test_cases=[2, 4, 6],
        )

        result = benchmark.run(test_cases=[2, 3, 4])

        assert result.metadata["total"] == 3
        assert result.metadata["correct"] == 2  # 2, 4 are even

    def test_accuracy_benchmark_to_dict(self):
        """Test converting accuracy benchmark to dictionary."""
        benchmark = AccuracyBenchmark(
            name="Test",
            func=lambda x: (True, x),
            test_cases=[1, 2, 3],
        )

        data = benchmark.to_dict()

        assert data["type"] == "accuracy"
        assert data["test_case_count"] == 3


class TestMultiMetricBenchmark:
    """Tests for MultiMetricBenchmark class."""

    def test_create_multimetric_benchmark(self):
        """Test creating a multi-metric benchmark."""
        def sample_func(input_data):
            return {
                BenchmarkMetric.ACCURACY: 0.95,
                BenchmarkMetric.PRECISION: 0.9,
            }

        benchmark = MultiMetricBenchmark(
            name="Multi Test",
            func=sample_func,
        )

        assert benchmark.name == "Multi Test"

    def test_multimetric_benchmark_run(self):
        """Test running a multi-metric benchmark."""
        def sample_func(input_data):
            return {
                BenchmarkMetric.ACCURACY: 0.95,
                BenchmarkMetric.PRECISION: 0.9,
            }

        benchmark = MultiMetricBenchmark(
            name="Multi Test",
            func=sample_func,
        )

        result = benchmark.run(input_data={"test": "data"})

        assert result.status == BenchmarkStatus.COMPLETED
        assert result.get_metric(BenchmarkMetric.ACCURACY) == 0.95
        assert result.get_metric(BenchmarkMetric.PRECISION) == 0.9
        assert result.get_metric(BenchmarkMetric.TIME) > 0

    def test_multimetric_benchmark_failure(self):
        """Test multi-metric benchmark with failing function."""
        def failing_func(input_data):
            raise RuntimeError("Multi error")

        benchmark = MultiMetricBenchmark(
            name="Failing Multi",
            func=failing_func,
        )

        result = benchmark.run()

        assert result.status == BenchmarkStatus.FAILED
        assert "Multi error" in result.error


class TestBenchmarkRunner:
    """Tests for BenchmarkRunner class."""

    def test_create_runner(self):
        """Test creating a benchmark runner."""
        runner = BenchmarkRunner(
            max_workers=4,
            timeout=30.0,
            warmup=True,
        )

        assert runner.max_workers == 4
        assert runner.timeout == 30.0
        assert runner.warmup is True
        assert runner.results == []

    def test_run_single_benchmark(self):
        """Test running a single benchmark."""
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(workspace=tmpdir)

            benchmark = TimingBenchmark(
                name="Test Bench",
                func=lambda: time.sleep(0.01),
                iterations=2,
            )

            result = runner.run_benchmark(benchmark)

            assert len(runner.results) == 1
            assert result.benchmark_id == benchmark.benchmark_id
            assert result.status == BenchmarkStatus.COMPLETED

    def test_run_multiple_benchmarks(self):
        """Test running multiple benchmarks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(workspace=tmpdir)

            bench1 = TimingBenchmark(name="Bench 1", func=lambda: None)
            bench2 = TimingBenchmark(name="Bench 2", func=lambda: None)

            results = runner.run_multiple([bench1, bench2])

            assert len(results) == 2
            assert len(runner.results) == 2

    def test_run_suite(self):
        """Test running a benchmark suite."""
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(workspace=tmpdir)

            suite = BenchmarkSuite(name="Test Suite")
            bench1 = TimingBenchmark(name="Bench 1", func=lambda: None)
            bench2 = TimingBenchmark(name="Bench 2", func=lambda: None)
            bench2.enabled = False
            suite.add_benchmark(bench1)
            suite.add_benchmark(bench2)

            results = runner.run_suite(suite)

            # Only enabled benchmarks should run
            assert len(results) == 1
            assert results[0].name == "Bench 1"

    def test_get_results_filters(self):
        """Test filtering benchmark results."""
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(workspace=tmpdir)

            bench1 = TimingBenchmark(name="Bench 1", func=lambda: None)
            bench2 = TimingBenchmark(name="Bench 2", func=lambda: None)

            runner.run_benchmark(bench1)
            runner.run_benchmark(bench2)

            # Filter by name
            results = runner.get_results(name="Bench 1")
            assert len(results) == 1
            assert results[0].name == "Bench 1"

            # Filter by status
            results = runner.get_results(status=BenchmarkStatus.COMPLETED)
            assert len(results) == 2

    def test_get_latest_results(self):
        """Test getting latest results."""
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(workspace=tmpdir)

            for i in range(5):
                bench = TimingBenchmark(name=f"Bench {i}", func=lambda: None)
                runner.run_benchmark(bench)
                time.sleep(0.01)  # Small delay to ensure different timestamps

            latest = runner.get_latest_results(limit=3)
            assert len(latest) == 3

    def test_get_successful_results(self):
        """Test getting successful results."""
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(workspace=tmpdir)

            bench1 = TimingBenchmark(name="Success", func=lambda: None)
            bench2 = TimingBenchmark(name="Fail", func=lambda: (_ for _ in ()).throw(ValueError()))

            runner.run_benchmark(bench1)
            runner.run_benchmark(bench2)

            successful = runner.get_successful_results()
            assert len(successful) == 1
            assert successful[0].name == "Success"

    def test_get_failed_results(self):
        """Test getting failed results."""
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(workspace=tmpdir)

            bench1 = TimingBenchmark(name="Success", func=lambda: None)
            bench2 = TimingBenchmark(name="Fail", func=lambda: (_ for _ in ()).throw(ValueError()))

            runner.run_benchmark(bench1)
            runner.run_benchmark(bench2)

            failed = runner.get_failed_results()
            assert len(failed) == 1
            assert failed[0].name == "Fail"

    def test_get_summary(self):
        """Test getting runner summary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(workspace=tmpdir)

            bench1 = TimingBenchmark(name="Bench 1", func=lambda: None)
            bench2 = TimingBenchmark(name="Bench 1", func=lambda: None)
            bench3 = TimingBenchmark(name="Bench 2", func=lambda: (_ for _ in ()).throw(ValueError()))

            runner.run_benchmark(bench1)
            runner.run_benchmark(bench2)
            runner.run_benchmark(bench3)

            summary = runner.get_summary()

            assert summary["total_runs"] == 3
            assert summary["successful"] == 2
            assert summary["failed"] == 1
            assert summary["success_rate"] == pytest.approx(2.0 / 3.0)
            assert summary["by_benchmark"]["Bench 1"] == 2
            assert summary["by_benchmark"]["Bench 2"] == 1

    def test_compare_results(self):
        """Test comparing results for a benchmark."""
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(workspace=tmpdir)

            bench = TimingBenchmark(name="Compare Test", func=lambda: time.sleep(0.01), iterations=2)

            # Run multiple times
            for _ in range(3):
                runner.run_benchmark(bench)
                time.sleep(0.01)

            comparison = runner.compare_results("Compare Test", limit=3)

            assert comparison["benchmark"] == "Compare Test"
            assert comparison["result_count"] == 3
            assert len(comparison["dates"]) == 3

    def test_clear_results(self):
        """Test clearing all results."""
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(workspace=tmpdir)

            bench = TimingBenchmark(name="Test", func=lambda: None)
            runner.run_benchmark(bench)

            assert len(runner.results) == 1

            runner.clear_results()

            assert len(runner.results) == 0

    def test_export_import_results(self):
        """Test exporting and importing results."""
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(workspace=tmpdir)

            bench = TimingBenchmark(name="Test", func=lambda: None)
            runner.run_benchmark(bench)

            # Export
            data = runner.export_results()
            assert "results" in data
            assert "summary" in data

            # Clear and import
            runner.clear_results()
            assert len(runner.results) == 0

            runner.import_results(data)
            assert len(runner.results) == 1

    def test_get_report(self):
        """Test generating a report."""
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(workspace=tmpdir)

            bench = TimingBenchmark(name="Test", func=lambda: None)
            runner.run_benchmark(bench)

            report = runner.get_report()

            assert "BENCHMARK REPORT" in report
            assert "Total Runs:" in report
            assert "Successful:" in report


class TestBenchmarkStore:
    """Tests for BenchmarkStore class."""

    def test_create_store(self):
        """Test creating a benchmark store."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = BenchmarkStore(workspace=tmpdir)

            assert store.workspace == tmpdir
            assert store.benchmarks == {}
            assert store.suites == {}

    def test_add_get_benchmark(self):
        """Test adding and getting a benchmark."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = BenchmarkStore(workspace=tmpdir)

            bench = Benchmark(name="Test Bench")
            store.add_benchmark(bench)

            assert store.count == 1

            retrieved = store.get_benchmark(bench.benchmark_id)
            assert retrieved.name == "Test Bench"

    def test_get_benchmark_by_name(self):
        """Test getting a benchmark by name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = BenchmarkStore(workspace=tmpdir)

            bench = Benchmark(name="Named Bench")
            store.add_benchmark(bench)

            retrieved = store.get_benchmark_by_name("Named Bench")
            assert retrieved is not None
            assert retrieved.name == "Named Bench"

            # Non-existent name
            retrieved = store.get_benchmark_by_name("Non Existent")
            assert retrieved is None

    def test_remove_benchmark(self):
        """Test removing a benchmark."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = BenchmarkStore(workspace=tmpdir)

            bench = Benchmark(name="Remove Test")
            store.add_benchmark(bench)

            assert store.count == 1

            removed = store.remove_benchmark(bench.benchmark_id)
            assert removed is True
            assert store.count == 0

            # Try removing non-existent
            removed = store.remove_benchmark("non_existent")
            assert removed is False

    def test_list_benchmarks_filters(self):
        """Test listing benchmarks with filters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = BenchmarkStore(workspace=tmpdir)

            bench1 = Benchmark(name="Bench 1", category="performance", enabled=True)
            bench2 = Benchmark(name="Bench 2", category="accuracy", enabled=False)
            bench3 = Benchmark(name="Bench 3", category="performance", enabled=True)

            store.add_benchmark(bench1)
            store.add_benchmark(bench2)
            store.add_benchmark(bench3)

            # All benchmarks
            all_bench = store.list_benchmarks()
            assert len(all_bench) == 3

            # Filter by category
            perf_bench = store.list_benchmarks(category="performance")
            assert len(perf_bench) == 2

            # Filter by enabled
            enabled_bench = store.list_benchmarks(enabled=True)
            assert len(enabled_bench) == 2

    def test_add_remove_suite(self):
        """Test adding and removing a suite."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = BenchmarkStore(workspace=tmpdir)

            suite = BenchmarkSuite(name="Test Suite")
            store.add_suite(suite)

            assert store.suite_count == 1

            retrieved = store.get_suite(suite.suite_id)
            assert retrieved.name == "Test Suite"

            removed = store.remove_suite(suite.suite_id)
            assert removed is True
            assert store.suite_count == 0

    def test_list_suites(self):
        """Test listing all suites."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = BenchmarkStore(workspace=tmpdir)

            suite1 = BenchmarkSuite(name="Suite 1")
            suite2 = BenchmarkSuite(name="Suite 2")

            store.add_suite(suite1)
            store.add_suite(suite2)

            suites = store.list_suites()
            assert len(suites) == 2

    def test_create_timing_benchmark(self):
        """Test creating a timing benchmark via store."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = BenchmarkStore(workspace=tmpdir)

            bench = store.create_timing_benchmark(
                name="Store Timing",
                func=lambda: None,
                warmup_runs=2,
                iterations=5,
            )

            assert bench.name == "Store Timing"
            assert store.count == 1

    def test_create_accuracy_benchmark(self):
        """Test creating an accuracy benchmark via store."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = BenchmarkStore(workspace=tmpdir)

            def test_func(x):
                return (x > 0, x)

            bench = store.create_accuracy_benchmark(
                name="Store Accuracy",
                func=test_func,
                test_cases=[1, 2, 3],
            )

            assert bench.name == "Store Accuracy"
            assert store.count == 1

    def test_create_multimetric_benchmark(self):
        """Test creating a multi-metric benchmark via store."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = BenchmarkStore(workspace=tmpdir)

            def metrics_func(x):
                return {BenchmarkMetric.ACCURACY: 0.9}

            bench = store.create_multimetric_benchmark(
                name="Store Multi",
                func=metrics_func,
            )

            assert bench.name == "Store Multi"
            assert store.count == 1

    def test_store_summary(self):
        """Test getting store summary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = BenchmarkStore(workspace=tmpdir)

            bench1 = Benchmark(name="Bench 1", category="performance", enabled=True)
            bench2 = Benchmark(name="Bench 2", category="accuracy", enabled=False)

            store.add_benchmark(bench1)
            store.add_benchmark(bench2)

            summary = store.get_summary()

            assert summary["total_benchmarks"] == 2
            assert summary["enabled_benchmarks"] == 1
            assert summary["categories"]["performance"] == 1
            assert summary["categories"]["accuracy"] == 1

    def test_clear_store(self):
        """Test clearing the store."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = BenchmarkStore(workspace=tmpdir)

            store.add_benchmark(Benchmark(name="Test"))
            store.add_suite(BenchmarkSuite(name="Test Suite"))

            assert store.count == 1
            assert store.suite_count == 1

            store.clear()

            assert store.count == 0
            assert store.suite_count == 0

    def test_export_import_store(self):
        """Test exporting and importing store data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = BenchmarkStore(workspace=tmpdir)

            bench = Benchmark(name="Export Test")
            suite = BenchmarkSuite(name="Export Suite")

            store.add_benchmark(bench)
            store.add_suite(suite)

            # Export
            data = store.export_to_dict()
            assert "benchmarks" in data
            assert "suites" in data
            assert "summary" in data

            # Create new store and import
            new_store = BenchmarkStore(workspace=tmpdir + "_new")
            new_store.import_from_dict(data)

            # Verify imported data persists
            new_store2 = BenchmarkStore(workspace=tmpdir + "_new")
            assert new_store2.count == 1
            assert new_store2.suite_count == 1

    def test_persistence(self):
        """Test that benchmarks persist to disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create store and add benchmark
            store1 = BenchmarkStore(workspace=tmpdir)
            bench = Benchmark(name="Persistent Test")
            store1.add_benchmark(bench)

            # Create new store from same directory
            store2 = BenchmarkStore(workspace=tmpdir)

            assert store2.count == 1
            retrieved = store2.get_benchmark_by_name("Persistent Test")
            assert retrieved is not None


class TestBenchmarkingIntegration:
    """Integration tests for the benchmarking framework."""

    def test_full_benchmarking_workflow(self):
        """Test a complete benchmarking workflow."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create store
            store = BenchmarkStore(workspace=tmpdir)

            # Create benchmarks
            timing_bench = store.create_timing_benchmark(
                name="Full Timing",
                func=lambda: time.sleep(0.01),
                iterations=3,
            )

            accuracy_bench = store.create_accuracy_benchmark(
                name="Full Accuracy",
                func=lambda x: (x > 5, x),
                test_cases=[6, 7, 4, 8, 3],
            )

            # Create suite
            suite = BenchmarkSuite(name="Full Suite")
            suite.add_benchmark(timing_bench)
            suite.add_benchmark(accuracy_bench)
            store.add_suite(suite)

            # Create runner
            runner = BenchmarkRunner(workspace=tmpdir)

            # Run benchmarks
            runner.run_benchmark(timing_bench)
            runner.run_benchmark(accuracy_bench)

            # Run suite
            suite_results = runner.run_suite(suite)
            assert len(suite_results) == 2

            # Check results
            assert runner.get_summary()["total_runs"] == 4
            assert runner.get_summary()["successful"] == 4

            # Check store summary
            store_summary = store.get_summary()
            assert store_summary["total_benchmarks"] == 2

    def test_compare_benchmark_results_over_time(self):
        """Test comparing benchmark results over multiple runs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(workspace=tmpdir)

            # Create a benchmark with varying performance
            call_count = [0]

            def varying_func():
                call_count[0] += 1
                time.sleep(0.01 * call_count[0])

            bench = TimingBenchmark(
                name="Varying Bench",
                func=varying_func,
                warmup_runs=0,
                iterations=1,
            )

            # Run multiple times
            for _ in range(5):
                runner.run_benchmark(bench)

            # Compare results
            comparison = runner.compare_results("Varying Bench", limit=5)

            assert comparison["result_count"] == 5
            assert len(comparison["dates"]) == 5
            assert "time" in comparison["metrics"]

            # Times should be increasing
            times = comparison["metrics"]["time"]["values"]
            assert times == sorted(times)  # Should be monotonically increasing
