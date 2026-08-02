"""Update Detector for Software Engineering Knowledge.

Monitors knowledge items for staleness and potential updates needed
based on age, source freshness, and version information.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

from app.software_engineering_knowledge.models import (
    EngineeringKnowledgeItem,
    KnowledgeSource,
)
from app.software_engineering_knowledge.storage import get_knowledge_storage
from app.core.logger import logger

# Shared infrastructure imports
from app.core.events import get_event_bus
from app.core.background_jobs import get_job_service
from app.core.background_jobs import JobTriggerConfig, JobTriggerType, JobPriority
from app.core.observability import get_observability_hub, HealthCheck, HealthResult, HealthStatus, ComponentInfo, ComponentType


@dataclass
class UpdateCheckConfig:
    """Configuration for update detection behavior."""
    # Age thresholds (in days)
    max_age_days: int = 90  # Consider items older than this as potentially stale
    critical_age_days: int = 365  # Items older than this are definitely stale

    # Source-specific freshness factors
    source_freshness_factors: Dict[KnowledgeSource, float] = field(default_factory=lambda: {
        KnowledgeSource.PROJECT_CODE: 1.0,      # Code is considered fresh if it's in the repo
        KnowledgeSource.DOCUMENTATION: 0.8,     # Docs can become outdated
        KnowledgeSource.EXPERIENCE_MEMORY: 0.6, # Experience needs reinforcement
        KnowledgeSource.ENGINEERING_LESSONS: 0.7, # Lessons can become outdated
        KnowledgeSource.REFLECTION: 0.5,        # Reflections are point-in-time
        KnowledgeSource.EXTERNAL_DOCS: 0.3,     # External docs often change
        KnowledgeSource.INTERNET_RESEARCH: 0.2, # Internet info changes frequently
        KnowledgeSource.USER_INPUT: 0.9,        # User input is usually current
        KnowledgeSource.LLM_TRAINING: 0.4,      # Training data can be stale
        KnowledgeSource.SYNTHESIZED: 0.5,       # Synthesis depends on source freshness
        KnowledgeSource.UNKNOWN: 0.5,
    })

    # Check frequency
    enable_version_checking: bool = True
    enable_external_link_checking: bool = True
    enable_content_hash_checking: bool = True

    # Thresholds
    staleness_score_threshold: float = 0.6  # Above this = needs update
    freshness_score_threshold: float = 0.8  # Above this = considered fresh


@dataclass
class UpdateAssessment:
    """Result of checking if a knowledge item needs updating."""
    item_id: str
    is_stale: bool
    staleness_score: float  # 0.0 = fresh, 1.0 = very stale
    factors: Dict[str, float]  # Contributing factors to staleness
    recommended_action: str  # "none", "review", "update", "replace"
    notes: List[str] = field(default_factory=list)


@dataclass
class UpdateDetectionResult:
    """Result of running update detection on a knowledge base."""
    total_items_checked: int
    stale_items: List[UpdateAssessment]
    fresh_items: List[UpdateAssessment]
    actions_recommended: Dict[str, int]  # action -> count
    processing_time_seconds: float


class UpdateDetector:
    """Detects knowledge items that may need updates due to staleness."""

    def __init__(
        self,
        config: Optional[UpdateCheckConfig] = None,
        storage_path: Optional[str] = None,
        event_bus: Optional[object] = None,
        job_service: Optional[object] = None,
        observability: Optional[object] = None,
    ):
        self.config = config or UpdateCheckConfig()
        self.storage = get_knowledge_storage(storage_path) if storage_path else get_knowledge_storage()

        # Shared infrastructure
        self._event_bus = event_bus or get_event_bus()
        self._job_service = job_service or get_job_service()
        self._observability = observability or get_observability_hub()

        # Register with observability
        self._register_with_observability()

        # Schedule periodic update detection
        self._schedule_update_detection()

        logger.info("UpdateDetector initialized")

    def _register_with_observability(self) -> None:
        """Register this subsystem with the shared ObservabilityHub."""
        if self._observability:
            self._observability.add_health_check(HealthCheck(
                name="update_detector_health",
                component="software_engineering_knowledge",
                check_func=self._health_check,
                interval_seconds=60.0,
            ))

            # Register component
            self._observability.register_component(ComponentInfo(
                name="UpdateDetector",
                component_type=ComponentType.SERVICE,
                version="1.0.0",
                description="Detects stale knowledge items needing updates",
                metadata={},
            ))

    def _health_check(self) -> HealthResult:
        """Health check for UpdateDetector."""
        try:
            return HealthResult(
                name="update_detector_health",
                component="software_engineering_knowledge",
                status=HealthStatus.HEALTHY,
                message="UpdateDetector operational",
                metadata={
                    "config": {
                        "max_age_days": self.config.max_age_days,
                        "staleness_score_threshold": self.config.staleness_score_threshold,
                    }
                },
            )
        except Exception as e:
            return HealthResult(
                name="update_detector_health",
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

    def _schedule_update_detection(self, interval_seconds: int = 3600) -> None:
        """Schedule periodic update detection using BackgroundJobService."""
        if not self._job_service:
            return

        # Check if job already exists to avoid duplicate scheduling
        existing_job = self._job_service.get_job("knowledge_update_detection")
        if existing_job:
            return

        trigger = JobTriggerConfig(
            type=JobTriggerType.RECURRING,
            interval_seconds=interval_seconds,
        )
        self._job_service.schedule(
            job_id="knowledge_update_detection",
            func=lambda: self.detect_updates(),
            trigger=trigger,
            name="Knowledge Update Detection",
            priority=JobPriority.LOW,
        )

    def check_item_for_updates(self, item: EngineeringKnowledgeItem) -> UpdateAssessment:
        """Check a single knowledge item for signs of staleness.

        Returns:
            UpdateAssessment with staleness score and recommendations.
        """
        factors = {}
        notes = []

        # Factor 1: Age-based staleness
        age_factor = self._calculate_age_factor(item)
        factors["age"] = age_factor
        if age_factor > 0.5:
            notes.append(f"Item is {self._get_age_days(item):.0f} days old")

        # Factor 2: Source-based freshness expectation
        source_factor = self._calculate_source_factor(item)
        factors["source_expectation"] = source_factor
        if source_factor < 0.5:
            notes.append(f"Source {item.source.value} typically requires frequent updates")

        # Factor 3: Content hash staleness (if enabled)
        hash_factor = 0.0
        if self.config.enable_content_hash_checking:
            hash_factor = self._calculate_content_hash_factor(item)
            factors["content_hash"] = hash_factor
            if hash_factor > 0.5:
                notes.append("Content may be outdated based on hash analysis")

        # Factor 4: Version/checksum staleness (if enabled)
        version_factor = 0.0
        if self.config.enable_version_checking:
            version_factor = self._calculate_version_factor(item)
            factors["version"] = version_factor
            if version_factor > 0.5:
                notes.append("Version information suggests possible updates")

        # Factor 5: Access pattern staleness
        access_factor = self._calculate_access_factor(item)
        factors["access_pattern"] = access_factor
        if access_factor > 0.5:
            notes.append("Item has not been accessed recently")

        # Combine factors (weighted average)
        weights = {
            "age": 0.3,
            "source_expectation": 0.2,
            "content_hash": 0.15,
            "version": 0.15,
            "access_pattern": 0.2,
        }

        staleness_score = sum(factors.get(factor, 0.0) * weight for factor, weight in weights.items())
        staleness_score = max(0.0, min(1.0, staleness_score))  # Clamp to 0-1

        # Determine if stale and recommend action
        is_stale = staleness_score >= self.config.staleness_score_threshold

        if staleness_score >= 0.8:
            recommended_action = "replace"
        elif staleness_score >= self.config.staleness_score_threshold:
            recommended_action = "update"
        elif staleness_score >= 0.3:
            recommended_action = "review"
        else:
            recommended_action = "none"

        return UpdateAssessment(
            item_id=item.id,
            is_stale=is_stale,
            staleness_score=staleness_score,
            factors=factors,
            recommended_action=recommended_action,
            notes=notes
        )

    def _calculate_age_factor(self, item: EngineeringKnowledgeItem) -> float:
        """Calculate staleness factor based on item age."""
        try:
            updated = datetime.fromisoformat(item.updated_at.replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - updated).days

            # Normalize age to 0-1 scale
            if age_days <= 0:
                return 0.0
            elif age_days >= self.config.critical_age_days:
                return 1.0
            else:
                # Linear interpolation between max_age_days and critical_age_days
                if age_days <= self.config.max_age_days:
                    return age_days / self.config.max_age_days
                else:
                    # Beyond max_age, increase toward 1.0
                    excess = age_days - self.config.max_age_days
                    max_excess = self.config.critical_age_days - self.config.max_age_days
                    return min(1.0, 0.5 + (0.5 * excess / max_excess))
        except Exception:
            return 0.5  # Unknown age = moderate concern

    def _calculate_source_factor(self, item: EngineeringKnowledgeItem) -> float:
        """Calculate how much the item's source expects frequent updates."""
        # Sources with low freshness factors need more frequent updates
        base_expectation = self.config.source_freshness_factors.get(item.source, 0.5)
        # Invert so that low freshness = high update need
        return 1.0 - base_expectation

    def _calculate_content_hash_factor(self, item: EngineeringKnowledgeItem) -> float:
        """Check if content appears stale based on internal markers."""
        # Simple heuristic: look for version numbers, dates in content
        content_lower = (item.content or "").lower()
        score = 0.0

        # Check for old-looking version patterns
        import re
        version_patterns = [
            r'v?\d+\.\d+\.\d+',  # Semantic versioning
            r'version\s+\d+',
            r'release\s+\d+',
            r'©\s*(19|20)\d{2}',  # Copyright dates
        ]

        for pattern in version_patterns:
            matches = re.findall(pattern, content_lower)
            if matches:
                # Try to extract years/numbers and see if they're old
                for match in matches:
                    # Extract numbers
                    numbers = re.findall(r'\d+', str(match))
                    for num_str in numbers:
                        try:
                            num = int(num_str)
                            # If it looks like a year and is old
                            if 1900 <= num <= 2030 and num < 2020:
                                score += 0.3
                        except ValueError:
                            pass

        # Check for technology-specific outdated terms
        outdated_terms = [
            'deprecated', 'obsolete', 'legacy', 'old version',
            'no longer supported', 'replaced by'
        ]
        for term in outdated_terms:
            if term in content_lower:
                score += 0.2

        return min(1.0, score)

    def _calculate_version_factor(self, item: EngineeringKnowledgeItem) -> float:
        """Check version information in metadata for staleness clues."""
        score = 0.0
        metadata = item.metadata or {}

        # Check for explicit version fields
        version_fields = ['version', 'api_version', 'library_version', 'sdk_version']
        for field in version_fields:
            if field in metadata:
                version_str = str(metadata[field])
                # Simple check: if version looks old-fashioned
                if 'beta' in version_str.lower() or 'alpha' in version_str.lower():
                    score += 0.2
                # Could add more sophisticated version parsing here

        # Check for last checked/update timestamps in metadata
        time_fields = ['last_checked', 'last_updated', 'checked_at']
        for field in time_fields:
            if field in metadata:
                try:
                    checked_time = datetime.fromisoformat(str(metadata[field]).replace("Z", "+00:00"))
                    age_days = (datetime.now(timezone.utc) - checked_time).days
                    if age_days > 30:  # Not checked in a month
                        score += 0.3
                except Exception:
                    pass

        return min(1.0, score)

    def _calculate_access_factor(self, item: EngineeringKnowledgeItem) -> float:
        """Calculate staleness based on access patterns."""
        # If we have access tracking
        if item.last_accessed:
            try:
                last_accessed = datetime.fromisoformat(item.last_accessed.replace("Z", "+00:00"))
                days_since_access = (datetime.now(timezone.utc) - last_accessed).days
                # Items not accessed in 6 months get higher score
                return min(1.0, days_since_access / 180.0)
            except Exception:
                pass

        # Fall back to access count (low usage might indicate outdated)
        if item.access_count < 5:
            return 0.3  # Low usage suggests possible neglect
        elif item.access_count < 1:
            return 0.5  # Never accessed
        else:
            return 0.0  # Regularly accessed

    def _get_age_days(self, item: EngineeringKnowledgeItem) -> float:
        """Get the age of an item in days."""
        try:
            updated = datetime.fromisoformat(item.updated_at.replace("Z", "+00:00"))
            return (datetime.now(timezone.utc) - updated).days
        except Exception:
            return 0.0

    def detect_updates(self, item_ids: Optional[List[str]] = None) -> UpdateDetectionResult:
        """Detect updates needed for items in the knowledge base.

        Args:
            item_ids: Optional list of specific item IDs to check. If None, checks all.

        Returns:
            UpdateDetectionResult with findings.
        """
        import time
        start_time = time.time()

        # Get items to check
        if item_ids is None:
            items = list(self.storage._items.values())
        else:
            items = []
            for item_id in item_ids:
                item = self.storage.get(item_id)
                if item:
                    items.append(item)
                else:
                    logger.warning(f"Item {item_id} not found for update check")

        if not items:
            return UpdateDetectionResult(
                total_items_checked=0,
                stale_items=[],
                fresh_items=[],
                actions_recommended={},
                processing_time_seconds=0.0
            )

        # Check each item
        stale_items = []
        fresh_items = []
        actions_count = {}

        for item in items:
            assessment = self.check_item_for_updates(item)
            if assessment.is_stale:
                stale_items.append(assessment)
            else:
                fresh_items.append(assessment)

            # Count recommended actions
            action = assessment.recommended_action
            actions_count[action] = actions_count.get(action, 0) + 1

        processing_time = time.time() - start_time

        logger.info(f"Update check complete: {len(items)} items checked, "
                   f"{len(stale_items)} stale, {len(fresh_items)} fresh")

        # Publish event
        self._publish_event("software_engineering_knowledge.update_detection_completed", {
            "total_items_checked": len(items),
            "stale_items_count": len(stale_items),
            "fresh_items_count": len(fresh_items),
            "actions_recommended": actions_count,
            "processing_time_seconds": processing_time,
        })

        return UpdateDetectionResult(
            total_items_checked=len(items),
            stale_items=stale_items,
            fresh_items=fresh_items,
            actions_recommended=actions_count,
            processing_time_seconds=processing_time
        )

    def get_stale_items_summary(self) -> Dict[str, Any]:
        """Get a summary of stale items in the knowledge base."""
        result = self.detect_updates()
        return {
            "total_items": result.total_items_checked,
            "stale_count": len(result.stale_items),
            "fresh_count": len(result.fresh_items),
            "staleness_distribution": {
                "high": len([i for i in result.stale_items if i.staleness_score >= 0.8]),
                "medium": len([i for i in result.stale_items if 0.6 <= i.staleness_score < 0.8]),
                "low": len([i for i in result.stale_items if i.staleness_score < 0.6])
            },
            "recommended_actions": result.actions_recommended,
            "top_stale_items": [
                {
                    "id": item.item_id,
                    "title": self.storage.get(item.item_id).title if self.storage.get(item.item_id) else "Unknown",
                    "staleness_score": item.staleness_score,
                    "recommended_action": item.recommended_action
                }
                for item in sorted(result.stale_items, key=lambda x: x.staleness_score, reverse=True)[:10]
            ]
        }


def create_update_detector(
    config: Optional[UpdateCheckConfig] = None,
    storage_path: Optional[str] = None
) -> UpdateDetector:
    """Factory function to create an update detector.

    Args:
        config: Configuration for the update detector
        storage_path: Path to knowledge storage

    Returns:
        Configured UpdateDetector instance
    """
    return UpdateDetector(config, storage_path)