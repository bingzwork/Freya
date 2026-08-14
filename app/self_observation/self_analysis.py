"""Centralized Self-Analysis Service for Self Observation.

Continuously evaluates Freya's operational state across multiple dimensions:
- Current capabilities
- Active limitations
- Resource utilization
- Goal progress
- Task execution quality
- Failure patterns
- Learning progress
- Knowledge gaps
- Decision quality
- System confidence
- Overall operational effectiveness

Reuses existing monitoring and observability data wherever possible.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import uuid4

from app.core.events import get_event_bus, Event
from app.core.observability import get_observability_hub, HealthStatus
from app.decision.manager import DecisionManager, get_default_manager
from app.world_model.model import WorldModel, create_world_model
from app.memory.unified_retrieval import UnifiedRetrieval
from app.failure_recovery.orchestrator import RecoveryOrchestrator
from app.autonomous_learning.pipeline import AutonomousLearningPipeline
from app.long_term_autonomy.manager import AutonomyManager

from .models import (
    AnalysisCategory,
    AnalysisResult,
    SelfAnalysisReport,
    ConfidenceLevel,
)

# Type checking imports to avoid circular dependency
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.orchestrator.workflow_orchestrator import WorkflowOrchestrator

logger = logging.getLogger(__name__)


@dataclass
class AnalysisConfig:
    """Configuration for self-analysis."""
    enabled_categories: List[AnalysisCategory] = field(default_factory=lambda: list(AnalysisCategory))
    analysis_interval_seconds: float = 300.0  # 5 minutes
    min_samples_for_trend: int = 10
    confidence_threshold: float = 0.6
    trend_window_seconds: float = 3600.0  # 1 hour


class CentralizedSelfAnalysis:
    """
    Centralized Self-Analysis Service.

    Continuously evaluates Freya's operational state by analyzing data from
    all integrated subsystems. Provides comprehensive reports on:
    - Capabilities and limitations
    - Resource utilization
    - Goal progress
    - Task execution quality
    - Failure patterns
    - Learning progress
    - Knowledge gaps
    - Decision quality
    - System confidence
    - Overall operational effectiveness
    """

    def __init__(
        self,
        orchestrator: "Optional[WorkflowOrchestrator]" = None,
        decision_manager: Optional[DecisionManager] = None,
        world_model: Optional[WorldModel] = None,
        memory_retrieval: Optional[UnifiedRetrieval] = None,
        failure_recovery: Optional[RecoveryOrchestrator] = None,
        autonomous_learning: Optional[AutonomousLearningPipeline] = None,
        autonomy_manager: Optional[AutonomyManager] = None,
        config: Optional[AnalysisConfig] = None,
    ):
        """Initialize the self-analysis service."""
        self._orchestrator = orchestrator
        self._decision_manager = decision_manager
        self._world_model = world_model
        self._memory_retrieval = memory_retrieval
        self._failure_recovery = failure_recovery
        self._autonomous_learning = autonomous_learning
        self._autonomy_manager = autonomy_manager
        self._config = config or AnalysisConfig()

        self._event_bus = get_event_bus()
        self._observability = get_observability_hub()

        self._lock = threading.RLock()
        self._running = False
        self._analysis_thread: Optional[threading.Thread] = None

        # Analysis history
        self._analysis_history: List[SelfAnalysisReport] = []
        self._max_history = 50

        # Cached metrics for trend analysis
        self._metric_cache: Dict[str, List[Tuple[float, float]]] = {}  # metric -> [(timestamp, value)]
        self._cache_lock = threading.RLock()

        # Category analyzers
        self._analyzers: Dict[AnalysisCategory, Callable[[], AnalysisResult]] = {
            AnalysisCategory.CAPABILITIES: self._analyze_capabilities,
            AnalysisCategory.LIMITATIONS: self._analyze_limitations,
            AnalysisCategory.RESOURCE_UTILIZATION: self._analyze_resource_utilization,
            AnalysisCategory.GOAL_PROGRESS: self._analyze_goal_progress,
            AnalysisCategory.TASK_EXECUTION_QUALITY: self._analyze_task_execution_quality,
            AnalysisCategory.FAILURE_PATTERNS: self._analyze_failure_patterns,
            AnalysisCategory.LEARNING_PROGRESS: self._analyze_learning_progress,
            AnalysisCategory.KNOWLEDGE_GAPS: self._analyze_knowledge_gaps,
            AnalysisCategory.DECISION_QUALITY: self._analyze_decision_quality,
            AnalysisCategory.SYSTEM_CONFIDENCE: self._analyze_system_confidence,
            AnalysisCategory.OPERATIONAL_EFFECTIVENESS: self._analyze_operational_effectiveness,
        }

        # Import ComponentInfo and ComponentType
        from app.core.observability import ComponentInfo, ComponentType

        # Register with observability
        self._observability.register_component(
            ComponentInfo(
                name="CentralizedSelfAnalysis",
                component_type=ComponentType.SERVICE,
                description="Centralized self-analysis for Freya operational state",
                version="1.0.0"
            )
        )

        # Subscribe to events
        self._subscribe_events()

    def _subscribe_events(self) -> None:
        """Subscribe to events for real-time metric updates."""
        self._event_bus.subscribe("orchestrator.intent_executed", self._on_metric_event)
        self._event_bus.subscribe("workflow.completed", self._on_metric_event)
        self._event_bus.subscribe("workflow.failed", self._on_metric_event)
        self._event_bus.subscribe("decision.made", self._on_decision_event)
        self._event_bus.subscribe("failure_recovery.completed", self._on_recovery_event)
        self._event_bus.subscribe("autonomous_learning.research_completed", self._on_learning_event)

    def start(self) -> None:
        """Start the analysis service."""
        with self._lock:
            if self._running:
                return
            self._running = True

        self._analysis_thread = threading.Thread(
            target=self._analysis_loop,
            daemon=True,
            name="CentralizedSelfAnalysis"
        )
        self._analysis_thread.start()
        logger.info("CentralizedSelfAnalysis started")

    def stop(self) -> None:
        """Stop the analysis service."""
        with self._lock:
            if not self._running:
                return
            self._running = False

        if self._analysis_thread and self._analysis_thread.is_alive():
            self._analysis_thread.join(timeout=5.0)

        logger.info("CentralizedSelfAnalysis stopped")

    def _analysis_loop(self) -> None:
        """Background analysis loop."""
        while self._running:
            try:
                self.run_analysis()
            except Exception as e:
                logger.error(f"Error in analysis loop: {e}")

            time.sleep(self._config.analysis_interval_seconds)

    def run_analysis(self, force: bool = False) -> SelfAnalysisReport:
        """
        Run a complete self-analysis across all enabled categories.

        Args:
            force: Force analysis even if not enough time has passed

        Returns:
            SelfAnalysisReport with comprehensive analysis
        """
        start_time = time.perf_counter()
        report_id = f"analysis_{uuid4().hex[:8]}"

        logger.info(f"[{report_id}] Starting centralized self-analysis")

        analysis_results = {}
        critical_issues = []
        improvement_priorities = []

        # Run each category analyzer
        for category in self._config.enabled_categories:
            if category not in self._analyzers:
                continue

            try:
                analyzer = self._analyzers[category]
                result = analyzer()
                analysis_results[category] = result

                # Collect critical issues
                if result.score < 0.3:
                    critical_issues.append(f"{category.value}: {result.findings[0] if result.findings else 'Critical issue detected'}")

                # Collect improvement priorities
                for rec in result.recommendations[:2]:  # Top 2 per category
                    improvement_priorities.append(f"{category.value}: {rec}")

            except Exception as e:
                logger.error(f"[{report_id}] Failed to analyze {category.value}: {e}")
                analysis_results[category] = AnalysisResult(
                    category=category,
                    score=0.0,
                    confidence=ConfidenceLevel.CRITICAL,
                    findings=[f"Analysis failed: {e}"],
                    weaknesses=["Analysis unavailable"],
                )

        # Calculate overall score
        if analysis_results:
            overall_score = sum(r.score for r in analysis_results.values()) / len(analysis_results)
            # Weight by confidence
            conf_values = {"very_high": 1.0, "high": 0.8, "medium": 0.6, "low": 0.4, "critical": 0.2}
            weighted_sum = sum(r.score * conf_values.get(r.confidence.value, 0.5) for r in analysis_results.values())
            weight_sum = sum(conf_values.get(r.confidence.value, 0.5) for r in analysis_results.values())
            overall_score = weighted_sum / weight_sum if weight_sum > 0 else overall_score
        else:
            overall_score = 0.0

        # Determine overall confidence
        if overall_score >= 0.8:
            overall_confidence = ConfidenceLevel.VERY_HIGH
        elif overall_score >= 0.6:
            overall_confidence = ConfidenceLevel.HIGH
        elif overall_score >= 0.4:
            overall_confidence = ConfidenceLevel.MEDIUM
        elif overall_score >= 0.2:
            overall_confidence = ConfidenceLevel.LOW
        else:
            overall_confidence = ConfidenceLevel.CRITICAL

        # Generate summary
        summary_parts = [f"Overall operational effectiveness: {overall_score:.0%}"]
        if critical_issues:
            summary_parts.append(f"Critical issues: {len(critical_issues)}")
        summary = "; ".join(summary_parts)

        # Create report
        report = SelfAnalysisReport(
            report_id=report_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            overall_score=overall_score,
            overall_confidence=overall_confidence,
            analysis_results=analysis_results,
            summary=summary,
            critical_issues=critical_issues,
            improvement_priorities=improvement_priorities[:10],  # Top 10
            metadata={
                "analysis_duration_ms": (time.perf_counter() - start_time) * 1000,
                "categories_analyzed": len(analysis_results),
            }
        )

        # Store in history
        with self._lock:
            self._analysis_history.append(report)
            if len(self._analysis_history) > self._max_history:
                self._analysis_history.pop(0)

        # Update metric cache for trends
        self._update_metric_cache(report)

        # Emit event
        self._event_bus.emit(
            "self_analysis.completed",
            data={
                "report_id": report_id,
                "overall_score": overall_score,
                "overall_confidence": overall_confidence.value,
                "critical_issues_count": len(critical_issues),
                "improvement_priorities_count": len(improvement_priorities),
            },
            source="CentralizedSelfAnalysis"
        )

        # Record metrics
        self._observability.record_metric("self_analysis.overall_score", overall_score)
        self._observability.record_metric("self_analysis.critical_issues", len(critical_issues))

        logger.info(
            f"[{report_id}] Analysis completed in {(time.perf_counter() - start_time) * 1000:.1f}ms, "
            f"score: {overall_score:.2f}, confidence: {overall_confidence.value}"
        )

        return report

    def _update_metric_cache(self, report: SelfAnalysisReport) -> None:
        """Update metric cache for trend analysis."""
        now = time.time()
        with self._cache_lock:
            for category, result in report.analysis_results.items():
                key = f"analysis.{category.value}"
                if key not in self._metric_cache:
                    self._metric_cache[key] = []
                self._metric_cache[key].append((now, result.score))

                # Trim old entries
                cutoff = now - self._config.trend_window_seconds
                self._metric_cache[key] = [(t, v) for t, v in self._metric_cache[key] if t > cutoff]

    def get_trend(self, category: AnalysisCategory, window_seconds: float = 3600.0) -> Dict[str, Any]:
        """Get trend data for a category."""
        key = f"analysis.{category.value}"
        with self._cache_lock:
            data = self._metric_cache.get(key, [])

        if len(data) < self._config.min_samples_for_trend:
            return {"trend": "insufficient_data", "samples": len(data)}

        # Simple linear trend
        cutoff = time.time() - window_seconds
        recent = [(t, v) for t, v in data if t > cutoff]

        if len(recent) < 2:
            return {"trend": "insufficient_data", "samples": len(recent)}

        # Calculate slope
        t_vals = [t for t, _ in recent]
        v_vals = [v for _, v in recent]
        t_mean = sum(t_vals) / len(t_vals)
        v_mean = sum(v_vals) / len(v_vals)

        numerator = sum((t - t_mean) * (v - v_mean) for t, v in recent)
        denominator = sum((t - t_mean) ** 2 for t in t_vals)

        slope = numerator / denominator if denominator > 0 else 0

        if abs(slope) < 0.0001:
            trend = "stable"
        elif slope > 0:
            trend = "improving"
        else:
            trend = "declining"

        return {
            "trend": trend,
            "slope": slope,
            "samples": len(recent),
            "current_value": v_vals[-1],
            "mean_value": v_mean,
        }

    # ============================================================
    # Category Analyzers
    # ============================================================

    def _analyze_capabilities(self) -> AnalysisResult:
        """Analyze current capabilities."""
        findings = []
        strengths = []
        weaknesses = []
        recommendations = []

        if self._orchestrator and self._orchestrator._capability_registry:
            stats = self._orchestrator._capability_registry.get_stats()
            total = stats.get("total_capabilities", 0)
            by_state = stats.get("by_state", {})
            active = by_state.get("active", 0)
            healthy = by_state.get("healthy", 0)
            degraded = by_state.get("degraded", 0)
            error = by_state.get("error", 0)

            findings.append(f"Total capabilities: {total}, Active: {active}, Healthy: {healthy}, Degraded: {degraded}, Error: {error}")

            if active == total and total > 0:
                strengths.append("All capabilities active")
                score = 1.0
            elif active >= total * 0.8:
                strengths.append("Most capabilities active")
                score = 0.8
            elif active >= total * 0.5:
                weaknesses.append("Less than 80% capabilities active")
                recommendations.append("Investigate and restore inactive capabilities")
                score = 0.5
            else:
                weaknesses.append("Majority of capabilities inactive")
                recommendations.append("Critical: Restore capability registry health")
                score = 0.2
        else:
            findings.append("Capability registry not available")
            score = 0.0
            weaknesses.append("No capability data")

        return AnalysisResult(
            category=AnalysisCategory.CAPABILITIES,
            score=score,
            confidence=ConfidenceLevel.HIGH if score > 0 else ConfidenceLevel.CRITICAL,
            findings=findings,
            strengths=strengths,
            weaknesses=weaknesses,
            recommendations=recommendations,
        )

    def _analyze_limitations(self) -> AnalysisResult:
        """Analyze active limitations."""
        findings = []
        strengths = []
        weaknesses = []
        recommendations = []

        limitations = []

        # Check resource limitations
        if self._world_model:
            snapshot = self._world_model.get_snapshot()
            if snapshot.resources.memory_percent > 85:
                limitations.append(f"High memory usage: {snapshot.resources.memory_percent:.0f}%")
            if snapshot.resources.cpu_percent > 85:
                limitations.append(f"High CPU usage: {snapshot.resources.cpu_percent:.0f}%")
            if snapshot.resources.disk_percent > 90:
                limitations.append(f"High disk usage: {snapshot.resources.disk_percent:.0f}%")

        # Check capability limitations
        if self._orchestrator and self._orchestrator._capability_registry:
            stats = self._orchestrator._capability_registry.get_stats()
            by_state = stats.get("by_state", {})
            degraded = by_state.get("degraded", 0)
            error = by_state.get("error", 0)
            if degraded > 0:
                limitations.append(f"{degraded} capabilities degraded")
            if error > 0:
                limitations.append(f"{error} capabilities in error state")

        # Check decision limitations
        if self._decision_manager:
            # Would check for low confidence decisions, etc.
            pass

        # Check learning limitations
        if self._autonomous_learning:
            # Would check knowledge gaps, etc.
            pass

        findings.extend(limitations)
        if not limitations:
            strengths.append("No significant limitations detected")
            score = 1.0
        elif len(limitations) <= 2:
            weaknesses.append(f"Minor limitations: {len(limitations)}")
            score = 0.7
        elif len(limitations) <= 5:
            weaknesses.append(f"Moderate limitations: {len(limitations)}")
            recommendations.append("Address resource and capability limitations")
            score = 0.4
        else:
            weaknesses.append(f"Significant limitations: {len(limitations)}")
            recommendations.append("Urgent: Address multiple system limitations")
            score = 0.2

        if limitations:
            recommendations.append("Monitor resource usage and capability health")

        return AnalysisResult(
            category=AnalysisCategory.LIMITATIONS,
            score=score,
            confidence=ConfidenceLevel.HIGH,
            findings=findings,
            strengths=strengths,
            weaknesses=weaknesses,
            recommendations=recommendations,
        )

    def _analyze_resource_utilization(self) -> AnalysisResult:
        """Analyze resource utilization."""
        findings = []
        strengths = []
        weaknesses = []
        recommendations = []

        score = 1.0

        if self._world_model:
            snapshot = self._world_model.get_snapshot()
            cpu = snapshot.resources.cpu_percent
            mem = snapshot.resources.memory_percent
            disk = snapshot.resources.disk_percent

            findings.append(f"CPU: {cpu:.0f}%, Memory: {mem:.0f}%, Disk: {disk:.0f}%")

            # Score based on resource headroom
            if cpu < 50 and mem < 60 and disk < 70:
                strengths.append("Healthy resource headroom")
                score = 1.0
            elif cpu < 70 and mem < 75 and disk < 80:
                strengths.append("Adequate resource headroom")
                score = 0.8
            elif cpu < 85 and mem < 85 and disk < 90:
                weaknesses.append("Limited resource headroom")
                recommendations.append("Monitor resource trends; consider optimization")
                score = 0.5
            else:
                weaknesses.append("Critical resource pressure")
                recommendations.append("Urgent: Reduce workload or scale resources")
                score = 0.2

            # Check for trends
            if cpu > 80:
                recommendations.append("High CPU sustained; evaluate workload efficiency")
            if mem > 80:
                recommendations.append("High memory sustained; check for leaks or cache issues")
        else:
            findings.append("World model not available for resource data")
            score = 0.0

        return AnalysisResult(
            category=AnalysisCategory.RESOURCE_UTILIZATION,
            score=score,
            confidence=ConfidenceLevel.HIGH,
            findings=findings,
            strengths=strengths,
            weaknesses=weaknesses,
            recommendations=recommendations,
        )

    def _analyze_goal_progress(self) -> AnalysisResult:
        """Analyze goal progress."""
        findings = []
        strengths = []
        weaknesses = []
        recommendations = []

        if not self._orchestrator:
            findings.append("Goal system not available")
            return AnalysisResult(
                category=AnalysisCategory.GOAL_PROGRESS,
                score=0.0,
                confidence=ConfidenceLevel.CRITICAL,
                findings=findings,
                weaknesses=["Goal tracking unavailable"],
            )

        # This would integrate with goal management
        # For now, use a placeholder
        findings.append("Goal progress analysis requires goal management integration")
        score = 0.5

        return AnalysisResult(
            category=AnalysisCategory.GOAL_PROGRESS,
            score=score,
            confidence=ConfidenceLevel.MEDIUM,
            findings=findings,
            strengths=[],
            weaknesses=["Goal tracking integration incomplete"],
            recommendations=["Integrate with GoalStorage for detailed progress analysis"],
        )

    def _analyze_task_execution_quality(self) -> AnalysisResult:
        """Analyze task execution quality."""
        findings = []
        strengths = []
        weaknesses = []
        recommendations = []

        if self._orchestrator and self._orchestrator.task_executor:
            stats = self._orchestrator.task_executor.get_stats()
            completed = stats.get("completed_workflows", 0)
            failed = stats.get("failed_workflows", 0)
            total = completed + failed

            if total > 0:
                success_rate = completed / total
                findings.append(f"Task success rate: {success_rate:.1%} ({completed}/{total})")

                if success_rate >= 0.9:
                    strengths.append("Excellent task execution quality")
                    score = 1.0
                elif success_rate >= 0.75:
                    strengths.append("Good task execution quality")
                    score = 0.8
                elif success_rate >= 0.5:
                    weaknesses.append("Moderate task execution quality")
                    recommendations.append("Investigate common failure patterns")
                    score = 0.5
                else:
                    weaknesses.append("Poor task execution quality")
                    recommendations.append("Urgent: Analyze and fix systemic execution issues")
                    score = 0.2
            else:
                findings.append("No task execution history yet")
                score = 0.5
        else:
            findings.append("Task executor not available")
            score = 0.0

        return AnalysisResult(
            category=AnalysisCategory.TASK_EXECUTION_QUALITY,
            score=score,
            confidence=ConfidenceLevel.HIGH if score > 0 else ConfidenceLevel.CRITICAL,
            findings=findings,
            strengths=strengths,
            weaknesses=weaknesses,
            recommendations=recommendations,
        )

    def _analyze_failure_patterns(self) -> AnalysisResult:
        """Analyze failure patterns."""
        findings = []
        strengths = []
        weaknesses = []
        recommendations = []

        if self._failure_recovery:
            failures = self._failure_recovery.get_failure_history(limit=50)
            if failures:
                # Analyze by error type
                error_types = {}
                for f in failures:
                    etype = f.get("error_type", "unknown")
                    error_types[etype] = error_types.get(etype, 0) + 1

                findings.append(f"Recent failures: {len(failures)} total, {len(error_types)} unique types")

                # Check for repeated failures
                repeated = [etype for etype, count in error_types.items() if count >= 3]
                if repeated:
                    weaknesses.append(f"Repeated failure types: {repeated}")
                    recommendations.append("Investigate root causes of repeated failure patterns")
                    score = 0.3
                elif len(failures) > 10:
                    weaknesses.append("High failure volume")
                    recommendations.append("Review failure trends and recovery effectiveness")
                    score = 0.5
                else:
                    strengths.append("No dominant failure patterns")
                    score = 0.8
            else:
                findings.append("No recent failures")
                score = 1.0
        else:
            findings.append("Failure recovery system not available")
            score = 0.0

        return AnalysisResult(
            category=AnalysisCategory.FAILURE_PATTERNS,
            score=score,
            confidence=ConfidenceLevel.HIGH,
            findings=findings,
            strengths=strengths,
            weaknesses=weaknesses,
            recommendations=recommendations,
        )

    def _analyze_learning_progress(self) -> AnalysisResult:
        """Analyze learning progress."""
        findings = []
        strengths = []
        weaknesses = []
        recommendations = []

        if self._autonomous_learning:
            # Would check learning pipeline status
            findings.append("Autonomous learning system integration available")
            score = 0.7
        else:
            findings.append("Autonomous learning not available")
            score = 0.0
            weaknesses.append("No autonomous learning integration")

        return AnalysisResult(
            category=AnalysisCategory.LEARNING_PROGRESS,
            score=score,
            confidence=ConfidenceLevel.MEDIUM,
            findings=findings,
            strengths=strengths,
            weaknesses=weaknesses,
            recommendations=recommendations,
        )

    def _analyze_knowledge_gaps(self) -> AnalysisResult:
        """Analyze knowledge gaps."""
        findings = []
        strengths = []
        weaknesses = []
        recommendations = []

        if self._memory_retrieval:
            # Would check knowledge coverage
            findings.append("Knowledge retrieval system available for gap analysis")
            score = 0.7
        else:
            findings.append("Unified memory retrieval not available")
            score = 0.0

        return AnalysisResult(
            category=AnalysisCategory.KNOWLEDGE_GAPS,
            score=score,
            confidence=ConfidenceLevel.MEDIUM,
            findings=findings,
            strengths=strengths,
            weaknesses=weaknesses,
            recommendations=recommendations,
        )

    def _analyze_decision_quality(self) -> AnalysisResult:
        """Analyze decision quality."""
        findings = []
        strengths = []
        weaknesses = []
        recommendations = []

        if self._decision_manager:
            stats = self._decision_manager.get_statistics()
            total = stats.get("total_decisions", 0)
            auto = stats.get("auto_executed", 0)
            review = stats.get("human_review_required", 0)

            if total > 0:
                auto_rate = auto / total
                review_rate = review / total
                findings.append(f"Decisions: {total}, Auto-executed: {auto_rate:.1%}, Required review: {review_rate:.1%}")

                if review_rate < 0.1 and auto_rate > 0.7:
                    strengths.append("High-quality autonomous decisions")
                    score = 0.9
                elif review_rate < 0.3:
                    strengths.append("Acceptable decision quality")
                    score = 0.7
                else:
                    weaknesses.append("High human review rate")
                    recommendations.append("Improve decision confidence or reduce risk")
                    score = 0.4
            else:
                findings.append("No decision history yet")
                score = 0.5
        else:
            findings.append("Decision manager not available")
            score = 0.0

        return AnalysisResult(
            category=AnalysisCategory.DECISION_QUALITY,
            score=score,
            confidence=ConfidenceLevel.HIGH if score > 0 else ConfidenceLevel.CRITICAL,
            findings=findings,
            strengths=strengths,
            weaknesses=weaknesses,
            recommendations=recommendations,
        )

    def _analyze_system_confidence(self) -> AnalysisResult:
        """Analyze system confidence."""
        findings = []
        strengths = []
        weaknesses = []
        recommendations = []

        # Aggregate confidence from multiple sources
        confidences = []

        if self._orchestrator and self._orchestrator.self_observer:
            perf = self._orchestrator.self_observer.get_performance_stats()
            confidences.append(perf.get("success_rate", 0.5))

        if self._decision_manager:
            stats = self._decision_manager.get_statistics()
            # Average confidence from history would be better
            confidences.append(0.7)  # Placeholder

        if confidences:
            avg_confidence = sum(confidences) / len(confidences)
            findings.append(f"Aggregated system confidence: {avg_confidence:.0%}")

            if avg_confidence >= 0.8:
                strengths.append("High system confidence")
                score = avg_confidence
            elif avg_confidence >= 0.6:
                strengths.append("Moderate system confidence")
                score = avg_confidence
            else:
                weaknesses.append("Low system confidence")
                recommendations.append("Investigate sources of low confidence")
                score = avg_confidence
        else:
            findings.append("No confidence data sources")
            score = 0.5

        return AnalysisResult(
            category=AnalysisCategory.SYSTEM_CONFIDENCE,
            score=score,
            confidence=ConfidenceLevel.MEDIUM,
            findings=findings,
            strengths=strengths,
            weaknesses=weaknesses,
            recommendations=recommendations,
        )

    def _analyze_operational_effectiveness(self) -> AnalysisResult:
        """Analyze overall operational effectiveness."""
        findings = []
        strengths = []
        weaknesses = []
        recommendations = []

        # Composite score from other categories
        # This is a meta-analysis
        findings.append("Operational effectiveness is a composite measure")

        # Would integrate multiple factors:
        # - Goal achievement rate
        # - Task completion rate
        # - Resource efficiency
        # - Learning velocity
        # - Failure recovery speed

        score = 0.7  # Placeholder composite

        return AnalysisResult(
            category=AnalysisCategory.OPERATIONAL_EFFECTIVENESS,
            score=score,
            confidence=ConfidenceLevel.MEDIUM,
            findings=findings,
            strengths=strengths,
            weaknesses=weaknesses,
            recommendations=recommendations,
        )

    # ============================================================
    # Event Handlers
    # ============================================================

    def _on_metric_event(self, event: Event) -> None:
        """Handle metric events for real-time updates."""
        pass  # Metrics recorded via observability

    def _on_decision_event(self, event: Event) -> None:
        """Handle decision events."""
        pass

    def _on_recovery_event(self, event: Event) -> None:
        """Handle recovery events."""
        pass

    def _on_learning_event(self, event: Event) -> None:
        """Handle learning events."""
        pass

    # ============================================================
    # Public API
    # ============================================================

    def get_latest_report(self) -> Optional[SelfAnalysisReport]:
        """Get the most recent analysis report."""
        with self._lock:
            return self._analysis_history[-1] if self._analysis_history else None

    def get_history(self, limit: int = 10) -> List[SelfAnalysisReport]:
        """Get analysis history."""
        with self._lock:
            return self._analysis_history[-limit:]

    def get_category_trend(self, category: AnalysisCategory) -> Dict[str, Any]:
        """Get trend for a specific category."""
        return self.get_trend(category)

    def get_all_trends(self) -> Dict[str, Any]:
        """Get trends for all categories."""
        return {
            cat.value: self.get_trend(cat)
            for cat in self._config.enabled_categories
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get analysis service statistics."""
        with self._lock:
            return {
                "running": self._running,
                "total_analyses": len(self._analysis_history),
                "enabled_categories": [c.value for c in self._config.enabled_categories],
                "interval_seconds": self._config.analysis_interval_seconds,
                "latest_report": self._analysis_history[-1].timestamp if self._analysis_history else None,
            }


