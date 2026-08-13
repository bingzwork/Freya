"""Watchdog - Observes system events and metrics, feeds LearningPipeline."""

import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from app.core.events import EventBus, Event, get_event_bus
from app.core.observability import ObservabilityHub, get_observability_hub
from app.learning.pipeline import LearningPipeline, create_learning_pipeline
from app.core.background_jobs import BackgroundJobService, get_job_service, JobTriggerConfig, JobTriggerType

from .models import (
    WatchdogObservation,
    WatchdogEventType,
    WatchdogSeverity,
    AutonomyConfig,
)


class Watchdog:
    """
    Watchdog component for Autonomy + Observation.
    
    Receives system events from EventBus and metrics/health from ObservabilityHub.
    Feeds observations to LearningPipeline.
    Uses BackgroundJobService for periodic health checks.
    """

    def __init__(
        self,
        config: Optional[AutonomyConfig] = None,
        event_bus: Optional[EventBus] = None,
        observability: Optional[ObservabilityHub] = None,
        learning_pipeline: Optional[LearningPipeline] = None,
        job_service: Optional[BackgroundJobService] = None,
    ):
        self.config = config or AutonomyConfig()
        self._event_bus = event_bus or get_event_bus()
        self._observability = observability or get_observability_hub()
        self._learning_pipeline = learning_pipeline
        self._job_service = job_service
        
        self._lock = threading.RLock()
        self._running = False
        self._shutdown_event = threading.Event()
        
        # Subscription IDs for cleanup
        self._subscription_ids: List[str] = []
        self._health_check_job_id: Optional[str] = None
        
        # Callbacks for custom handling
        self._observation_handlers: List[Callable[[WatchdogObservation], None]] = []

    def start(self) -> None:
        """Start the watchdog."""
        if self._running:
            return
            
        if not self.config.watchdog_enabled:
            return
            
        self._running = True
        self._shutdown_event.clear()
        
        # Subscribe to EventBus events
        self._subscribe_to_events()
        
        # Register health check with ObservabilityHub
        self._register_health_checks()
        
        # Schedule periodic health check job if using BackgroundJobService
        if self.config.use_background_job_service and self._job_service:
            self._schedule_periodic_health_check()
            
        # Also start a local monitoring thread as backup
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="WatchdogMonitor"
        )
        self._monitor_thread.start()

    def stop(self) -> None:
        """Stop the watchdog."""
        if not self._running:
            return
            
        self._running = False
        self._shutdown_event.set()
        
        # Unsubscribe from EventBus
        for sub_id in self._subscription_ids:
            try:
                self._event_bus.unsubscribe(sub_id)
            except Exception:
                pass
        self._subscription_ids.clear()
        
        # Cancel scheduled job
        if self._health_check_job_id and self._job_service:
            try:
                self._job_service.remove_job(self._health_check_job_id)
            except Exception:
                pass
                
        if hasattr(self, '_monitor_thread') and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5.0)

    def _subscribe_to_events(self) -> None:
        """Subscribe to relevant EventBus events."""
        for pattern in self.config.watchdog_event_subscriptions:
            sub_id = self._event_bus.subscribe(
                pattern,
                lambda event, p=pattern: self._on_event(event, p),
                priority=0,
                async_mode=True,
            )
            self._subscription_ids.append(sub_id)

    def _on_event(self, event: Event, pattern: str) -> None:
        """Handle incoming EventBus event."""
        try:
            # Create observation from event
            observation = WatchdogObservation(
                event_type=WatchdogEventType.SYSTEM_EVENT,
                severity=self._determine_severity(event),
                source="EventBus",
                component=event.source,
                message=f"Event: {event.name}",
                details={
                    "event_name": event.name,
                    "event_data": event.data,
                    "event_priority": event.priority.name if event.priority else "NORMAL",
                    "matched_pattern": pattern,
                    "event_id": event.event_id,
                },
                tags=["event_bus", event.name.split('.')[0] if '.' in event.name else event.name],
            )
            self._process_observation(observation)
        except Exception as e:
            # Don't let watchdog errors propagate
            pass

    def _determine_severity(self, event: Event) -> WatchdogSeverity:
        """Determine severity from event."""
        if event.priority:
            priority_name = event.priority.name if hasattr(event.priority, 'name') else str(event.priority)
            if priority_name == "CRITICAL":
                return WatchdogSeverity.CRITICAL
            elif priority_name == "HIGH":
                return WatchdogSeverity.WARNING
        return WatchdogSeverity.INFO

    def _register_health_checks(self) -> None:
        """Register health check callbacks with ObservabilityHub."""
        # The ObservabilityHub runs its own checks - we listen for results
        # This is a passive integration - we get health data via events or polling
        pass

    def _schedule_periodic_health_check(self) -> None:
        """Schedule periodic health check via BackgroundJobService."""
        trigger = JobTriggerConfig(
            type=JobTriggerType.RECURRING,
            interval_seconds=self.config.self_initiated_check_interval_seconds,
        )
        self._health_check_job_id = self._job_service.schedule(
            job_id="watchdog_health_check",
            func=self._periodic_health_check,
            trigger=trigger,
            name="Watchdog Periodic Health Check",
        )

    def _periodic_health_check(self) -> None:
        """Perform periodic health check."""
        try:
            # Get overall health from ObservabilityHub
            health = self._observability.get_health()
            
            # Create observations for degraded/unhealthy components
            if health.get("status") == "unhealthy":
                self._create_observation(
                    event_type=WatchdogEventType.HEALTH_CHECK,
                    severity=WatchdogSeverity.CRITICAL,
                    component="system",
                    message="System health is unhealthy",
                    details=health,
                )
            elif health.get("status") == "degraded":
                self._create_observation(
                    event_type=WatchdogEventType.HEALTH_CHECK,
                    severity=WatchdogSeverity.WARNING,
                    component="system",
                    message="System health is degraded",
                    details=health,
                )
                
            # Check individual components
            for comp in self._observability.list_components():
                if comp.get("status") == "unhealthy":
                    self._create_observation(
                        event_type=WatchdogEventType.HEALTH_CHECK,
                        severity=WatchdogSeverity.CRITICAL,
                        component=comp.get("name", "unknown"),
                        message=f"Component {comp.get('name')} is unhealthy",
                        details=comp,
                    )
                elif comp.get("status") == "degraded":
                    self._create_observation(
                        event_type=WatchdogEventType.HEALTH_CHECK,
                        severity=WatchdogSeverity.WARNING,
                        component=comp.get("name", "unknown"),
                        message=f"Component {comp.get('name')} is degraded",
                        details=comp,
                    )
        except Exception:
            raise

    def _monitor_loop(self) -> None:
        """Background monitoring loop as fallback."""
        while not self._shutdown_event.is_set():
            try:
                self._periodic_health_check()
                # Also check for metric alerts
                self._check_metric_alerts()
            except Exception:
                pass
            # Sleep in small chunks to allow quick shutdown
            for _ in range(60):
                if self._shutdown_event.is_set():
                    break
                time.sleep(1.0)

    def _check_metric_alerts(self) -> None:
        """Check for metric alerts from ObservabilityHub."""
        try:
            alerts = self._observability.get_active_alerts()
            for alert in alerts:
                severity = WatchdogSeverity.WARNING
                if alert.get("severity") == "critical":
                    severity = WatchdogSeverity.CRITICAL
                    
                self._create_observation(
                    event_type=WatchdogEventType.METRIC_ALERT,
                    severity=severity,
                    component=alert.get("rule", "unknown"),
                    message=f"Metric alert: {alert.get('message', 'Unknown')}",
                    details=alert,
                )
        except Exception:
            pass

    def _create_observation(
        self,
        event_type: WatchdogEventType,
        severity: WatchdogSeverity,
        component: str,
        message: str,
        details: Dict[str, Any],
        source: str = "Watchdog",
        tags: Optional[List[str]] = None,
    ) -> WatchdogObservation:
        """Create and process a watchdog observation."""
        observation = WatchdogObservation(
            event_type=event_type,
            severity=severity,
            source=source,
            component=component,
            message=message,
            details=details,
            tags=tags or [],
        )
        self._process_observation(observation)
        return observation

    def _process_observation(self, observation: WatchdogObservation) -> None:
        """Process an observation - feed to LearningPipeline and call handlers."""
        # Feed to LearningPipeline if available
        if self._learning_pipeline:
            try:
                candidate_data = observation.to_learning_candidate()
                from app.learning.models import LearningCandidate, LearningCandidateType
                candidate = LearningCandidate(
                    candidate_type=candidate_data["candidate_type"],
                    source_component=candidate_data["source_component"],
                    raw_observation=candidate_data["raw_observation"],
                    context=candidate_data["context"],
                    tags=candidate_data["tags"],
                )
                # Run pipeline asynchronously to avoid blocking
                threading.Thread(
                    target=lambda: self._learning_pipeline.run(candidate),
                    daemon=True,
                    name=f"Watchdog-LearningPipeline-{observation.id[:8]}"
                ).start()
            except Exception:
                pass
                
        # Call registered handlers
        for handler in self._observation_handlers:
            try:
                handler(observation)
            except Exception:
                pass

    def add_observation_handler(self, handler: Callable[[WatchdogObservation], None]) -> None:
        """Add a custom observation handler."""
        with self._lock:
            self._observation_handlers.append(handler)

    def observe_task_stalled(self, task_id: str, details: Dict[str, Any]) -> None:
        """Report a stalled task observation."""
        self._create_observation(
            event_type=WatchdogEventType.TASK_STALLED,
            severity=WatchdogSeverity.WARNING,
            component="WorkflowOrchestrator",
            message=f"Task stalled: {task_id}",
            details=details,
            tags=["task", "stalled"],
        )

    def observe_task_failed(self, task_id: str, error: str, details: Dict[str, Any]) -> None:
        """Report a failed task observation."""
        self._create_observation(
            event_type=WatchdogEventType.TASK_FAILED,
            severity=WatchdogSeverity.CRITICAL,
            component="WorkflowOrchestrator",
            message=f"Task failed: {task_id}",
            details={"error": error, **details},
            tags=["task", "failed"],
        )

    def observe_goal_stalled(self, goal_id: str, details: Dict[str, Any]) -> None:
        """Report a stalled goal observation."""
        self._create_observation(
            event_type=WatchdogEventType.GOAL_STALLED,
            severity=WatchdogSeverity.WARNING,
            component="GoalManager",
            message=f"Goal stalled: {goal_id}",
            details=details,
            tags=["goal", "stalled"],
        )

    def observe_goal_failed(self, goal_id: str, error: str, details: Dict[str, Any]) -> None:
        """Report a failed goal observation."""
        self._create_observation(
            event_type=WatchdogEventType.GOAL_FAILED,
            severity=WatchdogSeverity.CRITICAL,
            component="GoalManager",
            message=f"Goal failed: {goal_id}",
            details={"error": error, **details},
            tags=["goal", "failed"],
        )

    def observe_resource_pressure(self, resource: str, usage: float, threshold: float) -> None:
        """Report resource pressure observation."""
        severity = WatchdogSeverity.CRITICAL if usage > threshold * 1.2 else WatchdogSeverity.WARNING
        self._create_observation(
            event_type=WatchdogEventType.RESOURCE_PRESSURE,
            severity=severity,
            component="System",
            message=f"High {resource} usage: {usage:.1f}% (threshold: {threshold:.1f}%)",
            details={"resource": resource, "usage": usage, "threshold": threshold},
            tags=["resource", resource],
        )

    def set_learning_pipeline(self, pipeline: LearningPipeline) -> None:
        """Set the learning pipeline (for late binding)."""
        self._learning_pipeline = pipeline

    def is_running(self) -> bool:
        """Check if watchdog is running."""
        return self._running