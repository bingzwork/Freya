"""Project Metrics Collection module.

This module provides comprehensive metrics collection for software projects,
including file metrics, test metrics, and code quality metrics.
"""

import ast
import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional


@dataclass
class FileMetrics:
    """Metrics for a single file."""
    file_path: str
    lines_of_code: int = 0
    blank_lines: int = 0
    comment_lines: int = 0
    functions: int = 0
    classes: int = 0
    cyclomatic_complexity: int = 0
    imports: int = 0
    last_modified: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class TestMetrics:
    """Metrics for test files."""
    total_tests: int = 0
    passing_tests: int = 0
    failing_tests: int = 0
    skipped_tests: int = 0
    test_files: int = 0
    coverage_percentage: float = 0.0
    last_run: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class CodeQualityMetrics:
    """Metrics for code quality."""
    maintainability_index: float = 0.0
    duplicate_lines: int = 0
    code_smells: int = 0
    security_issues: int = 0
    technical_debt: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class ProjectMetrics:
    """Aggregated metrics for the entire project."""
    total_files: int = 0
    total_lines: int = 0
    python_files: int = 0
    test_files: int = 0
    file_metrics: Dict[str, FileMetrics] = field(default_factory=dict)
    test_metrics: Optional[TestMetrics] = None
    quality_metrics: Optional[CodeQualityMetrics] = None
    dependencies: List[str] = field(default_factory=list)
    languages: Dict[str, int] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, serializing nested dataclasses."""
        data = asdict(self)
        data["file_metrics"] = {k: v.to_dict() for k, v in self.file_metrics.items()}
        if self.test_metrics:
            data["test_metrics"] = self.test_metrics.to_dict()
        if self.quality_metrics:
            data["quality_metrics"] = self.quality_metrics.to_dict()
        return data


class ProjectMetricsCollector:
    """Collects and manages project metrics."""

    def __init__(
        self,
        workspace: str = ".",
        storage_path: str = "monitoring/project_metrics.json",
        include_patterns: List[str] = None,
        exclude_patterns: List[str] = None,
    ):
        """Initialize the collector."""
        self.workspace = Path(workspace).resolve()
        self.storage_path = Path(storage_path)
        self.include_patterns = include_patterns or ["*.py", "*.md", "*.txt", "*.json", "*.yaml", "*.yml"]
        self.exclude_patterns = exclude_patterns or [".git/*", "__pycache__/*", ".venv/*", "node_modules/*", "*.pyc"]
        self._metrics: Optional[ProjectMetrics] = None

    def _should_include(self, file_path: Path) -> bool:
        """Check if a file should be included based on patterns."""
        file_str = str(file_path)

        # Check exclude patterns
        for pattern in self.exclude_patterns:
            if pattern.endswith("/*"):
                dir_pattern = pattern[:-2]
                if dir_pattern in file_str:
                    return False
            elif pattern in file_str:
                return False

        # Check include patterns
        for pattern in self.include_patterns:
            if pattern.startswith("*") and file_str.endswith(pattern[1:]):
                return True
            elif pattern in file_str:
                return True

        return False

    def _count_lines(self, file_path: Path) -> tuple:
        """Count total, blank, and comment lines in a file."""
        total = 0
        blank = 0
        comment = 0

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    total += 1
                    stripped = line.strip()
                    if not stripped:
                        blank += 1
                    elif stripped.startswith("#"):
                        comment += 1
        except (UnicodeDecodeError, PermissionError):
            pass

        return total, blank, comment

    def _count_symbols(self, file_path: Path) -> tuple:
        """Count functions, classes, and imports in a Python file."""
        functions = 0
        classes = 0
        imports = 0

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read())

            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    functions += 1
                elif isinstance(node, ast.AsyncFunctionDef):
                    functions += 1
                elif isinstance(node, ast.ClassDef):
                    classes += 1
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    imports += 1
        except (SyntaxError, UnicodeDecodeError, PermissionError):
            pass

        return functions, classes, imports

    def _calculate_complexity(self, file_path: Path) -> int:
        """Calculate cyclomatic complexity for a Python file."""
        complexity = 1  # Base complexity

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read())

            for node in ast.walk(tree):
                if isinstance(node, (ast.If, ast.For, ast.While, ast.And, ast.Or)):
                    complexity += 1
                elif isinstance(node, ast.BoolOp):
                    complexity += len(node.values) - 1
                elif isinstance(node, ast.Compare):
                    complexity += len(node.ops) - 1
        except (SyntaxError, UnicodeDecodeError, PermissionError):
            pass

        return complexity

    def _get_python_files(self) -> List[Path]:
        """Get all Python files in the workspace."""
        python_files = []
        for py_file in self.workspace.rglob("*.py"):
            if self._should_include(py_file):
                python_files.append(py_file)
        return python_files

    def collect_file_metrics(self, file_path: Path = None) -> Dict[str, FileMetrics]:
        """Collect metrics for files."""
        file_metrics = {}

        if file_path:
            # Collect for a single file
            if self._should_include(file_path):
                total, blank, comment = self._count_lines(file_path)
                functions, classes, imports = self._count_symbols(file_path)
                complexity = self._calculate_complexity(file_path)

                try:
                    last_modified = datetime.fromtimestamp(
                        file_path.stat().st_mtime, timezone.utc
                    ).isoformat()
                except OSError:
                    last_modified = ""

                metrics = FileMetrics(
                    file_path=str(file_path.relative_to(self.workspace)),
                    lines_of_code=total - blank - comment,
                    blank_lines=blank,
                    comment_lines=comment,
                    functions=functions,
                    classes=classes,
                    cyclomatic_complexity=complexity,
                    imports=imports,
                    last_modified=last_modified,
                )
                file_metrics[str(file_path.relative_to(self.workspace))] = metrics
        else:
            # Collect for all files
            for file_path in self.workspace.rglob("*"):
                if file_path.is_file() and self._should_include(file_path):
                    total, blank, comment = self._count_lines(file_path)
                    functions, classes, imports = (0, 0, 0)
                    complexity = 1

                    # For Python files, count symbols
                    if file_path.suffix == ".py":
                        functions, classes, imports = self._count_symbols(file_path)
                        complexity = self._calculate_complexity(file_path)

                    try:
                        last_modified = datetime.fromtimestamp(
                            file_path.stat().st_mtime, timezone.utc
                        ).isoformat()
                    except OSError:
                        last_modified = ""

                    metrics = FileMetrics(
                        file_path=str(file_path.relative_to(self.workspace)),
                        lines_of_code=total - blank - comment,
                        blank_lines=blank,
                        comment_lines=comment,
                        functions=functions,
                        classes=classes,
                        cyclomatic_complexity=complexity,
                        imports=imports,
                        last_modified=last_modified,
                    )
                    file_metrics[str(file_path.relative_to(self.workspace))] = metrics

        return file_metrics

    def collect_test_metrics(self) -> TestMetrics:
        """Collect test metrics."""
        test_files = self._get_test_files()
        total_tests = 0

        for test_file in test_files:
            try:
                with open(test_file, "r", encoding="utf-8") as f:
                    content = f.read()
                    total_tests += content.count("def test_")
            except (UnicodeDecodeError, PermissionError):
                pass

        return TestMetrics(
            total_tests=total_tests,
            test_files=len(test_files),
        )

    def _get_test_files(self) -> List[Path]:
        """Get all test files in the workspace."""
        test_files = []
        for test_file in self.workspace.rglob("test_*.py"):
            if self._should_include(test_file):
                test_files.append(test_file)
        # Also check for files in tests directory
        tests_dir = self.workspace / "tests"
        if tests_dir.exists():
            for test_file in tests_dir.rglob("*.py"):
                if self._should_include(test_file) and test_file not in test_files:
                    test_files.append(test_file)
        return test_files

    def collect_dependencies(self) -> List[str]:
        """Collect dependencies from requirements files."""
        dependencies = []
        requirements_files = [
            self.workspace / "requirements.txt",
            self.workspace / "setup.py",
            self.workspace / "pyproject.toml",
        ]

        for req_file in requirements_files:
            if req_file.exists():
                try:
                    content = req_file.read_text(encoding="utf-8")
                    for line in content.split("\n"):
                        line = line.strip()
                        if line and not line.startswith("#"):
                            # Extract package name from requirements line
                            # Handle lines like "pytest>=8.0" or "numpy==1.24"
                            pkg = line.split(">=")[0].split("==")[0].split("[")[0].strip()
                            if pkg and pkg.lower() not in dependencies:
                                dependencies.append(pkg.lower())
                except (UnicodeDecodeError, PermissionError):
                    pass

        return dependencies

    def collect_language_stats(self) -> Dict[str, int]:
        """Collect language statistics."""
        languages: Dict[str, int] = {}

        for file_path in self.workspace.rglob("*"):
            if file_path.is_file() and self._should_include(file_path):
                ext = file_path.suffix.lower()
                if ext not in languages:
                    languages[ext] = 0
                languages[ext] += 1

        return languages

    def collect_quality_metrics(self) -> CodeQualityMetrics:
        """Collect code quality metrics."""
        python_files = self._get_python_files()
        total_complexity = 0
        total_files = len(python_files) or 1

        for py_file in python_files:
            complexity = self._calculate_complexity(py_file)
            total_complexity += complexity

        # Calculate a simple maintainability index (100 - avg complexity)
        avg_complexity = total_complexity / total_files
        maintainability = max(0, 100 - avg_complexity)

        return CodeQualityMetrics(
            maintainability_index=maintainability,
            duplicate_lines=0,
            code_smells=0,
            security_issues=0,
            technical_debt=0.0,
        )

    def collect(self) -> ProjectMetrics:
        """Collect all metrics for the project."""
        file_metrics = self.collect_file_metrics()
        test_metrics = self.collect_test_metrics()
        quality_metrics = self.collect_quality_metrics()
        dependencies = self.collect_dependencies()
        languages = self.collect_language_stats()

        total_files = len(file_metrics)
        total_lines = sum(m.lines_of_code for m in file_metrics.values())
        python_files = sum(1 for f, m in file_metrics.items() if f.endswith(".py"))
        test_files = test_metrics.test_files

        metrics = ProjectMetrics(
            total_files=total_files,
            total_lines=total_lines,
            python_files=python_files,
            test_files=test_files,
            file_metrics=file_metrics,
            test_metrics=test_metrics,
            quality_metrics=quality_metrics,
            dependencies=dependencies,
            languages=languages,
        )

        self._metrics = metrics
        return metrics

    def get(self) -> Optional[ProjectMetrics]:
        """Get the last collected metrics."""
        return self._metrics

    def save(self) -> None:
        """Save metrics to the storage path."""
        if self._metrics:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(self._metrics.to_dict(), f, indent=2)

    def load(self) -> Optional[ProjectMetrics]:
        """Load metrics from the storage path."""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # Convert back to ProjectMetrics
                file_metrics = {}
                for k, v in data.get("file_metrics", {}).items():
                    file_metrics[k] = FileMetrics(**v)

                test_metrics = None
                if "test_metrics" in data and data["test_metrics"]:
                    test_metrics = TestMetrics(**data["test_metrics"])

                quality_metrics = None
                if "quality_metrics" in data and data["quality_metrics"]:
                    quality_metrics = CodeQualityMetrics(**data["quality_metrics"])

                metrics = ProjectMetrics(
                    total_files=data.get("total_files", 0),
                    total_lines=data.get("total_lines", 0),
                    python_files=data.get("python_files", 0),
                    test_files=data.get("test_files", 0),
                    file_metrics=file_metrics,
                    test_metrics=test_metrics,
                    quality_metrics=quality_metrics,
                    dependencies=data.get("dependencies", []),
                    languages=data.get("languages", {}),
                    timestamp=data.get("timestamp", ""),
                )
                self._metrics = metrics
                return metrics
            except (json.JSONDecodeError, PermissionError):
                pass
        return None

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the collected metrics."""
        if not self._metrics:
            self.collect()

        metrics = self._metrics
        return {
            "timestamp": metrics.timestamp,
            "total_files": metrics.total_files,
            "total_lines": metrics.total_lines,
            "python_files": metrics.python_files,
            "test_files": metrics.test_files,
            "test_metrics": metrics.test_metrics.to_dict() if metrics.test_metrics else {},
            "quality_metrics": metrics.quality_metrics.to_dict() if metrics.quality_metrics else {},
            "languages": metrics.languages,
            "dependency_count": len(metrics.dependencies),
        }
