"""Root Cause Analyzer - Structured error parsing and cause identification.

This module analyzes failures to identify likely root causes before attempting repair.
It parses compiler errors, stack traces, verification failures, tool errors, and
returns ranked likely root causes with supporting evidence.

Reuses existing parsing logic where possible instead of duplicating functionality.
"""

import re
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from app.failure_recovery.detector import FailureEvent, FailureType, FailureSeverity

logger = logging.getLogger(__name__)


class CauseCategory(Enum):
    """Categories of root causes."""

    # Code issues
    SYNTAX_ERROR = "syntax_error"           # Python syntax errors
    IMPORT_ERROR = "import_error"           # Missing or broken imports
    TYPE_ERROR = "type_error"               # Type mismatches, attribute errors
    RUNTIME_EXCEPTION = "runtime_exception" # Unhandled exceptions
    ASSERTION_FAILURE = "assertion_failure" # Test assertion failures
    LOGIC_ERROR = "logic_error"             # Incorrect algorithm/implementation

    # Configuration/Environment
    CONFIGURATION = "configuration"         # Config, environment, setup issues
    DEPENDENCY = "dependency"               # Missing/broken dependencies
    PERMISSION = "permission"               # File/permission issues
    RESOURCE = "resource"                   # Memory, disk, CPU, network
    TIMEOUT = "timeout"                     # Operation timed out

    # Process issues
    VERIFICATION = "verification"           # Lint, format, type-check failures
    PLANNING = "planning"                   # Plan generation/execution issues
    PROVIDER = "provider"                   # LLM provider issues
    UNKNOWN = "unknown"


@dataclass
class RootCauseEvidence:
    """Supporting evidence for a root cause hypothesis."""

    source: str                     # Where evidence came from (stderr, stdout, stack_trace, etc.)
    excerpt: str                    # Relevant text snippet
    pattern_matched: str            # Pattern that matched
    confidence_boost: float         # How much this increases confidence (0.0-1.0)
    location: Optional[str] = None  # File:line if available


@dataclass
class RootCause:
    """A hypothesized root cause with supporting evidence and confidence."""

    category: CauseCategory
    description: str
    confidence: float  # 0.0-1.0
    evidence: List[RootCauseEvidence] = field(default_factory=list)
    suggested_fixes: List[str] = field(default_factory=list)
    related_failure_types: List[FailureType] = field(default_factory=list)

    def add_evidence(self, evidence: RootCauseEvidence) -> None:
        """Add supporting evidence and update confidence."""
        self.evidence.append(evidence)
        # Boost confidence based on evidence strength, capped at 1.0
        self.confidence = min(1.0, self.confidence + evidence.confidence_boost)

    def add_suggested_fix(self, fix: str) -> None:
        """Add a suggested fix for this root cause."""
        if fix not in self.suggested_fixes:
            self.suggested_fixes.append(fix)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category.value,
            "description": self.description,
            "confidence": self.confidence,
            "evidence": [
                {
                    "source": e.source,
                    "excerpt": e.excerpt[:300],
                    "pattern_matched": e.pattern_matched,
                    "confidence_boost": e.confidence_boost,
                    "location": e.location,
                }
                for e in self.evidence
            ],
            "suggested_fixes": self.suggested_fixes,
            "related_failure_types": [t.value for t in self.related_failure_types],
        }