# Global instance
_self_analysis: Optional[CentralizedSelfAnalysis] = None
_analysis_lock = threading.Lock()


def get_self_analysis(
    orchestrator: "Optional[WorkflowOrchestrator]" = None,
    decision_manager: Optional[DecisionManager] = None,
    world_model: Optional[WorldModel] = None,
    memory_retrieval: Optional[UnifiedRetrieval] = None,
    failure_recovery: Optional[RecoveryOrchestrator] = None,
    autonomous_learning: Optional[AutonomousLearningPipeline] = None,
    autonomy_manager: Optional[AutonomyManager] = None,
    config: Optional[AnalysisConfig] = None,
) -> CentralizedSelfAnalysis:
    """Get or create the global self-analysis instance."""
    global _self_analysis
    with _analysis_lock:
        if _self_analysis is None:
            _self_analysis = CentralizedSelfAnalysis(
                orchestrator=orchestrator,
                decision_manager=decision_manager,
                world_model=world_model,
                memory_retrieval=memory_retrieval,
                failure_recovery=failure_recovery,
                autonomous_learning=autonomous_learning,
                autonomy_manager=autonomy_manager,
                config=config,
            )
        return _self_analysis


def set_self_analysis(analysis: CentralizedSelfAnalysis) -> None:
    """Set the global self-analysis instance."""
    global _self_analysis
    with _analysis_lock:
        _self_analysis = analysis