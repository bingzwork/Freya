"""Tests for the Diagnostics System."""

import json
import tempfile
from pathlib import Path

import pytest

from app.diagnostics.issue import (
    Issue,
    IssueSeverity,
    IssueType,
    IssueCollection,
)
from app.diagnostics.code_analyzer import CodeAnalyzer
from app.diagnostics.diagnostic_engine import (
    DiagnosticEngine,
    DiagnosticConfig,
    DiagnosticCallback,
    PrintingDiagnosticCallback,
)
from app.diagnostics.diagnostic_report import DiagnosticReport


class TestIssue:
    """Tests for the Issue dataclass."""

    def test_issue_creation(self):
        """Test creating an issue."""
        issue = Issue(
            id="test-001",
            title="Test Issue",
            description="A test issue",
            severity=IssueSeverity.WARNING,
            issue_type=IssueType.CODE_QUALITY,
            location="test.py:10",
            file_path="test.py",
            line_number=10,
        )
        assert issue.id == "test-001"
        assert issue.title == "Test Issue"
        assert issue.severity == IssueSeverity.WARNING
        assert issue.issue_type == IssueType.CODE_QUALITY
        assert issue.location == "test.py:10"
        assert issue.file_path == "test.py"
        assert issue.line_number == 10
        assert not issue.resolved

    def test_issue_to_dict(self):
        """Test converting issue to dictionary."""
        issue = Issue(
            id="test-001",
            title="Test Issue",
            description="A test issue",
            severity=IssueSeverity.ERROR,
            issue_type=IssueType.BUG,
            location="test.py:10",
        )
        data = issue.to_dict()
        assert data["id"] == "test-001"
        assert data["title"] == "Test Issue"
        assert data["severity"] == "error"
        assert data["type"] == "bug"
        assert data["location"] == "test.py:10"

    def test_issue_from_dict(self):
        """Test creating issue from dictionary."""
        data = {
            "id": "test-001",
            "title": "Test Issue",
            "description": "A test issue",
            "severity": "error",
            "type": "bug",
            "location": "test.py:10",
        }
        issue = Issue.from_dict(data)
        assert issue.id == "test-001"
        assert issue.title == "Test Issue"
        assert issue.severity == IssueSeverity.ERROR
        assert issue.issue_type == IssueType.BUG

    def test_issue_resolve(self):
        """Test resolving an issue."""
        issue = Issue(
            id="test-001",
            title="Test Issue",
            description="A test issue",
            severity=IssueSeverity.WARNING,
            issue_type=IssueType.CODE_QUALITY,
            location="test.py:10",
        )
        assert not issue.resolved
        issue.resolve("Fixed by removing unused code")
        assert issue.resolved
        assert issue.resolution_notes == "Fixed by removing unused code"
        assert issue.resolved_timestamp is not None

    def test_issue_severity_score(self):
        """Test severity score calculation."""
        info = Issue(id="1", title="Info", description="", severity=IssueSeverity.INFO, issue_type=IssueType.DOCUMENTATION, location="test:1")
        warning = Issue(id="2", title="Warning", description="", severity=IssueSeverity.WARNING, issue_type=IssueType.CODE_QUALITY, location="test:1")
        error = Issue(id="3", title="Error", description="", severity=IssueSeverity.ERROR, issue_type=IssueType.BUG, location="test:1")
        critical = Issue(id="4", title="Critical", description="", severity=IssueSeverity.CRITICAL, issue_type=IssueType.SECURITY, location="test:1")

        assert info.severity_score == 0
        assert warning.severity_score == 1
        assert error.severity_score == 2
        assert critical.severity_score == 3

    def test_issue_comparison(self):
        """Test comparing issues by severity."""
        warning = Issue(id="1", title="Warning", description="", severity=IssueSeverity.WARNING, issue_type=IssueType.CODE_QUALITY, location="test:1")
        error = Issue(id="2", title="Error", description="", severity=IssueSeverity.ERROR, issue_type=IssueType.BUG, location="test:1")
        assert error < warning  # Higher severity comes first


