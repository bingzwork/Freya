"""Self-Initiated Work Generator for Long-Term Autonomy.

This module implements the capability for Freya to detect opportunities
and generate tasks autonomously without user prompting.
"""

import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4


class OpportunityType(Enum):
    """Types of opportunities that can trigger self-initiated work."""
    CODE_QUALITY = "code_quality"           # Refactoring, linting, formatting
    SECURITY = "security"                   # Security patches, vulnerability fixes
    DEPENDENCY = "dependency"               # Outdated dependencies, updates
    TEST_COVERAGE = "test_coverage"         # Missing tests, low coverage
    PERFORMANCE = "performance"             # Performance optimizations
    DOCUMENTATION = "documentation"         # Missing or outdated docs
    TECHNICAL_DEBT = "technical_debt"       # Code smells, complexity
    BUILD_ISSUES = "build_issues"           # Failing builds, broken tests
    ARCHITECTURE = "architecture"           # Architectural improvements
    UNKNOWN = "unknown"                     # Other opportunities


class OpportunityPriority(Enum):
    """Priority levels for opportunities."""
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class Opportunity:
    """Represents a detected opportunity for self-initiated work."""
    id: str = field(default_factory=lambda: f"opp_{uuid4().hex[:8]}")
    type: OpportunityType = OpportunityType.UNKNOWN
    priority: OpportunityPriority = OpportunityPriority.MEDIUM
    title: str = ""
    description: str = ""
    detected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: str = ""  # Which detector found this
    location: str = ""  # File, module, or system area
    metadata: Dict[str, Any] = field(default_factory=dict)
    status: str = "detected"  # detected, scheduled, in_progress, completed, dismissed
    confidence: float = 0.5  # 0.0 to 1.0


@dataclass
class DetectorConfig:
    """Configuration for an opportunity detector."""
    enabled: bool = True
    scan_interval: float = 300.0  # seconds
    priority: OpportunityPriority = OpportunityPriority.MEDIUM
    min_confidence: float = 0.3
    max_opportunities_per_scan: int = 10


class OpportunityDetector:
    """
    Base class for opportunity detectors.

    Subclasses implement specific detection logic for different
    types of opportunities (code quality, security, dependencies, etc.).
    """

    def __init__(self, config: DetectorConfig = None):
        self.config = config or DetectorConfig()
        self._last_scan: float = 0.0

    def scan(self, context: Dict[str, Any]) -> List[Opportunity]:
        """
        Scan for opportunities.

        Args:
            context: Context information (workspace, git status, etc.)

        Returns:
            List of detected opportunities
        """
        raise NotImplementedError("Subclasses must implement scan()")

    def should_scan(self) -> bool:
        """Check if it's time to scan."""
        return time.time() - self._last_scan >= self.config.scan_interval

    def mark_scanned(self) -> None:
        """Mark that a scan has been performed."""
        self._last_scan = time.time()


class CodeQualityDetector(OpportunityDetector):
    """Detects code quality opportunities (linting, formatting, complexity)."""

    def scan(self, context: Dict[str, Any]) -> List[Opportunity]:
        opportunities = []

        # Check for linting issues
        lint_results = context.get("lint_results", {})
        if lint_results.get("issues", 0) > 0:
            opportunities.append(Opportunity(
                type=OpportunityType.CODE_QUALITY,
                priority=OpportunityPriority.MEDIUM,
                title=f"Linting issues detected ({lint_results['issues']} issues)",
                description=f"Found {lint_results['issues']} linting issues that should be fixed",
                source="code_quality_detector",
                location=context.get("workspace", ""),
                confidence=0.8,
                metadata={"issues_count": lint_results["issues"]}
            ))

        # Check for formatting issues
        format_results = context.get("format_results", {})
        if format_results.get("needs_formatting", False):
            opportunities.append(Opportunity(
                type=OpportunityType.CODE_QUALITY,
                priority=OpportunityPriority.LOW,
                title="Code formatting issues",
                description="Files need formatting according to project style guide",
                source="code_quality_detector",
                location=context.get("workspace", ""),
                confidence=0.9,
                metadata={"files_count": format_results.get("files_count", 0)}
            ))

        # Check for complexity issues
        complexity_results = context.get("complexity_results", {})
        high_complexity = complexity_results.get("high_complexity_functions", [])
        if high_complexity:
            opportunities.append(Opportunity(
                type=OpportunityType.TECHNICAL_DEBT,
                priority=OpportunityPriority.MEDIUM,
                title=f"High complexity functions ({len(high_complexity)})",
                description="Functions with high cyclomatic complexity detected",
                source="code_quality_detector",
                location=context.get("workspace", ""),
                confidence=0.7,
                metadata={"functions": high_complexity}
            ))

        return opportunities[:self.config.max_opportunities_per_scan]


