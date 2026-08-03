"""Tests for the Project Health Dashboard system."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, Mock

import pytest


# Fixtures to mock expensive operations for HealthMonitor and integration tests
@pytest.fixture
def temp_workspace():
    """Create a small temporary workspace for fast metric testing."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)

        # Create a minimal project structure
        (workspace / "app").mkdir()
        (workspace / "tests").mkdir()
        (workspace / "app" / "__init__.py").write_text("")
        (workspace / "app" / "main.py").write_text("def hello():\n    return 'world'\n")
        (workspace / "app" / "utils.py").write_text("""
def add(a, b):
    '''Add two numbers.'''
    return a + b
""")
        (workspace / "tests" / "__init__.py").write_text("")
        (workspace / "tests" / "test_main.py").write_text("""
def test_hello():
    assert hello() == 'world'

def test_add():
    assert add(1, 2) == 3
""")

        yield str(workspace)


@pytest.fixture
def mock_expensive_operations():
    """Mock expensive subprocess calls and external operations."""
    with patch("subprocess.run") as mock_run, \
         patch("app.core.project_index.ProjectIndex") as mock_pi, \
         patch("app.core.symbol_index.SymbolIndex") as mock_si, \
         patch("app.core.llm.LLM") as mock_llm, \
         patch("app.health.health_metrics.psutil") as mock_psutil:

        # Mock subprocess.run for flake8, pytest, etc.
        # Note: pytest output parser expects format like "10 passed" "2 failed" "3 skipped"
        mock_run.return_value = Mock(stdout="10 passed 2 failed 3 skipped", stderr="", returncode=0)

        # Mock ProjectIndex and SymbolIndex
        mock_pi_instance = Mock()
        mock_pi_instance.build.return_value = None
        mock_pi.return_value = mock_pi_instance

        mock_si_instance = Mock()
        mock_si_instance.build.return_value = None
        mock_si.return_value = mock_si_instance

        # Mock LLM
        mock_llm_instance = Mock()
        mock_llm_instance.ask.return_value = "4"
        mock_llm.return_value = mock_llm_instance

        # Mock psutil
        mock_psutil.cpu_percent.return_value = 25.0
        mock_psutil.virtual_memory.return_value = Mock(percent=50.0, used=1024*1024*1024)
        mock_psutil.disk_usage.return_value = Mock(percent=60.0, used=1024*1024*1024, total=1024*1024*1024)

        yield mock_run

from app.health.health_metrics import (
    Metric,
    HealthStatus,
    CodeQualityMetrics,
    TestMetrics,
    PerformanceMetrics,
    SystemMetrics,
)
from app.health.health_monitor import (
    HealthMonitor,
    Alert,
    AlertCallback,
    LoggingAlertCallback,
)
from app.health.health_report import HealthReport
from app.health.health_dashboard import HealthDashboard


class TestMetric:
    """Tests for the Metric dataclass."""

    def test_metric_creation(self):
        """Test creating a metric."""
        metric = Metric(
            name="test_metric",
            description="A test metric",
            category="test",
            value=75.0,
            unit="%",
        )
        assert metric.name == "test_metric"
        assert metric.value == 75.0
        assert metric.unit == "%"

    def test_metric_evaluate_status_excellent(self):
        """Test status evaluation for excellent metric."""
        metric = Metric(
            name="test",
            description="Test",
            category="test",
            value=100.0,
            unit="%",
        )
        assert metric.evaluate_status() == HealthStatus.EXCELLENT

    def test_metric_evaluate_status_good(self):
        """Test status evaluation for good metric."""
        metric = Metric(
            name="test",
            description="Test",
            category="test",
            value=85.0,
            unit="%",
            threshold_excellent=100,
            threshold_good=80,
            threshold_fair=60,
            threshold_poor=40,
        )
        assert metric.evaluate_status() == HealthStatus.GOOD

    def test_metric_evaluate_status_fair(self):
        """Test status evaluation for fair metric."""
        metric = Metric(
            name="test",
            description="Test",
            category="test",
            value=65.0,
            unit="%",
            threshold_excellent=100,
            threshold_good=80,
            threshold_fair=60,
        )
        assert metric.evaluate_status() == HealthStatus.FAIR

    def test_metric_evaluate_status_poor(self):
        """Test status evaluation for poor metric."""
        metric = Metric(
            name="test",
            description="Test",
            category="test",
            value=50.0,
            unit="%",
            threshold_excellent=100,
            threshold_good=80,
            threshold_fair=60,
            threshold_poor=40,
        )
        assert metric.evaluate_status() == HealthStatus.POOR

    def test_metric_evaluate_status_critical(self):
        """Test status evaluation for critical metric."""
        metric = Metric(
            name="test",
            description="Test",
            category="test",
            value=15.0,
            unit="%",
            threshold_excellent=100,
            threshold_good=80,
            threshold_fair=60,
            threshold_poor=40,
        )
        assert metric.evaluate_status() == HealthStatus.CRITICAL

    def test_metric_to_dict(self):
        """Test converting metric to dictionary."""
        metric = Metric(
            name="test",
            description="Test metric",
            category="test",
            value=50.0,
            unit="%",
        )
        data = metric.to_dict()
        assert data["name"] == "test"
        assert data["value"] == 50.0
        assert data["category"] == "test"