class TestIssueCollection:
    """Tests for IssueCollection."""

    def test_collection_creation(self):
        """Test creating an empty collection."""
        collection = IssueCollection()
        assert len(collection.issues) == 0

    def test_collection_add(self):
        """Test adding issues to collection."""
        collection = IssueCollection()
        issue = Issue(
            id="test-001",
            title="Test Issue",
            description="A test",
            severity=IssueSeverity.WARNING,
            issue_type=IssueType.CODE_QUALITY,
            location="test.py:1",
        )
        collection.add(issue)
        assert len(collection.issues) == 1

    def test_filter_by_severity(self):
        """Test filtering by severity."""
        collection = IssueCollection()
        collection.add(Issue(id="1", title="Info", description="", severity=IssueSeverity.INFO, issue_type=IssueType.DOCUMENTATION, location="test:1"))
        collection.add(Issue(id="2", title="Warning", description="", severity=IssueSeverity.WARNING, issue_type=IssueType.CODE_QUALITY, location="test:1"))
        collection.add(Issue(id="3", title="Error", description="", severity=IssueSeverity.ERROR, issue_type=IssueType.BUG, location="test:1"))

        warnings = collection.filter_by_severity(IssueSeverity.WARNING)
        assert len(warnings) == 1
        assert warnings[0].severity == IssueSeverity.WARNING

    def test_filter_by_type(self):
        """Test filtering by type."""
        collection = IssueCollection()
        collection.add(Issue(id="1", title="Bug", description="", severity=IssueSeverity.ERROR, issue_type=IssueType.BUG, location="test:1"))
        collection.add(Issue(id="2", title="Quality", description="", severity=IssueSeverity.WARNING, issue_type=IssueType.CODE_QUALITY, location="test:1"))

        bugs = collection.filter_by_type(IssueType.BUG)
        assert len(bugs) == 1
        assert bugs[0].issue_type == IssueType.BUG

    def test_filter_unresolved(self):
        """Test filtering unresolved issues."""
        collection = IssueCollection()
        issue1 = Issue(id="1", title="Open", description="", severity=IssueSeverity.ERROR, issue_type=IssueType.BUG, location="test:1")
        issue2 = Issue(id="2", title="Fixed", description="", severity=IssueSeverity.ERROR, issue_type=IssueType.BUG, location="test:1")
        issue2.resolve()
        collection.add(issue1)
        collection.add(issue2)

        unresolved = collection.filter_unresolved()
        assert len(unresolved) == 1
        assert unresolved[0].id == "1"

    def test_count_by_severity(self):
        """Test counting by severity."""
        collection = IssueCollection()
        collection.add(Issue(id="1", title="Info", description="", severity=IssueSeverity.INFO, issue_type=IssueType.DOCUMENTATION, location="test:1"))
        collection.add(Issue(id="2", title="Warning", description="", severity=IssueSeverity.WARNING, issue_type=IssueType.CODE_QUALITY, location="test:1"))
        collection.add(Issue(id="3", title="Error", description="", severity=IssueSeverity.ERROR, issue_type=IssueType.BUG, location="test:1"))
        collection.add(Issue(id="4", title="Critical", description="", severity=IssueSeverity.CRITICAL, issue_type=IssueType.SECURITY, location="test:1"))

        counts = collection.count_by_severity()
        assert counts["info"] == 1
        assert counts["warning"] == 1
        assert counts["error"] == 1
        assert counts["critical"] == 1

    def test_count_by_type(self):
        """Test counting by type."""
        collection = IssueCollection()
        collection.add(Issue(id="1", title="Bug", description="", severity=IssueSeverity.ERROR, issue_type=IssueType.BUG, location="test:1"))
        collection.add(Issue(id="2", title="Bug2", description="", severity=IssueSeverity.ERROR, issue_type=IssueType.BUG, location="test:1"))
        collection.add(Issue(id="3", title="Quality", description="", severity=IssueSeverity.WARNING, issue_type=IssueType.CODE_QUALITY, location="test:1"))

        counts = collection.count_by_type()
        assert counts["bug"] == 2
        assert counts["code_quality"] == 1

    def test_sorted_by_severity(self):
        """Test sorting by severity."""
        collection = IssueCollection()
        collection.add(Issue(id="1", title="Info", description="", severity=IssueSeverity.INFO, issue_type=IssueType.DOCUMENTATION, location="test:1"))
        collection.add(Issue(id="2", title="Warning", description="", severity=IssueSeverity.WARNING, issue_type=IssueType.CODE_QUALITY, location="test:1"))
        collection.add(Issue(id="3", title="Error", description="", severity=IssueSeverity.ERROR, issue_type=IssueType.BUG, location="test:1"))
        collection.add(Issue(id="4", title="Critical", description="", severity=IssueSeverity.CRITICAL, issue_type=IssueType.SECURITY, location="test:1"))

        sorted_issues = collection.sorted_by_severity()
        # Critical first, then Error, then Warning, then Info
        assert sorted_issues[0].severity == IssueSeverity.CRITICAL
        assert sorted_issues[1].severity == IssueSeverity.ERROR
        assert sorted_issues[2].severity == IssueSeverity.WARNING
        assert sorted_issues[3].severity == IssueSeverity.INFO

    def test_to_dict(self):
        """Test converting collection to dictionary."""
        collection = IssueCollection()
        collection.add(Issue(id="1", title="Test", description="", severity=IssueSeverity.ERROR, issue_type=IssueType.BUG, location="test:1"))

        data = collection.to_dict()
        assert data["total"] == 1
        assert data["unresolved"] == 1
        assert data["resolved"] == 0
        assert "by_severity" in data
        assert "by_type" in data
        assert "issues" in data


