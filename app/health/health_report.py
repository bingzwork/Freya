"""Health Report generation for Freya.

This module provides structured report generation for health metrics.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

from app.health.health_monitor import HealthMonitor, HealthStatus, Alert
from app.health.health_metrics import Metric


class HealthReport:
    """Generates health reports for the Freya project.

    This class provides structured reporting of health metrics,
    including summary statistics, detailed metrics, and recommendations.
    """

    def __init__(
        self,
        monitor: Optional[HealthMonitor] = None,
        workspace: str = ".",
    ):
        """Initialize the health report generator.

        Args:
            monitor: The health monitor to generate reports from.
            workspace: The project workspace directory.
        """
        self.monitor = monitor or HealthMonitor(workspace)
        self.workspace = Path(workspace).resolve()
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.report_data: Optional[Dict[str, Any]] = None

    def generate(self, run_check: bool = True) -> Dict[str, Any]:
        """Generate a comprehensive health report.

        Args:
            run_check: Whether to run a fresh health check before generating.
        """
        if run_check:
            self.monitor.check_metrics()

        self.report_data = {
            "metadata": {
                "timestamp": self.timestamp,
                "project": "Freya",
                "version": self._get_version(),
                "workspace": str(self.workspace),
            },
            "summary": self.monitor.get_summary(),
            "status": {
                "overall": self.monitor.get_status().value,
                "score": round(self.monitor.get_health_score(), 2),
            },
            "metrics": self._format_metrics(),
            "alerts": self._format_alerts(),
            "history": self.monitor.get_history(limit=10),
            "recommendations": self._generate_recommendations(),
        }

        return self.report_data

    def _get_version(self) -> str:
        """Get the current project version."""
        try:
            pyproject_path = self.workspace / "pyproject.toml"
            if pyproject_path.exists():
                import tomllib
                with open(pyproject_path, "rb") as f:
                    data = tomllib.load(f)
                return data.get("project", {}).get("version", "unknown")
        except Exception:
            pass
        return "unknown"

    def _format_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Format metrics for the report."""
        metrics = self.monitor.get_metrics()
        formatted = {}
        for name, metric in metrics.items():
            formatted[name] = metric.to_dict()
            formatted[name]["status"] = metric.status.value
        return formatted

    def _format_alerts(self) -> List[Dict[str, Any]]:
        """Format alerts for the report."""
        alerts = self.monitor.get_alerts()
        return [alert.to_dict() for alert in alerts]

    def _generate_recommendations(self) -> List[Dict[str, Any]]:
        """Generate recommendations based on current metrics."""
        recommendations = []
        metrics = self.monitor.get_metrics()
        alerts = self.monitor.get_alerts()

        # Recommendations for alerts
        for alert in alerts:
            recommendations.append({
                "priority": self._alert_priority(alert),
                "type": "alert",
                "title": f"Address {alert.metric_name} issue",
                "description": alert.message,
                "action": self._get_alert_action(alert),
            })

        # Metric-specific recommendations
        for name, metric in metrics.items():
            if metric.status == HealthStatus.CRITICAL:
                recommendations.append({
                    "priority": "critical",
                    "type": "metric",
                    "title": f"Fix {name}",
                    "description": f"{name} is at critical level: {metric.value}{metric.unit}",
                    "action": "Investigate and resolve the underlying issue",
                })
            elif metric.status == HealthStatus.POOR:
                recommendations.append({
                    "priority": "high",
                    "type": "metric",
                    "title": f"Improve {name}",
                    "description": f"{name} is below acceptable level: {metric.value}{metric.unit}",
                    "action": "Review and improve the metric",
                })

        # Sort by priority
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        recommendations.sort(key=lambda r: priority_order.get(r["priority"], 4))

        return recommendations

    def _alert_priority(self, alert: Alert) -> str:
        """Get priority for an alert based on its status."""
        if alert.status == HealthStatus.CRITICAL:
            return "critical"
        elif alert.status == HealthStatus.POOR:
            return "high"
        else:
            return "medium"

    def _get_alert_action(self, alert: Alert) -> str:
        """Get suggested action for an alert."""
        actions = {
            "total_files": "Check why file count is low",
            "python_files": "Review Python file structure",
            "lines_of_code": "Review code volume",
            "pep8_compliance": "Run flake8 and fix violations",
            "docstring_coverage": "Add missing docstrings",
            "type_hint_coverage": "Add missing type hints",
            "total_tests": "Add more tests",
            "test_pass_rate": "Fix failing tests",
            "test_coverage": "Add tests for un-covered code",
            "indexing_speed": "Optimize indexing performance",
            "llm_response_time": "Check LLM performance",
            "cpu_usage": "Investigate high CPU usage",
            "memory_usage": "Investigate high memory usage",
            "disk_usage": "Clean up disk space",
        }
        return actions.get(alert.metric_name, "Investigate the issue")

    def save(self, path: str, format: str = "json") -> None:
        """Save the report to a file.

        Args:
            path: The file path to save to.
            format: The format of the report ("json", "markdown", "text").
        """
        path_obj = Path(path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)

        if self.report_data is None:
            self.generate()

        if format == "json":
            with open(path_obj, "w", encoding="utf-8") as f:
                json.dump(self.report_data, f, indent=2, ensure_ascii=False)
        elif format == "markdown":
            with open(path_obj, "w", encoding="utf-8") as f:
                f.write(self._format_markdown())
        elif format == "text":
            with open(path_obj, "w", encoding="utf-8") as f:
                f.write(self._format_text())
        else:
            raise ValueError(f"Unsupported format: {format}")

    def _format_markdown(self) -> str:
        """Format the report as Markdown."""
        if self.report_data is None:
            self.generate()

        data = self.report_data

        status_emoji = {
            "excellent": "🟢",
            "good": "🔵",
            "fair": "🟡",
            "poor": "🟠",
            "critical": "🔴",
            "unknown": "⚪",
        }

        lines = []

        # Header
        lines.append("# Freya Health Report")
        lines.append("")
        lines.append(f"**Date:** {data['metadata']['timestamp'][:10]}")
        lines.append(f"**Version:** {data['metadata']['version']}")
        lines.append(f"**Status:** {data['status']['overall'].upper()}")
        lines.append(f"**Score:** {data['status']['score']}/100")
        lines.append("")

        # Status Badge
        overall_status = data['status']['overall']
        status_label = overall_status.upper()
        lines.append(f"**Overall Health: {status_label}**")
        lines.append("")

        # Summary
        lines.append("## Summary")
        lines.append("")
        summary = data["summary"]
        lines.append(f"- **Metrics Collected:** {summary['metrics_count']}")
        lines.append(f"- **Active Alerts:** {summary['alerts_count']}")
        lines.append(f"- **Last Check:** {summary['timestamp'][:19]}")
        lines.append("")

        # Metrics by Category
        lines.append("## Metrics")
        lines.append("")
        metrics = data["metrics"]
        categories: Dict[str, List[Dict]] = {}
        for name, metric in metrics.items():
            category = metric["category"]
            if category not in categories:
                categories[category] = []
            categories[category].append((name, metric))

        for category, category_metrics in sorted(categories.items()):
            lines.append(f"### {category.replace('_', ' ').title()}")
            lines.append("")
            lines.append("| Metric | Value | Status |")
            lines.append("|--------|-------|--------|")
            for name, metric in sorted(category_metrics, key=lambda x: x[0]):
                status = metric["status"]
                emoji = status_emoji.get(status, "⚪")
                value = f"{metric['value']}{metric.get('unit', '')}" if metric.get('value') is not None else "N/A"
                lines.append(f"| {name} | {value} | {emoji} {status} |")
            lines.append("")

        # Alerts
        alerts = data.get("alerts", [])
        if alerts:
            lines.append("## Active Alerts")
            lines.append("")
            for alert in alerts:
                lines.append(f"- **{alert['metric_name']}:** {alert['message']}")
            lines.append("")

        # Recommendations
        recommendations = data.get("recommendations", [])
        if recommendations:
            lines.append("## Recommendations")
            lines.append("")
            for rec in recommendations:
                priority_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}.get(rec["priority"], "⚪")
                lines.append(f"{priority_icon} **{rec['title']}** ({rec['priority']})")
                lines.append(f"  - {rec['description']}")
                lines.append(f"  - *Action: {rec['action']}*")
                lines.append("")

        return "\n".join(lines)

    def _format_text(self) -> str:
        """Format the report as plain text."""
        if self.report_data is None:
            self.generate()

        data = self.report_data
        lines = []

        lines.append("=" * 60)
        lines.append("FREYA HEALTH REPORT")
        lines.append("=" * 60)
        lines.append("")
        lines.append(f"Date: {data['metadata']['timestamp'][:10]}")
        lines.append(f"Version: {data['metadata']['version']}")
        lines.append(f"Status: {data['status']['overall'].upper()}")
        lines.append(f"Score: {data['status']['score']}/100")
        lines.append("")

        lines.append("-" * 60)
        lines.append("SUMMARY")
        lines.append("-" * 60)
        summary = data["summary"]
        lines.append(f"Metrics: {summary['metrics_count']}")
        lines.append(f"Alerts: {summary['alerts_count']}")
        lines.append("")

        lines.append("-" * 60)
        lines.append("METRICS")
        lines.append("-" * 60)
        for name, metric in sorted(data["metrics"].items()):
            value = f"{metric['value']}{metric.get('unit', '')}" if metric.get('value') is not None else "N/A"
            lines.append(f"{name}: {value} ({metric['status']})")
        lines.append("")

        if data.get("alerts"):
            lines.append("-" * 60)
            lines.append("ALERTS")
            lines.append("-" * 60)
            for alert in data["alerts"]:
                lines.append(f"{alert['metric_name']}: {alert['message']}")
            lines.append("")

        return "\n".join(lines)

    def get_summary(self) -> str:
        """Get a brief summary of the health status."""
        if self.report_data is None:
            self.generate()

        data = self.report_data
        status = data["status"]
        summary = data["summary"]

        lines = [
            "Freya Health Status",
            "=" * 30,
            f"Overall: {status['overall'].upper()}",
            f"Score: {status['score']:.1f}/100",
            f"Metrics: {summary['metrics_count']}",
            f"Alerts: {summary['alerts_count']}",
        ]

        return "\n".join(lines)
