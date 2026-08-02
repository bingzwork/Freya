"""Knowledge Maintenance Orchestrator for Software Engineering Knowledge.

Coordinates knowledge consolidation, ranking, updating, and scheduling
to maintain a high-quality, non-redundant knowledge base.
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

from app.software_engineering_knowledge.consolidation import (
    ConsolidationEngine,
    ConsolidationConfig,
    ConsolidationResult
)
from app.software_engineering_knowledge.ranking import (
    EngineeringRankingEngine,
    create_engineering_ranker
)
from app.software_engineering_knowledge.validation import (
    KnowledgeValidator,
    ValidationConfig
)
from app.software_engineering_knowledge.storage import get_knowledge_storage
from app.software_engineering_knowledge.update_detector import (
    UpdateDetector,
    UpdateCheckConfig,
    UpdateAssessment,
    UpdateDetectionResult
)
from app.core.logger import logger

# Shared infrastructure imports
from app.core.events import get_event_bus
from app.core.background_jobs import get_job_service
from app.core.background_jobs import JobTriggerConfig, JobTriggerType, JobPriority
from app.core.observability import get_observability_hub, HealthCheck, HealthResult, HealthStatus, ComponentInfo, ComponentType


@dataclass
class MaintenanceConfig:
    """Configuration for knowledge maintenance operations."""
    # Consolidation settings
    consolidation_enabled: bool = True
    consolidation_config: Optional[ConsolidationConfig] = None

    # Ranking settings
    ranking_enabled: bool = True
    ranking_config: Optional[Any] = None  # Using Any to avoid circular imports

    # Validation settings
    validation_enabled: bool = True
    validation_config: Optional[ValidationConfig] = None

    # Update detection settings
    update_detection_enabled: bool = True
    update_detection_config: Optional[UpdateCheckConfig] = None
    update_interval_hours: int = 12  # How often to run update detection

    # Scheduling
    auto_run_enabled: bool = False
    consolidation_interval_hours: int = 24
    ranking_interval_hours: int = 6
    validation_interval_hours: int = 12

    # Thresholds
    min_confidence_after_maintenance: float = 0.6
    max_consolidation_runtime_minutes: int = 30


@dataclass
class MaintenanceResult:
    """Result of a maintenance cycle."""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    consolidation: Optional[ConsolidationResult] = None
    validation_stats: Optional[dict] = None
    update_detection: Optional[UpdateDetectionResult] = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0


class MaintenanceOrchestrator:
    """Orchestrates knowledge maintenance operations."""

    def __init__(
        self,
        config: Optional[MaintenanceConfig] = None,
        storage_path: Optional[str] = None,
        event_bus: Optional[object] = None,
        job_service: Optional[object] = None,
        observability: Optional[object] = None,
    ):
        self.config = config or MaintenanceConfig()
        self.storage_path = storage_path
        self.storage = get_knowledge_storage(storage_path) if storage_path else get_knowledge_storage()

        # Shared infrastructure
        self._event_bus = event_bus or get_event_bus()
        self._job_service = job_service or get_job_service()
        self._observability = observability or get_observability_hub()

        # Initialize components
        if self.config.consolidation_enabled:
            self.consolidation_engine = ConsolidationEngine(
                self.config.consolidation_config,
                storage_path,
                event_bus=self._event_bus,
                job_service=self._job_service,
                observability=self._observability,
            )
        else:
            self.consolidation_engine = None

        if self.config.ranking_enabled:
            self.ranking_engine = create_engineering_ranker(storage_path)
        else:
            self.ranking_engine = None

        if self.config.validation_enabled:
            self.validator = KnowledgeValidator(
                self.config.validation_config,
                storage_path
            )
        else:
            self.validator = None

        if self.config.update_detection_enabled:
            self.update_detector = UpdateDetector(
                self.config.update_detection_config,
                storage_path
            )
        else:
            self.update_detector = None

        # Register with observability
        self._register_with_observability()

        # Schedule maintenance using BackgroundJobService
        self._schedule_maintenance_jobs()

        logger.info("MaintenanceOrchestrator initialized")

    def _register_with_observability(self) -> None:
        """Register this subsystem with the shared ObservabilityHub."""
        if self._observability:
            self._observability.add_health_check(HealthCheck(
                name="maintenance_orchestrator_health",
                component="software_engineering_knowledge",
                check_func=self._health_check,
                interval_seconds=60.0,
            ))

            # Register component
            self._observability.register_component(ComponentInfo(
                name="MaintenanceOrchestrator",
                component_type=ComponentType.SERVICE,
                version="1.0.0",
                description="Orchestrates knowledge maintenance operations",
                metadata={
                    "consolidation_enabled": self.config.consolidation_enabled,
                    "validation_enabled": self.config.validation_enabled,
                    "update_detection_enabled": self.config.update_detection_enabled,
                    "ranking_enabled": self.config.ranking_enabled,
                },
            ))

    def _health_check(self) -> HealthResult:
        """Health check for MaintenanceOrchestrator."""
        try:
            components = {
                "consolidation_engine": self.consolidation_engine is not None,
                "ranking_engine": self.ranking_engine is not None,
                "validator": self.validator is not None,
                "update_detector": self.update_detector is not None,
            }
            return HealthResult(
                name="maintenance_orchestrator_health",
                component="software_engineering_knowledge",
                status=HealthStatus.HEALTHY,
                message="MaintenanceOrchestrator operational",
                metadata={"components": components},
            )
        except Exception as e:
            return HealthResult(
                name="maintenance_orchestrator_health",
                component="software_engineering_knowledge",
                status=HealthStatus.UNHEALTHY,
                message=f"Health check failed: {e}",
                metadata={"error": str(e)}
            )

    def _publish_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Publish an event to the EventBus."""
        try:
            self._event_bus.emit(event_type, data)
        except Exception:
            # Don't let event publishing break the system
            pass

    def _schedule_maintenance_jobs(self) -> None:
        """Schedule periodic maintenance jobs using BackgroundJobService."""
        if not self._job_service:
            return

        # Consolidation job
        if self.config.consolidation_enabled and self.config.auto_run_enabled:
            trigger = JobTriggerConfig(
                type=JobTriggerType.RECURRING,
                interval_seconds=self.config.consolidation_interval_hours * 3600,
            )
            self._job_service.schedule(
                job_id="knowledge_maintenance_consolidation",
                func=lambda: self.run_consolidation_only(),
                trigger=trigger,
                name="Knowledge Consolidation",
                priority=JobPriority.LOW,
            )

        # Validation job
        if self.config.validation_enabled and self.config.auto_run_enabled:
            trigger = JobTriggerConfig(
                type=JobTriggerType.RECURRING,
                interval_seconds=self.config.validation_interval_hours * 3600,
            )
            self._job_service.schedule(
                job_id="knowledge_maintenance_validation",
                func=lambda: self.validate_knowledge_base(),
                trigger=trigger,
                name="Knowledge Validation",
                priority=JobPriority.LOW,
            )

        # Update detection job
        if self.config.update_detection_enabled and self.config.auto_run_enabled:
            trigger = JobTriggerConfig(
                type=JobTriggerType.RECURRING,
                interval_seconds=self.config.update_interval_hours * 3600,
            )
            self._job_service.schedule(
                job_id="knowledge_maintenance_update_detection",
                func=lambda: self.update_detector.detect_updates() if self.update_detector else None,
                trigger=trigger,
                name="Knowledge Update Detection",
                priority=JobPriority.LOW,
            )

    def run_maintenance_cycle(self) -> MaintenanceResult:
        """Run a full maintenance cycle: consolidation, validation, ranking.

        Returns:
            MaintenanceResult with outcomes of each operation.
        """
        import time
        start_time = time.time()
        result = MaintenanceResult()

        try:
            logger.info("Starting knowledge maintenance cycle")

            # Run validation first to assess current state
            if self.config.validation_enabled and self.validator:
                try:
                    result.validation_stats = self.validator.get_validation_stats()
                    logger.info(f"Validation stats: {result.validation_stats}")
                except Exception as e:
                    error_msg = f"Validation failed: {e}"
                    logger.error(error_msg)
                    result.errors.append(error_msg)

            # Run consolidation
            if self.config.consolidation_enabled and self.consolidation_engine:
                try:
                    # Check if we should run based on time since last run
                    if self._should_run_consolidation():
                        result.consolidation = self.consolidation_engine.consolidate()
                        logger.info(f"Consolidation completed: {result.consolidation}")
                    else:
                        logger.info("Skipping consolidation - not yet due")
                except Exception as e:
                    error_msg = f"Consolidation failed: {e}"
                    logger.error(error_msg)
                    result.errors.append(error_msg)

            # Note: Ranking is typically done at query time, not as a batch process
            # But we could run a ranking refresh if needed
            if self.config.ranking_enabled and self.ranking_engine:
                try:
                    # For now, just verify the ranking engine is working
                    # In a full implementation, we might update cached ranks or similar
                    logger.info("Ranking engine is ready")
                except Exception as e:
                    warning_msg = f"Ranking check warning: {e}"
                    logger.warning(warning_msg)
                    result.warnings.append(warning_msg)

            # Update detection
            if self.config.update_detection_enabled and self.update_detector:
                try:
                    # Check if we should run based on time since last run
                    if self._should_run_update_detection():
                        result.update_detection = self.update_detector.detect_updates()
                        logger.info(f"Update detection completed: {len(result.update_detection.stale_items)} stale items found")
                    else:
                        logger.info("Skipping update detection - not yet due")
                except Exception as e:
                    error_msg = f"Update detection failed: {e}"
                    logger.error(error_msg)
                    result.errors.append(error_msg)

        except Exception as e:
            error_msg = f"Maintenance cycle failed: {e}"
            logger.error(error_msg)
            result.errors.append(error_msg)

        result.duration_seconds = time.time() - start_time
        logger.info(f"Maintenance cycle completed in {result.duration_seconds:.2f}s")

        # Publish event
        self._publish_event("software_engineering_knowledge.maintenance_cycle_completed", {
            "consolidation": result.consolidation.duplicates_merged if result.consolidation else 0,
            "validation_stats": result.validation_stats,
            "update_detection_stale_count": len(result.update_detection.stale_items) if result.update_detection else 0,
            "errors": len(result.errors),
            "warnings": len(result.warnings),
            "duration_seconds": result.duration_seconds,
        })

        return result

    def _should_run_consolidation(self) -> bool:
        """Check if consolidation should run based on time since last run.

        For now, we'll implement a simple time-based check.
        In a production system, we might store the last run time in a file or database.
        """
        # For this implementation, we'll allow it to run every time
        # A more sophisticated implementation would track last run time
        return True

    def _should_run_update_detection(self) -> bool:
        """Check if update detection should run based on time since last run.

        For now, we'll implement a simple time-based check.
        In a production system, we might store the last run time in a file or database.
        """
        # For this implementation, we'll allow it to run every time
        # A more sophisticated implementation would track last run time
        return True

    def run_consolidation_only(self) -> Optional[ConsolidationResult]:
        """Run only the consolidation process.

        Returns:
            ConsolidationResult if consolidation was run, None if skipped or disabled.
        """
        if not self.config.consolidation_enabled or not self.consolidation_engine:
            return None

        if self._should_run_consolidation():
            return self.consolidation_engine.consolidate()
        else:
            return None

    def validate_knowledge_base(self) -> Optional[dict]:
        """Run validation on the knowledge base.

        Returns:
            Validation statistics if validation was run, None if disabled.
        """
        if not self.config.validation_enabled or not self.validator:
            return None

        return self.validator.get_validation_stats()

    def get_maintenance_status(self) -> dict[str, any]:
        """Get current maintenance status and statistics."""
        status = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "config": {
                "consolidation_enabled": self.config.consolidation_enabled,
                "ranking_enabled": self.config.ranking_enabled,
                "validation_enabled": self.config.validation_enabled,
                "update_detection_enabled": self.config.update_detection_enabled,
                "auto_run_enabled": self.config.auto_run_enabled,
            },
            "components": {
                "consolidation_engine": self.consolidation_engine is not None,
                "ranking_engine": self.ranking_engine is not None,
                "validator": self.validator is not None,
            }
        }

        # Add consolidation stats if available
        if self.consolidation_engine:
            status["consolidation_stats"] = self.consolidation_engine.get_consolidation_stats()

        # Add validation stats if available
        if self.validator:
            try:
                status["validation_stats"] = self.validator.get_validation_stats()
            except Exception as e:
                status["validation_error"] = str(e)

        # Add update detection stats if available
        if self.update_detector:
            try:
                status["update_detection_stats"] = self.update_detector.get_stale_items_summary()
            except Exception as e:
                status["update_detection_error"] = str(e)

        return status


