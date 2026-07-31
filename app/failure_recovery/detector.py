"""Unified Failure Detection - Single entry point for all failure detection.

This module provides a centralized system for detecting, classifying, and routing
all failures through a unified entry point. Instead of failures surfacing in
5+ different places, they all route through FailureDetector which classifies
them by type and severity.
"""

import re
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union
import logging

logger = logging.getLogger(__name__)


class FailureType(Enum):
    """Categories of failures that can occur in Freya."""

    COMPILATION = "compilation"           # Syntax errors, type errors, import errors
    TEST_FAILURE = "test_failure"         # Test assertions, failures, errors
    RUNTIME_ERROR = "runtime_error"       # Exceptions during execution
    TOOL_ERROR = "tool_error"             # Tool execution failures (permissions, missing deps)
    VERIFICATION = "verification"         # Lint, type-check, format failures
    PLANNING = "planning"                 # Plan generation, decomposition failures
    EXECUTION = "execution"               # Task/step execution failures
    ENVIRONMENTAL = "environmental"       # Network, disk, permission, missing deps
    PROVIDER = "provider"                 # LLM provider failures, rate limits
    PERMISSION = "permission"             # User denied permission
    TIMEOUT = "timeout"                   # Timeout during execution
    UNKNOWN = "unknown"                   # Unclassified failures

    @classmethod
    def from_exception(cls, exc: Exception) -> "FailureType":
        """Infer failure type from exception."""
        exc_type = type(exc).__name__
        exc_msg = str(exc).lower()

        if "import" in exc_msg or "modulenotfound" in exc_type.lower():
            return cls.COMPILATION
        if "syntax" in exc_type.lower() or "indentation" in exc_msg:
            return cls.COMPILATION
        if "permission" in exc_msg or "access denied" in exc_msg:
            return cls.PERMISSION
        if "timeout" in exc_msg or "timed out" in exc_msg:
            return cls.TIMEOUT
        if "connection" in exc_msg or "network" in exc_msg or "dns" in exc_msg:
            return cls.ENVIRONMENTAL
        if "pytest" in exc_msg or "assert" in exc_msg:
            return cls.TEST_FAILURE
        if "lint" in exc_msg or "flake8" in exc_msg or "pylint" in exc_msg:
            return cls.VERIFICATION
        return cls.RUNTIME_ERROR


class FailureSeverity(Enum):
    """Severity levels for failures."""

    INFO = "info"           # Informational, no action needed
    LOW = "low"             # Minor issue, automatic recovery likely
    MEDIUM = "medium"       # Moderate issue, may need retry/alternative
    HIGH = "high"           # Significant issue, likely needs alternative approach
    CRITICAL = "critical"   # Critical failure, may need human intervention

    @property
    def priority(self) -> int:
        """Numeric priority for sorting (higher = more urgent)."""
        return {
            FailureSeverity.INFO: 0,
            FailureSeverity.LOW: 1,
            FailureSeverity.MEDIUM: 2,
            FailureSeverity.HIGH: 3,
            FailureSeverity.CRITICAL: 4,
        }[self]

    @classmethod
    def from_exit_code(cls, exit_code: int) -> "FailureSeverity":
        """Infer severity from process exit code."""
        if exit_code == 0:
            return cls.INFO
        elif exit_code in (1, 2):
            return cls.MEDIUM
        elif exit_code in (127, 126):  # Command not found, permission
            return cls.HIGH
        elif exit_code >= 128:  # Signal termination
            return cls.CRITICAL
        return cls.MEDIUM