class TestCodeQualityMetrics:
    """Tests for CodeQualityMetrics."""

    def test_count_files(self, temp_workspace):
        """Test counting files."""
        cq = CodeQualityMetrics(temp_workspace)
        metric = cq.count_files()
        assert metric.name == "total_files"
        assert metric.value > 0
        assert metric.unit == "files"

    def test_count_python_files(self, temp_workspace):
        """Test counting Python files."""
        cq = CodeQualityMetrics(temp_workspace)
        metric = cq.count_python_files()
        assert metric.name == "python_files"
        assert metric.value > 0
        assert metric.unit == "files"

    def test_count_lines_of_code(self, temp_workspace):
        """Test counting lines of code."""
        cq = CodeQualityMetrics(temp_workspace)
        metric = cq.count_lines_of_code()
        assert metric.name == "lines_of_code"
        assert metric.value > 0
        assert metric.unit == "lines"

    @patch("subprocess.run")
    def test_check_pep8_compliance(self, mock_run):
        """Test PEP 8 compliance check (mocked - calls flake8 subprocess)."""
        mock_run.return_value = Mock(stdout="", stderr="", returncode=0)
        cq = CodeQualityMetrics()
        metric = cq.check_pep8_compliance()
        assert metric.name == "pep8_compliance"
        assert metric.value is not None
        assert metric.unit == "%"

    def test_check_import_structure(self, temp_workspace):
        """Test import structure check."""
        cq = CodeQualityMetrics(temp_workspace)
        metric = cq.check_import_structure()
        assert metric.name == "import_structure"
        assert metric.value is not None
        assert metric.unit == "%"

    def test_count_docstrings(self, temp_workspace):
        """Test docstring count."""
        cq = CodeQualityMetrics(temp_workspace)
        metric = cq.count_docstrings()
        assert metric.name == "docstring_coverage"
        assert metric.value is not None
        assert metric.unit == "%"

    def test_check_type_hints(self, temp_workspace):
        """Test type hints check."""
        cq = CodeQualityMetrics(temp_workspace)
        metric = cq.check_type_hints()
        assert metric.name == "type_hint_coverage"
        assert metric.value is not None
        assert metric.unit == "%"

    def test_collect_all(self, temp_workspace):
        """Test collecting all code quality metrics."""
        cq = CodeQualityMetrics(temp_workspace)
        metrics = cq.collect_all()
        assert len(metrics) > 0
        names = [m.name for m in metrics]
        assert "total_files" in names
        assert "python_files" in names
        assert "lines_of_code" in names


