"""Diagnostic Engine for running comprehensive code analysis.

This module provides the main diagnostic engine that coordinates
various analysis passes and collects results.
"""

import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable
import json

from app.diagnostics.issue import Issue, IssueSeverity, IssueType, IssueCollection
from app.diagnostics.code_analyzer import CodeAnalyzer
from app.core.events import Event, EventPriority, get_event_bus


@dataclass
class DiagnosticConfig:
    """Configuration for diagnostic analysis."""
    paths: List[str] = field(default_factory=list)
    include_patterns: List[str] = field(default_factory=lambda: ["**/*.py"])
    exclude_patterns: List[str] = field(default_factory=lambda: ["**/__pycache__/**", "**/.git/**", "**/.venv/**"])
    check_unused_imports: bool = True
    check_unreachable_code: bool = True
    check_empty_blocks: bool = True
    check_long_functions: bool = True
    check_complex_functions: bool = True
    check_missing_docstrings: bool = True
    check_missing_type_hints: bool = True
    check_bare_except: bool = True
    check_security: bool = True
    long_function_threshold: int = 100
    complex_function_threshold: int = 10


class DiagnosticEngine:
    """Main engine for running diagnostics on the codebase.

    This class coordinates various analysis passes and collects
    all diagnostic issues into a comprehensive report.
    """

    def __init__(self, workspace: str = ".", config: Optional[DiagnosticConfig] = None, event_bus=None):
        """Initialize the diagnostic engine.

        Args:
            workspace: The project workspace directory.
            config: Optional configuration for the diagnostic run.
            event_bus: Optional EventBus for emitting diagnostic events.
        """
        self.workspace = Path(workspace).resolve()
        self.config = config or DiagnosticConfig()
        self._issues: IssueCollection = IssueCollection()
        self._start_time: Optional[datetime] = None
        self._end_time: Optional[datetime] = None
        self._event_bus = event_bus or get_event_bus()
        self._failure_patterns: List[Dict[str, Any]] = []

    def record_failure_pattern(self, pattern: Dict[str, Any]) -> None:
        """Record and publish a bounded execution failure pattern."""
        normalized = {**pattern, "recorded_at": datetime.now(timezone.utc).isoformat()}
        self._failure_patterns.append(normalized)
        self._failure_patterns = self._failure_patterns[-100:]
        self._event_bus.emit(
            "diagnostics.execution_failure_pattern",
            normalized,
            source="DiagnosticEngine",
        )

    def run(self, paths: Optional[List[str]] = None) -> IssueCollection:
        """Run diagnostic analysis on specified paths.

        Args:
            paths: List of paths to analyze. If None, uses config.paths or workspace.
        """
        self._start_time = datetime.now(timezone.utc)
        self._issues = IssueCollection()

        if paths is None:
            paths = self.config.paths if self.config.paths else [str(self.workspace)]

        # Create the code analyzer
        analyzer = CodeAnalyzer(str(self.workspace))

        # Run analysis on all paths
        issues = analyzer.analyze(paths)
        self._issues = issues

        self._end_time = datetime.now(timezone.utc)

        # Emit diagnostic completed event
        self._emit_diagnostic_event()

        return self._issues

    def _emit_diagnostic_event(self) -> None:
        """Emit diagnostic results as an EventBus event for downstream consumers.

        Publication failures deliberately propagate so a completed diagnostic run cannot
        be mistaken for a successfully delivered diagnostic event.
        """
        summary = self.get_summary()
        event = Event(
            name="diagnostics.completed",
            data={
                "summary": summary,
                "issues": [i.to_dict() for i in self._issues.issues],
                "workspace": str(self.workspace),
            },
            source="DiagnosticEngine",
            priority=EventPriority.NORMAL,
        )
        self._event_bus.publish(event)

    def run_all_checks(self) -> IssueCollection:
        """Run all diagnostic checks."""
        return self.run()

    def get_issues(self) -> IssueCollection:
        """Get all collected issues."""
        return self._issues

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the diagnostic run."""
        duration = 0
        if self._start_time and self._end_time:
            duration = (self._end_time - self._start_time).total_seconds()

        return {
            "timestamp": self._start_time.isoformat() if self._start_time else None,
            "duration_seconds": duration,
            "total_issues": len(self._issues.issues),
            "by_severity": self._issues.count_by_severity(),
            "by_type": self._issues.count_by_type(),
        }

    def filter_issues(
        self,
        severity: Optional[IssueSeverity] = None,
        issue_type: Optional[IssueType] = None,
        file_path: Optional[str] = None,
        resolved: Optional[bool] = None,
    ) -> List[Issue]:
        """Filter issues by various criteria."""
        issues = self._issues.issues

        if severity:
            issues = [i for i in issues if i.severity == severity]
        if issue_type:
            issues = [i for i in issues if i.issue_type == issue_type]
        if file_path:
            issues = [i for i in issues if i.file_path == file_path]
        if resolved is not None:
            issues = [i for i in issues if i.resolved == resolved]

        return issues

    def get_worst_issues(self, limit: int = 10) -> List[Issue]:
        """Get the most severe unresolved issues."""
        unresolved = self._issues.filter_unresolved()
        sorted_issues = sorted(unresolved, reverse=True)
        return sorted_issues[:limit]

    def export_json(self, path: str) -> None:
        """Export diagnostic results to JSON file."""
        data = {
            "metadata": {
                "timestamp": self._start_time.isoformat() if self._start_time else None,
                "duration_seconds": (self._end_time - self._start_time).total_seconds() if self._start_time and self._end_time else 0,
                "workspace": str(self.workspace),
            },
            "summary": self.get_summary(),
            "issues": [i.to_dict() for i in self._issues.issues],
        }

        path_obj = Path(path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        with open(path_obj, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def export_text(self, path: str) -> None:
        """Export diagnostic results to text file."""
        lines = []
        lines.append("=" * 60)
        lines.append("FREYA DIAGNOSTIC REPORT")
        lines.append("=" * 60)
        lines.append("")

        # Summary
        summary = self.get_summary()
        lines.append("SUMMARY")
        lines.append("-" * 40)
        lines.append(f"Total Issues: {summary['total_issues']}")
        lines.append(f"Duration: {summary['duration_seconds']:.2f} seconds")
        lines.append("")

        # By Severity
        lines.append("BY SEVERITY")
        lines.append("-" * 40)
        for severity, count in summary['by_severity'].items():
            lines.append(f"  {severity.upper()}: {count}")
        lines.append("")

        # By Type
        lines.append("BY TYPE")
        lines.append("-" * 40)
        for issue_type, count in summary['by_type'].items():
            lines.append(f"  {issue_type.upper():<15}: {count}")
        lines.append("")

        # Issues
        lines.append("ISSUES")
        lines.append("-" * 40)
        for issue in self._issues.sorted_by_severity():
            status = "[RESOLVED]" if issue.resolved else "[OPEN]"
            lines.append(f"{status} [{issue.severity.value.upper()}] {issue.title}")
            lines.append(f"  Type: {issue.issue_type.value}")
            lines.append(f"  Location: {issue.location}")
            if issue.description:
                lines.append(f"  Description: {issue.description}")
            if issue.fix_suggestion:
                lines.append(f"  Suggestion: {issue.fix_suggestion}")
            lines.append("")

        path_obj = Path(path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        with open(path_obj, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))


class DiagnosticCallback:
    """Base class for diagnostic callbacks."""

    def on_issue_found(self, issue: Issue) -> None:
        """Called when an issue is found."""
        raise NotImplementedError

    def on_run_complete(self, engine: DiagnosticEngine) -> None:
        """Called when the diagnostic run is complete."""
        raise NotImplementedError


class PrintingDiagnosticCallback(DiagnosticCallback):
    """Prints diagnostic progress to console."""

    def __init__(self, verbosity: int = 1):
        self.verbosity = verbosity
        self._count = 0

    def on_issue_found(self, issue: Issue) -> None:
        """Print issue when found."""
        if self.verbosity >= 2:
            print(f"  [{issue.severity.value.upper()}] {issue.title} at {issue.location}")
        self._count += 1

    def on_run_complete(self, engine: DiagnosticEngine) -> None:
        """Print summary when complete."""
        summary = engine.get_summary()
        print(f"\nDiagnostic complete: {summary['total_issues']} issues found in {summary['duration_seconds']:.2f}s")
        for severity, count in summary['by_severity'].items():
            if count > 0:
                print(f"  {severity.upper()}: {count}")
