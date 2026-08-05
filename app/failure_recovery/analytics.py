"""Recovery Analytics - Analytics for autonomous recovery behavior.

This module provides analytics for autonomous recovery behavior so Freya can
observe, measure, and improve recovery performance over time.

It analyzes historical recovery activity rather than performing recovery itself.
"""

import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional, Tuple
from collections import Counter

from app.failure_recovery.orchestrator import RecoveryOrchestrator, RecoveryResult, RecoveryStage
from app.failure_recovery.detector import FailureEvent, FailureType, FailureSeverity, Recoverability
from app.failure_recovery.analyzer import RootCause, CauseCategory
from app.core.events import get_event_bus, EventPriority
from app.core.observability import get_observability_hub, ComponentInfo, ComponentType
from app.core.logger import logger

logger = logging.getLogger(__name__)


class RecoveryAnalytics:
    """Analytics for autonomous recovery behavior."""

    def __init__(
        self,
        orchestrator: Optional[RecoveryOrchestrator] = None,
        event_bus: Optional[object] = None,
        observability: Optional[object] = None,
    ):
        """Initialize the recovery analytics.

        Args:
            orchestrator: RecoveryOrchestrator instance (uses global if not provided)
            event_bus: Optional EventBus instance (uses global if not provided)
            observability: Optional ObservabilityHub instance (uses global if not provided)
        """
        self.orchestrator = orchestrator or RecoveryOrchestrator()
        self._event_bus = event_bus or get_event_bus()
        self._observability = observability or get_observability_hub()

        # Register with observability
        self._register_with_observability()

        # Subscribe to recovery events to update metrics in real-time
        self._subscribe_to_events()

        # Cache for analytics (to avoid recomputation)
        self._analytics_cache: Dict[str, Any] = {}
        self._cache_timestamp: Optional[datetime] = None
        self._cache_ttl_seconds = 30  # Cache valid for 30 seconds

        logger.info("[RecoveryAnalytics] Initialized")

    def _register_with_observability(self) -> None:
        """Register this subsystem with the shared ObservabilityHub."""
        if self._observability:
            # Register health check
            from app.core.observability import HealthCheck
            self._observability.add_health_check(HealthCheck(
                name="recovery_analytics_health",
                component="recovery_analytics",
                check_func=self._health_check,
                interval_seconds=60.0,
            ))

            # Register component
            self._observability.register_component(ComponentInfo(
                name="RecoveryAnalytics",
                component_type=ComponentType.SERVICE,
                version="1.0.0",
                description="Analytics for autonomous recovery behavior",
                metadata={},
            ))

    def _health_check(self):
        """Health check for RecoveryAnalytics."""
        from app.core.observability import HealthResult, HealthStatus
        try:
            # Check if we have data
            history = self.orchestrator.get_recovery_history(limit=1)
            return HealthResult(
                name="recovery_analytics_health",
                component="recovery_analytics",
                status=HealthStatus.HEALTHY,
                message="RecoveryAnalytics operational",
                metadata={
                    "history_size": len(self.orchestrator.get_recovery_history(limit=1000)),
                }
            )
        except Exception as e:
            return HealthResult(
                name="recovery_analytics_health",
                component="recovery_analytics",
                status=HealthStatus.UNHEALTHY,
                message=f"Health check failed: {e}",
                metadata={"error": str(e)}
            )

    def _subscribe_to_events(self) -> None:
        """Subscribe to recovery events to update metrics."""
        # We could subscribe to events here, but for simplicity we'll compute on demand
        # In a high-frequency scenario, we would update incremental metrics
        pass

    def _get_cached_analytics(self, key: str) -> Optional[Any]:
        """Get cached analytics if still valid."""
        if self._cache_timestamp is None:
            return None
        if (datetime.now(timezone.utc) - self._cache_timestamp).total_seconds() > self._cache_ttl_seconds:
            self._analytics_cache.clear()
            self._cache_timestamp = None
            return None
        return self._analytics_cache.get(key)

    def _set_cached_analytics(self, key: str, value: Any) -> None:
        """Set cached analytics."""
        self._analytics_cache[key] = value
        self._cache_timestamp = datetime.now(timezone.utc)

    def get_recovery_analytics(self) -> Dict[str, Any]:
        """Get comprehensive recovery analytics.

        Returns:
            Dictionary with:
            - success_rate: Overall recovery success rate
            - failure_rate: Overall recovery failure rate
            - avg_recovery_time: Average recovery duration in seconds
            - avg_retries: Average number of retry attempts
            - recovery_frequency: Recoveries per hour
            - failures_by_subsystem: Failures grouped by subsystem/component
            - failures_by_category: Failures grouped by category/failure type
            - recovery_trend: Success rate over time (last 24h, 7d, 30d)
            - most_common_strategies: Most frequently used recovery strategies
            - strategy_success_rates: Success rate per recovery strategy
            - repeated_failures: Failures that occur repeatedly (same component/type)
            - failure_hotspots: Subsystems with highest failure rates
            - recovery_loop_detected: Whether recovery loops were detected
            - oscillating_failures: Whether oscillating failures detected
            - ineffective_strategies: Strategies with low success rates
            - recommendations: List of recommendations for improvement
        """
        # Check cache
        cached = self._get_cached_analytics("full_analytics")
        if cached is not None:
            return cached

        # Get recovery history
        history = self.orchestrator.get_recovery_history(limit=1000)  # Get last 1000 recoveries
        if not history:
            return self._empty_analytics()

        # Calculate basic metrics
        total = len(history)
        successful = sum(1 for r in history if r.success)
        failed = sum(1 for r in history if not r.success and not r.exhausted)
        exhausted = sum(1 for r in history if r.exhausted)

        success_rate = successful / total if total > 0 else 0.0
        failure_rate = (failed + exhausted) / total if total > 0 else 0.0

        # Calculate average recovery time and retries
        recovery_times = []
        retry_counts = []
        for record in history:
            if record.attempts:
                # For progressive recovery, use total duration
                recovery_times.append(record.duration_seconds)
                # Count total attempts across all strategies
                retry_counts.append(len(record.attempts) - 1)  # Subtract 1 for initial attempt
            else:
                recovery_times.append(record.duration_seconds)
                retry_counts.append(0)

        avg_recovery_time = sum(recovery_times) / len(recovery_times) if recovery_times else 0.0
        avg_retries = sum(retry_counts) / len(retry_counts) if retry_counts else 0.0

        # Calculate recovery frequency (recoveries per hour)
        if history:
            oldest = min(
                datetime.fromisoformat(attempt.timestamp.replace("Z", "+00:00"))
                for record in history
                for attempt in record.attempts
            )
            newest = max(
                datetime.fromisoformat(attempt.timestamp.replace("Z", "+00:00"))
                for record in history
                for attempt in record.attempts
            )
            time_span_hours = max(1.0, (newest - oldest).total_seconds() / 3600)
            recovery_frequency = total / time_span_hours
        else:
            recovery_frequency = 0.0

        # Group failures by subsystem/component
        failures_by_subsystem = defaultdict(int)
        failures_by_component = defaultdict(int)  # Component from FailureEvent
        failures_by_category = defaultdict(int)   # FailureType
        strategy_usage = defaultdict(int)
        strategy_success = defaultdict(lambda: [0, 0])  # [success, total]
        component_attempts = defaultdict(int)  # For failure rate calculation
        component_success = defaultdict(int)   # For success rate calculation

        for record in history:
            # Get the failure type from the first attempt (they should be the same for a recovery record)
            if record.attempts:
                failure_type = record.attempts[0].failure_event.failure_type.value
                component = record.attempts[0].failure_event.component
                failures_by_category[failure_type] += 1
                failures_by_component[component] += 1

                # Track strategy usage and success
                strategy = record.strategy_used.value
                strategy_usage[strategy] += 1
                strategy_success[strategy][1] += 1  # increment total
                if record.success:
                    strategy_success[strategy][0] += 1  # increment success

                # For component-level success rate
                component_attempts[component] += 1
                if record.success:
                    component_success[component] += 1

        # Calculate failure rates by subsystem (where we have attempts)
        failure_rate_by_subsystem = {}
        for component, attempts in component_attempts.items():
            successes = component_success.get(component, 0)
            failure_rate = (attempts - successes) / attempts if attempts > 0 else 0.0
            failure_rate_by_subsystem[component] = failure_rate

        # Find most common strategies
        most_common_strategies = sorted(
            strategy_usage.items(), key=lambda x: x[1], reverse=True
        )[:5]

        # Calculate strategy success rates
        strategy_success_rates = {}
        for strategy, (success, total) in strategy_success.items():
            strategy_success_rates[strategy] = success / total if total > 0 else 0.0

        # Identify ineffective strategies (success rate < 0.3 and used at least 3 times)
        ineffective_strategies = [
            strategy for strategy, rate in strategy_success_rates.items()
            if rate < 0.3 and strategy_usage.get(strategy, 0) >= 3
        ]

        # Find repeated failures (same component and failure type occurring multiple times)
        failure_instances = []
        for record in history:
            if record.attempts:
                attempt = record.attempts[0]  # First attempt represents the failure
                failure_instances.append((
                    attempt.failure_event.component,
                    attempt.failure_event.failure_type.value,
                    attempt.failure_event.event_id
                ))

        # Count occurrences of each (component, failure_type) pair
        failure_counts = Counter(
            (comp, ftype) for comp, ftype, _ in failure_instances
        )
        repeated_failures = [
            {"component": comp, "failure_type": ftype, "count": count}
            for (comp, ftype), count in failure_counts.items()
            if count > 1
        ]

        # Calculate recovery trend (success rate over time)
        now = datetime.now(timezone.utc)
        time_windows = {
            "1h": now - timedelta(hours=1),
            "24h": now - timedelta(days=1),
            "7d": now - timedelta(days=7),
            "30d": now - timedelta(days=30),
        }
        recovery_trend = {}
        for window_name, start_time in time_windows.items():
            window_history = []
            for record in history:
                # Check if any attempt in this record falls within the window
                if any(
                    datetime.fromisoformat(attempt.timestamp.replace("Z", "+00:00")) >= start_time
                    for attempt in record.attempts
                ):
                    window_history.append(record)
            if window_history:
                window_success = sum(1 for r in window_history if r.success)
                recovery_trend[window_name] = window_success / len(window_history)
            else:
                recovery_trend[window_name] = 0.0

        # Detect recovery loops (same strategy failing repeatedly for same failure)
        recovery_loop_detected = self._detect_recovery_loops(history)

        # Detect oscillating failures (failing, recovering, failing again quickly)
        oscillating_failures = self._detect_oscillating_failures(history)

        # Identify failure hotspots (components with high failure rate and high volume)
        failure_hotspots = [
            {"component": comp, "failure_rate": rate, "attempts": count}
            for comp, rate in failure_rate_by_subsystem.items()
            if count >= 5 and rate > 0.5  # At least 5 attempts and >50% failure rate
        ]
        failure_hotspots.sort(key=lambda x: x["failure_rate"], reverse=True)

        # Generate recommendations
        recommendations = self._generate_recommendations(
            ineffective_strategies, failure_hotspots, repeated_failures,
            recovery_loop_detected, oscillating_failures, strategy_success_rates
        )

        # Prepare result
        result = {
            "total_recoveries": total,
            "success_rate": success_rate,
            "failure_rate": failure_rate,
            "avg_recovery_time_seconds": avg_recovery_time,
            "avg_retries": avg_retries,
            "recovery_frequency_per_hour": recovery_frequency,
            "failures_by_subsystem": dict(failure_rate_by_subsystem),
            "failures_by_component": dict(failures_by_component),
            "failures_by_category": dict(failures_by_category),
            "recovery_trend": recovery_trend,
            "most_common_strategies": dict(most_common_strategies),
            "strategy_success_rates": strategy_success_rates,
            "repeated_failures": repeated_failures,
            "failure_hotspots": failure_hotspots,
            "recovery_loop_detected": recovery_loop_detected,
            "oscillating_failures_detected": oscillating_failures,
            "ineffective_strategies": ineffective_strategies,
            "recommendations": recommendations,
        }

        # Cache the result
        self._set_cached_analytics("full_analytics", result)

        # Emit event for observability
        self._emit_event("recovery_analytics_updated", {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_recoveries": total,
            "success_rate": success_rate,
        })

        # Update metrics in observability hub
        self._update_observability_metrics(result)

        return result

    def _empty_analytics(self) -> Dict[str, Any]:
        """Return empty analytics structure when no data is available."""
        return {
            "total_recoveries": 0,
            "success_rate": 0.0,
            "failure_rate": 0.0,
            "avg_recovery_time_seconds": 0.0,
            "avg_retries": 0.0,
            "recovery_frequency_per_hour": 0.0,
            "failures_by_subsystem": {},
            "failures_by_component": {},
            "failures_by_category": {},
            "recovery_trend": {"1h": 0.0, "24h": 0.0, "7d": 0.0, "30d": 0.0},
            "most_common_strategies": {},
            "strategy_success_rates": {},
            "repeated_failures": [],
            "failure_hotspots": [],
            "recovery_loop_detected": False,
            "oscillating_failures_detected": False,
            "ineffective_strategies": [],
            "recommendations": ["No recovery data available yet."],
        }

    def _detect_recovery_loops(self, history: List[Any]) -> bool:
        """Detect if there are recovery loops (same strategy failing repeatedly).

        Returns:
            True if a recovery loop is detected, False otherwise.
        """
        if len(history) < 3:
            return False

        # Look for sequences of 3+ failed attempts with the same strategy
        consecutive_failures = 0
        last_strategy = None

        # We need to look at individual attempts, not just recovery records
        all_attempts = []
        for record in history:
            for attempt in record.attempts:
                all_attempts.append({
                    "strategy": attempt.strategy_used.value,
                    "success": attempt.success,
                    "timestamp": attempt.timestamp
                })

        # Sort by timestamp
        all_attempts.sort(key=lambda x: x["timestamp"])

        for attempt in all_attempts:
            if not attempt["success"]:
                if attempt["strategy"] == last_strategy:
                    consecutive_failures += 1
                    if consecutive_failures >= 3:
                        return True
                else:
                    consecutive_failures = 1
                    last_strategy = attempt["strategy"]
            else:
                consecutive_failures = 0
                last_strategy = None

        return False

    def _detect_oscillating_failures(self, history: List[Any]) -> bool:
        """Detect oscillating failures (fail, recover, fail, recover in short time).

        Returns:
            True if oscillating pattern detected, False otherwise.
        """
        if len(history) < 4:
            return False

        # Look at success/failure pattern over time
        sorted_history = sorted(
            history,
            key=lambda r: r.attempts[0].timestamp if r.attempts else ""
        )

        # Look for pattern: fail, success, fail, success within short time window
        oscillations = 0
        for i in range(len(sorted_history) - 3):
            window = sorted_history[i:i+4]
            # Check if pattern is [fail, success, fail, success]
            if (not window[0].success and window[1].success and
                not window[2].success and window[3].success):
                # Check time span of window
                try:
                    start = datetime.fromisoformat(
                        window[0].attempts[0].timestamp.replace("Z", "+00:00")
                    )
                    end = datetime.fromisoformat(
                        window[3].attempts[-1].timestamp.replace("Z", "+00:00")
                    )
                    if (end - start).total_seconds() < 300:  # Within 5 minutes
                        oscillations += 1
                except Exception:
                    pass

        return oscillations >= 2  # At least two oscillations

    def _generate_recommendations(
        self,
        ineffective_strategies: List[str],
        failure_hotspots: List[Dict],
        repeated_failures: List[Dict],
        recovery_loop_detected: bool,
        oscillating_failures: bool,
        strategy_success_rates: Dict[str, float]
    ) -> List[str]:
        """Generate recommendations based on analysis.

        Returns:
            List of recommendation strings.
        """
        recommendations = []

        # Recommendations for ineffective strategies
        if ineffective_strategies:
            strategies_str = ", ".join(ineffective_strategies)
            recommendations.append(
                f"Consider reviewing or adjusting these ineffective recovery strategies: {strategies_str}"
            )

        # Recommendations for failure hotspots
        if failure_hotspots:
            hotspot = failure_hotspots[0]  # Worst one
            recommendations.append(
                f"Component '{hotspot['component']}' has high failure rate ({hotspot['failure_rate']:.1%}) "
                f"over {hotspot['attempts']} attempts. Consider preventive maintenance or design improvements."
            )

        # Recommendations for repeated failures
        if repeated_failures:
            repeat = repeated_failures[0]  # Most frequent
            recommendations.append(
                f"Repeated failure detected: {repeat['component']} experiencing "
                f"{repeat['failure_type']} {repeat['count']} times. Investigate root cause."
            )

        # Recommendations for recovery loops
        if recovery_loop_detected:
            recommendations.append(
                "Recovery loop detected (same strategy failing repeatedly). "
                "Consider escalating strategies faster or adding alternative approaches."
            )

        # Recommendations for oscillating failures
        if oscillating_failures:
            recommendations.append(
                "Oscillating failure pattern detected (fail/recover/fail/recover). "
                "Check for environmental factors or intermittent issues."
            )

        # Recommendations based on low success strategies
        low_success_strategies = [
            s for s, rate in strategy_success_rates.items()
            if rate < 0.5 and s not in ineffective_strategies
        ]
        if low_success_strategies:
            strategies_str = ", ".join(low_success_strategies[:3])  # Top 3
            recommendations.append(
                f"These strategies have suboptimal success rates: {strategies_str}. "
                "Consider refinement or better targeting."
            )

        # General recommendations if none specific
        if not recommendations:
            if self._get_cached_analytics("full_analytics"):
                data = self._get_cached_analytics("full_analytics")
                if data["success_rate"] > 0.9:
                    recommendations.append("Recovery performance is excellent. Keep up the good work!")
                elif data["success_rate"] > 0.7:
                    recommendations.append("Recovery performance is good. Minor improvements possible.")
                else:
                    recommendations.append("Recovery performance needs improvement. Consider reviewing failure patterns and strategy effectiveness.")

        return recommendations

    def _emit_event(self, event_name: str, data: Dict[str, Any]) -> None:
        """Emit an event to the EventBus."""
        try:
            self._event_bus.emit(
                name=event_name,
                data=data,
                source="RecoveryAnalytics",
                priority=EventPriority.NORMAL,
            )
        except Exception as e:
            logger.warning(f"[RecoveryAnalytics] Failed to emit event {event_name}: {e}")

    def _update_observability_metrics(self, analytics: Dict[str, Any]) -> None:
        """Update metrics in the ObservabilityHub."""
        try:
            # Record key metrics
            self._observability.record_metric("recovery.success_rate", analytics["success_rate"])
            self._observability.record_metric("recovery.failure_rate", analytics["failure_rate"])
            self._observability.record_metric("recovery.avg_recovery_time_seconds",
                                              analytics["avg_recovery_time_seconds"])
            self._observability.record_metric("recovery.avg_retries", analytics["avg_retries"])
            self._observability.record_metric("recovery.frequency_per_hour",
                                              analytics["recovery_frequency_per_hour"])

            # Record strategy success rates
            for strategy, rate in analytics["strategy_success_rates"].items():
                self._observability.record_metric(
                    f"recovery.strategy_success.{strategy}", rate
                )

            # Record failure rates by component (top 5)
            sorted_components = sorted(
                analytics["failures_by_subsystem"].items(),
                key=lambda x: x[1],
                reverse=True
            )[:5]
            for component, rate in sorted_components:
                # Sanitize component name for metric
                safe_component = "".join(c if c.isalnum() else "_" for c in component)
                self._observability.record_metric(
                    f"recovery.failure_rate.component.{safe_component}", rate
                )
        except Exception as e:
            logger.warning(f"[RecoveryAnalytics] Failed to update observability metrics: {e}")

    def get_recovery_recommendations(self) -> List[str]:
        """Get recovery-specific recommendations.

        Returns:
            List of recommendation strings.
        """
        analytics = self.get_recovery_analytics()
        return analytics.get("recommendations", [])

    def detect_recovery_patterns(self) -> Dict[str, bool]:
        """Detect specific recovery patterns.

        Returns:
            Dictionary indicating which patterns were detected.
        """
        analytics = self.get_recovery_analytics()
        return {
            "recovery_loop_detected": analytics.get("recovery_loop_detected", False),
            "oscillating_failures_detected": analytics.get("oscillating_failures_detected", False),
            "ineffective_strategies_detected": bool(analytics.get("ineffective_strategies", [])),
        }


# Convenience functions for quick recovery
def recover_from_failure(
    failure_event: FailureEvent,
    root_causes: Optional[List[RootCause]] = None,
    context: Optional[Dict[str, Any]] = None,
    **orchestrator_kwargs,
) -> RecoveryResult:
    """Quick recovery - creates orchestrator, runs recovery, returns result."""
    orchestrator = RecoveryOrchestrator(**orchestrator_kwargs)
    return orchestrator.recover(failure_event, root_causes, context)


def recover_progressive(
    failure_event: FailureEvent,
    root_causes: Optional[List[RootCause]] = None,
    context: Optional[Dict[str, Any]] = None,
    **orchestrator_kwargs,
) -> RecoveryResult:
    """Quick progressive recovery - creates orchestrator, runs progressive recovery."""
    orchestrator = RecoveryOrchestrator(**orchestrator_kwargs)
    return orchestrator.recover_progressive(failure_event, root_causes, context)