class SecurityDetector(OpportunityDetector):
    """Detects security opportunities (vulnerabilities, outdated packages)."""

    def scan(self, context: Dict[str, Any]) -> List[Opportunity]:
        opportunities = []

        # Check for security vulnerabilities
        vuln_results = context.get("vulnerability_scan", {})
        vulnerabilities = vuln_results.get("vulnerabilities", [])
        if vulnerabilities:
            for vuln in vulnerabilities[:self.config.max_opportunities_per_scan]:
                severity = vuln.get("severity", "medium").lower()
                priority_map = {
                    "critical": OpportunityPriority.CRITICAL,
                    "high": OpportunityPriority.HIGH,
                    "medium": OpportunityPriority.MEDIUM,
                    "low": OpportunityPriority.LOW
                }
                opportunities.append(Opportunity(
                    type=OpportunityType.SECURITY,
                    priority=priority_map.get(severity, OpportunityPriority.MEDIUM),
                    title=f"Security vulnerability: {vuln.get('id', 'unknown')}",
                    description=vuln.get("description", "Security vulnerability detected"),
                    source="security_detector",
                    location=vuln.get("file", context.get("workspace", "")),
                    confidence=0.9,
                    metadata=vuln
                ))

        return opportunities


class DependencyDetector(OpportunityDetector):
    """Detects outdated dependency opportunities."""

    def scan(self, context: Dict[str, Any]) -> List[Opportunity]:
        opportunities = []

        # Check for outdated dependencies
        dep_results = context.get("dependency_check", {})
        outdated = dep_results.get("outdated", [])
        if outdated:
            for dep in outdated[:self.config.max_opportunities_per_scan]:
                # Higher priority for security-related updates
                is_security = dep.get("security_update", False)
                priority = OpportunityPriority.HIGH if is_security else OpportunityPriority.MEDIUM
                opportunities.append(Opportunity(
                    type=OpportunityType.DEPENDENCY,
                    priority=priority,
                    title=f"Outdated dependency: {dep.get('name', 'unknown')}",
                    description=f"Version {dep.get('current', '?')} -> {dep.get('latest', '?')}"
                                f"{' (security update)' if is_security else ''}",
                    source="dependency_detector",
                    location=dep.get("file", context.get("workspace", "")),
                    confidence=0.8,
                    metadata=dep
                ))

        return opportunities


class TestCoverageDetector(OpportunityDetector):
    """Detects test coverage opportunities."""

    def scan(self, context: Dict[str, Any]) -> List[Opportunity]:
        opportunities = []

        # Check for low test coverage
        coverage_results = context.get("coverage_report", {})
        overall_coverage = coverage_results.get("overall_coverage", 100)
        uncovered_files = coverage_results.get("uncovered_files", [])

        if overall_coverage < 80:
            opportunities.append(Opportunity(
                type=OpportunityType.TEST_COVERAGE,
                priority=OpportunityPriority.MEDIUM if overall_coverage > 50 else OpportunityPriority.HIGH,
                title=f"Low test coverage: {overall_coverage}%",
                description=f"Overall test coverage is {overall_coverage}%, target is 80%+",
                source="test_coverage_detector",
                location=context.get("workspace", ""),
                confidence=0.8,
                metadata={"coverage": overall_coverage, "uncovered_files": uncovered_files[:10]}
            ))

        # Check for completely untested modules
        for file_info in uncovered_files[:self.config.max_opportunities_per_scan]:
            if file_info.get("coverage", 100) == 0:
                opportunities.append(Opportunity(
                    type=OpportunityType.TEST_COVERAGE,
                    priority=OpportunityPriority.HIGH,
                    title=f"Untested module: {file_info.get('file', 'unknown')}",
                    description="Module has 0% test coverage",
                    source="test_coverage_detector",
                    location=file_info.get("file", ""),
                    confidence=0.9,
                    metadata=file_info
                ))

        return opportunities


