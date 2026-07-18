"""Tests for the Capability Audit System."""

import json
import tempfile
from pathlib import Path

import pytest

from app.audit.capability_registry import (
    Capability,
    CapabilityRegistry,
    CapabilityStatus,
    CapabilityCategory,
    CapabilityPriority,
)
from app.audit.capability_auditor import CapabilityAuditor, AuditFindings
from app.audit.audit_report import AuditReport


class TestCapability:
    """Tests for the Capability dataclass."""

    def test_capability_creation(self):
        """Test creating a capability."""
        cap = Capability(
            id="test.cap",
            name="Test Capability",
            description="A test capability",
            category=CapabilityCategory.CORE,
            status=CapabilityStatus.FULLY_IMPLEMENTED,
        )
        assert cap.id == "test.cap"
        assert cap.name == "Test Capability"
        assert cap.category == CapabilityCategory.CORE
        assert cap.status == CapabilityStatus.FULLY_IMPLEMENTED

    def test_capability_to_dict(self):
        """Test converting capability to dictionary."""
        cap = Capability(
            id="test.cap",
            name="Test Capability",
            description="A test capability",
            category=CapabilityCategory.CORE,
            status=CapabilityStatus.FULLY_IMPLEMENTED,
            priority=CapabilityPriority.HIGH,
            module="test.module",
            file_path="test/file.py",
        )
        data = cap.to_dict()
        assert data["id"] == "test.cap"
        assert data["name"] == "Test Capability"
        assert data["category"] == "core"
        assert data["status"] == "fully_implemented"
        assert data["priority"] == "high"

    def test_capability_from_dict(self):
        """Test creating capability from dictionary."""
        data = {
            "id": "test.cap",
            "name": "Test Capability",
            "description": "A test capability",
            "category": "core",
            "status": "fully_implemented",
            "priority": "high",
        }
        cap = Capability.from_dict(data)
        assert cap.id == "test.cap"
        assert cap.name == "Test Capability"
        assert cap.category == CapabilityCategory.CORE
        assert cap.status == CapabilityStatus.FULLY_IMPLEMENTED
        assert cap.priority == CapabilityPriority.HIGH


class TestCapabilityRegistry:
    """Tests for the CapabilityRegistry."""

    def test_registry_initialization(self):
        """Test registry initialization."""
        registry = CapabilityRegistry()
        registry.initialize()
        assert registry._initialized
        assert len(registry.get_all_capabilities()) > 0

    def test_get_capability(self):
        """Test getting a capability by ID."""
        registry = CapabilityRegistry()
        registry.initialize()
        cap = registry.get_capability("core.llm")
        assert cap is not None
        assert cap.id == "core.llm"
        assert cap.name == "LLM Integration"

    def test_get_all_capabilities(self):
        """Test getting all capabilities."""
        registry = CapabilityRegistry()
        registry.initialize()
        all_caps = registry.get_all_capabilities()
        assert len(all_caps) > 0

    def test_get_capabilities_by_status(self):
        """Test getting capabilities by status."""
        registry = CapabilityRegistry()
        registry.initialize()
        fully_implemented = registry.get_capabilities_by_status(CapabilityStatus.FULLY_IMPLEMENTED)
        partially_implemented = registry.get_capabilities_by_status(CapabilityStatus.PARTIALLY_IMPLEMENTED)
        not_implemented = registry.get_capabilities_by_status(CapabilityStatus.NOT_IMPLEMENTED)
        assert len(fully_implemented) > 0
        assert len(partially_implemented) > 0
        assert len(not_implemented) > 0

    def test_get_capabilities_by_category(self):
        """Test getting capabilities by category."""
        registry = CapabilityRegistry()
        registry.initialize()
        core_caps = registry.get_capabilities_by_category(CapabilityCategory.CORE)
        agent_caps = registry.get_capabilities_by_category(CapabilityCategory.AGENT)
        assert len(core_caps) > 0
        assert len(agent_caps) > 0

    def test_get_capabilities_by_priority(self):
        """Test getting capabilities by priority."""
        registry = CapabilityRegistry()
        registry.initialize()
        critical = registry.get_capabilities_by_priority(CapabilityPriority.CRITICAL)
        high = registry.get_capabilities_by_priority(CapabilityPriority.HIGH)
        assert len(critical) > 0
        assert len(high) > 0

    def test_get_summary(self):
        """Test getting registry summary."""
        registry = CapabilityRegistry()
        registry.initialize()
        summary = registry.get_summary()
        assert "total" in summary
        assert "by_status" in summary
        assert "by_category" in summary
        assert "by_priority" in summary
        assert summary["total"] > 0

    def test_to_dict(self):
        """Test exporting registry as dictionary."""
        registry = CapabilityRegistry()
        registry.initialize()
        data = registry.to_dict()
        assert "capabilities" in data
        assert "summary" in data
        assert len(data["capabilities"]) > 0

    def test_save_and_load(self):
        """Test saving and loading registry."""
        registry = CapabilityRegistry()
        registry.initialize()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "registry.json"
            registry.save(str(path))
            assert path.exists()

            new_registry = CapabilityRegistry()
            new_registry.load(str(path))
            assert len(new_registry.get_all_capabilities()) > 0


