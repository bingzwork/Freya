"""Monitoring Report generation for Freya.

This module provides structured report generation for monitoring results.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

from app.monitoring.system_monitor import (
    SystemMonitor,
    ResourceMetrics,
    SystemHealthStatus,
    MonitorConfig,
)
from app.monitoring.alert_manager import (
    AlertManager,
    SystemAlert,
    AlertSeverity,
    AlertStatus,
)
from app.monitoring.process_monitor import ProcessMonitor, ProcessInfo


class MonitoringReport:
    """Generates monitoring reports for the Freya project.

    This class provides structured reporting of monitoring results,
    including system metrics, alerts, and process information.
    """

    def __init__(
        self,
        system_monitor: Optional[SystemMonitor] = None,
        alert_manager: Optional[AlertManager] = None,
        process_monitor: Optional[ProcessMonitor] = None,
        workspace: str = ".",
    ):
        """Initialize the monitoring report generator.

        Args:
            system_monitor: The system monitor to generate reports from.
            alert_manager: The alert manager to get alerts from.
            process_monitor: The process monitor to get process info from.
            workspace: The project workspace directory.
        """
        self.system_monitor = system_monitor or SystemMonitor()
        self.alert_manager = alert_manager or AlertManager()
        self.process_monitor = process_monitor or ProcessMonitor()
        self.workspace = Path(workspace).resolve()
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.report_data: Optional[Dict[str, Any]] = None

    def generate(self, run_monitoring: bool = True) -> Dict[str, Any]:
        """Generate a comprehensive monitoring report.

        Args:
            run_monitoring: Whether to run monitoring before generating.
        """
        if run_monitoring:
            self.system_monitor.collect_metrics()
            self.process_monitor.update_tracked()

        metrics = self.system_monitor.get_current_metrics()
        health_status = self.system_monitor.get_health_status()
        summary = self.system_monitor.get_summary()
        alerts = self.alert_manager.get_active_alerts()
        alert_summary = self.alert_manager.get_summary()
        process_summary = self.process_monitor.get_summary()

        self.report_data = {
            "metadata": {
                "timestamp": self.timestamp,
                "project": "Freya",
                "version": self._get_version(),
                "workspace": str(self.workspace),
            },
            "system": {
                "status": health_status.value,
                "health_score": summary.get("health_score", 0),
                "summary": summary,
            },
            "metrics": metrics.to_dict() if metrics else {},
            "alerts": {
                "active": [a.to_dict() for a in alerts],
                "summary": alert_summary,
            },
            "processes": process_summary,
            "recommendations": self._generate_recommendations(summary, alerts),
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

    def _generate_recommendations(
        self,
        summary: Dict[str, Any],
        alerts: List[SystemAlert],
    ) -> List[Dict[str, Any]]:
        """Generate prioritized recommendations based on monitoring findings."""
        recommendations = []

        # Critical alerts first
        critical_alerts = [a for a in alerts if a.severity == AlertSeverity.CRITICAL]
        for alert in critical_alerts:
            recommendations.append({
                "priority": "critical",
                "title": f"Address: {alert.title}",
                "description": alert.description,
                "action": f"Investigate and resolve the {alert.metric_name} issue",
            })

        # High alerts
        high_alerts = [a for a in alerts if a.severity == AlertSeverity.HIGH]
        for alert in high_alerts:
            recommendations.append({
                "priority": "high",
                "title": f"Address: {alert.title}",
                "description": alert.description,
                "action": f"Investigate the {alert.metric_name} issue",
            })

        # Low health score
        health_score = summary.get("health_score", 100)
        if health_score < 60:
            recommendations.append({
                "priority": "high",
                "title": "Improve System Health",
                "description": f"System health score is {health_score:.1f}%",
                "action": "Investigate resource usage and optimize system performance",
            })

        # High CPU
        cpu_percent = summary.get("cpu_percent", 0)
        if cpu_percent > 80:
            recommendations.append({
                "priority": "medium",
                "title": "High CPU Usage",
                "description": f"CPU usage is at {cpu_percent:.1f}%",
                "action": "Identify and optimize CPU-intensive processes",
            })

        # High memory
        memory_percent = summary.get("memory_percent", 0)
        if memory_percent > 80:
            recommendations.append({
                "priority": "medium",
                "title": "High Memory Usage",
                "description": f"Memory usage is at {memory_percent:.1f}%",
                "action": "Identify memory leaks or optimize memory usage",
            })

        # High disk
        disk_percent = summary.get("disk_percent", 0)
        if disk_percent > 85:
            recommendations.append({
                "priority": "medium",
                "title": "High Disk Usage",
                "description": f"Disk usage is at {disk_percent:.1f}%",
                "action": "Clean up disk space or expand storage",
            })

        # Sort by priority
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        recommendations.sort(key=lambda r: priority_order.get(r["priority"], 4))

        return recommendations

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
        lines = []

        # Header
        lines.append("# Freya Monitoring Report")
        lines.append("")
        lines.append(f"**Date:** {data['metadata']['timestamp'][:10]}")
        lines.append(f"**Version:** {data['metadata']['version']}")
        lines.append(f"**Workspace:** {data['metadata']['workspace']}")
        lines.append("")

        # System Status
        lines.append("## System Status")
        lines.append("")
        system = data["system"]
        health_emoji = {
            "excellent": "EXCELLENT",
            "good": "GOOD",
            "warning": "WARNING",
            "critical": "CRITICAL",
            "unknown": "?",
        }.get(system["status"], "?")
        lines.append(f"**Status:** [{health_emoji}] {system['status'].upper()}")
        lines.append(f"**Health Score:** {system['health_score']:.1f}%")
        lines.append("")

        # Metrics
        lines.append("## Resource Metrics")
        lines.append("")
        metrics = data.get("metrics", {})

        # CPU
        cpu = metrics.get("cpu", {})
        lines.append("### CPU")
        lines.append(f"- Usage: {cpu.get('percent', 0):.1f}%")
        lines.append(f"- Cores: {cpu.get('count', 0)}")
        lines.append(f"- Frequency: {cpu.get('freq_mhz', 0):.1f} MHz")
        lines.append("")

        # Memory
        memory = metrics.get("memory", {})
        lines.append("### Memory")
        lines.append(f"- Total: {memory.get('total_gb', 0):.2f} GB")
        lines.append(f"- Used: {memory.get('used_gb', 0):.2f} GB")
        lines.append(f"- Free: {memory.get('free_gb', 0):.2f} GB")
        lines.append(f"- Usage: {memory.get('percent', 0):.1f}%")
        lines.append("")

        # Disk
        disk = metrics.get("disk", {})
        lines.append("### Disk")
        lines.append(f"- Total: {disk.get('total_gb', 0):.2f} GB")
        lines.append(f"- Used: {disk.get('used_gb', 0):.2f} GB")
        lines.append(f"- Free: {disk.get('free_gb', 0):.2f} GB")
        lines.append(f"- Usage: {disk.get('percent', 0):.1f}%")
        lines.append("")

        # Alerts
        alerts = data.get("alerts", {})
        active_alerts = alerts.get("active", [])
        if active_alerts:
            lines.append("## Active Alerts")
            lines.append("")
            for alert in active_alerts:
                severity = alert.get("severity", "unknown").upper()
                lines.append(f"- **[{severity}] {alert.get('title', 'Unknown')}**")
                lines.append(f"  - {alert.get('description', '')}")
                if alert.get('metric_name'):
                    lines.append(f"  - Metric: {alert['metric_name']}")
                    if alert.get('current_value') is not None:
                        lines.append(f"  - Value: {alert['current_value']}")
                lines.append("")

        # Recommendations
        recommendations = data.get("recommendations", [])
        if recommendations:
            lines.append("## Recommendations")
            lines.append("")
            for rec in recommendations:
                priority = rec.get("priority", "low").upper()
                lines.append(f"- **[{priority}] {rec.get('title', 'Unknown')}**")
                lines.append(f"  - {rec.get('description', '')}")
                lines.append(f"  - *Action: {rec.get('action', '')}*")
                lines.append("")

        return "\n".join(lines)

    def _format_text(self) -> str:
        """Format the report as plain text."""
        if self.report_data is None:
            self.generate()

        data = self.report_data
        lines = []

        lines.append("=" * 60)
        lines.append("FREYA MONITORING REPORT")
        lines.append("=" * 60)
        lines.append("")
        lines.append(f"Date: {data['metadata']['timestamp'][:10]}")
        lines.append(f"Version: {data['metadata']['version']}")
        lines.append(f"Workspace: {data['metadata']['workspace']}")
        lines.append("")

        lines.append("-" * 60)
        lines.append("SYSTEM STATUS")
        lines.append("-" * 60)
        system = data["system"]
        lines.append(f"Status: {system['status'].upper()}")
        lines.append(f"Health Score: {system['health_score']:.1f}%")
        lines.append("")

        lines.append("-" * 60)
        lines.append("RESOURCE METRICS")
        lines.append("-" * 60)
        metrics = data.get("metrics", {})
        cpu = metrics.get("cpu", {})
        memory = metrics.get("memory", {})
        disk = metrics.get("disk", {})
        lines.append(f"CPU: {cpu.get('percent', 0):.1f}% ({cpu.get('count', 0)} cores)")
        lines.append(f"Memory: {memory.get('used_gb', 0):.2f} GB / {memory.get('total_gb', 0):.2f} GB ({memory.get('percent', 0):.1f}%)")
        lines.append(f"Disk: {disk.get('used_gb', 0):.2f} GB / {disk.get('total_gb', 0):.2f} GB ({disk.get('percent', 0):.1f}%)")
        lines.append("")

        # Alerts
        alerts = data.get("alerts", {})
        active_alerts = alerts.get("active", [])
        if active_alerts:
            lines.append("-" * 60)
            lines.append("ACTIVE ALERTS")
            lines.append("-" * 60)
            for alert in active_alerts:
                severity = alert.get("severity", "unknown").upper()
                lines.append(f"[{severity}] {alert.get('title', 'Unknown')}")
                lines.append(f"  {alert.get('description', '')}")
            lines.append("")

        return "\n".join(lines)

    def get_summary(self) -> str:
        """Get a brief summary of the monitoring results."""
        if self.report_data is None:
            self.generate()

        data = self.report_data
        system = data["system"]
        alerts = data.get("alerts", {})

        lines = [
            "Freya Monitoring Summary",
            "=" * 40,
            f"Status: {system['status'].upper()}",
            f"Health Score: {system['health_score']:.1f}%",
            f"Active Alerts: {len(alerts.get('active', []))}",
        ]

        return "\n".join(lines)

    def get_metrics_history(self) -> Dict[str, Any]:
        """Get metrics history from the system monitor."""
        return {
            "metrics": [m.to_dict() for m in self.system_monitor.get_metrics_history()],
            "alerts": [a.to_dict() for a in self.alert_manager.get_history()],
        }