class TestTestMetrics:
    """Tests for TestMetrics."""

    def test_count_tests(self, temp_workspace):
        """Test counting tests."""
        tm = TestMetrics(temp_workspace)
        metric = tm.count_tests()
        assert metric.name == "total_tests"
        assert metric.value > 0
        assert metric.unit == "tests"

    @patch("subprocess.run")
    def test_run_tests(self, mock_run):
        """Test running tests returns pass rate metric (mocked - calls pytest subprocess)."""
        mock_run.return_value = Mock(stdout="10 passed 2 failed 3 skipped", stderr="", returncode=0)
        tm = TestMetrics()
        metric = tm.run_tests()
        assert metric.name == "test_pass_rate"
        assert metric.value >= 0
        assert metric.unit == "%"

    @patch("subprocess.run")
    def test_test_coverage(self, mock_run):
        """Test coverage metric (mocked - calls pytest with coverage subprocess)."""
        mock_run.return_value = Mock(stdout="TOTAL    85%", stderr="", returncode=0)
        tm = TestMetrics()
        metric = tm.test_coverage()
        assert metric.name == "test_coverage"
        assert metric.value is not None
        assert metric.unit == "%"

    @patch("subprocess.run")
    def test_count_skipped_tests(self, mock_run):
        """Test counting skipped tests (mocked - calls pytest subprocess)."""
        mock_run.return_value = Mock(stdout="5 skipped", stderr="", returncode=0)
        tm = TestMetrics()
        metric = tm.count_skipped_tests()
        assert metric.name == "skipped_tests"
        assert metric.value >= 0
        assert metric.unit == "tests"

    def test_collect_all(self, temp_workspace, mock_expensive_operations):
        """Test collecting all test metrics."""
        tm = TestMetrics(temp_workspace)
        metrics = tm.collect_all()
        assert len(metrics) > 0
        names = [m.name for m in metrics]
        assert "total_tests" in names


class TestPerformanceMetrics:
    """Tests for PerformanceMetrics."""

    @patch("app.core.project_index.ProjectIndex")
    @patch("app.core.symbol_index.SymbolIndex")
    def test_indexing_speed(self, mock_symbol_index, mock_project_index, mock_expensive_operations):
        """Test measuring indexing speed (mocked - builds actual indexes)."""
        mock_pi = Mock()
        mock_pi.build.return_value = None
        mock_project_index.return_value = mock_pi

        mock_si = Mock()
        mock_si.build.return_value = None
        mock_symbol_index.return_value = mock_si

        pm = PerformanceMetrics()
        metric = pm.indexing_speed()
        assert metric.name == "indexing_speed"
        assert metric.unit == "seconds"
        assert metric.value is not None

    @patch("app.core.llm.LLM")
    def test_llm_response_time(self, mock_llm, mock_expensive_operations):
        """Test LLM response time (mocked - calls actual LLM)."""
        mock_llm_instance = Mock()
        mock_llm_instance.ask.return_value = "4"
        mock_llm.return_value = mock_llm_instance

        pm = PerformanceMetrics()
        metric = pm.llm_response_time()
        assert metric.name == "llm_response_time"
        assert metric.unit == "seconds"
        assert metric.value is not None

    def test_collect_all(self, temp_workspace, mock_expensive_operations):
        """Test collecting all performance metrics."""
        pm = PerformanceMetrics(temp_workspace)
        metrics = pm.collect_all()
        assert len(metrics) > 0
        names = [m.name for m in metrics]
        assert "indexing_speed" in names


class TestSystemMetrics:
    """Tests for SystemMetrics."""

    def test_cpu_usage(self, mock_expensive_operations):
        """Test getting CPU usage (mocked - uses psutil)."""
        sm = SystemMetrics()
        metric = sm.cpu_usage()
        assert metric.name == "cpu_usage"
        assert metric.unit == "%"
        if metric.value is not None:
            assert 0 <= metric.value <= 100

    def test_memory_usage(self, mock_expensive_operations):
        """Test getting memory usage (mocked - uses psutil)."""
        sm = SystemMetrics()
        metric = sm.memory_usage()
        assert metric.name == "memory_usage"
        assert metric.unit == "%"
        if metric.value is not None:
            assert 0 <= metric.value <= 100

    def test_disk_usage(self, mock_expensive_operations):
        """Test getting disk usage (mocked - uses psutil)."""
        sm = SystemMetrics()
        metric = sm.disk_usage()
        assert metric.name == "disk_usage"
        assert metric.unit == "%"

    def test_pycache_size(self, temp_workspace):
        """Test getting __pycache__ size."""
        sm = SystemMetrics(temp_workspace)
        metric = sm.pycache_size()
        assert metric.name == "pycache_size"
        assert metric.unit == "MB"
        assert metric.value >= 0

    def test_collect_all(self, temp_workspace, mock_expensive_operations):
        """Test collecting all system metrics."""
        sm = SystemMetrics(temp_workspace)
        metrics = sm.collect_all()
        assert len(metrics) > 0
        names = [m.name for m in metrics]
        assert "cpu_usage" in names
        assert "memory_usage" in names
        assert "disk_usage" in names


