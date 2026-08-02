"""Reflection engine for generating self-reflection records after task completion.

This module provides functionality to create structured reflection records
that capture successes, failures, root causes, lessons learned, and
recommendations from completed tasks.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.logger import logger
from app.evaluation.models import EvaluationResult
from app.software_engineering_knowledge.models import (
    EngineeringDomain,
    EngineeringKnowledgeItem,
    EngineeringKnowledgeType,
    KnowledgeSource,
    ValidationStatus,
)
from app.software_engineering_knowledge.storage import get_knowledge_storage

# Shared infrastructure imports
from app.core.events import get_event_bus
from app.core.background_jobs import get_job_service
from app.core.background_jobs import JobTriggerConfig, JobTriggerType, JobPriority
from app.core.observability import get_observability_hub, ComponentInfo, ComponentType, HealthCheck, HealthResult, HealthStatus


@dataclass
class ReflectionContext:
    """Context information for generating a reflection."""
    task_description: str
    original_request: str
    outcome: str  # success, failure, partial
    eval_result: EvaluationResult
    goal_id: Optional[str] = None
    plan_id: Optional[str] = None
    task_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class ReflectionEngine:
    """Engine for generating reflection records from task completion context."""

    def __init__(
        self,
        storage_path: Optional[str] = None,
        event_bus: Optional[object] = None,
        job_service: Optional[object] = None,
        observability: Optional[object] = None,
    ):
        """Initialize the reflection engine.

        Args:
            storage_path: Optional path for knowledge storage
            event_bus: Optional EventBus instance (uses global if not provided)
            job_service: Optional BackgroundJobService instance (uses global if not provided)
            observability: Optional ObservabilityHub instance (uses global if not provided)
        """
        self.storage = get_knowledge_storage(storage_path)

        # Shared infrastructure
        self._event_bus = event_bus or get_event_bus()
        self._job_service = job_service or get_job_service()
        self._observability = observability or get_observability_hub()

        # Register with observability
        self._register_with_observability()

        # Schedule periodic persistence
        self._schedule_persistence()

        logger.debug("ReflectionEngine initialized")

    def _register_with_observability(self) -> None:
        """Register this subsystem with the shared ObservabilityHub."""
        if self._observability:
            self._observability.add_health_check(HealthCheck(
                name="reflection_engine_health",
                component="self_improvement",
                check_func=self._health_check,
                interval_seconds=60.0,
            ))

            # Register component
            self._observability.register_component(ComponentInfo(
                name="ReflectionEngine",
                component_type=ComponentType.SERVICE,
                version="1.0.0",
                description="Generates reflection records from task completion",
                metadata={},
            ))

    def _health_check(self) -> HealthResult:
        """Health check for ReflectionEngine."""
        try:
            return HealthResult(
                name="reflection_engine_health",
                component="self_improvement",
                status=HealthStatus.HEALTHY,
                message="ReflectionEngine operational",
                metadata={},
            )
        except Exception as e:
            return HealthResult(
                name="reflection_engine_health",
                component="self_improvement",
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

    def _schedule_persistence(self, interval_seconds: int = 300) -> None:
        """Schedule periodic persistence (no-op for reflection engine, storage handles it)."""
        pass

    def create_reflection(self, context: ReflectionContext) -> EngineeringKnowledgeItem:
        """Create a reflection record from task completion context.

        Args:
            context: ReflectionContext containing task details and evaluation results

        Returns:
            EngineeringKnowledgeItem representing the reflection
        """
        # Generate unique ID for this reflection
        reflection_id = f"ref_{uuid.uuid4().hex[:12]}"
        timestamp = datetime.now(timezone.utc).isoformat()

        # Determine domain and knowledge type
        domain = EngineeringDomain.ENGINEERING_LESSONS
        knowledge_type = EngineeringKnowledgeType.LESSON_LEARNED

        # Build reflection content
        content_parts = []

        # Summary
        summary = f"Task: {context.task_description}\nOutcome: {context.outcome}"
        content_parts.append(summary)

        # Evaluation scores
        content_parts.append(
            f"\nEvaluation Scores:\n"
            f"- Overall Confidence: {context.eval_result.overall_confidence:.0%}\n"
            f"- Requirement Verification: {context.eval_result.requirement_score:.0%}\n"
            f"- Functional Validation: {context.eval_result.validation_score:.0%}"
        )

        # Successes (from evaluation)
        if context.eval_result.requirement_verifications:
            satisfied_reqs = [
                v for v in context.eval_result.requirement_verifications
                if v.is_satisfied
            ]
            if satisfied_reqs:
                content_parts.append("\nSuccesses (Requirements Met):")
                for req in satisfied_reqs[:5]:  # Limit to top 5
                    content_parts.append(f"  - {req.requirement_description}")

        # Failures / gaps
        gaps = []
        for v in context.eval_result.requirement_verifications:
            if not v.is_satisfied:
                gaps.extend(v.gaps)
        if gaps:
            content_parts.append("\nFailures / Gaps:")
            for gap in gaps[:5]:
                content_parts.append(f"  - {gap}")

        # Root causes (could be inferred from validation failures)
        if context.eval_result.validation_results:
            failed_validations = [
                r for r in context.eval_result.validation_results if not r.passed
            ]
            if failed_validations:
                content_parts.append("\nRoot Causes (Validation Failures):")
                for val in failed_validations[:5]:
                    content_parts.append(f"  - {val.check_name}: {val.stderr[:100] if val.stderr else ''}")

        # Lessons learned (extract from gaps and failures)
        lessons = []
        if gaps:
            lessons.append(f"Address requirement gaps: {', '.join(set(gaps[:3]))}")
        if context.eval_result.validation_results:
            failed_vals = [r.check_name for r in context.eval_result.validation_results if not r.passed]
            if failed_vals:
                lessons.append(f"Fix validation issues: {', '.join(set(failed_vals[:3]))}")
        # Add generic lessons based on outcome
        if context.outcome == "failure":
            lessons.append("Review task planning and feasibility assessment")
        elif context.outcome == "success":
            lessons.append("Successful approach can be reused for similar tasks")

        if lessons:
            content_parts.append("\nLessons Learned:")
            for lesson in lessons:
                content_parts.append(f"  - {lesson}")

        # Recommendations
        recommendations = []
        if context.eval_result.requires_rework:
            recommendations.append("Address identified gaps before considering task complete")
        if context.eval_result.requires_human_review:
            recommendations.append("Seek human review due to low confidence")
        if context.eval_result.overall_confidence < 0.6:
            recommendations.append("Gather more information or clarify requirements")

        # Add general recommendations
        recommendations.append("Document lessons learned for future reference")
        recommendations.append("Update knowledge base with new insights")

        if recommendations:
            content_parts.append("\nRecommendations:")
            for rec in recommendations:
                content_parts.append(f"  - {rec}")

        # Confidence and Importance
        confidence = context.eval_result.overall_confidence
        # Importance could be based on impact; for now use confidence as proxy
        importance = confidence

        content_parts.append(f"\nConfidence: {confidence:.0%}")
        content_parts.append(f"Importance: {importance:.0%}")
        content_parts.append(f"Timestamp: {timestamp}")

        content = "\n".join(content_parts)

        # Tags
        tags = [
            "reflection",
            "task",
            context.outcome,
            f"confidence_{int(confidence * 100)}",
        ]
        if context.goal_id:
            tags.append("goal")
        if context.plan_id:
            tags.append("plan")

        # Source metadata
        source_metadata = {
            "task_description": context.task_description,
            "original_request": context.original_request,
            "goal_id": context.goal_id,
            "plan_id": context.plan_id,
            "task_id": context.task_id,
            "evaluation_id": context.eval_result.evaluation_id,
            "reflection_generated_at": timestamp,
        }
        source_metadata.update(context.metadata)

        # Create the engineering knowledge item
        reflection_item = EngineeringKnowledgeItem(
            id=reflection_id,
            title=f"Reflection: {context.task_description[:60]}...",
            summary=summary,
            content=content,
            domain=domain,
            sub_category="reflection",
            knowledge_type=knowledge_type,
            source=KnowledgeSource.REFLECTION,
            source_uri=reflection_id,  # Could also be a URL or path
            source_metadata=source_metadata,
            tags=tags,
            confidence=confidence,
            validation_status=ValidationStatus.PENDING,  # Will be validated later
        )

        logger.debug(
            f"Created reflection {reflection_id} for task '{context.task_description[:30]}...'"
        )
        return reflection_item

    def store_reflection(self, reflection_item: EngineeringKnowledgeItem) -> bool:
        """Store a reflection item in the knowledge base.

        Args:
            reflection_item: The reflection item to store

        Returns:
            True if stored successfully
        """
        try:
            self.storage.create(reflection_item)
            logger.info(f"Stored reflection {reflection_item.id}")

            # Publish event
            self._publish_event("self_improvement.reflection_stored", {
                "reflection_id": reflection_item.id,
                "title": reflection_item.title,
                "outcome": reflection_item.source_metadata.get("task_description", ""),
            })
            return True
        except Exception as e:
            logger.error(f"Failed to store reflection {reflection_item.id}: {e}")
            return False

    def reflect_and_store(self, context: ReflectionContext) -> Optional[EngineeringKnowledgeItem]:
        """Convenience method to create and store a reflection.

        Args:
            context: ReflectionContext for the reflection

        Returns:
            Stored EngineeringKnowledgeItem if successful, None otherwise
        """
        reflection = self.create_reflection(context)
        if self.store_reflection(reflection):
            return reflection
        return None