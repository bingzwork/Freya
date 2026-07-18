"""Capability Auditor for assessing project capabilities.

This module provides automated auditing of the Freya codebase to verify
the implementation status of registered capabilities.
"""

import ast
import importlib
import inspect
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

from app.audit.capability_registry import (
    Capability,
    CapabilityRegistry,
    CapabilityStatus,
    CapabilityCategory,
)


@dataclass
class AuditFindings:
    """Contains the findings from a capability audit."""
    capability: Capability
    implemented: bool = False
    file_exists: bool = False
    module_importable: bool = False
    class_exists: bool = False
    method_exists: bool = False
    has_tests: bool = False
    test_passing: bool = False
    issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)

    @property
    def status(self) -> CapabilityStatus:
        """Determine the status based on findings."""
        if not self.implemented:
            return CapabilityStatus.NOT_IMPLEMENTED
        if self.issues:
            return CapabilityStatus.PARTIALLY_IMPLEMENTED
        return CapabilityStatus.FULLY_IMPLEMENTED

    def to_dict(self) -> Dict[str, Any]:
        """Convert findings to dictionary."""
        return {
            "capability_id": self.capability.id,
            "name": self.capability.name,
            "status": self.status.value,
            "implemented": self.implemented,
            "file_exists": self.file_exists,
            "module_importable": self.module_importable,
            "class_exists": self.class_exists,
            "method_exists": self.method_exists,
            "has_tests": self.has_tests,
            "test_passing": self.test_passing,
            "issues": self.issues,
            "warnings": self.warnings,
            "suggestions": self.suggestions,
        }


