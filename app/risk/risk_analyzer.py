"""Risk Analyzer module for analyzing risks in code and systems."""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Callable
from pathlib import Path
import re

from app.risk.risk_item import (
    RiskItem,
    RiskSeverity,
    RiskProbability,
    RiskStatus,
    RiskCategory,
)
from app.risk.risk_assessment import RiskAssessment, RiskAssessmentResult


@dataclass
class RiskAnalyzer:
    """Analyzes code, dependencies, and systems for risks."""

    # Configuration
    checks: Dict[str, Callable] = field(default_factory=dict)
    patterns: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Results storage
    findings: List[RiskItem] = field(default_factory=list)
    assessment_results: List[RiskAssessmentResult] = field(default_factory=list)

    def __post_init__(self):
        """Initialize default checks and patterns."""
        self._initialize_default_checks()
        self._initialize_default_patterns()

    def _initialize_default_checks(self) -> None:
        """Initialize default risk checks."""
        self.checks = {
            "hardcoded_passwords": self._check_hardcoded_passwords,
            "sql_injection": self._check_sql_injection,
            "high_complexity": self._check_high_complexity,
            "outdated_dependencies": self._check_outdated_dependencies,
            "memory_leaks": self._check_memory_leaks,
            "todo_comments": self._check_todo_comments,
            "deprecated_api": self._check_deprecated_api,
            "error_swallowing": self._check_error_swallowing,
        }

    def _initialize_default_patterns(self) -> None:
        """Initialize default patterns for risk detection."""
        self.patterns = {
            "hardcoded_passwords": {
                "patterns": [
                    r'password\s*=\s*[\'"].+[\'"]',
                    r'api_key\s*=\s*[\'"].+[\'"]',
                    r'secret\s*=\s*[\'"].+[\'"]',
                ],
                "severity": RiskSeverity.CRITICAL,
                "probability": RiskProbability.LIKELY,
                "category": RiskCategory.SECURITY,
            },
            "sql_injection": {
                "patterns": [
                    r'execute\s*\(.*\+.*\)',
                    r'format\s*\(.*\{.*\}.*\)',
                    r'f\"\s*.*\{.*\}.*\"',
                ],
                "severity": RiskSeverity.CRITICAL,
                "probability": RiskProbability.POSSIBLE,
                "category": RiskCategory.SECURITY,
            },
            "todo_comments": {
                "patterns": [
                    r'#\s*TODO',
                    r'//\s*TODO',
                    r'/\*\s*TODO',
                    r'FIXME',
                    r'HACK',
                ],
                "severity": RiskSeverity.LOW,
                "probability": RiskProbability.LIKELY,
                "category": RiskCategory.MAINTAINABILITY,
            },
            "error_swallowing": {
                "patterns": [
                    r'except\s*:\s*pass',
                    r'catch\s*\(\s*\w+\s*\)\s*\{',
                ],
                "severity": RiskSeverity.MEDIUM,
                "probability": RiskProbability.POSSIBLE,
                "category": RiskCategory.RELIABILITY,
            },
        }

    def register_check(
        self,
        name: str,
        check_func: Callable,
    ) -> None:
        """Register a custom check function."""
        self.checks[name] = check_func

    def register_pattern(
        self,
        name: str,
        patterns: List[str],
        severity: RiskSeverity,
        probability: RiskProbability,
        category: RiskCategory,
    ) -> None:
        """Register a custom pattern for risk detection."""
        self.patterns[name] = {
            "patterns": patterns,
            "severity": severity,
            "probability": probability,
            "category": category,
        }

    def analyze_file(
        self,
        file_path: Path,
        category: Optional[RiskCategory] = None,
    ) -> List[RiskItem]:
        """Analyze a file for risks."""
        findings = []
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            findings.extend(self._analyze_content(content, file_path, category))
        except Exception as e:
            # Create a risk item for the analysis failure
            findings.append(
                RiskItem(
                    title=f"Analysis Error: {file_path.name}",
                    description=str(e),
                    category=RiskCategory.TECHNICAL,
                    severity=RiskSeverity.MEDIUM,
                    probability=RiskProbability.RARE,
                )
            )
        return findings

    def analyze_directory(
        self,
        directory: Path,
        extensions: Optional[List[str]] = None,
        exclude_dirs: Optional[List[str]] = None,
    ) -> List[RiskItem]:
        """Analyze all files in a directory for risks."""
        if extensions is None:
            extensions = [".py", ".js", ".ts", ".java", ".go", ".rs", ".cpp", ".c", ".h"]
        if exclude_dirs is None:
            exclude_dirs = [".git", "__pycache__", ".mypy_cache", ".pytest_cache", "venv", "node_modules"]

        findings = []
        for ext in extensions:
            for file_path in directory.rglob(f"*{ext}"):
                if any(excl in file_path.parts for excl in exclude_dirs):
                    continue
                findings.extend(self.analyze_file(file_path))
        return findings

    def _analyze_content(
        self,
        content: str,
        file_path: Optional[Path] = None,
        category: Optional[RiskCategory] = None,
    ) -> List[RiskItem]:
        """Analyze content for risks using registered patterns."""
        findings = []
        for name, pattern_info in self.patterns.items():
            patterns = pattern_info["patterns"]
            severity = pattern_info["severity"]
            probability = pattern_info["probability"]
            risk_category = pattern_info["category"]

            if category:
                risk_category = category

            for pattern in patterns:
                matches = re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE)
                for match in matches:
                    line_number = content[: match.start()].count("\n") + 1
                    line_content = content.split("\n")[line_number - 1].strip()

                    risk = RiskItem(
                        title=f"{name.replace('_', ' ').title()}: {file_path.name if file_path else 'content'}:{line_number}",
                        description=f"Pattern matched: {pattern[:50]}...\nLine: {line_content[:100]}",
                        category=risk_category,
                        severity=severity,
                        probability=probability,
                        impact=f"Matched pattern: {name}",
                        metadata={
                            "file": str(file_path) if file_path else None,
                            "line": line_number,
                            "pattern": pattern,
                            "match": match.group(),
                        },
                    )
                    findings.append(risk)

        return findings

    def run_checks(
        self,
        content: str,
        file_path: Optional[Path] = None,
    ) -> List[RiskItem]:
        """Run all registered check functions."""
        findings = []
        for name, check_func in self.checks.items():
            try:
                result = check_func(content, file_path)
                if result:
                    findings.extend(result)
            except Exception as e:
                findings.append(
                    RiskItem(
                        title=f"Check Error: {name}",
                        description=str(e),
                        category=RiskCategory.TECHNICAL,
                        severity=RiskSeverity.LOW,
                        probability=RiskProbability.RARE,
                    )
                )
        return findings

    def _check_hardcoded_passwords(
        self,
        content: str,
        file_path: Optional[Path] = None,
    ) -> List[RiskItem]:
        """Check for hardcoded passwords and secrets."""
        return self._analyze_content(content, file_path, RiskCategory.SECURITY)

    def _check_sql_injection(
        self,
        content: str,
        file_path: Optional[Path] = None,
    ) -> List[RiskItem]:
        """Check for SQL injection vulnerabilities."""
        return self._analyze_content(content, file_path, RiskCategory.SECURITY)

    def _check_high_complexity(
        self,
        content: str,
        file_path: Optional[Path] = None,
    ) -> List[RiskItem]:
        """Check for high complexity functions/methods."""
        # This would need AST parsing for accurate complexity calculation
        # For now, return empty as this requires more complex analysis
        return []

    def _check_outdated_dependencies(
        self,
        content: str,
        file_path: Optional[Path] = None,
    ) -> List[RiskItem]:
        """Check for outdated dependencies."""
        # This would require access to dependency files and version info
        return []

    def _check_memory_leaks(
        self,
        content: str,
        file_path: Optional[Path] = None,
    ) -> List[RiskItem]:
        """Check for potential memory leaks."""
        patterns = [
            r"open\s*\(\s*.+\s*\)",
        ]
        return self._analyze_content(content, file_path, RiskCategory.PERFORMANCE)

    def _check_todo_comments(
        self,
        content: str,
        file_path: Optional[Path] = None,
    ) -> List[RiskItem]:
        """Check for TODO and FIXME comments."""
        return self._analyze_content(content, file_path, RiskCategory.MAINTAINABILITY)

    def _check_deprecated_api(
        self,
        content: str,
        file_path: Optional[Path] = None,
    ) -> List[RiskItem]:
        """Check for deprecated API usage."""
        patterns = [
            r'@deprecated',
        ]
        return self._analyze_content(content, file_path, RiskCategory.MAINTAINABILITY)

    def _check_error_swallowing(
        self,
        content: str,
        file_path: Optional[Path] = None,
    ) -> List[RiskItem]:
        """Check for error swallowing."""
        return self._analyze_content(content, file_path, RiskCategory.RELIABILITY)

    def assess_risk(
        self,
        risk_item: RiskItem,
        assessor: str = "system",
    ) -> RiskAssessmentResult:
        """Perform a detailed assessment of a risk item."""
        # Calculate the risk score
        severity_score = risk_item.severity.score
        probability_score = risk_item.probability.score
        risk_score = (severity_score * probability_score * risk_item.likely_hood) / 25.0 * 100

        result = RiskAssessmentResult(
            assessment_id=self._generate_id(),
            risk_id=risk_item.id,
            assessor=assessor,
            severity=risk_item.severity,
            probability=risk_item.probability,
            risk_score=risk_score,
            findings=[f"Risk identified: {risk_item.title}"],
            recommendations=self._generate_recommendations(risk_item),
        )
        return result

    def _generate_id(self) -> str:
        """Generate a unique ID."""
        import uuid
        return f"assessment_{uuid.uuid4().hex[:8]}"

    def _generate_recommendations(self, risk_item: RiskItem) -> List[str]:
        """Generate recommendations for a risk item."""
        recommendations = []

        if risk_item.category == RiskCategory.SECURITY:
            if risk_item.severity == RiskSeverity.CRITICAL:
                recommendations.append("Fix immediately - this is a critical security vulnerability")
            recommendations.append("Review and sanitize all user inputs")
            recommendations.append("Use parameterized queries for database operations")

        elif risk_item.category == RiskCategory.PERFORMANCE:
            recommendations.append("Profile the code to identify bottlenecks")
            recommendations.append("Consider caching frequently accessed data")
            recommendations.append("Optimize database queries")

        elif risk_item.category == RiskCategory.RELIABILITY:
            recommendations.append("Add proper error handling and logging")
            recommendations.append("Implement circuit breakers for external dependencies")
            recommendations.append("Add comprehensive tests")

        elif risk_item.category == RiskCategory.MAINTAINABILITY:
            recommendations.append("Add documentation for complex code")
            recommendations.append("Refactor code to improve readability")
            recommendations.append("Remove technical debt")

        # Generic recommendations based on severity
        if risk_item.severity == RiskSeverity.CRITICAL:
            recommendations.append("Assign highest priority to address this risk")
        elif risk_item.severity == RiskSeverity.HIGH:
            recommendations.append("Address this risk in the next sprint")

        return list(set(recommendations))  # Deduplicate

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the analyzer's findings."""
        return {
            "total_findings": len(self.findings),
            "critical_count": len([f for f in self.findings if f.risk_level == "critical"]),
            "high_count": len([f for f in self.findings if f.risk_level == "high"]),
            "medium_count": len([f for f in self.findings if f.risk_level == "medium"]),
            "low_count": len([f for f in self.findings if f.risk_level == "low"]),
            "info_count": len([f for f in self.findings if f.risk_level == "info"]),
            "average_risk_score": sum(f.risk_score for f in self.findings) / len(self.findings) if self.findings else 0.0,
        }

    def clear_findings(self) -> None:
        """Clear all findings."""
        self.findings = []
        self.assessment_results = []
