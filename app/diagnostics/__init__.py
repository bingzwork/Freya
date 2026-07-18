"""Diagnostics System for Freya.

This module provides comprehensive diagnostics for identifying and reporting
issues in the codebase including bugs, performance issues, and architectural problems.
"""

from app.diagnostics.diagnostic_engine import DiagnosticEngine
from app.diagnostics.issue import Issue, IssueSeverity
from app.diagnostics.diagnostic_report import DiagnosticReport
from app.diagnostics.code_analyzer import CodeAnalyzer

__all__ = [
    "DiagnosticEngine",
    "Issue",
    "IssueSeverity",
    "DiagnosticReport",
    "CodeAnalyzer",
]
