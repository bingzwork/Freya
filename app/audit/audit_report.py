"""Audit Report generation for Freya capability audits.

This module provides structured report generation and formatting
for capability audit results.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

from app.audit.capability_auditor import CapabilityAuditor
from app.audit.capability_registry import CapabilityRegistry, CapabilityStatus


class AuditReport:
    """Generates and manages audit reports for Freya capabilities.

    This class provides structured reporting of capability audit results,
    including summary statistics, detailed findings, and recommendations.
    """

    def __init__(
        self,
        registry: Optional[CapabilityRegistry] = None,
        auditor: Optional[CapabilityAuditor] = None,
        workspace: str = ".",
    ):
        """Initialize the audit report generator.

        Args:
            registry: The capability registry to report on.
            auditor: The capability auditor to use for findings.
            workspace: The root directory of the project.
        """
        self.registry = registry or CapabilityRegistry()
        self.auditor = auditor or CapabilityAuditor(self.registry, workspace)
        self.workspace = Path(workspace).resolve()
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.report_data: Optional[Dict[str, Any]] = None

    def generate(self) -> Dict[str, Any]:
        """Generate a comprehensive audit report."""
        registry_data = self.registry.to_dict()
        auditor_data = self.auditor.get_report()

        # Merge data
        self.report_data = {
            "metadata": {
                "timestamp": self.timestamp,
                "project": "Freya",
                "version": self._get_version(),
                "auditor": "CapabilityAuditSystem",
            },
            "summary": {
                **registry_data["summary"],
                **auditor_data["summary"],
            },
            "registry": registry_data,
            "audit": auditor_data,
            "duplicates": self.auditor.identify_duplicates(),
            "technical_debt": self.auditor.identify_technical_debt(),
            "dependencies": self.auditor.check_dependencies(),
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
        """Generate prioritized recommendations based on audit findings."""
        recommendations = []
        audit_data = self.auditor.get_report()

        # Critical: Fix not implemented capabilities that are high priority
        for cap_id in audit_data.get("capabilities_not_implemented", []):
            cap = self.registry.get_capability(cap_id)
            if cap and cap.priority.value in ["critical", "high"]:
                recommendations.append({
                    "priority": cap.priority.value,
                    "type": "missing_capability",
                    "capability_id": cap_id,
                    "title": f"Implement {cap.name}",
                    "description": cap.description,
                    "category": cap.category.value,
                    "effort": "medium",
                })

        # High: Fix partially implemented capabilities
        for cap_id in audit_data.get("capabilities_partially_implemented", []):
            cap = self.registry.get_capability(cap_id)
            findings = self.auditor.audit_capability(cap)
            if findings.issues:
                recommendations.append({
                    "priority": cap.priority.value,
                    "type": "partial_capability",
                    "capability_id": cap_id,
                    "title": f"Complete {cap.name}",
                    "description": f"Issues: {', '.join(findings.issues)}",
                    "category": cap.category.value,
                    "effort": "low",
                })

        # Medium: Clean up duplicates
        for dup in self.auditor.identify_duplicates():
            if dup.get("status") == "confirmed":
                recommendations.append({
                    "priority": "medium",
                    "type": "cleanup",
                    "title": f"Consolidate duplicate: {', '.join(dup['files'])}",
                    "description": dup["description"],
                    "recommendation": dup["recommendation"],
                    "effort": "low",
                })

        # Low: Clean up technical debt
        for debt in self.auditor.identify_technical_debt():
            recommendations.append({
                "priority": "low",
                "type": "technical_debt",
                "title": f"Clean up {debt['location']}",
                "description": debt["description"],
                "fix": debt["fix"],
                "effort": "very_low",
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
        lines.append("# Freya Capability Audit Report")
        lines.append("")
        lines.append(f"**Date:** {data['metadata']['timestamp'][:10]}")
        lines.append(f"**Version:** {data['metadata']['version']}")
        lines.append(f"**Auditor:** {data['metadata']['auditor']}")
        lines.append("")

        # Summary
        lines.append("## Executive Summary")
        lines.append("")
        summary = data["summary"]
        lines.append(f"- **Total Capabilities:** {summary['total_capabilities']}")
        lines.append(f"- **Fully Implemented:** {summary.get('fully_implemented', 0)}")
        lines.append(f"- **Partially Implemented:** {summary.get('partially_implemented', 0)}")
        lines.append(f"- **Not Implemented:** {summary.get('not_implemented', 0)}")
        lines.append(f"- **Total Issues:** {summary.get('total_issues', 0)}")
        lines.append(f"- **Total Warnings:** {summary.get('total_warnings', 0)}")
        lines.append("")

        # By Category
        lines.append("### Capabilities by Category")
        lines.append("")
        for category, count in summary.get("by_category", {}).items():
            lines.append(f"- **{category}:** {count}")
        lines.append("")

        # Recommendations
        lines.append("## Priority Recommendations")
        lines.append("")
        for rec in data.get("recommendations", []):
            priority_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}.get(rec["priority"], "⚪")
            lines.append(f"{priority_icon} **{rec['title']}** ({rec['priority']})")
            if "description" in rec:
                lines.append(f"  - {rec['description']}")
            if "recommendation" in rec:
                lines.append(f"  - *{rec['recommendation']}*")
            if "effort" in rec:
                lines.append(f"  - Effort: {rec['effort']}")
            lines.append("")

        # Duplicates
        duplicates = data.get("duplicates", [])
        if duplicates:
            lines.append("## Duplicate Implementations")
            lines.append("")
            for dup in duplicates:
                lines.append(f"- **Files:** {', '.join(dup['files'])}")
                lines.append(f"  - {dup['description']}")
                lines.append(f"  - {dup['recommendation']}")
                lines.append("")

        # Technical Debt
        debt = data.get("technical_debt", [])
        if debt:
            lines.append("## Technical Debt")
            lines.append("")
            for item in debt:
                lines.append(f"- **{item['location']}:** {item['description']}")
                lines.append(f"  - Fix: {item['fix']}")
                lines.append("")

        return "\n".join(lines)

    def _format_text(self) -> str:
        """Format the report as plain text."""
        if self.report_data is None:
            self.generate()

        data = self.report_data
        lines = []

        lines.append("=" * 60)
        lines.append("FREYA CAPABILITY AUDIT REPORT")
        lines.append("=" * 60)
        lines.append("")
        lines.append(f"Date: {data['metadata']['timestamp'][:10]}")
        lines.append(f"Version: {data['metadata']['version']}")
        lines.append("")

        lines.append("-" * 60)
        lines.append("EXECUTIVE SUMMARY")
        lines.append("-" * 60)
        summary = data["summary"]
        lines.append(f"Total Capabilities: {summary['total_capabilities']}")
        lines.append(f"Fully Implemented: {summary.get('fully_implemented', 0)}")
        lines.append(f"Partially Implemented: {summary.get('partially_implemented', 0)}")
        lines.append(f"Not Implemented: {summary.get('not_implemented', 0)}")
        lines.append("")

        return "\n".join(lines)

    def getsummary(self) -> str:
        """Get a brief summary of the audit results."""
        if self.report_data is None:
            self.generate()

        data = self.report_data
        summary = data["summary"]

        lines = [
            "Freya Capability Audit Summary",
            "=" * 40,
            f"Total: {summary['total_capabilities']} capabilities",
            f"  Fully Implemented: {summary.get('fully_implemented', 0)}",
            f"  Partially Implemented: {summary.get('partially_implemented', 0)}",
            f"  Not Implemented: {summary.get('not_implemented', 0)}",
            f"Issues: {summary.get('total_issues', 0)}",
            f"Warnings: {summary.get('total_warnings', 0)}",
        ]

        return "\n".join(lines)

    def get_capabilities_by_status(self) -> Dict[str, List[str]]:
        """Get lists of capability IDs grouped by status."""
        if self.report_data is None:
            self.generate()

        data = self.report_data
        return {
            "fully_implemented": data["audit"].get("capabilities_fully_implemented", []),
            "partially_implemented": data["audit"].get("capabilities_partially_implemented", []),
            "not_implemented": data["audit"].get("capabilities_not_implemented", []),
        }