# NOTE: MaintenanceScheduler has been DEPRECATED in favor of BackgroundJobService.
# The old MaintenanceScheduler class that used asyncio loops for scheduling
# has been replaced by the unified BackgroundJobService which handles all
# recurring/one-time/cron jobs across the system.
# If you need the old asyncio-based scheduler for legacy compatibility,
# it can be re-implemented but is no longer the recommended approach.

def create_maintenance_system(
    config: Optional[MaintenanceConfig] = None,
    storage_path: Optional[str] = None,
    event_bus: Optional[object] = None,
    job_service: Optional[object] = None,
    observability: Optional[object] = None,
) -> MaintenanceOrchestrator:
    """Factory function to create a maintenance system.

    Args:
        config: Configuration for the maintenance system
        storage_path: Path to knowledge storage
        event_bus: Optional EventBus instance (uses global if not provided)
        job_service: Optional BackgroundJobService instance (uses global if not provided)
        observability: Optional ObservabilityHub instance (uses global if not provided)

    Returns:
        Configured MaintenanceOrchestrator instance
    """
    return MaintenanceOrchestrator(
        config=config,
        storage_path=storage_path,
        event_bus=event_bus,
        job_service=job_service,
        observability=observability,
    )


def create_maintenance_scheduler(
    orchestrator: MaintenanceOrchestrator,
    check_interval_seconds: int = 3600
) -> None:
    """Factory function to create a maintenance scheduler (DEPRECATED).

    This function is kept for backward compatibility but returns None
    since scheduling is now handled by BackgroundJobService via
    MaintenanceOrchestrator._schedule_maintenance_jobs().

    Args:
        orchestrator: The MaintenanceOrchestrator instance
        check_interval_seconds: How often to check for scheduled tasks (unused)

    Returns:
        None - use BackgroundJobService instead
    """
    logger.warning("create_maintenance_scheduler is deprecated. "
                   "Use BackgroundJobService via MaintenanceOrchestrator instead.")
    return None