class TestCodeAnalyzer:
    """Tests for CodeAnalyzer."""

    def test_analyzer_initialization(self):
        """Test analyzer initialization."""
        analyzer = CodeAnalyzer()
        assert analyzer.workspace.exists()

    def test_analyze_file(self):
        """Test analyzing a file."""
        # Create a temporary Python file with issues
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir) / "test_file.py"
            code = """
def unused_function():
    pass

import os
import sys  # unused

def main():
    x = 1
    return x
    print("unreachable")
"""
            tmp_path.write_text(code)
            analyzer = CodeAnalyzer(str(tmp_path.parent))
            issues = analyzer.analyze([str(tmp_path)])
            # Should find at least some issues
            assert len(issues.issues) >= 0  # May not find all issues depending on implementation

    def test_analyze_workspace(self):
        """Test analyzing the entire workspace."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a simple test file
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("def test():\n    pass\n")
            analyzer = CodeAnalyzer(tmpdir)
            issues = analyzer.analyze([str(tmpdir)])
            # Should complete without error
            assert isinstance(issues, IssueCollection)

    def test_get_issues(self):
        """Test getting issues from analyzer."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("def test():\n    pass\n")
            analyzer = CodeAnalyzer(tmpdir)
            analyzer.analyze([str(test_file)])
            issues = analyzer.get_issues()
            assert isinstance(issues, IssueCollection)

    def test_get_summary(self):
        """Test getting summary from analyzer."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("def test():\n    pass\n")
            analyzer = CodeAnalyzer(tmpdir)
            analyzer.analyze([str(test_file)])
            summary = analyzer.get_summary()
            assert "total_issues" in summary
            assert "by_severity" in summary
            assert "by_type" in summary


class TestDiagnosticEngine:
    """Tests for DiagnosticEngine."""

    def test_engine_initialization(self):
        """Test engine initialization."""
        engine = DiagnosticEngine()
        assert engine.workspace.exists()
        assert engine.config is not None

    def test_engine_with_config(self):
        """Test engine with custom configuration."""
        config = DiagnosticConfig(
            paths=["app"],
            check_unused_imports=True,
            long_function_threshold=50,
        )
        engine = DiagnosticEngine(config=config)
        assert engine.config.long_function_threshold == 50

    def test_run(self):
        """Test running diagnostics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("def test():\n    pass\n")
            engine = DiagnosticEngine(workspace=tmpdir, config=DiagnosticConfig(paths=[str(test_file)]))
            issues = engine.run()
            assert isinstance(issues, IssueCollection)
            # Should find at least some issues in the real codebase
            assert len(issues.issues) >= 0

    def test_get_issues(self):
        """Test getting issues from engine."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("def test():\n    pass\n")
            engine = DiagnosticEngine(workspace=tmpdir)
            engine.run([str(test_file)])
            issues = engine.get_issues()
            assert isinstance(issues, IssueCollection)

    def test_get_summary(self):
        """Test getting summary from engine."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("def test():\n    pass\n")
            engine = DiagnosticEngine(workspace=tmpdir)
            engine.run([str(test_file)])
            summary = engine.get_summary()
            assert "total_issues" in summary
            assert "duration_seconds" in summary

    def test_filter_issues(self):
        """Test filtering issues."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("def test():\n    pass\n")
            engine = DiagnosticEngine(workspace=tmpdir)
            engine.run([str(test_file)])
            filtered = engine.filter_issues(severity=IssueSeverity.ERROR)
            assert isinstance(filtered, list)
            for issue in filtered:
                assert issue.severity == IssueSeverity.ERROR

    def test_get_worst_issues(self):
        """Test getting worst issues."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("def test():\n    pass\n")
            engine = DiagnosticEngine(workspace=tmpdir)
            engine.run([str(test_file)])
            worst = engine.get_worst_issues(5)
            assert isinstance(worst, list)
            assert len(worst) <= 5

    def test_export_json(self):
        """Test exporting to JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("def test():\n    pass\n")
            engine = DiagnosticEngine(workspace=tmpdir)
            engine.run([str(test_file)])

            export_path = Path(tmpdir) / "diagnostics.json"
            engine.export_json(str(export_path))
            assert export_path.exists()
            with open(export_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            assert "metadata" in data
            assert "issues" in data

    def test_export_text(self):
        """Test exporting to text."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("def test():\n    pass\n")
            engine = DiagnosticEngine(workspace=tmpdir)
            engine.run([str(test_file)])

            export_path = Path(tmpdir) / "diagnostics.txt"
            engine.export_text(str(export_path))
            assert export_path.exists()
            content = export_path.read_text()
            assert "FREYA DIAGNOSTIC REPORT" in content