class Recoverability(Enum):
    """Assessment of whether a failure can be automatically recovered."""

    AUTO_RECOVERABLE = "auto_recoverable"      # Can retry/fix automatically
    MANUAL_RETRY = "manual_retry"              # Can retry with different approach
    NEEDS_ALTERNATIVE = "needs_alternative"    # Need different strategy
    NEEDS_REPLAN = "needs_replan"              # Need new plan
    NEEDS_HUMAN = "needs_human"                # Requires human intervention
    UNRECOVERABLE = "unrecoverable"            # Cannot recover

    @classmethod
    def from_type_and_severity(
        cls, failure_type: FailureType, severity: FailureSeverity, attempt: int
    ) -> "Recoverability":
        """Infer recoverability from failure type, severity, and attempt number."""
        # Critical failures on later attempts need human
        if severity == FailureSeverity.CRITICAL and attempt > 1:
            return cls.NEEDS_HUMAN

        # Permission issues always need human
        if failure_type == FailureType.PERMISSION:
            return cls.NEEDS_HUMAN

        # Provider issues may need failover
        if failure_type == FailureType.PROVIDER:
            return cls.NEEDS_ALTERNATIVE if attempt == 1 else cls.NEEDS_HUMAN

        # Environmental issues may auto-resolve
        if failure_type == FailureType.ENVIRONMENTAL:
            return cls.AUTO_RECOVERABLE if attempt == 1 else cls.MANUAL_RETRY

        # Compilation/verification - can fix automatically
        if failure_type in (FailureType.COMPILATION, FailureType.VERIFICATION):
            return cls.AUTO_RECOVERABLE if attempt <= 2 else cls.MANUAL_RETRY

        # Test failures - need code fix
        if failure_type == FailureType.TEST_FAILURE:
            return cls.MANUAL_RETRY if attempt <= 2 else cls.NEEDS_ALTERNATIVE

        # Default based on severity and attempt
        if severity == FailureSeverity.LOW and attempt <= 2:
            return cls.AUTO_RECOVERABLE
        elif severity == FailureSeverity.MEDIUM and attempt <= 2:
            return cls.MANUAL_RETRY
        elif severity == FailureSeverity.HIGH and attempt <= 1:
            return cls.MANUAL_RETRY
        elif attempt <= 2:
            return cls.NEEDS_ALTERNATIVE
        else:
            return cls.NEEDS_HUMAN


@dataclass
class FailureEvent:
    """A detected failure event with all context needed for analysis and recovery."""

    # Core identification
    event_id: str = field(default_factory=lambda: f"fail_{uuid.uuid4().hex[:12]}")
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Classification
    failure_type: FailureType = FailureType.UNKNOWN
    severity: FailureSeverity = FailureSeverity.MEDIUM
    recoverability: Recoverability = Recoverability.MANUAL_RETRY

    # Context
    component: str = "freya_agent"
    operation: str = ""
    task_description: str = ""

    # Error details
    error_message: str = ""
    error_type: str = ""  # Exception class name
    stack_trace: str = ""

    # Process output
    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None

    # Execution context
    attempt_number: int = 1
    max_attempts: int = 3
    plan_id: Optional[str] = None
    task_id: Optional[str] = None
    step_description: Optional[str] = None

    # Additional metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Related failures (for cascading failures)
    related_events: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "failure_type": self.failure_type.value,
            "severity": self.severity.value,
            "recoverability": self.recoverability.value,
            "component": self.component,
            "operation": self.operation,
            "task_description": self.task_description,
            "error_message": self.error_message,
            "error_type": self.error_type,
            "stack_trace": self.stack_trace,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "attempt_number": self.attempt_number,
            "max_attempts": self.max_attempts,
            "plan_id": self.plan_id,
            "task_id": self.task_id,
            "step_description": self.step_description,
            "metadata": self.metadata,
            "related_events": self.related_events,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FailureEvent":
        """Create from dictionary."""
        return cls(
            event_id=data.get("event_id", f"fail_{uuid.uuid4().hex[:12]}"),
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            failure_type=FailureType(data.get("failure_type", "unknown")),
            severity=FailureSeverity(data.get("severity", "medium")),
            recoverability=Recoverability(data.get("recoverability", "manual_retry")),
            component=data.get("component", "freya_agent"),
            operation=data.get("operation", ""),
            task_description=data.get("task_description", ""),
            error_message=data.get("error_message", ""),
            error_type=data.get("error_type", ""),
            stack_trace=data.get("stack_trace", ""),
            stdout=data.get("stdout", ""),
            stderr=data.get("stderr", ""),
            exit_code=data.get("exit_code"),
            attempt_number=data.get("attempt_number", 1),
            max_attempts=data.get("max_attempts", 3),
            plan_id=data.get("plan_id"),
            task_id=data.get("task_id"),
            step_description=data.get("step_description"),
            metadata=data.get("metadata", {}),
            related_events=data.get("related_events", []),
        )


