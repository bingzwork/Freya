"""Health Dashboard for Freya.

This module provides a terminal-based dashboard for viewing
project health metrics in real-time.
"""

from typing import Dict, List, Any, Optional
from pathlib import Path

from app.health.health_monitor import HealthMonitor, HealthStatus, Alert
from app.health.health_metrics import Metric
from app.health.health_report import HealthReport


class HealthDashboard:
    """Terminal-based health dashboard.

    This class provides a simple terminal interface for viewing
    and interacting with project health metrics.
    """

    def __init__(
        self,
        monitor: Optional[HealthMonitor] = None,
        workspace: str = ".",
    ):
        """Initialize the health dashboard.

        Args:
            monitor: The health monitor to display data from.
            workspace: The project workspace directory.
        """
        self.monitor = monitor or HealthMonitor(workspace)
        self.workspace = Path(workspace).resolve()
        self.report = HealthReport(self.monitor, workspace)

    def display(self, format: str = "text") -> None:
        """Display the health dashboard.

        Args:
            format: Output format ("text", "markdown", "json").
        """
        self.report.generate()

        if format == "json":
            import json
            print(json.dumps(self.report.report_data, indent=2))
        elif format == "markdown":
            print(self.report._format_markdown())
        else:
            self._display_text()

    def _display_text(self) -> None:
        """Display the dashboard as formatted text."""
        self.report.generate()

        data = self.report.report_data
        status = data["status"]
        summary = data["summary"]
        metrics = data["metrics"]

        # Header
        self._print_header()

        # Status Overview
        self._print_status(status)

        # Summary
        self._print_summary(summary)

        # Metrics by Category
        self._print_metrics(metrics)

        # Alerts
        alerts = self.monitor.get_alerts()
        if alerts:
            self._print_alerts(alerts)

        # Recommendations
        recommendations = data.get("recommendations", [])
        if recommendations:
            self._print_recommendations(recommendations)

    def _print_header(self) -> None:
        """Print the dashboard header."""
        print("\n" + "=" * 60)
        print("FREYA HEALTH DASHBOARD")
        print("=" * 60)
        print(f"Workspace: {self.workspace}")
        print(f"Timestamp: {self.report.timestamp[:19]}")
        print()

    def _print_status(self, status: Dict[str, Any]) -> None:
        """Print the overall status."""
        status_colors = {
            "excellent": "\033[92m",  # Green
            "good": "\033[93m",      # Yellow
            "fair": "\033[93m",       # Yellow
            "poor": "\033[91m",       # Red
            "critical": "\033[91m",    # Red
            "unknown": "\033[90m",    # Gray
        }
        reset_color = "\033[0m"

        color = status_colors.get(status["overall"], reset_color)
        print("-" * 60)
        print("OVERALL HEALTH STATUS")
        print("-" * 60)
        print(f"Status: {color}{status['overall'].upper()}{reset_color}")
        print(f"Score: {status['score']:.1f}/100")
        print()

    def _print_summary(self, summary: Dict[str, Any]) -> None:
        """Print the summary statistics."""
        print("-" * 60)
        print("SUMMARY")
        print("-" * 60)
        print(f"Total Metrics: {summary['metrics_count']}")
        print(f"Active Alerts: {summary['alerts_count']}")
        print()

    def _print_metrics(self, metrics: Dict[str, Dict[str, Any]]) -> None:
        """Print metrics grouped by category."""
        print("-" * 60)
        print("METRICS BY CATEGORY")
        print("-" * 60)

        categories: Dict[str, List[Dict]] = {}
        for name, metric in metrics.items():
            category = metric["category"]
            if category not in categories:
                categories[category] = []
            categories[category].append((name, metric))

        for category, category_metrics in sorted(categories.items()):
            print(f"\n{category.replace('_', ' ').title()}:")
            print("-" * 40)
            for name, metric in sorted(category_metrics, key=lambda x: x[0]):
                value = f"{metric['value']}{metric.get('unit', '')}" if metric.get('value') is not None else "N/A"
                status = metric["status"]
                print(f"  {name:30} {value:15} [{status}]")

        print()

    def _print_alerts(self, alerts: List[Alert]) -> None:
        """Print active alerts."""
        print("-" * 60)
        print("ACTIVE ALERTS")
        print("-" * 60)
        for alert in alerts:
            print(f"  [{alert.status.value.upper()}] {alert.metric_name}: {alert.message}")
        print()

    def _print_recommendations(self, recommendations: List[Dict[str, Any]]) -> None:
        """Print recommendations."""
        print("-" * 60)
        print("RECOMMENDATIONS")
        print("-" * 60)
        for rec in recommendations:
            print(f"  [{rec['priority'].upper()}] {rec['title']}")
            print(f"    -> {rec['action']}")
        print()

    def refresh(self) -> None:
        """Refresh the dashboard data."""
        self.monitor.check_metrics()
        self.report.generate()

    def watch(self, interval: int = 10, iterations: Optional[int] = None) -> None:
        """Watch health metrics in real-time.

        Args:
            interval: Seconds between refreshes.
            iterations: Number of iterations to run (None for infinite).
        """
        import time

        print(f"\nStarting health watch... (Ctrl+C to stop)")
        print(f"Refresh interval: {interval} seconds")
        print()

        count = 0
        try:
            while iterations is None or count < iterations:
                count += 1
                self.refresh()
                # Clear screen for better watch experience
                if count > 1:
                    print("\033[2J\033[H", end="")  # Clear screen
                self.display(format="text")
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\nWatch mode stopped.")

    def get_metric(self, name: str) -> Optional[Metric]:
        """Get a specific metric by name."""
        metrics = self.monitor.get_metrics()
        return metrics.get(name)

    def get_alerts(self) -> List[Alert]:
        """Get all active alerts."""
        return self.monitor.get_alerts()

    def get_summary(self) -> Dict[str, Any]:
        """Get the health summary."""
        return self.monitor.get_summary()
