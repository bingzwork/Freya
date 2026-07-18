"""Tests for the Project Health Dashboard system."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

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
            value=35.0,
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

    def test_count_files(self):
        """Test counting files."""
        cq = CodeQualityMetrics()
        metric = cq.count_files()
        assert metric.name == "total_files"
        assert metric.value > 0
        assert metric.unit == "files"

    def test_count_python_files(self):
        """Test counting Python files."""
        cq = CodeQualityMetrics()
        metric = cq.count_python_files()
        assert metric.name == "python_files"
        assert metric.value > 0
        assert metric.unit == "files"

    def test_count_lines_of_code(self):
        """Test counting lines of code."""
        cq = CodeQualityMetrics()
        metric = cq.count_lines_of_code()
        assert metric.name == "lines_of_code"
        assert metric.value > 0
        assert metric.unit == "lines"

    def test_collect_all(self):
        """Test collecting all code quality metrics."""
        cq = CodeQualityMetrics()
        metrics = cq.collect_all()
        assert len(metrics) > 0
        names = [m.name for m in metrics]
        assert "total_files" in names
        assert "python_files" in names
        assert "lines_of_code" in names


class TestTestMetrics:
    """Tests for TestMetrics."""

    def test_count_tests(self):
        """Test counting tests."""
        tm = TestMetrics()
        metric = tm.count_tests()
        assert metric.name == "total_tests"
        assert metric.value > 0
        assert metric.unit == "tests"

    def test_collect_all(self):
        """Test collecting all test metrics."""
        tm = TestMetrics()
        metrics = tm.collect_all()
        assert len(metrics) > 0
        names = [m.name for m in metrics]
        assert "total_tests" in names


class TestPerformanceMetrics:
    """Tests for PerformanceMetrics."""

    def test_indexing_speed(self):
        """Test measuring indexing speed."""
        pm = PerformanceMetrics()
        metric = pm.indexing_speed()
        assert metric.name == "indexing_speed"
        assert metric.unit == "seconds"

    def test_collect_all(self):
        """Test collecting all performance metrics."""
        pm = PerformanceMetrics()
        metrics = pm.collect_all()
        assert len(metrics) > 0
        names = [m.name for m in metrics]
        assert "indexing_speed" in names


class TestSystemMetrics:
    """Tests for SystemMetrics."""

    def test_cpu_usage(self):
        """Test getting CPU usage."""
        sm = SystemMetrics()
        metric = sm.cpu_usage()
        assert metric.name == "cpu_usage"
        assert metric.unit == "%"
        if metric.value is not None:
            assert 0 <= metric.value <= 100

    def test_memory_usage(self):
        """Test getting memory usage."""
        sm = SystemMetrics()
        metric = sm.memory_usage()
        assert metric.name == "memory_usage"
        assert metric.unit == "%"
        if metric.value is not None:
            assert 0 <= metric.value <= 100

    def test_disk_usage(self):
        """Test getting disk usage."""
        sm = SystemMetrics()
        metric = sm.disk_usage()
        assert metric.name == "disk_usage"
        assert metric.unit == "%"

    def test_pycache_size(self):
        """Test getting __pycache__ size."""
        sm = SystemMetrics()
        metric = sm.pycache_size()
        assert metric.name == "pycache_size"
        assert metric.unit == "MB"
        assert metric.value >= 0

    def test_collect_all(self):
        """Test collecting all system metrics."""
        sm = SystemMetrics()
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

    def test_monitor_initialization(self):
        """Test monitor initialization."""
        monitor = HealthMonitor()
        assert monitor.workspace.exists()
        assert monitor.check_interval == 300

    def test_collect_metrics(self):
        """Test collecting metrics."""
        monitor = HealthMonitor()
        metrics = monitor.collect_metrics()
        assert len(metrics) > 0

    def test_check_metrics(self):
        """Test checking metrics and getting alerts."""
        monitor = HealthMonitor()
        alerts = monitor.check_metrics()
        assert isinstance(alerts, dict)

    def test_get_summary(self):
        """Test getting summary."""
        monitor = HealthMonitor()
        monitor.check_metrics()
        summary = monitor.get_summary()
        assert "status" in summary
        assert "score" in summary
        assert "metrics_count" in summary
        assert "alerts_count" in summary

    def test_get_health_score(self):
        """Test getting health score."""
        monitor = HealthMonitor()
        monitor.check_metrics()
        score = monitor.get_health_score()
        assert 0 <= score <= 100

    def test_get_status(self):
        """Test getting overall status."""
        monitor = HealthMonitor()
        monitor.check_metrics()
        status = monitor.get_status()
        assert isinstance(status, HealthStatus)

    def test_set_threshold(self):
        """Test setting custom threshold."""
        monitor = HealthMonitor()
        monitor.set_threshold("test_metric", "excellent", 90.0)
        assert "test_metric" in monitor.custom_thresholds
        assert monitor.custom_thresholds["test_metric"]["excellent"] == 90.0

    def test_identify_duplicates(self):
        """Test identifying duplicates."""
        monitor = HealthMonitor()
        duplicates = monitor.identify_duplicates()
        assert isinstance(duplicates, dict)

    def test_identify_technical_debt(self):
        """Test identifying technical debt."""
        monitor = HealthMonitor()
        debt = monitor.identify_technical_debt()
        assert isinstance(debt, dict)


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

    def test_report_generation(self):
        """Test generating a report."""
        monitor = HealthMonitor()
        report = HealthReport(monitor)
        data = report.generate(run_check=True)
        assert "metadata" in data
        assert "summary" in data
        assert "metrics" in data
        assert "alerts" in data
        assert "recommendations" in data

    def test_report_save_json(self):
        """Test saving report as JSON."""
        monitor = HealthMonitor()
        report = HealthReport(monitor)
        report.generate()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "report.json"
            report.save(str(path), format="json")
            assert path.exists()
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            assert "metadata" in loaded

    def test_report_save_markdown(self):
        """Test saving report as Markdown."""
        monitor = HealthMonitor()
        report = HealthReport(monitor)
        report.generate()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "report.md"
            report.save(str(path), format="markdown")
            assert path.exists()
            content = path.read_text()
            assert "# Freya Health Report" in content

    def test_report_save_text(self):
        """Test saving report as plain text."""
        monitor = HealthMonitor()
        report = HealthReport(monitor)
        report.generate()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "report.txt"
            report.save(str(path), format="text")
            assert path.exists()
            content = path.read_text()
            assert "FREYA HEALTH REPORT" in content

    def test_get_summary(self):
        """Test getting report summary."""
        monitor = HealthMonitor()
        report = HealthReport(monitor)
        summary = report.get_summary()
        assert "Freya Health Status" in summary
        assert "Overall:" in summary


class TestHealthDashboard:
    """Tests for HealthDashboard."""

    def test_dashboard_initialization(self):
        """Test dashboard initialization."""
        dashboard = HealthDashboard()
        assert dashboard.monitor is not None
        assert dashboard.report is not None

    def test_display_text(self, capsys):
        """Test displaying dashboard as text."""
        dashboard = HealthDashboard()
        dashboard.display(format="text")
        captured = capsys.readouterr()
        assert "FREYA HEALTH DASHBOARD" in captured.out

    def test_display_markdown(self, capsys):
        """Test displaying dashboard as Markdown."""
        dashboard = HealthDashboard()
        dashboard.display(format="markdown")
        captured = capsys.readouterr()
        assert "# Freya Health Report" in captured.out

    def test_display_json(self, capsys):
        """Test displaying dashboard as JSON."""
        dashboard = HealthDashboard()
        dashboard.display(format="json")
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert "metadata" in output

    def test_get_metric(self):
        """Test getting a specific metric."""
        dashboard = HealthDashboard()
        dashboard.refresh()
        metric = dashboard.get_metric("total_files")
        assert metric is not None
        assert metric.name == "total_files"

    def test_get_alerts(self):
        """Test getting alerts."""
        dashboard = HealthDashboard()
        alerts = dashboard.get_alerts()
        assert isinstance(alerts, list)

    def test_get_summary(self):
        """Test getting summary."""
        dashboard = HealthDashboard()
        summary = dashboard.get_summary()
        assert "status" in summary
        assert "score" in summary

    def test_refresh(self):
        """Test refreshing dashboard data."""
        dashboard = HealthDashboard()
        dashboard.refresh()
        assert dashboard.report.report_data is not None


class TestHealthIntegration:
    """Integration tests for the health system."""

    def test_full_health_check(self):
        """Test a complete health check."""
        monitor = HealthMonitor()
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