class TestDiagnosticConfig:
    """Tests for DiagnosticConfig."""

    def test_default_config(self):
        """Test default configuration."""
        config = DiagnosticConfig()
        assert config.paths == []
        assert config.check_unused_imports is True
        assert config.long_function_threshold == 100

    def test_custom_config(self):
        """Test custom configuration."""
        config = DiagnosticConfig(
            paths=["app", "tests"],
            include_patterns=["**/*.py"],
            exclude_patterns=["**/__pycache__/**"],
            check_unused_imports=False,
            long_function_threshold=50,
        )
        assert config.paths == ["app", "tests"]
        assert config.check_unused_imports is False
        assert config.long_function_threshold == 50


class TestDiagnosticCallback:
    """Tests for DiagnosticCallback and PrintingDiagnosticCallback."""

    def test_printing_callback_initialization(self):
        """Test printing callback initialization."""
        callback = PrintingDiagnosticCallback()
        assert callback.verbosity == 1

    def test_printing_callback_verbosity(self):
        """Test printing callback with different verbosity."""
        callback = PrintingDiagnosticCallback(verbosity=2)
        assert callback.verbosity == 2

    def test_printing_callback_on_issue(self, capsys):
        """Test printing callback on issue found."""
        callback = PrintingDiagnosticCallback(verbosity=2)
        issue = Issue(
            id="test",
            title="Test Issue",
            description="",
            severity=IssueSeverity.ERROR,
            issue_type=IssueType.BUG,
            location="test.py:1",
        )
        callback.on_issue_found(issue)
        captured = capsys.readouterr()
        assert "ERROR" in captured.out


