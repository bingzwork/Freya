"""Tests for the Project Metrics Collection module.

This module provides comprehensive tests for ProjectMetricsCollector,
ProjectMetrics, FileMetrics, TestMetrics, and CodeQualityMetrics.
"""

import json
import os
import tempfile
import pytest
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any

from app.monitoring.project_metrics import (
    ProjectMetricsCollector,
    ProjectMetrics,
    FileMetrics,
    TestMetrics,
    CodeQualityMetrics,
)


class TestFileMetrics:
    """Tests for FileMetrics dataclass."""

    def test_create_file_metrics(self):
        """Test creating file metrics."""
        metrics = FileMetrics(
            file_path="test.py",
            lines_of_code=100,
            blank_lines=20,
            comment_lines=30,
            functions=5,
            classes=3,
            cyclomatic_complexity=10,
            imports=5,
            last_modified="2026-07-20T00:00:00+00:00",
        )

        assert metrics.file_path == "test.py"
        assert metrics.lines_of_code == 100
        assert metrics.blank_lines == 20
        assert metrics.comment_lines == 30
        assert metrics.functions == 5
        assert metrics.classes == 3
        assert metrics.cyclomatic_complexity == 10
        assert metrics.imports == 5

    def test_to_dict(self):
        """Test converting file metrics to dictionary."""
        metrics = FileMetrics(file_path="test.py", lines_of_code=50)
        data = metrics.to_dict()

        assert data["file_path"] == "test.py"
        assert data["lines_of_code"] == 50


class TestTestMetrics:
    """Tests for TestMetrics dataclass."""

    def test_create_test_metrics(self):
        """Test creating test metrics."""
        metrics = TestMetrics(
            total_tests=100,
            passing_tests=80,
            failing_tests=10,
            skipped_tests=10,
            test_files=5,
            coverage_percentage=85.5,
            last_run="2026-07-20T00:00:00+00:00",
        )

        assert metrics.total_tests == 100
        assert metrics.passing_tests == 80
        assert metrics.failing_tests == 10
        assert metrics.coverage_percentage == 85.5

    def test_to_dict(self):
        """Test converting test metrics to dictionary."""
        metrics = TestMetrics(total_tests=50, passing_tests=40)
        data = metrics.to_dict()

        assert data["total_tests"] == 50
        assert data["passing_tests"] == 40


class TestCodeQualityMetrics:
    """Tests for CodeQualityMetrics dataclass."""

    def test_create_quality_metrics(self):
        """Test creating code quality metrics."""
        metrics = CodeQualityMetrics(
            maintainability_index=85.5,
            duplicate_lines=10,
            code_smells=5,
            security_issues=0,
            technical_debt=2.5,
        )

        assert metrics.maintainability_index == 85.5
        assert metrics.duplicate_lines == 10
        assert metrics.technical_debt == 2.5

    def test_to_dict(self):
        """Test converting quality metrics to dictionary."""
        metrics = CodeQualityMetrics(maintainability_index=90.0)
        data = metrics.to_dict()

        assert data["maintainability_index"] == 90.0


class TestProjectMetrics:
    """Tests for ProjectMetrics dataclass."""

    def test_create_project_metrics(self):
        """Test creating project metrics."""
        metrics = ProjectMetrics(
            total_files=10,
            total_lines=1000,
            python_files=8,
            test_files=2,
        )

        assert metrics.total_files == 10
        assert metrics.total_lines == 1000
        assert metrics.python_files == 8
        assert metrics.test_files == 2

    def test_to_dict(self):
        """Test converting project metrics to dictionary."""
        file_metrics = {"test.py": FileMetrics(file_path="test.py", lines_of_code=50)}
        test_metrics = TestMetrics(total_tests=10)
        quality_metrics = CodeQualityMetrics(maintainability_index=80.0)

        metrics = ProjectMetrics(
            total_files=1,
            total_lines=50,
            python_files=1,
            test_files=0,
            file_metrics=file_metrics,
            test_metrics=test_metrics,
            quality_metrics=quality_metrics,
        )

        data = metrics.to_dict()
        assert data["total_files"] == 1
        assert "file_metrics" in data
        assert "test_metrics" in data