class TestCapabilityAuditor:
    """Tests for the CapabilityAuditor."""

    def test_auditor_initialization(self):
        """Test auditor initialization."""
        auditor = CapabilityAuditor()
        assert auditor.registry is not None
        assert auditor.workspace.exists()

    def test_audit_capability_exists(self):
        """Test auditing a capability that exists."""
        auditor = CapabilityAuditor()
        cap = auditor.registry.get_capability("core.llm")
        assert cap is not None

        findings = auditor.audit_capability(cap)
        assert findings.capability == cap
        assert findings.file_exists

    def test_audit_capability_not_exists(self):
        """Test auditing a capability that doesn't exist."""
        auditor = CapabilityAuditor()
        cap = Capability(
            id="test.nonexistent",
            name="Nonexistent Capability",
            description="This doesn't exist",
            category=CapabilityCategory.CORE,
            status=CapabilityStatus.NOT_IMPLEMENTED,
            file_path="nonexistent/file.py",
        )
        findings = auditor.audit_capability(cap)
        assert not findings.file_exists

    def test_audit_all(self):
        """Test auditing all capabilities."""
        auditor = CapabilityAuditor()
        findings = auditor.audit_all()
        assert len(findings) > 0

    def test_get_report(self):
        """Test generating audit report."""
        auditor = CapabilityAuditor()
        report = auditor.get_report()
        assert "summary" in report
        assert "findings" in report
        assert "capabilities_not_implemented" in report
        assert "capabilities_partially_implemented" in report
        assert "capabilities_fully_implemented" in report

    def test_identify_duplicates(self):
        """Test identifying duplicate implementations."""
        auditor = CapabilityAuditor()
        duplicates = auditor.identify_duplicates()
        assert isinstance(duplicates, list)
        # Check that we find at least some known duplicates
        for dup in duplicates:
            assert "files" in dup
            assert "description" in dup

    def test_identify_technical_debt(self):
        """Test identifying technical debt."""
        auditor = CapabilityAuditor()
        debt = auditor.identify_technical_debt()
        assert isinstance(debt, list)

    def test_check_dependencies(self):
        """Test checking project dependencies."""
        auditor = CapabilityAuditor()
        deps = auditor.check_dependencies()
        assert "sources" in deps
        assert "packages" in deps