class TestAlert:
    """Tests for Alert dataclass."""

    def test_alert_creation(self):
        """Test creating an alert."""
        alert = Alert(
            metric_name="test_metric",
            current_value=90.0,
            threshold=80.0,
            status=HealthStatus.POOR,
            message="Test alert",
        )
        assert alert.metric_name == "test_metric"
        assert alert.current_value == 90.0
        assert alert.status == HealthStatus.POOR
        assert not alert.resolved

    def test_alert_to_dict(self):
        """Test converting alert to dictionary."""
        alert = Alert(
            metric_name="test",
            current_value=50.0,
            threshold=40.0,
            status=HealthStatus.CRITICAL,
            message="Test",
        )
        data = alert.to_dict()
        assert data["metric_name"] == "test"
        assert data["current_value"] == 50.0
        assert data["status"] == "critical"


class TestHealthMonitor:
    """Tests for HealthMonitor."""

    def test_monitor_initialization(self, temp_workspace):
        """Test monitor initialization."""
        monitor = HealthMonitor(temp_workspace)
        assert monitor.workspace.exists()
        assert monitor.check_interval == 300

    def test_collect_metrics(self, temp_workspace, mock_expensive_operations):
        """Test collecting metrics."""
        monitor = HealthMonitor(temp_workspace)
        metrics = monitor.collect_metrics()
        assert len(metrics) > 0

    def test_check_metrics(self, temp_workspace, mock_expensive_operations):
        """Test checking metrics and getting alerts."""
        monitor = HealthMonitor(temp_workspace)
        alerts = monitor.check_metrics()
        assert isinstance(alerts, dict)

    def test_get_summary(self, temp_workspace, mock_expensive_operations):
        """Test getting summary."""
        monitor = HealthMonitor(temp_workspace)
        monitor.check_metrics()
        summary = monitor.get_summary()
        assert "status" in summary
        assert "score" in summary
        assert "metrics_count" in summary
        assert "alerts_count" in summary

    def test_get_health_score(self, temp_workspace, mock_expensive_operations):
        """Test getting health score."""
        monitor = HealthMonitor(temp_workspace)
        monitor.check_metrics()
        score = monitor.get_health_score()
        assert 0 <= score <= 100

    def test_get_status(self, temp_workspace, mock_expensive_operations):
        """Test getting overall status."""
        monitor = HealthMonitor(temp_workspace)
        monitor.check_metrics()
        status = monitor.get_status()
        assert isinstance(status, HealthStatus)

    def test_set_threshold(self, temp_workspace):
        """Test setting custom threshold."""
        monitor = HealthMonitor(temp_workspace)
        monitor.set_threshold("test_metric", "excellent", 90.0)
        assert "test_metric" in monitor.custom_thresholds
        assert monitor.custom_thresholds["test_metric"]["excellent"] == 90.0


class TestLoggingAlertCallback:
    """Tests for LoggingAlertCallback."""

    def test_on_alert(self, capsys):
        """Test alert logging."""
        callback = LoggingAlertCallback()
        alert = Alert(
            metric_name="test",
            current_value=50.0,
            threshold=40.0,
            status=HealthStatus.CRITICAL,
            message="Test alert",
        )
        callback.on_alert(alert)
        captured = capsys.readouterr()
        assert "ALERT" in captured.out
        assert "CRITICAL" in captured.out

    def test_on_resolve(self, capsys):
        """Test resolution logging."""
        callback = LoggingAlertCallback()
        alert = Alert(
            metric_name="test",
            current_value=50.0,
            threshold=40.0,
            status=HealthStatus.CRITICAL,
            message="Test resolved",
        )
        callback.on_resolve(alert)
        captured = capsys.readouterr()
        assert "RESOLVED" in captured.out