class RootCauseAnalyzer:
    """Analyzes failures to identify ranked likely root causes.

    Parses:
    - Compiler errors (SyntaxError, ImportError, TypeError)
    - Stack traces
    - Verification failures (test, lint, type-check)
    - Tool execution errors
    - Runtime exceptions

    Returns ranked list of RootCause objects with evidence.
    """

    # Python exception patterns with their cause categories
    _EXCEPTION_PATTERNS = [
        # Syntax errors
        (CauseCategory.SYNTAX_ERROR, r"SyntaxError:\s*(.+)"),
        (CauseCategory.SYNTAX_ERROR, r"IndentationError:\s*(.+)"),
        (CauseCategory.SYNTAX_ERROR, r"TabError:\s*(.+)"),

        # Import errors
        (CauseCategory.IMPORT_ERROR, r"ImportError:\s*(.+)"),
        (CauseCategory.IMPORT_ERROR, r"ModuleNotFoundError:\s*No module named\s*'(.+?)'"),
        (CauseCategory.IMPORT_ERROR, r"ImportError:\s*cannot import name\s*'(.+?)'"),
        (CauseCategory.IMPORT_ERROR, r"ImportError:\s*attempted relative import with no known parent package"),

        # Type/Attribute errors
        (CauseCategory.TYPE_ERROR, r"TypeError:\s*(.+)"),
        (CauseCategory.TYPE_ERROR, r"AttributeError:\s*'(.+?)'\s*object has no attribute\s*'(.+?)'"),
        (CauseCategory.TYPE_ERROR, r"NameError:\s*name\s*'(.+?)'\s*is not defined"),
        (CauseCategory.TYPE_ERROR, r"ValueError:\s*(.+)"),
        (CauseCategory.TYPE_ERROR, r"KeyError:\s*'(.+?)'"),
        (CauseCategory.TYPE_ERROR, r"IndexError:\s*(.+)"),

        # Assertions
        (CauseCategory.ASSERTION_FAILURE, r"AssertionError:\s*(.+)"),
        (CauseCategory.ASSERTION_FAILURE, r"^assert\s+(.+?),\s*$"),

        # Runtime
        (CauseCategory.RUNTIME_EXCEPTION, r"RuntimeError:\s*(.+)"),
        (CauseCategory.RUNTIME_EXCEPTION, r"Exception:\s*(.+)"),
        (CauseCategory.RUNTIME_EXCEPTION, r"Error:\s*(.+)"),

        # Resources
        (CauseCategory.RESOURCE, r"MemoryError:\s*(.+)"),
        (CauseCategory.RESOURCE, r"OSError:\s*\[Errno 28\]\s*No space left"),
        (CauseCategory.PERMISSION, r"PermissionError:\s*(.+)"),
        (CauseCategory.PERMISSION, r"OSError:\s*\[Errno 13\]\s*Permission denied"),

        # Timeout
        (CauseCategory.TIMEOUT, r"TimeoutError:\s*(.+)"),
        (CauseCategory.TIMEOUT, r"timed out"),
    ]

    # File/line extraction from tracebacks
    _FILE_LINE_PATTERN = re.compile(r'File "([^"]+)", line (\d+)')

    # Test failure patterns
    _TEST_PATTERNS = [
        (CauseCategory.ASSERTION_FAILURE, r"FAILED\s+(.+?)\s*-\s*(.+)"),
        (CauseCategory.ASSERTION_FAILURE, r"AssertionError:\s*(.+)"),
        (CauseCategory.ASSERTION_FAILURE, r"Expected:\s*(.+)\nActual:\s*(.+)"),
    ]

    # Lint/type-check patterns
    _LINT_PATTERNS = [
        (CauseCategory.VERIFICATION, r"(.+?):(\d+):\d+:\s*(error|warning):\s*(.+)"),
        (CauseCategory.VERIFICATION, r"(.+\.py):(\d+):\s*(error|warning)\s*\[(.+?)\]\s*(.+)"),
    ]

    # Dependency/config patterns
    _DEPENDENCY_PATTERNS = [
        (CauseCategory.DEPENDENCY, r"No module named\s*'(.+?)'"),
        (CauseCategory.DEPENDENCY, r"pip.*not found"),
        (CauseCategory.DEPENDENCY, r"command not found:\s*(.+)"),
        (CauseCategory.CONFIGURATION, r"config.*not found"),
        (CauseCategory.CONFIGURATION, r"missing.*configuration"),
    ]

    def __init__(self):
        # Compile patterns for performance
        self._compiled_exception_patterns = [
            (cat, re.compile(pat, re.MULTILINE | re.IGNORECASE))
            for cat, pat in self._EXCEPTION_PATTERNS
        ]
        self._compiled_test_patterns = [
            (cat, re.compile(pat, re.MULTILINE | re.IGNORECASE))
            for cat, pat in self._TEST_PATTERNS
        ]
        self._compiled_lint_patterns = [
            (cat, re.compile(pat, re.MULTILINE | re.IGNORECASE))
            for cat, pat in self._LINT_PATTERNS
        ]
        self._compiled_dep_patterns = [
            (cat, re.compile(pat, re.MULTILINE | re.IGNORECASE))
            for cat, pat in self._DEPENDENCY_PATTERNS
        ]

        logger.info("[RootCauseAnalyzer] Initialized")

    def analyze(self, event: FailureEvent, max_causes: int = 5) -> List[RootCause]:
        """Analyze a failure event and return ranked root causes.

        Args:
            event: The failure event to analyze
            max_causes: Maximum number of causes to return

        Returns:
            List of RootCause objects sorted by confidence (highest first)
        """
        logger.info(f"[RootCauseAnalyzer] Analyzing failure {event.event_id}: {event.failure_type.value}")

        causes: Dict[CauseCategory, RootCause] = {}

        # Route to appropriate analyzer based on failure type
        if event.failure_type in (FailureType.COMPILATION, FailureType.RUNTIME_ERROR):
            self._analyze_exception(event, causes)
        elif event.failure_type == FailureType.TEST_FAILURE:
            self._analyze_test_failure(event, causes)
        elif event.failure_type == FailureType.VERIFICATION:
            self._analyze_verification(event, causes)
        elif event.failure_type == FailureType.TOOL_ERROR:
            self._analyze_tool_error(event, causes)
        elif event.failure_type == FailureType.ENVIRONMENTAL:
            self._analyze_environmental(event, causes)
        elif event.failure_type == FailureType.PROVIDER:
            self._analyze_provider(event, causes)
        elif event.failure_type == FailureType.PLANNING:
            self._analyze_planning(event, causes)

        # Always check for dependency/config issues (can underlie other failures)
        self._analyze_dependencies(event, causes)

        # Add suggested fixes for each cause
        self._add_suggested_fixes(causes)

        # Convert to list and sort by confidence
        ranked = sorted(causes.values(), key=lambda c: c.confidence, reverse=True)

        # Limit results
        ranked = ranked[:max_causes]

        # Log results
        for i, cause in enumerate(ranked):
            logger.info(
                f"[RootCauseAnalyzer] Cause #{i+1}: {cause.category.value} "
                f"(confidence={cause.confidence:.2f}) - {cause.description[:100]}"
            )

        return ranked

    def _analyze_exception(
        self, event: FailureEvent, causes: Dict[CauseCategory, RootCause]
    ) -> None:
        """Analyze Python exceptions from stack trace and error message."""
        text = event.stack_trace or event.error_message or event.stderr
        locations = self._FILE_LINE_PATTERN.findall(text)

        # Match exception patterns
        for category, pattern in self._compiled_exception_patterns:
            matches = pattern.findall(text)
            if matches:
                # Get or create cause
                if category not in causes:
                    first_match = matches[0]
                    desc_text = first_match if isinstance(first_match, str) else " ".join(first_match)
                    causes[category] = RootCause(
                        category=category,
                        description=self._generate_description(category, desc_text),
                        confidence=0.7,
                        related_failure_types=[event.failure_type],
                    )

                cause = causes[category]
                for match in matches[:3]:  # Limit evidence per pattern
                    excerpt = str(match) if isinstance(match, str) else " | ".join(str(m) for m in match)
                    location = f"{locations[0][0]}:{locations[0][1]}" if locations else None
                    cause.add_evidence(RootCauseEvidence(
                        source="stack_trace",
                        excerpt=excerpt[:300],
                        pattern_matched=pattern.pattern,
                        confidence_boost=0.1,
                        location=location,
                    ))

        # Also check dependency patterns in exception output
        self._check_dependency_patterns(text, causes)

    def _analyze_test_failure(
        self, event: FailureEvent, causes: Dict[CauseCategory, RootCause]
    ) -> None:
        """Analyze test failures from pytest output."""
        text = event.stdout + "\n" + event.stderr

        for category, pattern in self._compiled_test_patterns:
            matches = pattern.findall(text)
            if matches:
                if category not in causes:
                    causes[category] = RootCause(
                        category=category,
                        description="Test assertion failure - expected behavior not met",
                        confidence=0.8,
                        related_failure_types=[FailureType.TEST_FAILURE],
                    )

                cause = causes[category]
                for match in matches[:3]:
                    excerpt = " | ".join(str(m) for m in match) if isinstance(match, tuple) else str(match)
                    cause.add_evidence(RootCauseEvidence(
                        source="test_output",
                        excerpt=excerpt[:300],
                        pattern_matched=pattern.pattern,
                        confidence_boost=0.15,
                    ))

        # Check for fixture/config issues
        if "fixture" in text.lower() or "fixture" in text.lower():
            if CauseCategory.CONFIGURATION not in causes:
                causes[CauseCategory.CONFIGURATION] = RootCause(
                    category=CauseCategory.CONFIGURATION,
                    description="Test fixture/configuration issue",
                    confidence=0.6,
                    related_failure_types=[FailureType.TEST_FAILURE],
                )
                causes[CauseCategory.CONFIGURATION].add_evidence(RootCauseEvidence(
                    source="test_output",
                    excerpt="fixture mentioned in test output",
                    pattern_matched="fixture",
                    confidence_boost=0.1,
                ))

        self._check_dependency_patterns(text, causes)

    def _analyze_verification(
        self, event: FailureEvent, causes: Dict[CauseCategory, RootCause]
    ) -> None:
        """Analyze lint/type-check/format verification failures."""
        text = event.stdout + "\n" + event.stderr

        for category, pattern in self._compiled_lint_patterns:
            matches = pattern.findall(text)
            if matches:
                if category not in causes:
                    causes[category] = RootCause(
                        category=category,
                        description="Code verification failure (lint/type-check/format)",
                        confidence=0.85,
                        related_failure_types=[FailureType.VERIFICATION],
                    )

                cause = causes[category]
                for match in matches[:5]:  # Can have many lint errors
                    if isinstance(match, tuple):
                        file_path = match[0] if match else "unknown"
                        line = match[1] if len(match) > 1 else "?"
                        msg = match[-1] if match else ""
                        excerpt = f"{file_path}:{line}: {msg}"
                        location = f"{file_path}:{line}"
                    else:
                        excerpt = str(match)
                        location = None

                    cause.add_evidence(RootCauseEvidence(
                        source="verification_output",
                        excerpt=excerpt[:300],
                        pattern_matched=pattern.pattern,
                        confidence_boost=0.1,
                        location=location,
                    ))

    def _analyze_tool_error(
        self, event: FailureEvent, causes: Dict[CauseCategory, RootCause]
    ) -> None:
        """Analyze tool execution errors."""
        text = event.error_message + "\n" + event.stderr

        # Permission errors
        if "permission" in text.lower() or "access denied" in text.lower():
            if CauseCategory.PERMISSION not in causes:
                causes[CauseCategory.PERMISSION] = RootCause(
                    category=CauseCategory.PERMISSION,
                    description="Tool execution permission denied",
                    confidence=0.9,
                    related_failure_types=[FailureType.TOOL_ERROR, FailureType.PERMISSION],
                )
                causes[CauseCategory.PERMISSION].add_evidence(RootCauseEvidence(
                    source="tool_error",
                    excerpt=text[:300],
                    pattern_matched="permission|access denied",
                    confidence_boost=0.1,
                ))

        # Command not found
        if "not found" in text.lower() or "command not found" in text.lower():
            if CauseCategory.DEPENDENCY not in causes:
                causes[CauseCategory.DEPENDENCY] = RootCause(
                    category=CauseCategory.DEPENDENCY,
                    description="Required command/tool not installed",
                    confidence=0.85,
                    related_failure_types=[FailureType.TOOL_ERROR, FailureType.ENVIRONMENTAL],
                )
                causes[CauseCategory.DEPENDENCY].add_evidence(RootCauseEvidence(
                    source="tool_error",
                    excerpt=text[:300],
                    pattern_matched="not found|command not found",
                    confidence_boost=0.1,
                ))

        # Timeout
        if "timeout" in text.lower() or "timed out" in text.lower():
            if CauseCategory.TIMEOUT not in causes:
                causes[CauseCategory.TIMEOUT] = RootCause(
                    category=CauseCategory.TIMEOUT,
                    description="Tool execution timed out",
                    confidence=0.9,
                    related_failure_types=[FailureType.TIMEOUT],
                )
                causes[CauseCategory.TIMEOUT].add_evidence(RootCauseEvidence(
                    source="tool_error",
                    excerpt=text[:300],
                    pattern_matched="timeout|timed out",
                    confidence_boost=0.1,
                ))

    def _analyze_environmental(
        self, event: FailureEvent, causes: Dict[CauseCategory, RootCause]
    ) -> None:
        """Analyze environmental failures (network, disk, etc.)."""
        text = event.error_message + "\n" + event.stderr + "\n" + event.stdout

        # Network issues
        if any(kw in text.lower() for kw in ["connection", "network", "dns", "unreachable", "timeout"]):
            if CauseCategory.CONFIGURATION not in causes:
                causes[CauseCategory.CONFIGURATION] = RootCause(
                    category=CauseCategory.CONFIGURATION,
                    description="Network connectivity issue",
                    confidence=0.75,
                    related_failure_types=[FailureType.ENVIRONMENTAL],
                )
                causes[CauseCategory.CONFIGURATION].add_evidence(RootCauseEvidence(
                    source="error_output",
                    excerpt=text[:300],
                    pattern_matched="connection|network|dns|unreachable",
                    confidence_boost=0.1,
                ))

        # Disk space
        if "no space left" in text.lower() or "disk full" in text.lower():
            if CauseCategory.RESOURCE not in causes:
                causes[CauseCategory.RESOURCE] = RootCause(
                    category=CauseCategory.RESOURCE,
                    description="Insufficient disk space",
                    confidence=0.95,
                    related_failure_types=[FailureType.ENVIRONMENTAL],
                )
                causes[CauseCategory.RESOURCE].add_evidence(RootCauseEvidence(
                    source="error_output",
                    excerpt=text[:300],
                    pattern_matched="no space left|disk full",
                    confidence_boost=0.1,
                ))

    def _analyze_provider(
        self, event: FailureEvent, causes: Dict[CauseCategory, RootCause]
    ) -> None:
        """Analyze LLM provider failures."""
        text = event.error_message + "\n" + event.stderr

        # Rate limiting
        if "rate limit" in text.lower() or "429" in text:
            if CauseCategory.PROVIDER not in causes:
                causes[CauseCategory.PROVIDER] = RootCause(
                    category=CauseCategory.PROVIDER,
                    description="LLM provider rate limit exceeded",
                    confidence=0.9,
                    related_failure_types=[FailureType.PROVIDER],
                )
                causes[CauseCategory.PROVIDER].add_suggested_fix("Wait and retry with exponential backoff")
                causes[CauseCategory.PROVIDER].add_suggested_fix("Switch to alternative provider")
                causes[CauseCategory.PROVIDER].add_suggested_fix("Reduce request frequency")

        # Model not available
        if "model" in text.lower() and ("not found" in text.lower() or "unavailable" in text.lower()):
            if CauseCategory.CONFIGURATION not in causes:
                causes[CauseCategory.CONFIGURATION] = RootCause(
                    category=CauseCategory.CONFIGURATION,
                    description="Requested LLM model not available",
                    confidence=0.85,
                    related_failure_types=[FailureType.PROVIDER],
                )
                causes[CauseCategory.CONFIGURATION].add_suggested_fix("Switch to available model")
                causes[CauseCategory.CONFIGURATION].add_suggested_fix("Check provider model list")

        # Authentication
        if "auth" in text.lower() or "unauthorized" in text.lower() or "401" in text:
            if CauseCategory.PERMISSION not in causes:
                causes[CauseCategory.PERMISSION] = RootCause(
                    category=CauseCategory.PERMISSION,
                    description="LLM provider authentication failed",
                    confidence=0.95,
                    related_failure_types=[FailureType.PROVIDER, FailureType.PERMISSION],
                )
                causes[CauseCategory.PERMISSION].add_suggested_fix("Verify API key/credentials")
                causes[CauseCategory.PERMISSION].add_suggested_fix("Check provider authentication setup")

    def _analyze_planning(
        self, event: FailureEvent, causes: Dict[CauseCategory, RootCause]
    ) -> None:
        """Analyze planning failures."""
        text = event.error_message + "\n" + event.stderr

        if "cycle" in text.lower() or "circular" in text.lower():
            causes[CauseCategory.PLANNING] = RootCause(
                category=CauseCategory.PLANNING,
                description="Cyclic dependency in plan",
                confidence=0.9,
                related_failure_types=[FailureType.PLANNING],
            )
            causes[CauseCategory.PLANNING].add_suggested_fix("Review task dependencies for cycles")
            causes[CauseCategory.PLANNING].add_suggested_fix("Break circular dependencies")

        if "no task" in text.lower() or "empty plan" in text.lower():
            causes[CauseCategory.PLANNING] = RootCause(
                category=CauseCategory.PLANNING,
                description="Plan generation produced no executable tasks",
                confidence=0.8,
                related_failure_types=[FailureType.PLANNING],
            )
            causes[CauseCategory.PLANNING].add_suggested_fix("Verify task decomposition logic")
            causes[CauseCategory.PLANNING].add_suggested_fix("Check planner prompt and context")

    def _analyze_dependencies(
        self, event: FailureEvent, causes: Dict[CauseCategory, RootCause]
    ) -> None:
        """Always check for underlying dependency/config issues."""
        text = event.error_message + "\n" + event.stderr + "\n" + event.stdout
        self._check_dependency_patterns(text, causes)

    def _check_dependency_patterns(
        self, text: str, causes: Dict[CauseCategory, RootCause]
    ) -> None:
        """Check text for dependency/config patterns."""
        for category, pattern in self._compiled_dep_patterns:
            matches = pattern.findall(text)
            if matches:
                if category not in causes:
                    match_text = matches[0] if isinstance(matches[0], str) else " ".join(matches[0])
                    causes[category] = RootCause(
                        category=category,
                        description=self._generate_description(category, match_text),
                        confidence=0.75,
                        related_failure_types=[event.failure_type for event in [event] if False][0] if False else [],  # placeholder
                    )
                    # Fix: add the right failure types
                    causes[category].related_failure_types = self._get_failure_types_for_category(category)

                cause = causes[category]
                for match in matches[:3]:
                    excerpt = str(match) if isinstance(match, str) else " | ".join(str(m) for m in match)
                    cause.add_evidence(RootCauseEvidence(
                        source="error_output",
                        excerpt=excerpt[:300],
                        pattern_matched=pattern.pattern,
                        confidence_boost=0.1,
                    ))

    def _get_failure_types_for_category(self, category: CauseCategory) -> List[FailureType]:
        """Map cause category to failure types."""
        mapping = {
            CauseCategory.SYNTAX_ERROR: [FailureType.COMPILATION],
            CauseCategory.IMPORT_ERROR: [FailureType.COMPILATION],
            CauseCategory.TYPE_ERROR: [FailureType.RUNTIME_ERROR, FailureType.COMPILATION],
            CauseCategory.RUNTIME_EXCEPTION: [FailureType.RUNTIME_ERROR],
            CauseCategory.ASSERTION_FAILURE: [FailureType.TEST_FAILURE],
            CauseCategory.LOGIC_ERROR: [FailureType.RUNTIME_ERROR],
            CauseCategory.CONFIGURATION: [FailureType.ENVIRONMENTAL, FailureType.PROVIDER],
            CauseCategory.DEPENDENCY: [FailureType.ENVIRONMENTAL, FailureType.COMPILATION],
            CauseCategory.PERMISSION: [FailureType.PERMISSION, FailureType.TOOL_ERROR],
            CauseCategory.RESOURCE: [FailureType.ENVIRONMENTAL],
            CauseCategory.TIMEOUT: [FailureType.TIMEOUT],
            CauseCategory.VERIFICATION: [FailureType.VERIFICATION],
            CauseCategory.PLANNING: [FailureType.PLANNING],
            CauseCategory.PROVIDER: [FailureType.PROVIDER],
            CauseCategory.UNKNOWN: [FailureType.UNKNOWN],
        }
        return mapping.get(category, [FailureType.UNKNOWN])

    def _generate_description(self, category: CauseCategory, match_text: str) -> str:
        """Generate human-readable description for a cause category."""
        descriptions = {
            CauseCategory.SYNTAX_ERROR: f"Python syntax error: {match_text}",
            CauseCategory.IMPORT_ERROR: f"Import error: {match_text}",
            CauseCategory.TYPE_ERROR: f"Type/attribute error: {match_text}",
            CauseCategory.RUNTIME_EXCEPTION: f"Runtime exception: {match_text}",
            CauseCategory.ASSERTION_FAILURE: f"Assertion failure: {match_text}",
            CauseCategory.LOGIC_ERROR: f"Logic error: {match_text}",
            CauseCategory.CONFIGURATION: f"Configuration issue: {match_text}",
            CauseCategory.DEPENDENCY: f"Missing dependency: {match_text}",
            CauseCategory.PERMISSION: f"Permission denied: {match_text}",
            CauseCategory.RESOURCE: f"Resource exhausted: {match_text}",
            CauseCategory.TIMEOUT: f"Operation timed out: {match_text}",
            CauseCategory.VERIFICATION: f"Code verification failed: {match_text}",
            CauseCategory.PLANNING: f"Planning error: {match_text}",
            CauseCategory.PROVIDER: f"Provider error: {match_text}",
            CauseCategory.UNKNOWN: f"Unknown cause: {match_text}",
        }
        return descriptions.get(category, str(match_text))

    def _add_suggested_fixes(self, causes: Dict[CauseCategory, RootCause]) -> None:
        """Add suggested fixes for each root cause category."""
        fix_suggestions = {
            CauseCategory.SYNTAX_ERROR: [
                "Fix syntax error at indicated location",
                "Run linter/formatter to auto-fix",
                "Check for mismatched brackets, quotes, indentation",
            ],
            CauseCategory.IMPORT_ERROR: [
                "Install missing package with pip",
                "Check import path and spelling",
                "Verify virtual environment has package",
                "Check for circular imports",
            ],
            CauseCategory.TYPE_ERROR: [
                "Add type annotations to clarify expected types",
                "Fix attribute access - check object type",
                "Handle None values with Optional types",
                "Use isinstance() checks before attribute access",
            ],
            CauseCategory.RUNTIME_EXCEPTION: [
                "Add exception handling for this case",
                "Validate inputs before operation",
                "Check preconditions and invariants",
            ],
            CauseCategory.ASSERTION_FAILURE: [
                "Fix the code to match expected behavior",
                "Update test if assertion is incorrect",
                "Add debugging to understand actual vs expected",
            ],
            CauseCategory.CONFIGURATION: [
                "Verify configuration files exist and are valid",
                "Check environment variables are set",
                "Validate config schema",
            ],
            CauseCategory.DEPENDENCY: [
                "Install missing package: pip install <package>",
                "Add to requirements.txt/pyproject.toml",
                "Verify package name and version",
            ],
            CauseCategory.PERMISSION: [
                "Check file/directory permissions",
                "Run with appropriate privileges",
                "Verify user has write access to workspace",
            ],
            CauseCategory.RESOURCE: [
                "Free up disk space",
                "Increase memory limit",
                "Optimize resource usage",
            ],
            CauseCategory.TIMEOUT: [
                "Increase timeout setting",
                "Optimize slow operation",
                "Add progress reporting for long operations",
            ],
            CauseCategory.VERIFICATION: [
                "Run auto-formatter (black, ruff, etc.)",
                "Fix type annotations",
                "Address lint warnings individually",
            ],
            CauseCategory.PLANNING: [
                "Check task decomposition logic",
                "Verify dependencies are acyclic",
                "Ensure planner has sufficient context",
            ],
            CauseCategory.PROVIDER: [
                "Retry with exponential backoff",
                "Switch to alternative model/provider",
                "Check API key and quota",
            ],
        }

        for category, cause in causes.items():
            if category in fix_suggestions:
                for fix in fix_suggestions[category]:
                    cause.add_suggested_fix(fix)


# Convenience function for quick analysis
def analyze_failure(event: FailureEvent, max_causes: int = 5) -> List[RootCause]:
    """Quick root cause analysis - creates analyzer, analyzes, returns causes."""
    analyzer = RootCauseAnalyzer()
    return analyzer.analyze(event, max_causes)