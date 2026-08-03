"""Health Metrics for tracking project vital signs.

This module defines various metric types for monitoring the health
of the Freya project.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Any, Callable
import subprocess
import time
import psutil
import os
from pathlib import Path


class HealthStatus(Enum):
    """Status levels for health metrics."""
    EXCELLENT = "excellent"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


@dataclass
class Metric:
    """Base class for all health metrics."""
    name: str
    description: str
    category: str
    status: HealthStatus = HealthStatus.UNKNOWN
    value: Optional[float] = None
    unit: str = ""
    threshold_excellent: float = 100.0
    threshold_good: float = 80.0
    threshold_fair: float = 60.0
    threshold_poor: float = 40.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    details: Dict[str, Any] = field(default_factory=dict)

    def evaluate_status(self) -> HealthStatus:
        """Evaluate the status based on the value and thresholds."""
        if self.value is None:
            return HealthStatus.UNKNOWN
        if self.value >= self.threshold_excellent:
            return HealthStatus.EXCELLENT
        elif self.value >= self.threshold_good:
            return HealthStatus.GOOD
        elif self.value >= self.threshold_fair:
            return HealthStatus.FAIR
        elif self.value >= self.threshold_poor:
            return HealthStatus.POOR
        else:
            return HealthStatus.CRITICAL

    def to_dict(self) -> Dict[str, Any]:
        """Convert metric to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "status": self.status.value,
            "value": self.value,
            "unit": self.unit,
            "timestamp": self.timestamp,
            "details": self.details,
        }