class TestHealthReport:
    """Tests for HealthReport."""

    def test_report_generation(self, temp_workspace, mock_expensive_operations):
        """Test generating a report."""
        monitor = HealthMonitor(temp_workspace)
        report = HealthReport(monitor)
        data = report.generate(run_check=True)
        assert "metadata" in data
        assert "summary" in data
        assert "metrics" in data
        assert "alerts" in data
        assert "recommendations" in data

    def test_report_save_json(self, temp_workspace, mock_expensive_operations):
        """Test saving report as JSON."""
        monitor = HealthMonitor(temp_workspace)
        report = HealthReport(monitor)
        report.generate()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "report.json"
            report.save(str(path), format="json")
            assert path.exists()
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            assert "metadata" in loaded

    def test_report_save_markdown(self, temp_workspace, mock_expensive_operations):
        """Test saving report as Markdown."""
        monitor = HealthMonitor(temp_workspace)
        report = HealthReport(monitor)
        report.generate()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "report.md"
            report.save(str(path), format="markdown")
            assert path.exists()
            content = path.read_text()
            assert "# Freya Health Report" in content

    def test_report_save_text(self, temp_workspace, mock_expensive_operations):
        """Test saving report as plain text."""
        monitor = HealthMonitor(temp_workspace)
        report = HealthReport(monitor)
        report.generate()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "report.txt"
            report.save(str(path), format="text")
            assert path.exists()
            content = path.read_text()
            assert "FREYA HEALTH REPORT" in content

    def test_get_summary(self, temp_workspace, mock_expensive_operations):
        """Test getting report summary."""
        monitor = HealthMonitor(temp_workspace)
        report = HealthReport(monitor)
        summary = report.get_summary()
        assert "Freya Health Status" in summary
        assert "Overall:" in summary


class TestHealthDashboard:
    """Tests for HealthDashboard."""

    def test_dashboard_initialization(self, temp_workspace, mock_expensive_operations):
        """Test dashboard initialization."""
        dashboard = HealthDashboard(workspace=temp_workspace)
        assert dashboard.monitor is not None
        assert dashboard.report is not None

    def test_display_text(self, capsys, temp_workspace, mock_expensive_operations):
        """Test displaying dashboard as text."""
        dashboard = HealthDashboard(workspace=temp_workspace)
        dashboard.display(format="text")
        captured = capsys.readouterr()
        assert "FREYA HEALTH DASHBOARD" in captured.out

    def test_display_markdown(self, capsys, temp_workspace, mock_expensive_operations):
        """Test displaying dashboard as Markdown."""
        dashboard = HealthDashboard(workspace=temp_workspace)
        dashboard.display(format="markdown")
        captured = capsys.readouterr()
        assert "# Freya Health Report" in captured.out

    def test_display_json(self, capsys, temp_workspace, mock_expensive_operations):
        """Test displaying dashboard as JSON."""
        dashboard = HealthDashboard(workspace=temp_workspace)
        dashboard.display(format="json")
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert "metadata" in output

    def test_get_metric(self, temp_workspace, mock_expensive_operations):
        """Test getting a specific metric."""
        dashboard = HealthDashboard(workspace=temp_workspace)
        dashboard.refresh()
        metric = dashboard.get_metric("total_files")
        assert metric is not None
        assert metric.name == "total_files"

    def test_get_alerts(self, temp_workspace, mock_expensive_operations):
        """Test getting alerts."""
        dashboard = HealthDashboard(workspace=temp_workspace)
        alerts = dashboard.get_alerts()
        assert isinstance(alerts, list)

    def test_get_summary(self, temp_workspace, mock_expensive_operations):
        """Test getting summary."""
        dashboard = HealthDashboard(workspace=temp_workspace)
        summary = dashboard.get_summary()
        assert "status" in summary
        assert "score" in summary

    def test_refresh(self, temp_workspace, mock_expensive_operations):
        """Test refreshing dashboard data."""
        dashboard = HealthDashboard(workspace=temp_workspace)
        dashboard.refresh()
        assert dashboard.report.report_data is not None


class TestHealthIntegration:
    """Integration tests for the health system."""

    def test_full_health_check(self, temp_workspace, mock_expensive_operations):
        """Test a complete health check."""
        monitor = HealthMonitor(temp_workspace)
        monitor.check_metrics()

        # Check we have metrics
        metrics = monitor.get_metrics()
        assert len(metrics) > 0

        # Check summary
        summary = monitor.get_summary()
        assert summary["metrics_count"] > 0

        # Check report
        report = HealthReport(monitor)
        data = report.generate(run_check=False)
        assert "metadata" in data
        assert "metrics" in data

    def test_health_system_exports(self):
        """Test that the health module exports all expected classes."""
        from app.health import (
            HealthMonitor,
            CodeQualityMetrics,
            TestMetrics,
            PerformanceMetrics,
            SystemMetrics,
            HealthReport,
            HealthDashboard,
        )
        assert HealthMonitor is not None
        assert CodeQualityMetrics is not None
        assert TestMetrics is not None
        assert PerformanceMetrics is not None
        assert SystemMetrics is not None
        assert HealthReport is not None
        assert HealthDashboard is not None