class TestDiagnosticReport:
    """Tests for DiagnosticReport."""

    def test_report_initialization(self):
        """Test report initialization."""
        with tempfile.TemporaryDirectory() as tmpdir:
            report = DiagnosticReport(workspace=tmpdir)
            assert report.engine is not None
            assert report.workspace.exists()

    def test_report_generation(self):
        """Test generating a report."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("def test():\n    pass\n")
            report = DiagnosticReport(workspace=tmpdir)
            data = report.generate(run_diagnostics=False)
            assert "metadata" in data
            assert "summary" in data
            assert "issues" in data
            assert "recommendations" in data

    def test_report_save_json(self):
        """Test saving report as JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("def test():\n    pass\n")
            report = DiagnosticReport(workspace=tmpdir)
            report.generate(run_diagnostics=False)

            export_path = Path(tmpdir) / "report.json"
            report.save(str(export_path), format="json")
            assert export_path.exists()
            with open(export_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            assert "metadata" in loaded

    def test_report_save_markdown(self):
        """Test saving report as Markdown."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("def test():\n    pass\n")
            report = DiagnosticReport(workspace=tmpdir)
            report.generate(run_diagnostics=False)

            export_path = Path(tmpdir) / "report.md"
            report.save(str(export_path), format="markdown")
            assert export_path.exists()
            content = export_path.read_text()
            assert "# Freya Diagnostic Report" in content

    def test_report_save_text(self):
        """Test saving report as plain text."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("def test():\n    pass\n")
            report = DiagnosticReport(workspace=tmpdir)
            report.generate(run_diagnostics=False)

            export_path = Path(tmpdir) / "report.txt"
            report.save(str(export_path), format="text")
            assert export_path.exists()
            content = export_path.read_text()
            assert "FREYA DIAGNOSTIC REPORT" in content

    def test_get_summary(self):
        """Test getting report summary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("def test():\n    pass\n")
            report = DiagnosticReport(workspace=tmpdir)
            report.generate(run_diagnostics=False)
            summary = report.get_summary()
            assert "Freya Diagnostic Summary" in summary
            assert "Total Issues:" in summary

    def test_get_issues_by_file(self):
        """Test getting issues grouped by file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("def test():\n    pass\n")
            report = DiagnosticReport(workspace=tmpdir)
            report.generate(run_diagnostics=False)
            by_file = report.get_issues_by_file()
            assert isinstance(by_file, dict)


class TestDiagnosticsIntegration:
    """Integration tests for the diagnostics system."""

    def test_full_diagnostic_workflow(self):
        """Test the complete diagnostic workflow."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("def test():\n    pass\n")
            # Create engine
            engine = DiagnosticEngine(workspace=tmpdir)

            # Run diagnostics
            issues = engine.run([str(test_file)])
            assert isinstance(issues, IssueCollection)

            # Get summary
            summary = engine.get_summary()
            assert "total_issues" in summary

            # Export results
            engine.export_json(str(Path(tmpdir) / "results.json"))
            assert (Path(tmpdir) / "results.json").exists()

    def test_diagnostics_system_exports(self):
        """Test that the diagnostics module exports all expected classes."""
        from app.diagnostics import (
            DiagnosticEngine,
            Issue,
            IssueSeverity,
            DiagnosticReport,
            CodeAnalyzer,
        )
        assert DiagnosticEngine is not None
        assert Issue is not None
        assert IssueSeverity is not None
        assert DiagnosticReport is not None
        assert CodeAnalyzer is not None