class FailureDetector:
    """Unified failure detection - single entry point for all failures.

    Usage:
        detector = FailureDetector()

        # From exception
        event = detector.detect(
            error=exception,
            component="executor",
            operation="execute_step",
            task_description="Fix bug in login.py",
        )

        # From process result
        event = detector.detect_from_result(
            result=verification_result,
            component="verifier",
            operation="run_tests",
        )

        # From tool execution result
        event = detector.detect_from_tool_result(
            tool_result=tool_result,
            component="executor",
            operation="run_terminal",
        )
    """

    def __init__(
        self,
        workspace: str = ".",
        default_max_attempts: int = 3,
        enable_logging: bool = True,
    ):
        self.workspace = workspace
        self.default_max_attempts = default_max_attempts
        self.enable_logging = enable_logging

        # Statistics
        self._stats: Dict[str, int] = {
            "total_detected": 0,
            "by_type": {},
            "by_severity": {},
            "by_component": {},
        }

        # Callbacks for integrations
        self._on_failure_detected: List[callable] = []

        logger.info(f"[FailureDetector] Initialized with workspace: {workspace}")

    def register_callback(self, callback: callable) -> None:
        """Register a callback to be called when a failure is detected."""
        self._on_failure_detected.append(callback)

    def detect(
        self,
        error: Exception,
        component: str,
        operation: str,
        task_description: str = "",
        attempt_number: int = 1,
        max_attempts: Optional[int] = None,
        plan_id: Optional[str] = None,
        task_id: Optional[str] = None,
        step_description: Optional[str] = None,
        stdout: str = "",
        stderr: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> FailureEvent:
        """Detect and classify a failure from an exception.

        Args:
            error: The exception that occurred
            component: Component where failure originated (executor, verifier, planner, etc.)
            operation: Operation being performed (execute_step, run_tests, lint, etc.)
            task_description: Human-readable description of the task
            attempt_number: Current attempt number (1-indexed)
            max_attempts: Maximum attempts allowed
            plan_id: Optional plan ID
            task_id: Optional task ID
            step_description: Optional step being executed
            stdout: Stdout from the operation
            stderr: Stderr from the operation
            metadata: Additional metadata

        Returns:
            FailureEvent with classification and context
        """
        error_type = type(error).__name__
        error_msg = str(error)
        stack_trace = "".join(traceback.format_exception(type(error), error, error.__traceback__))

        # Classify failure type
        failure_type = FailureType.from_exception(error)

        # Infer severity
        severity = self._infer_severity(failure_type, error, stderr)

        # Determine recoverability
        max_att = max_attempts or self.default_max_attempts
        recoverability = Recoverability.from_type_and_severity(
            failure_type, severity, attempt_number
        )

        event = FailureEvent(
            failure_type=failure_type,
            severity=severity,
            recoverability=recoverability,
            component=component,
            operation=operation,
            task_description=task_description,
            error_message=error_msg,
            error_type=error_type,
            stack_trace=stack_trace,
            stdout=stdout,
            stderr=stderr,
            attempt_number=attempt_number,
            max_attempts=max_att,
            plan_id=plan_id,
            task_id=task_id,
            step_description=step_description,
            metadata=metadata or {},
        )

        self._record_and_notify(event)
        return event

    def detect_from_result(
        self,
        result: Any,  # VerificationResult or similar
        component: str,
        operation: str,
        task_description: str = "",
        attempt_number: int = 1,
        max_attempts: Optional[int] = None,
        plan_id: Optional[str] = None,
        task_id: Optional[str] = None,
        step_description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> FailureEvent:
        """Detect failure from a verification/process result object.

        Expects result to have: success (bool), stdout (str), stderr (str),
        return_code (int), command (list)
        """
        success = getattr(result, "success", False)
        stdout = getattr(result, "stdout", "")
        stderr = getattr(result, "stderr", "")
        exit_code = getattr(result, "return_code", getattr(result, "exit_code", 1))
        command = getattr(result, "command", [])

        if success:
            # Not a failure - return info event
            return FailureEvent(
                failure_type=FailureType.UNKNOWN,
                severity=FailureSeverity.INFO,
                recoverability=Recoverability.AUTO_RECOVERABLE,
                component=component,
                operation=operation,
                task_description=task_description,
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                attempt_number=attempt_number,
                max_attempts=max_attempts or self.default_max_attempts,
                plan_id=plan_id,
                task_id=task_id,
                step_description=step_description,
                metadata=metadata or {},
            )

        # Classify based on operation and output
        failure_type = self._classify_from_output(operation, stdout, stderr, exit_code)
        severity = FailureSeverity.from_exit_code(exit_code)

        max_att = max_attempts or self.default_max_attempts
        recoverability = Recoverability.from_type_and_severity(
            failure_type, severity, attempt_number
        )

        error_msg = stderr or stdout or f"Command failed with exit code {exit_code}"
        error_msg = error_msg[:5000]  # Limit length

        event = FailureEvent(
            failure_type=failure_type,
            severity=severity,
            recoverability=recoverability,
            component=component,
            operation=operation,
            task_description=task_description,
            error_message=error_msg,
            error_type=f"ExitCode_{exit_code}",
            stack_trace=stderr[:10000] if stderr else "",
            stdout=stdout[:10000],
            stderr=stderr[:10000],
            exit_code=exit_code,
            attempt_number=attempt_number,
            max_attempts=max_att,
            plan_id=plan_id,
            task_id=task_id,
            step_description=step_description,
            metadata={**(metadata or {}), "command": command},
        )

        self._record_and_notify(event)
        return event

    def detect_from_tool_result(
        self,
        tool_result: Any,  # ToolResult from tool_manager
        component: str,
        operation: str,
        task_description: str = "",
        attempt_number: int = 1,
        max_attempts: Optional[int] = None,
        plan_id: Optional[str] = None,
        task_id: Optional[str] = None,
        step_description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> FailureEvent:
        """Detect failure from a tool execution result.

        Expects tool_result to have: success (bool), output (str), error (str)
        """
        success = getattr(tool_result, "success", False)
        output = getattr(tool_result, "output", "")
        error = getattr(tool_result, "error", "")

        if success:
            return FailureEvent(
                failure_type=FailureType.UNKNOWN,
                severity=FailureSeverity.INFO,
                recoverability=Recoverability.AUTO_RECOVERABLE,
                component=component,
                operation=operation,
                task_description=task_description,
                stdout=output,
                stderr="",
                exit_code=0,
                attempt_number=attempt_number,
                max_attempts=max_attempts or self.default_max_attempts,
                plan_id=plan_id,
                task_id=task_id,
                step_description=step_description,
                metadata=metadata or {},
            )

        # Classify tool error
        failure_type = self._classify_tool_error(operation, error, output)
        severity = self._infer_severity_from_tool_error(failure_type, error)

        max_att = max_attempts or self.default_max_attempts
        recoverability = Recoverability.from_type_and_severity(
            failure_type, severity, attempt_number
        )

        event = FailureEvent(
            failure_type=failure_type,
            severity=severity,
            recoverability=recoverability,
            component=component,
            operation=operation,
            task_description=task_description,
            error_message=error[:5000] if error else output[:5000],
            error_type="ToolError",
            stack_trace=error[:10000] if error else "",
            stdout=output[:10000] if output else "",
            stderr=error[:10000] if error else "",
            exit_code=1,
            attempt_number=attempt_number,
            max_attempts=max_att,
            plan_id=plan_id,
            task_id=task_id,
            step_description=step_description,
            metadata=metadata or {},
        )

        self._record_and_notify(event)
        return event

    def detect_manual(
        self,
        failure_type: FailureType,
        severity: FailureSeverity,
        component: str,
        operation: str,
        error_message: str,
        task_description: str = "",
        attempt_number: int = 1,
        max_attempts: Optional[int] = None,
        plan_id: Optional[str] = None,
        task_id: Optional[str] = None,
        step_description: Optional[str] = None,
        stdout: str = "",
        stderr: str = "",
        stack_trace: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> FailureEvent:
        """Manually create a failure event with explicit classification."""
        max_att = max_attempts or self.default_max_attempts
        recoverability = Recoverability.from_type_and_severity(
            failure_type, severity, attempt_number
        )

        event = FailureEvent(
            failure_type=failure_type,
            severity=severity,
            recoverability=recoverability,
            component=component,
            operation=operation,
            task_description=task_description,
            error_message=error_message,
            error_type="Manual",
            stack_trace=stack_trace,
            stdout=stdout,
            stderr=stderr,
            attempt_number=attempt_number,
            max_attempts=max_att,
            plan_id=plan_id,
            task_id=task_id,
            step_description=step_description,
            metadata=metadata or {},
        )

        self._record_and_notify(event)
        return event

    def _classify_from_output(
        self, operation: str, stdout: str, stderr: str, exit_code: int
    ) -> FailureType:
        """Classify failure based on operation type and output."""
        output = (stdout + "\n" + stderr).lower()

        # By operation type
        if "test" in operation or "pytest" in operation:
            if "assert" in output or "failed" in output:
                return FailureType.TEST_FAILURE
            return FailureType.RUNTIME_ERROR

        if "lint" in operation or "flake8" in operation or "pylint" in operation:
            return FailureType.VERIFICATION

        if "compile" in operation or "py_compile" in operation:
            return FailureType.COMPILATION

        if "type" in operation or "mypy" in operation or "pyright" in operation:
            return FailureType.VERIFICATION

        # By output content
        if "syntaxerror" in output or "indentationerror" in output:
            return FailureType.COMPILATION
        if "importerror" in output or "modulenotfounderror" in output:
            return FailureType.COMPILATION
        if "permission" in output or "access denied" in output:
            return FailureType.PERMISSION
        if "timeout" in output or "timed out" in output:
            return FailureType.TIMEOUT
        if "connection" in output or "network" in output:
            return FailureType.ENVIRONMENTAL
        if "command not found" in output or "not found" in output:
            return FailureType.ENVIRONMENTAL

        return FailureType.RUNTIME_ERROR

    def _classify_tool_error(
        self, operation: str, error: str, output: str
    ) -> FailureType:
        """Classify failure from tool execution."""
        text = (error + "\n" + output).lower()

        if "permission" in text or "access denied" in text:
            return FailureType.PERMISSION
        if "timeout" in text or "timed out" in text:
            return FailureType.TIMEOUT
        if "not found" in text or "command not found" in text:
            return FailureType.ENVIRONMENTAL
        if "connection" in text or "network" in text or "dns" in text:
            return FailureType.ENVIRONMENTAL
        if "importerror" in text or "modulenotfounderror" in text:
            return FailureType.COMPILATION

        return FailureType.TOOL_ERROR

    def _infer_severity(
        self, failure_type: FailureType, error: Exception, stderr: str
    ) -> FailureSeverity:
        """Infer severity from exception type and output."""
        text = str(error).lower() + "\n" + stderr.lower()

        # Critical: System-level issues
        if any(kw in text for kw in ["memoryerror", "systemexit", "keyboardinterrupt", "segmentation fault"]):
            return FailureSeverity.CRITICAL

        # High: Configuration, permissions, missing deps
        if failure_type in (FailureType.PERMISSION, FailureType.PROVIDER):
            return FailureSeverity.HIGH
        if any(kw in text for kw in ["permission", "access denied", "not found", "modulenotfounderror"]):
            return FailureSeverity.HIGH

        # Medium: Compilation, verification, test failures
        if failure_type in (FailureType.COMPILATION, FailureType.VERIFICATION, FailureType.TEST_FAILURE):
            return FailureSeverity.MEDIUM

        # Low/Medium: Runtime errors
        return FailureSeverity.MEDIUM

    def _infer_severity_from_tool_error(
        self, failure_type: FailureType, error: str
    ) -> FailureSeverity:
        """Infer severity from tool error."""
        if failure_type in (FailureType.PERMISSION, FailureType.PROVIDER):
            return FailureSeverity.HIGH
        if failure_type == FailureType.TIMEOUT:
            return FailureSeverity.HIGH
        if failure_type == FailureType.ENVIRONMENTAL:
            return FailureSeverity.MEDIUM
        return FailureSeverity.MEDIUM

    def _record_and_notify(self, event: FailureEvent) -> None:
        """Record statistics and notify callbacks."""
        self._stats["total_detected"] += 1
        self._stats["by_type"][event.failure_type.value] = (
            self._stats["by_type"].get(event.failure_type.value, 0) + 1
        )
        self._stats["by_severity"][event.severity.value] = (
            self._stats["by_severity"].get(event.severity.value, 0) + 1
        )
        self._stats["by_component"][event.component] = (
            self._stats["by_component"].get(event.component, 0) + 1
        )

        if self.enable_logging:
            logger.warning(
                f"[FailureDetector] {event.failure_type.value.upper()} "
                f"({event.severity.value}) in {event.component}.{event.operation}: "
                f"{event.error_message[:200]}"
            )

        # Notify callbacks
        for callback in self._on_failure_detected:
            try:
                callback(event)
            except Exception as e:
                logger.error(f"[FailureDetector] Callback error: {e}")

    def get_statistics(self) -> Dict[str, Any]:
        """Get detection statistics."""
        return self._stats.copy()

    def reset_statistics(self) -> None:
        """Reset detection statistics."""
        self._stats = {
            "total_detected": 0,
            "by_type": {},
            "by_severity": {},
            "by_component": {},
        }


# Convenience function for quick detection
def detect_failure(
    error: Exception,
    component: str,
    operation: str,
    task_description: str = "",
    **kwargs,
) -> FailureEvent:
    """Quick failure detection - creates detector, detects, returns event."""
    detector = FailureDetector()
    return detector.detect(
        error=error,
        component=component,
        operation=operation,
        task_description=task_description,
        **kwargs,
    )