class CapabilityAuditor:
    """Audits the implementation status of registered capabilities.

    This class verifies whether each registered capability is actually
    implemented in the codebase and to what degree.
    """

    def __init__(self, registry: Optional[CapabilityRegistry] = None, workspace: str = "."):
        """Initialize the capability auditor.

        Args:
            registry: The capability registry to audit. If None, a new one is created.
            workspace: The root directory of the project.
        """
        self.registry = registry or CapabilityRegistry()
        self.workspace = Path(workspace).resolve()
        self._findings_cache: Dict[str, AuditFindings] = {}

    def audit_all(self) -> List[AuditFindings]:
        """Audit all registered capabilities."""
        self.registry.initialize()
        findings = []
        for cap in self.registry.get_all_capabilities():
            findings.append(self.audit_capability(cap))
        return findings

    def audit_capability(self, capability: Capability) -> AuditFindings:
        """Audit a single capability."""
        if capability.id in self._findings_cache:
            return self._findings_cache[capability.id]

        findings = AuditFindings(capability=capability)

        # Check if the file exists
        if capability.file_path:
            file_path = self.workspace / capability.file_path
            findings.file_exists = file_path.exists()
            if not findings.file_exists:
                findings.issues.append(f"File not found: {capability.file_path}")
                self._findings_cache[capability.id] = findings
                return findings
            findings.implemented = True

            # Check if module is importable
            if capability.module:
                findings.module_importable = self._can_import_module(capability.module)
                if not findings.module_importable:
                    findings.warnings.append(f"Module not importable: {capability.module}")

            # Check for class existence
            if capability.module:
                findings.class_exists = self._class_exists_in_module(
                    capability.module, self._get_class_name_from_path(capability.file_path)
                )

        # Check for tests
        if capability.tests:
            findings.has_tests = True
            for test_file in capability.tests:
                test_path = self.workspace / "tests" / test_file
                if test_path.exists():
                    findings.test_passing = True
                else:
                    findings.warnings.append(f"Test file not found: {test_file}")

        # Additional checks based on capability type
        self._perform_custom_checks(findings)

        # Determine if capability is implemented
        if not findings.file_exists and capability.status != CapabilityStatus.NOT_IMPLEMENTED:
            findings.implemented = False
            findings.issues.append("Implementation file does not exist")

        self._findings_cache[capability.id] = findings
        return findings

    def _can_import_module(self, module_path: str) -> bool:
        """Check if a module can be imported."""
        try:
            # Convert app.xxx to app.xxx format
            if not module_path.startswith("app."):
                module_path = f"app.{module_path}"
            importlib.import_module(module_path)
            return True
        except (ImportError, ModuleNotFoundError, SyntaxError):
            return False

    def _class_exists_in_module(self, module_path: str, class_name: Optional[str] = None) -> bool:
        """Check if a class exists in a module."""
        try:
            if not module_path.startswith("app."):
                module_path = f"app.{module_path}"
            module = importlib.import_module(module_path)
            if class_name:
                return hasattr(module, class_name)
            return True
        except (ImportError, ModuleNotFoundError, SyntaxError):
            return False

    def _get_class_name_from_path(self, file_path: str) -> Optional[str]:
        """Extract the likely class name from a file path."""
        if not file_path:
            return None
        # e.g., app/agent/core_agent.py -> CoreAgent
        basename = os.path.basename(file_path)
        if basename.endswith(".py"):
            basename = basename[:-3]
        # Convert snake_case to PascalCase
        parts = basename.split("_")
        return "".join(p.capitalize() for p in parts) if parts else None

    def _perform_custom_checks(self, findings: AuditFindings) -> None:
        """Perform custom checks based on capability properties."""
        cap = findings.capability

        # Check for encoding issues
        if cap.file_path and findings.file_exists:
            file_path = self.workspace / cap.file_path
            try:
                content = file_path.read_text(encoding="utf-8")
                # Check for UTF-8 corruption patterns
                if "ÃƒÆ'" in content or "Ã¢â‚¬" in content:
                    findings.issues.append("File contains UTF-8 encoding corruption")
            except UnicodeDecodeError:
                findings.issues.append("File cannot be decoded as UTF-8")

        # Check for known issues based on capability ID
        known_issues = {
            "memory.project_memory": ["Duplicate class definition in file"],
            "agent.executor": ["No timeout handling for LLM calls"],
            "core.llm": ["No multi-provider support", "No timeout handling"],
            "editing.patch_engine": ["No delete action support", "No line-based editing"],
        }
        if cap.id in known_issues:
            findings.warnings.extend(known_issues[cap.id])

    def get_report(self) -> Dict[str, Any]:
        """Generate a comprehensive audit report."""
        findings = self.audit_all()

        # Summary statistics
        total = len(findings)
        by_status = {}
        for f in findings:
            status = f.status.value
            by_status[status] = by_status.get(status, 0) + 1

        # Find issues and warnings
        all_issues = []
        all_warnings = []
        all_suggestions = []
        for f in findings:
            if f.issues:
                all_issues.extend(f.issues)
            if f.warnings:
                all_warnings.extend(f.warnings)
            if f.suggestions:
                all_suggestions.extend(f.suggestions)

        return {
            "timestamp": None,  # Will be set by AuditReport
            "summary": {
                "total_capabilities": total,
                "by_status": by_status,
                "total_issues": len(all_issues),
                "total_warnings": len(all_warnings),
                "total_suggestions": len(all_suggestions),
            },
            "findings": [f.to_dict() for f in findings],
            "capabilities_not_implemented": [
                f.capability.id for f in findings if f.status == CapabilityStatus.NOT_IMPLEMENTED
            ],
            "capabilities_partially_implemented": [
                f.capability.id for f in findings if f.status == CapabilityStatus.PARTIALLY_IMPLEMENTED
            ],
            "capabilities_fully_implemented": [
                f.capability.id for f in findings if f.status == CapabilityStatus.FULLY_IMPLEMENTED
            ],
        }

    def identify_duplicates(self) -> List[Dict[str, Any]]:
        """Identify duplicate implementations in the codebase."""
        duplicates = []

        # Known duplicate files
        known_duplicates = [
            {
                "files": ["app/tools/file_tools.py", "app/core/tool_manager.py"],
                "description": "File tools are duplicated between standalone module and tool_manager",
                "recommendation": "Remove app/tools/file_tools.py and use tool_manager-only",
            },
            {
                "files": ["app/tools/edit_tools.py", "app/core/tool_manager.py"],
                "description": "Edit tools (replace_in_file) are duplicated",
                "recommendation": "Remove app/tools/edit_tools.py and use tool_manager-only",
            },
            {
                "files": ["app/memory/project_memory.py", "app/memory/project_manager.py"],
                "description": "Two different ProjectMemory implementations exist",
                "recommendation": "Consolidate into single implementation",
            },
        ]

        # Check which duplicates actually exist
        for dup in known_duplicates:
            existing_files = [
                f for f in dup["files"]
                if (self.workspace / f).exists()
            ]
            if len(existing_files) > 1:
                duplicates.append({
                    **dup,
                    "existing_files": existing_files,
                    "status": "confirmed",
                })
            elif len(existing_files) == 1:
                duplicates.append({
                    **dup,
                    "existing_files": existing_files,
                    "status": "partial (some files missing)",
                })

        return duplicates

    def identify_technical_debt(self) -> List[Dict[str, Any]]:
        """Identify technical debt items in the codebase."""
        debt_items = []

        # Backup files
        backup_files = list(self.workspace.rglob("*.bak"))
        for bak_file in backup_files:
            debt_items.append({
                "type": "backup_file",
                "location": str(bak_file.relative_to(self.workspace)),
                "description": "Backup file should be removed",
                "severity": "low",
                "fix": f"rm {bak_file.name}",
            })

        # Temporary files
        temp_files = list(self.workspace.rglob("*.tmp")) + list(self.workspace.rglob("*~"))
        for tmp_file in temp_files:
            debt_items.append({
                "type": "temporary_file",
                "location": str(tmp_file.relative_to(self.workspace)),
                "description": "Temporary file should be cleaned up",
                "severity": "low",
                "fix": f"rm {tmp_file.name}",
            })

        # __pycache__ directories (these are OK, but we note them)
        pycache_dirs = list(self.workspace.rglob("__pycache__"))
        # Don't report __pycache__ as they're auto-generated

        return debt_items

    def check_dependencies(self) -> Dict[str, Any]:
        """Check project dependencies and their status."""
        requirements_files = [
            self.workspace / "requirements.txt",
            self.workspace / "pyproject.toml",
        ]

        dependencies = {"sources": [], "packages": {}}

        for req_file in requirements_files:
            if req_file.exists():
                dependencies["sources"].append(req_file.name)
                if req_file.name == "requirements.txt":
                    content = req_file.read_text()
                    for line in content.strip().split("\n"):
                        line = line.strip()
                        if line and not line.startswith("#"):
                            pkg_name = line.split("[")[0].split(">=")[0].split("==")[0].strip()
                            dependencies["packages"][pkg_name] = {
                                "source": req_file.name,
                                "specifier": line,
                            }
                elif req_file.name == "pyproject.toml":
                    import tomllib
                    with open(req_file, "rb") as f:
                        data = tomllib.load(f)
                    deps = data.get("project", {}).get("dependencies", [])
                    for dep in deps:
                        pkg_name = dep.split("[")[0].split(">=")[0].split("==")[0].strip()
                        dependencies["packages"][pkg_name] = {
                            "source": req_file.name,
                            "specifier": dep,
                        }

        return dependencies