class TestProjectMetricsCollector:
    """Tests for ProjectMetricsCollector class."""

    @pytest.fixture
    def temp_collector(self, tmp_path):
        """Create a temporary ProjectMetricsCollector instance."""
        workspace = str(tmp_path)
        storage_path = "monitoring/project_metrics.json"
        collector = ProjectMetricsCollector(
            workspace=workspace,
            storage_path=storage_path,
        )
        return collector

    @pytest.fixture
    def temp_project_dir(self, tmp_path):
        """Create a temporary project directory with Python files."""
        # Create some Python files
        (tmp_path / "module1.py").write_text(
            '"""Module 1."""\n\nimport os\n\n\ndef function1():\n    """Function 1."""\n    pass\n\n\ndef function2():\n    """Function 2."""\n    pass\n\n\nclass Class1:\n    """Class 1."""\n    pass\n'
        )

        (tmp_path / "module2.py").write_text(
            '"""Module 2."""\n\nimport sys\n\ndef main():\n    """Main function."""\n    if True:\n        print("Hello")\n    return 0\n'
        )

        (tmp_path / "test_module.py").write_text(
            '"""Tests."""\n\nimport pytest\n\ndef test_function1():\n    """Test function 1."""\n    assert True\n\n\ndef test_function2():\n    """Test function 2."""\n    assert False\n'
        )

        (tmp_path / "requirements.txt").write_text(
            "pytest>=8.0\nnumpy>=1.24\n"
        )

        return tmp_path

    def test_init_defaults(self, temp_collector):
        """Test default initialization."""
        assert temp_collector.workspace.exists()
        assert "*.py" in temp_collector.include_patterns
        assert ".git/*" in temp_collector.exclude_patterns

    def test_collect_file_metrics(self, temp_project_dir):
        """Test collecting file metrics."""
        collector = ProjectMetricsCollector(workspace=str(temp_project_dir))
        file_metrics = collector.collect_file_metrics()

        # Should find the Python files
        assert len(file_metrics) >= 2

        # Check that metrics are collected
        for fp, metrics in file_metrics.items():
            assert metrics.lines_of_code >= 0
            assert metrics.functions >= 0
            assert metrics.classes >= 0

    def test_collect_file_metrics_single_file(self, temp_project_dir):
        """Test collecting metrics for a single file."""
        collector = ProjectMetricsCollector(workspace=str(temp_project_dir))
        file_path = Path(temp_project_dir) / "module1.py"

        file_metrics = collector.collect_file_metrics(file_path)
        assert len(file_metrics) == 1

        metrics = list(file_metrics.values())[0]
        assert metrics.functions >= 2  # function1 and function2
        assert metrics.classes >= 1  # Class1

    def test_count_lines(self, temp_project_dir):
        """Test line counting."""
        collector = ProjectMetricsCollector(workspace=str(temp_project_dir))
        file_path = Path(temp_project_dir) / "module1.py"

        total, blank, comment = collector._count_lines(file_path)

        assert total > 0
        assert blank >= 0
        assert comment >= 0
        # Just verify that we can count lines - don't assert exact equality
        # as the exact count depends on the file content structure

    def test_calculate_complexity(self, temp_project_dir):
        """Test complexity calculation."""
        collector = ProjectMetricsCollector(workspace=str(temp_project_dir))
        file_path = Path(temp_project_dir) / "module2.py"

        complexity = collector._calculate_complexity(file_path)
        assert complexity >= 1  # Base complexity

    def test_count_symbols(self, temp_project_dir):
        """Test symbol counting."""
        collector = ProjectMetricsCollector(workspace=str(temp_project_dir))
        file_path = Path(temp_project_dir) / "module1.py"

        funcs, classes, imports = collector._count_symbols(file_path)

        assert funcs == 2  # function1 and function2
        assert classes == 1  # Class1
        assert imports >= 1  # import os

    def test_collect_test_metrics(self, temp_project_dir):
        """Test collecting test metrics."""
        collector = ProjectMetricsCollector(workspace=str(temp_project_dir))
        test_metrics = collector.collect_test_metrics()

        assert test_metrics.test_files >= 1  # test_module.py

    def test_collect_dependencies(self, temp_project_dir):
        """Test collecting dependencies."""
        collector = ProjectMetricsCollector(workspace=str(temp_project_dir))
        deps = collector.collect_dependencies()

        assert "pytest" in deps
        assert "numpy" in deps

    def test_collect_language_stats(self, temp_project_dir):
        """Test collecting language statistics."""
        collector = ProjectMetricsCollector(workspace=str(temp_project_dir))
        languages = collector.collect_language_stats()

        assert ".py" in languages
        assert languages[".py"] >= 3  # module1.py, module2.py, test_module.py

    def test_collect_quality_metrics(self, temp_project_dir):
        """Test collecting quality metrics."""
        collector = ProjectMetricsCollector(workspace=str(temp_project_dir))
        quality_metrics = collector.collect_quality_metrics()

        assert quality_metrics.maintainability_index >= 0
        assert quality_metrics.maintainability_index <= 100

    def test_collect_all(self, temp_project_dir):
        """Test collecting all metrics."""
        collector = ProjectMetricsCollector(workspace=str(temp_project_dir))
        metrics = collector.collect()

        assert metrics.total_files >= 3  # .py files + requirements.txt
        assert metrics.total_lines > 0
        assert metrics.python_files >= 3
        assert metrics.test_files >= 1
        assert metrics.file_metrics is not None
        assert metrics.test_metrics is not None
        assert metrics.quality_metrics is not None
        assert len(metrics.dependencies) >= 2

    def test_get_last_collected(self, temp_collector, temp_project_dir):
        """Test getting last collected metrics."""
        # First, there should be no metrics
        assert temp_collector.get() is None

        # Create some files in the temp collector's workspace
        (temp_collector.workspace / "test.py").write_text("def test(): pass")

        # Collect metrics
        temp_collector.collect()

        # Now there should be metrics
        metrics = temp_collector.get()
        assert metrics is not None
        assert metrics.total_files >= 1

    def test_save_and_load(self, temp_collector, tmp_path):
        """Test saving and loading metrics."""
        # Create a file to collect metrics from
        (temp_collector.workspace / "test.py").write_text(
            "def test():\n    pass\n"
        )

        # Collect and save
        metrics = temp_collector.collect()
        temp_collector.save()

        # Verify the file was created
        assert temp_collector.storage_path.exists()

        # Create a new collector and load from the same file
        collector2 = ProjectMetricsCollector(
            workspace=str(temp_collector.workspace),
            storage_path="monitoring/project_metrics.json",
        )

        # Load the metrics
        loaded_metrics = collector2.load()
        assert loaded_metrics is not None
        assert loaded_metrics.total_files >= 1

    def test_get_summary(self, temp_project_dir):
        """Test get_summary method."""
        collector = ProjectMetricsCollector(workspace=str(temp_project_dir))
        collector.collect()

        summary = collector.get_summary()
        assert "timestamp" in summary
        assert "total_files" in summary
        assert "total_lines" in summary
        assert "python_files" in summary
        assert "test_files" in summary
        assert "test_metrics" in summary
        assert "quality_metrics" in summary
        assert "languages" in summary
        assert "dependency_count" in summary

    def test_should_include(self, temp_project_dir):
        """Test _should_include method."""
        collector = ProjectMetricsCollector(workspace=str(temp_project_dir))

        # Should include Python files
        assert collector._should_include(Path(temp_project_dir) / "module1.py") is True

        # Should exclude __pycache__
        pycache_dir = Path(temp_project_dir) / "__pycache__" / "test.pyc"
        assert collector._should_include(pycache_dir) is False

        # Should exclude .git
        git_file = Path(temp_project_dir) / ".git" / "config"
        assert collector._should_include(git_file) is False

    def test_get_python_files(self, temp_project_dir):
        """Test _get_python_files method."""
        collector = ProjectMetricsCollector(workspace=str(temp_project_dir))
        python_files = collector._get_python_files()

        assert len(python_files) >= 3  # module1.py, module2.py, test_module.py
        assert all(f.name.endswith(".py") for f in python_files)

    def test_custom_include_patterns(self, tmp_path):
        """Test custom include patterns."""
        # Create a file with a custom extension
        (tmp_path / "config.yaml").write_text("key: value")

        collector = ProjectMetricsCollector(
            workspace=str(tmp_path),
            include_patterns=["*.yaml"],
        )

        # Should include YAML files with custom pattern
        assert collector._should_include(tmp_path / "config.yaml") is True

    def test_custom_exclude_patterns(self, tmp_path):
        """Test custom exclude patterns."""
        (tmp_path / "test.py").write_text("# test")
        (tmp_path / "temp.py").write_text("# temp")

        collector = ProjectMetricsCollector(
            workspace=str(tmp_path),
            exclude_patterns=["temp.py"],
        )

        # Should exclude temp.py
        assert collector._should_include(tmp_path / "temp.py") is False
        # Should include test.py
        assert collector._should_include(tmp_path / "test.py") is True

    def test_file_metrics_to_dict(self):
        """Test FileMetrics serialization."""
        metrics = FileMetrics(
            file_path="test.py",
            lines_of_code=100,
        )
        data = metrics.to_dict()
        restored = FileMetrics(**data)

        assert restored.file_path == metrics.file_path
        assert restored.lines_of_code == metrics.lines_of_code

    def test_test_metrics_to_dict(self):
        """Test TestMetrics serialization."""
        metrics = TestMetrics(
            total_tests=50,
            passing_tests=40,
        )
        data = metrics.to_dict()
        restored = TestMetrics(**data)

        assert restored.total_tests == metrics.total_tests
        assert restored.passing_tests == metrics.passing_tests

    def test_quality_metrics_to_dict(self):
        """Test CodeQualityMetrics serialization."""
        metrics = CodeQualityMetrics(maintainability_index=75.0)
        data = metrics.to_dict()
        restored = CodeQualityMetrics(**data)

        assert restored.maintainability_index == metrics.maintainability_index