class SelfInitiatedWorkManager:
    """
    Manages self-initiated work generation.

    This class orchestrates multiple opportunity detectors and manages
    the lifecycle of detected opportunities from detection to task creation.
    """

    def __init__(self, workspace: str = ".", max_concurrent_tasks: int = 5):
        """
        Initialize the self-initiated work manager.

        Args:
            workspace: Workspace directory
            max_concurrent_tasks: Maximum concurrent self-initiated tasks
        """
        self.workspace = workspace
        self.max_concurrent_tasks = max_concurrent_tasks
        self._lock = threading.RLock()

        # Initialize detectors
        self._detectors: List[OpportunityDetector] = [
            CodeQualityDetector(DetectorConfig(
                scan_interval=300.0,  # 5 minutes
                priority=OpportunityPriority.MEDIUM
            )),
            SecurityDetector(DetectorConfig(
                scan_interval=3600.0,  # 1 hour
                priority=OpportunityPriority.HIGH
            )),
            DependencyDetector(DetectorConfig(
                scan_interval=86400.0,  # 1 day
                priority=OpportunityPriority.MEDIUM
            )),
            TestCoverageDetector(DetectorConfig(
                scan_interval=1800.0,  # 30 minutes
                priority=OpportunityPriority.MEDIUM
            ))
        ]

        # Opportunity tracking
        self._opportunities: Dict[str, Opportunity] = {}
        self._active_opportunities: Dict[str, str] = {}  # opportunity_id -> task_id

        # Callbacks
        self._task_creator: Optional[Callable] = None
        self._context_provider: Optional[Callable] = None

        # Scheduler thread
        self._running = False
        self._scheduler_thread = None
        self._shutdown_event = threading.Event()

    def set_task_creator(self, creator: Callable[[Opportunity], str]) -> None:
        """
        Set the callback for creating tasks from opportunities.

        Args:
            creator: Function that takes an Opportunity and returns a task_id
        """
        self._task_creator = creator

    def set_context_provider(self, provider: Callable[[], Dict[str, Any]]) -> None:
        """
        Set the callback for providing context to detectors.

        Args:
            provider: Function that returns context dictionary for scanning
        """
        self._context_provider = provider

    def add_detector(self, detector: OpportunityDetector) -> None:
        """Add a custom opportunity detector."""
        with self._lock:
            self._detectors.append(detector)

    def start(self) -> None:
        """Start the self-initiated work scheduler."""
        if self._running:
            return

        self._running = True
        self._shutdown_event.clear()
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop,
            daemon=True,
            name="SelfInitiatedWorkScheduler"
        )
        self._scheduler_thread.start()

    def stop(self) -> None:
        """Stop the scheduler."""
        if not self._running:
            return

        self._running = False
        self._shutdown_event.set()
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            self._scheduler_thread.join(timeout=5.0)

    def _scheduler_loop(self) -> None:
        """Main scheduler loop."""
        while not self._shutdown_event.is_set():
            try:
                self._scan_and_generate()
            except Exception as e:
                print(f"Self-initiated work scheduler error: {e}")

            # Sleep for a short interval before checking again
            self._shutdown_event.wait(60.0)

    def _scan_and_generate(self) -> None:
        """Run all detectors and generate tasks from opportunities."""
        if not self._context_provider:
            return

        # Get context for detectors
        context = self._context_provider()
        context["workspace"] = self.workspace

        # Run detectors that are due for scanning
        with self._lock:
            for detector in self._detectors:
                if not detector.config.enabled or not detector.should_scan():
                    continue

                try:
                    opportunities = detector.scan(context)
                    detector.mark_scanned()

                    for opp in opportunities:
                        if opp.id not in self._opportunities:
                            # Filter by confidence
                            if opp.confidence >= detector.config.min_confidence:
                                self._opportunities[opp.id] = opp
                except Exception as e:
                    print(f"Detector {detector.__class__.__name__} error: {e}")

    def get_pending_opportunities(self) -> List[Opportunity]:
        """Get all pending (detected but not scheduled) opportunities."""
        with self._lock:
            return [
                opp for opp in self._opportunities.values()
                if opp.status == "detected"
            ]

    def get_opportunity(self, opportunity_id: str) -> Optional[Opportunity]:
        """Get a specific opportunity by ID."""
        with self._lock:
            return self._opportunities.get(opportunity_id)

    def schedule_opportunity(self, opportunity_id: str) -> Optional[str]:
        """
        Schedule an opportunity for execution.

        Args:
            opportunity_id: ID of the opportunity to schedule

        Returns:
            Task ID if scheduled, None otherwise
        """
        with self._lock:
            opp = self._opportunities.get(opportunity_id)
            if not opp or opp.status != "detected":
                return None

            # Check concurrent task limit
            if len(self._active_opportunities) >= self.max_concurrent_tasks:
                return None

            if not self._task_creator:
                opp.status = "scheduled"
                return None

            try:
                task_id = self._task_creator(opp)
                opp.status = "scheduled"
                self._active_opportunities[opportunity_id] = task_id
                return task_id
            except Exception as e:
                print(f"Failed to create task for opportunity {opportunity_id}: {e}")
                return None

    def mark_opportunity_completed(self, opportunity_id: str) -> bool:
        """
        Mark an opportunity as completed.

        Args:
            opportunity_id: ID of the opportunity

        Returns:
            True if found and updated, False otherwise
        """
        with self._lock:
            opp = self._opportunities.get(opportunity_id)
            if not opp:
                return False
            opp.status = "completed"
            if opportunity_id in self._active_opportunities:
                del self._active_opportunities[opportunity_id]
            return True

    def dismiss_opportunity(self, opportunity_id: str, reason: str = "") -> bool:
        """
        Dismiss an opportunity (won't be scheduled).

        Args:
            opportunity_id: ID of the opportunity
            reason: Reason for dismissal

        Returns:
            True if found and updated, False otherwise
        """
        with self._lock:
            opp = self._opportunities.get(opportunity_id)
            if not opp:
                return False
            opp.status = "dismissed"
            opp.metadata["dismissal_reason"] = reason
            return True

    def get_status(self) -> Dict[str, Any]:
        """Get status of the self-initiated work system."""
        with self._lock:
            return {
                "running": self._running,
                "total_opportunities": len(self._opportunities),
                "by_status": {
                    status: len([o for o in self._opportunities.values() if o.status == status])
                    for status in ["detected", "scheduled", "in_progress", "completed", "dismissed"]
                },
                "active_tasks": len(self._active_opportunities),
                "detectors": len(self._detectors),
                "max_concurrent_tasks": self.max_concurrent_tasks
            }