"""Diagnostic Report generation for Freya.

This module provides structured report generation for diagnostic results.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

from app.diagnostics.issue import Issue, IssueSeverity, IssueType, IssueCollection
from app.diagnostics.diagnostic_engine import DiagnosticEngine


class DiagnosticReport:
    """Generates diagnostic reports for the Freya project.

    This class provides structured reporting of diagnostic results,
    including summary statistics, detailed issues, and recommendations.
    """

    def __init__(
        self,
        engine: Optional[DiagnosticEngine] = None,
        workspace: str = ".",
    ):
        """Initialize the diagnostic report generator.

        Args:
            engine: The diagnostic engine to generate reports from.
            workspace: The project workspace directory.
        """
        self.engine = engine or DiagnosticEngine(workspace)
        self.workspace = Path(workspace).resolve()
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.report_data: Optional[Dict[str, Any]] = None

    def generate(self, run_diagnostics: bool = True) -> Dict[str, Any]:
        """Generate a comprehensive diagnostic report.

        Args:
            run_diagnostics: Whether to run diagnostics before generating.
        """
        if run_diagnostics:
            self.engine.run()

        summary = self.engine.get_summary()
        issues = self.engine.get_issues()

        self.report_data = {
            "metadata": {
                "timestamp": self.timestamp,
                "project": "Freya",
                "version": self._get_version(),
                "workspace": str(self.workspace),
                "duration_seconds": summary["duration_seconds"],
            },
            "summary": {
                "total_issues": summary["total_issues"],
                "by_severity": summary["by_severity"],
                "by_type": summary["by_type"],
            },
            "issues": [i.to_dict() for i in issues.issues],
            "worst_issues": [i.to_dict() for i in self.engine.get_worst_issues(10)],
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

    def _generate_recommendations(self) -> List[Dict[str, Any]]:
        """Generate prioritized recommendations based on diagnostic findings."""
        recommendations = []
        issues = self.engine.get_issues()

        # Critical issues first
        critical_issues = issues.filter_by_severity(IssueSeverity.CRITICAL)
        for issue in critical_issues:
            recommendations.append({
                "priority": "critical",
                "type": issue.issue_type.value,
                "title": f"Fix: {issue.title}",
                "description": issue.description,
                "location": issue.location,
                "action": issue.fix_suggestion or "Investigate and fix immediately",
            })

        # Error issues
        error_issues = issues.filter_by_severity(IssueSeverity.ERROR)
        for issue in error_issues:
            recommendations.append({
                "priority": "high",
                "type": issue.issue_type.value,
                "title": f"Fix: {issue.title}",
                "description": issue.description,
                "location": issue.location,
                "action": issue.fix_suggestion or "Investigate and fix",
            })

        # Warning issues
        warning_issues = issues.filter_by_severity(IssueSeverity.WARNING)
        for issue in warning_issues:
            recommendations.append({
                "priority": "medium",
                "type": issue.issue_type.value,
                "title": f"Address: {issue.title}",
                "description": issue.description,
                "location": issue.location,
                "action": issue.fix_suggestion or "Review and address",
            })

        # Info issues (group by type)
        info_by_type: Dict[str, List[Issue]] = {}
        info_issues = issues.filter_by_severity(IssueSeverity.INFO)
        for issue in info_issues:
            if issue.issue_type.value not in info_by_type:
                info_by_type[issue.issue_type.value] = []
            info_by_type[issue.issue_type.value].append(issue)

        for issue_type, type_issues in info_by_type.items():
            if len(type_issues) > 3:
                recommendations.append({
                    "priority": "low",
                    "type": "maintenance",
                    "title": f"Address {len(type_issues)} {issue_type} issues",
                    "description": f"There are {len(type_issues)} {issue_type} issues to review",
                    "action": "Review and address these issues",
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
        lines.append("# Freya Diagnostic Report")
        lines.append("")
        lines.append(f"**Date:** {data['metadata']['timestamp'][:10]}")
        lines.append(f"**Version:** {data['metadata']['version']}")
        lines.append(f"**Duration:** {data['metadata']['duration_seconds']:.2f}s")
        lines.append("")

        # Summary
        lines.append("## Summary")
        lines.append("")
        summary = data["summary"]
        lines.append(f"- **Total Issues:** {summary['total_issues']}")
        lines.append("")

        # By Severity
        lines.append("### By Severity")
        lines.append("")
        for severity, count in summary['by_severity'].items():
            if count > 0:
                lines.append(f"- **{severity.upper()}:** {count}")
        lines.append("")

        # By Type
        lines.append("### By Type")
        lines.append("")
        for issue_type, count in summary['by_type'].items():
            if count > 0:
                lines.append(f"- **{issue_type.upper()}:** {count}")
        lines.append("")

        # Worst Issues
        worst = data.get("worst_issues", [])
        if worst:
            lines.append("## Top Issues")
            lines.append("")
            for issue in worst:
                severity = issue['severity']
                severityIcon = {"critical": "CRITICAL", "error": "ERROR", "warning": "WARNING", "info": "INFO"}.get(severity, "?")
                lines.append(f"- **[{severityIcon}] {issue['title']}**")
                lines.append(f"  - Type: {issue['type']}")
                lines.append(f"  - Location: {issue['location']}")
                if issue.get('fix_suggestion'):
                    lines.append(f"  - Suggestion: {issue['fix_suggestion']}")
                lines.append("")

        # Recommendations
        recommendations = data.get("recommendations", [])
        if recommendations:
            lines.append("## Recommendations")
            lines.append("")
            for rec in recommendations:
                priority_icon = {"critical": "CRITICAL", "high": "HIGH", "medium": "MEDIUM", "low": "LOW"}.get(rec["priority"], "?")
                lines.append(f"- **[{priority_icon}] {rec['title']}**")
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
        lines.append("FREYA DIAGNOSTIC REPORT")
        lines.append("=" * 60)
        lines.append("")
        lines.append(f"Date: {data['metadata']['timestamp'][:10]}")
        lines.append(f"Version: {data['metadata']['version']}")
        lines.append(f"Duration: {data['metadata']['duration_seconds']:.2f}s")
        lines.append("")

        lines.append("-" * 60)
        lines.append("SUMMARY")
        lines.append("-" * 60)
        summary = data["summary"]
        lines.append(f"Total Issues: {summary['total_issues']}")
        lines.append("")

        for severity, count in summary['by_severity'].items():
            if count > 0:
                lines.append(f"  {severity.upper()}: {count}")

        lines.append("")

        # Issues
        lines.append("-" * 60)
        lines.append("TOP ISSUES")
        lines.append("-" * 60)
        for issue in data.get("worst_issues", []):
            lines.append(f"[{issue['severity'].upper()}] {issue['title']} at {issue['location']}")

        return "\n".join(lines)

    def get_summary(self) -> str:
        """Get a brief summary of the diagnostic results."""
        if self.report_data is None:
            self.generate()

        data = self.report_data
        summary = data["summary"]

        lines = [
            "Freya Diagnostic Summary",
            "=" * 40,
            f"Total Issues: {summary['total_issues']}",
        ]
        for severity, count in summary['by_severity'].items():
            if count > 0:
                lines.append(f"  {severity.upper()}: {count}")

        return "\n".join(lines)

    def get_issues_by_file(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get issues grouped by file."""
        if self.report_data is None:
            self.generate()

        issues_by_file: Dict[str, List[Dict[str, Any]]] = {}
        for issue in self.report_data.get("issues", []):
            file_path = issue.get("file_path", "unknown")
            if file_path not in issues_by_file:
                issues_by_file[file_path] = []
            issues_by_file[file_path].append(issue)

        return issues_by_file