class CodeQualityMetrics:
    """Metrics related to code quality."""

    def __init__(self, workspace: str = "."):
        self.workspace = Path(workspace).resolve()

    def collect_all(self) -> List[Metric]:
        """Collect all code quality metrics."""
        metrics = []
        metrics.append(self.count_files())
        metrics.append(self.count_lines_of_code())
        metrics.append(self.count_python_files())
        metrics.append(self.check_pep8_compliance())
        metrics.append(self.check_import_structure())
        metrics.append(self.count_docstrings())
        metrics.append(self.check_type_hints())
        return metrics

    def count_files(self) -> Metric:
        """Count total files in the project."""
        count = 0
        for root, dirs, files in os.walk(self.workspace):
            # Skip hidden directories and common non-source dirs
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ["__pycache__", "node_modules", ".venv", "venv"]]
            count += len(files)
        return Metric(
            name="total_files",
            description="Total number of files in the project",
            category="code_quality",
            value=float(count),
            unit="files",
        )

    def count_python_files(self) -> Metric:
        """Count Python files in the project."""
        count = len(list(self.workspace.rglob("*.py")))
        # Exclude __pycache__ files
        py_files = [f for f in self.workspace.rglob("*.py") if "__pycache__" not in str(f)]
        count = len(py_files)
        return Metric(
            name="python_files",
            description="Number of Python files in the project",
            category="code_quality",
            value=float(count),
            unit="files",
        )

    def count_lines_of_code(self) -> Metric:
        """Count total lines of Python code."""
        count = 0
        for py_file in self.workspace.rglob("*.py"):
            if "__pycache__" not in str(py_file):
                try:
                    with open(py_file, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                        # Count non-empty, non-comment lines
                        for line in lines:
                            stripped = line.strip()
                            if stripped and not stripped.startswith("#"):
                                count += 1
                except (UnicodeDecodeError, PermissionError):
                    pass
        return Metric(
            name="lines_of_code",
            description="Total lines of Python code (excluding blanks and comments)",
            category="code_quality",
            value=float(count),
            unit="lines",
        )

    def check_pep8_compliance(self) -> Metric:
        """Check PEP 8 compliance using flake8 if available."""
        try:
            result = subprocess.run(
                ["flake8", str(self.workspace / "app"), str(self.workspace / "tests")],
                capture_output=True,
                text=True,
                timeout=30,
            )
            # Count violations
            violations = result.stdout.count("\n") if result.stdout else 0
            if violations == 0:
                score = 100.0
            else:
                # Approximate score based on violations
                score = max(0, 100 - (violations * 5))
            return Metric(
                name="pep8_compliance",
                description="PEP 8 compliance score",
                category="code_quality",
                value=float(score),
                unit="%",
                details={"violations": violations},
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return Metric(
                name="pep8_compliance",
                description="PEP 8 compliance score",
                category="code_quality",
                status=HealthStatus.UNKNOWN,
                value=None,
                unit="%",
                details={"error": "flake8 not available"},
            )

    def check_import_structure(self) -> Metric:
        """Check that imports are properly structured."""
        # Check for circular imports
        circular_imports = 0
        try:
            # Try importing all app modules
            import importlib
            import pkgutil
            app_path = self.workspace / "app"
            for module_info in pkgutil.iter_modules([str(app_path)]):
                try:
                    importlib.import_module(f"app.{module_info.name}")
                except ImportError as e:
                    if "circular" in str(e).lower():
                        circular_imports += 1
        except Exception:
            pass

        score = max(0, 100 - (circular_imports * 20))
        return Metric(
            name="import_structure",
            description="Import structure quality score",
            category="code_quality",
            value=float(score),
            unit="%",
            details={"circular_imports": circular_imports},
        )

    def count_docstrings(self) -> Metric:
        """Count docstrings in Python files."""
        import ast
        count = 0
        total_functions = 0
        for py_file in self.workspace.rglob("*.py"):
            if "__pycache__" not in str(py_file):
                try:
                    with open(py_file, "r", encoding="utf-8") as f:
                        tree = ast.parse(f.read())
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
                            total_functions += 1
                            if ast.get_docstring(node):
                                count += 1
                except (SyntaxError, UnicodeDecodeError):
                    pass

        if total_functions > 0:
            percentage = (count / total_functions) * 100
        else:
            percentage = 100.0

        return Metric(
            name="docstring_coverage",
            description="Percentage of functions/classes with docstrings",
            category="code_quality",
            value=float(percentage),
            unit="%",
            details={"docstrings": count, "total": total_functions},
        )

    def check_type_hints(self) -> Metric:
        """Check type hint usage in Python files."""
        import ast
        typed = 0
        total = 0
        for py_file in self.workspace.rglob("*.py"):
            if "__pycache__" not in str(py_file):
                try:
                    with open(py_file, "r", encoding="utf-8") as f:
                        tree = ast.parse(f.read())
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            total += 1
                            # Check if function has return type annotation
                            if node.returns:
                                typed += 1
                except (SyntaxError, UnicodeDecodeError):
                    pass

        if total > 0:
            percentage = (typed / total) * 100
        else:
            percentage = 100.0

        return Metric(
            name="type_hint_coverage",
            description="Percentage of functions with return type hints",
            category="code_quality",
            value=float(percentage),
            unit="%",
            details={"typed": typed, "total": total},
        )


class TestMetrics:
    """Metrics related to testing."""

    def __init__(self, workspace: str = "."):
        self.workspace = Path(workspace).resolve()

    def collect_all(self) -> List[Metric]:
        """Collect all test metrics."""
        metrics = []
        metrics.append(self.count_tests())
        metrics.append(self.run_tests())
        metrics.append(self.test_coverage())
        metrics.append(self.count_skipped_tests())
        return metrics

    def count_tests(self) -> Metric:
        """Count total number of tests."""
        count = 0
        for test_file in self.workspace.rglob("test_*.py"):
            try:
                with open(test_file, "r", encoding="utf-8") as f:
                    content = f.read()
                    # Count test functions (def test_...)
                    count += content.count("def test_")
            except (UnicodeDecodeError, PermissionError):
                pass
        return Metric(
            name="total_tests",
            description="Total number of test functions",
            category="testing",
            value=float(count),
            unit="tests",
        )

    def run_tests(self) -> Metric:
        """Run tests and return pass/fail metrics."""
        try:
            result = subprocess.run(
                ["pytest", str(self.workspace / "tests"), "-q", "--tb=no"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            output = result.stdout + result.stderr
            # Parse output for passed/failed counts
            # Pytest output format: "10 passed, 2 failed, 3 skipped in 1.23s"
            import re
            passed = 0
            failed = 0
            skipped = 0

            # Match patterns like "10 passed", "2 failed", "3 skipped" (with optional commas)
            for match in re.finditer(r"(\d+)\s+(passed|failed|skipped)", output):
                count = int(match.group(1))
                kind = match.group(2)
                if kind == "passed":
                    passed = count
                elif kind == "failed":
                    failed = count
                elif kind == "skipped":
                    skipped = count

            total = passed + failed + skipped
            if total > 0:
                score = (passed / total) * 100
            else:
                score = 100.0

            return Metric(
                name="test_pass_rate",
                description="Percentage of tests passing",
                category="testing",
                value=float(score),
                unit="%",
                details={"passed": passed, "failed": failed, "skipped": skipped},
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return Metric(
                name="test_pass_rate",
                description="Percentage of tests passing",
                category="testing",
                status=HealthStatus.UNKNOWN,
                value=None,
                unit="%",
                details={"error": "pytest not available or timed out"},
            )

    def test_coverage(self) -> Metric:
        """Calculate test coverage using pytest-cov if available."""
        try:
            result = subprocess.run(
                ["pytest", str(self.workspace / "tests"), "--cov=app", "--cov-report=term", "-q"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            output = result.stdout + result.stderr
            # Parse coverage percentage
            for line in output.split("\n"):
                if "%" in line and ("coverage" in line.lower() or "TOTAL" in line):
                    parts = line.split()
                    for part in parts:
                        if part.endswith("%"):
                            coverage = float(part.replace("%", "").replace(",", ""))
                            return Metric(
                                name="test_coverage",
                                description="Test coverage percentage",
                                category="testing",
                                value=float(coverage),
                                unit="%",
                            )
            return Metric(
                name="test_coverage",
                description="Test coverage percentage",
                category="testing",
                status=HealthStatus.UNKNOWN,
                value=None,
                unit="%",
                details={"error": "Could not parse coverage from output"},
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return Metric(
                name="test_coverage",
                description="Test coverage percentage",
                category="testing",
                status=HealthStatus.UNKNOWN,
                value=None,
                unit="%",
                details={"error": "pytest-cov not available"},
            )

    def count_skipped_tests(self) -> Metric:
        """Count skipped tests."""
        try:
            result = subprocess.run(
                ["pytest", str(self.workspace / "tests"), "-q", "--tb=no"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            output = result.stdout + result.stderr
            import re
            for match in re.finditer(r"(\d+)\s+skipped", output):
                skipped = int(match.group(1))
                return Metric(
                    name="skipped_tests",
                    description="Number of skipped tests",
                    category="testing",
                    value=float(skipped),
                    unit="tests",
                )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return Metric(
            name="skipped_tests",
            description="Number of skipped tests",
            category="testing",
            value=0.0,
            unit="tests",
        )


class PerformanceMetrics:
    """Metrics related to performance."""

    def __init__(self, workspace: str = "."):
        self.workspace = Path(workspace).resolve()

    def collect_all(self) -> List[Metric]:
        """Collect all performance metrics."""
        metrics = []
        metrics.append(self.indexing_speed())
        metrics.append(self.llm_response_time())
        return metrics

    def indexing_speed(self) -> Metric:
        """Measure the speed of project indexing."""
        try:
            from app.core.project_index import ProjectIndex
            from app.core.symbol_index import SymbolIndex

            start = time.time()
            pi = ProjectIndex(str(self.workspace))
            pi.build()
            build_time = time.time() - start

            start = time.time()
            si = SymbolIndex(str(self.workspace))
            si.build()
            symbol_time = time.time() - start

            total_time = build_time + symbol_time
            return Metric(
                name="indexing_speed",
                description="Time to build project and symbol indexes",
                category="performance",
                value=float(total_time),
                unit="seconds",
                details={"project_index_time": build_time, "symbol_index_time": symbol_time},
            )
        except Exception as e:
            return Metric(
                name="indexing_speed",
                description="Time to build project and symbol indexes",
                category="performance",
                status=HealthStatus.UNKNOWN,
                value=None,
                unit="seconds",
                details={"error": str(e)},
            )

    def llm_response_time(self) -> Metric:
        """Measure LLM response time."""
        try:
            from app.core.llm import LLM
            llm = LLM()
            start = time.time()
            response = llm.ask("What is 2+2?")
            elapsed = time.time() - start
            return Metric(
                name="llm_response_time",
                description="Average LLM response time",
                category="performance",
                value=float(elapsed),
                unit="seconds",
                details={"response_length": len(response)},
            )
        except Exception as e:
            return Metric(
                name="llm_response_time",
                description="Average LLM response time",
                category="performance",
                status=HealthStatus.UNKNOWN,
                value=None,
                unit="seconds",
                details={"error": str(e)},
            )


class SystemMetrics:
    """Metrics related to system resources."""

    def __init__(self, workspace: str = "."):
        self.workspace = Path(workspace).resolve()

    def collect_all(self) -> List[Metric]:
        """Collect all system metrics."""
        metrics = []
        metrics.append(self.cpu_usage())
        metrics.append(self.memory_usage())
        metrics.append(self.disk_usage())
        metrics.append(self.pycache_size())
        return metrics

    def cpu_usage(self) -> Metric:
        """Get current CPU usage."""
        try:
            cpu = psutil.cpu_percent(interval=1)
            return Metric(
                name="cpu_usage",
                description="Current CPU usage percentage",
                category="system",
                value=float(cpu),
                unit="%",
            )
        except Exception:
            return Metric(
                name="cpu_usage",
                description="Current CPU usage percentage",
                category="system",
                status=HealthStatus.UNKNOWN,
                value=None,
                unit="%",
            )

    def memory_usage(self) -> Metric:
        """Get current memory usage."""
        try:
            memory = psutil.virtual_memory()
            percent = memory.percent
            used_mb = memory.used / (1024 * 1024)
            return Metric(
                name="memory_usage",
                description="Current memory usage percentage",
                category="system",
                value=float(percent),
                unit="%",
                details={"used_mb": used_mb},
            )
        except Exception:
            return Metric(
                name="memory_usage",
                description="Current memory usage percentage",
                category="system",
                status=HealthStatus.UNKNOWN,
                value=None,
                unit="%",
            )

    def disk_usage(self) -> Metric:
        """Get disk usage for the workspace."""
        try:
            disk = psutil.disk_usage(str(self.workspace))
            percent = disk.percent
            used_mb = disk.used / (1024 * 1024)
            total_mb = disk.total / (1024 * 1024)
            return Metric(
                name="disk_usage",
                description="Disk usage for workspace",
                category="system",
                value=float(percent),
                unit="%",
                details={"used_mb": used_mb, "total_mb": total_mb},
            )
        except Exception:
            return Metric(
                name="disk_usage",
                description="Disk usage for workspace",
                category="system",
                status=HealthStatus.UNKNOWN,
                value=None,
                unit="%",
            )

    def pycache_size(self) -> Metric:
        """Calculate size of __pycache__ directories."""
        total_size = 0
        for pycache in self.workspace.rglob("__pycache__"):
            for pyc in pycache.glob("*.pyc"):
                try:
                    total_size += pyc.stat().st_size
                except (OSError, PermissionError):
                    pass
        size_mb = total_size / (1024 * 1024)
        return Metric(
            name="pycache_size",
            description="Total size of __pycache__ directories",
            category="system",
            value=float(size_mb),
            unit="MB",
        )