class TestAuditFindings:
    """Tests for AuditFindings."""

    def test_findings_status(self):
        """Test determining status from findings."""
        cap = Capability(
            id="test",
            name="Test",
            description="Test",
            category=CapabilityCategory.CORE,
            status=CapabilityStatus.NOT_IMPLEMENTED,
        )

        # Not implemented
        findings = AuditFindings(
            capability=cap,
            implemented=False,
            file_exists=False,
            module_importable=False,
            class_exists=False,
            method_exists=False,
            has_tests=False,
            test_passing=False,
        )
        assert findings.status == CapabilityStatus.NOT_IMPLEMENTED

        # Implemented with issues
        findings = AuditFindings(
            capability=cap,
            implemented=True,
            file_exists=True,
            module_importable=True,
            class_exists=True,
            method_exists=True,
            has_tests=True,
            test_passing=True,
            issues=["Has a bug"],
        )
        assert findings.status == CapabilityStatus.PARTIALLY_IMPLEMENTED

        # Fully implemented
        findings = AuditFindings(
            capability=cap,
            implemented=True,
            file_exists=True,
            module_importable=True,
            class_exists=True,
            method_exists=True,
            has_tests=True,
            test_passing=True,
            issues=[],
        )
        assert findings.status == CapabilityStatus.FULLY_IMPLEMENTED

    def test_findings_to_dict(self):
        """Test converting findings to dictionary."""
        cap = Capability(
            id="test",
            name="Test",
            description="Test",
            category=CapabilityCategory.CORE,
            status=CapabilityStatus.NOT_IMPLEMENTED,
        )
        findings = AuditFindings(
            capability=cap,
            implemented=True,
            file_exists=True,
            module_importable=True,
            class_exists=True,
            method_exists=True,
            has_tests=True,
            test_passing=True,
        )
        data = findings.to_dict()
        assert "capability_id" in data
        assert "status" in data
        assert "implemented" in data


class TestAuditReport:
    """Tests for the AuditReport."""

    def test_report_generation(self):
        """Test generating a report."""
        report = AuditReport()
        data = report.generate()
        assert "metadata" in data
        assert "summary" in data
        assert "registry" in data
        assert "audit" in data
        assert "recommendations" in data

    def test_report_save_json(self):
        """Test saving report as JSON."""
        report = AuditReport()
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
        report = AuditReport()
        report.generate()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "report.md"
            report.save(str(path), format="markdown")
            assert path.exists()
            content = path.read_text()
            assert "# Freya Capability Audit Report" in content

    def test_report_save_text(self):
        """Test saving report as plain text."""
        report = AuditReport()
        report.generate()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "report.txt"
            report.save(str(path), format="text")
            assert path.exists()
            content = path.read_text()
            assert "FREYA CAPABILITY AUDIT REPORT" in content

    def test_get_summary(self):
        """Test getting report summary."""
        report = AuditReport()
        summary = report.getsummary()
        assert "Freya Capability Audit Summary" in summary
        assert "Total:" in summary

    def test_get_capabilities_by_status(self):
        """Test getting capabilities grouped by status."""
        report = AuditReport()
        report.generate()
        by_status = report.get_capabilities_by_status()
        assert "fully_implemented" in by_status
        assert "partially_implemented" in by_status
        assert "not_implemented" in by_status


class TestAuditIntegration:
    """Integration tests for the entire audit system."""

    def test_full_audit_workflow(self):
        """Test the complete audit workflow."""
        # Create registry
        registry = CapabilityRegistry()
        registry.initialize()

        # Create auditor
        auditor = CapabilityAuditor(registry)

        # Run audit
        findings = auditor.audit_all()
        assert len(findings) > 0

        # Generate report
        report = AuditReport(registry, auditor)
        data = report.generate()
        assert "metadata" in data
        assert "summary" in data

        # Check summary statistics
        summary = data["summary"]
        assert summary["total_capabilities"] == len(registry.get_all_capabilities())

    def test_audit_system_exports(self):
        """Test that the audit module exports all expected classes."""
        from app.audit import (
            CapabilityAuditor,
            CapabilityRegistry,
            CapabilityStatus,
            AuditReport,
        )
        assert CapabilityAuditor is not None
        assert CapabilityRegistry is not None
        assert CapabilityStatus is not None
        assert AuditReport is not None
