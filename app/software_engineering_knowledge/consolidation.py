"""Knowledge Consolidation for Software Engineering Knowledge.

Handles duplicate detection, merging, and knowledge consolidation to
maintain a clean, non-redundant knowledge base.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from difflib import SequenceMatcher

from app.software_engineering_knowledge.models import (
    EngineeringDomain,
    EngineeringKnowledgeItem,
    EngineeringKnowledgeType,
    KnowledgeSource,
    ValidationStatus,
)
from app.software_engineering_knowledge.storage import get_knowledge_storage
from app.software_engineering_knowledge.validation import KnowledgeValidator
from app.core.logger import logger

# Shared infrastructure imports
from app.core.events import get_event_bus
from app.core.background_jobs import get_job_service
from app.core.background_jobs import JobTriggerConfig, JobTriggerType, JobPriority
from app.core.observability import get_observability_hub, HealthCheck, HealthResult, HealthStatus, ComponentInfo, ComponentType


@dataclass
class ConsolidationConfig:
    """Configuration for consolidation behavior."""
    # Duplicate detection thresholds
    title_similarity_threshold: float = 0.85
    content_similarity_threshold: float = 0.80
    summary_similarity_threshold: float = 0.75

    # Merge preferences
    prefer_higher_confidence: bool = True
    prefer_newer: bool = True
    prefer_higher_validation: bool = True
    prefer_more_complete: bool = True

    # Fields to merge when duplicates are found
    merge_tags: bool = True
    merge_related_items: bool = True
    merge_source_metadata: bool = True

    # Consolidation behavior
    auto_merge_threshold: float = 0.95  # Auto-merge if similarity above this
    require_manual_review_below: float = 0.70  # Require review below this

    # Performance
    max_comparisons_per_run: int = 1000  # Limit comparisons to avoid O(n^2) explosion


@dataclass
class DuplicateGroup:
    """A group of items identified as duplicates."""
    primary_id: str  # The item to keep as the canonical version
    duplicate_ids: List[str]  # Items to be merged into primary
    similarity_scores: Dict[str, float]  # Similarity scores for each duplicate
    merge_reason: str  # Why these were considered duplicates


@dataclass
class ConsolidationResult:
    """Result of a consolidation run."""
    duplicates_found: int
    duplicates_merged: int
    duplicates_skipped: int
    errors: List[str]
    merged_pairs: List[Tuple[str, str]]  # (primary_id, duplicate_id)
    processing_time_seconds: float


class ConsolidationEngine:
    """Engine for detecting and merging duplicate knowledge items."""

    def __init__(
        self,
        config: Optional[ConsolidationConfig] = None,
        storage_path: Optional[str] = None,
        event_bus: Optional[object] = None,
        job_service: Optional[object] = None,
        observability: Optional[object] = None,
    ):
        self.config = config or ConsolidationConfig()
        self.storage = get_knowledge_storage(storage_path) if storage_path else get_knowledge_storage()
        self.validator = KnowledgeValidator(storage_path=storage_path)

        # Shared infrastructure
        self._event_bus = event_bus or get_event_bus()
        self._job_service = job_service or get_job_service()
        self._observability = observability or get_observability_hub()

        # Register with observability
        self._register_with_observability()

        # Schedule periodic persistence
        self._schedule_persistence()

        logger.info("ConsolidationEngine initialized")

    def _register_with_observability(self) -> None:
        """Register this subsystem with the shared ObservabilityHub."""
        if self._observability:
            self._observability.add_health_check(HealthCheck(
                name="consolidation_engine_health",
                component="software_engineering_knowledge",
                check_func=self._health_check,
                interval_seconds=60.0,
            ))

            # Register component
            self._observability.register_component(ComponentInfo(
                name="ConsolidationEngine",
                component_type=ComponentType.SERVICE,
                version="1.0.0",
                description="Detects and merges duplicate knowledge items",
                metadata={},
            ))

    def _health_check(self) -> HealthResult:
        """Health check for ConsolidationEngine."""
        try:
            return HealthResult(
                name="consolidation_engine_health",
                component="software_engineering_knowledge",
                status=HealthStatus.HEALTHY,
                message="ConsolidationEngine operational",
                metadata={
                    "config": {
                        "title_similarity_threshold": self.config.title_similarity_threshold,
                        "content_similarity_threshold": self.config.content_similarity_threshold,
                    }
                },
            )
        except Exception as e:
            return HealthResult(
                name="consolidation_engine_health",
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

    def _schedule_persistence(self, interval_seconds: int = 300) -> None:
        """Schedule periodic state save (no-op for consolidation engine, storage handles persistence)."""
        pass

    def consolidate(self) -> ConsolidationResult:
        """Run a full consolidation cycle: detect duplicates and merge them.

        Returns:
            ConsolidationResult with statistics about the operation.
        """
        import time
        start_time = time.time()

        logger.info("Starting knowledge consolidation process")

        # Get all knowledge items
        all_items = list(self.storage._items.values())
        if not all_items:
            return ConsolidationResult(
                duplicates_found=0,
                duplicates_merged=0,
                duplicates_skipped=0,
                errors=[],
                merged_pairs=[],
                processing_time_seconds=0.0
            )

        # Find duplicate groups
        duplicate_groups = self._find_duplicate_groups(all_items)
        duplicates_found = sum(len(group.duplicate_ids) for group in duplicate_groups)

        # Merge duplicates
        merged_pairs = []
        duplicates_merged = 0
        duplicates_skipped = 0
        errors = []

        for group in duplicate_groups:
            try:
                # Check if we should auto-merger or flag for review
                avg_similarity = sum(group.similarity_scores.values()) / len(group.similarity_scores)

                if avg_similarity >= self.config.auto_merge_threshold:
                    # Auto-merge
                    success = self._merge_duplicate_group(group)
                    if success:
                        duplicates_merged += len(group.duplicate_ids)
                        merged_pairs.extend([(group.primary_id, dup_id) for dup_id in group.duplicate_ids])
                    else:
                        duplicates_skipped += len(group.duplicate_ids)
                        errors.append(f"Failed to merge duplicate group {group.primary_id}")
                else:
                    # Below auto-merge threshold, skip for manual review
                    duplicates_skipped += len(group.duplicate_ids)
                    logger.info(f"Skipping duplicate group {group.primary_id} - similarity {avg_similarity:.2f} below auto-merge threshold")

            except Exception as e:
                error_msg = f"Error processing duplicate group {group.primary_id}: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)
                duplicates_skipped += len(group.duplicate_ids)

        processing_time = time.time() - start_time

        logger.info(f"Consolidation complete: {duplicates_found} duplicates found, "
                   f"{duplicates_merged} merged, {duplicates_skipped} skipped, "
                   f"{len(errors)} errors in {processing_time:.2f}s")

        # Publish event
        self._publish_event("software_engineering_knowledge.consolidation_completed", {
            "duplicates_found": duplicates_found,
            "duplicates_merged": duplicates_merged,
            "duplicates_skipped": duplicates_skipped,
            "errors": len(errors),
            "processing_time_seconds": processing_time,
        })

        return ConsolidationResult(
            duplicates_found=duplicates_found,
            duplicates_merged=duplicates_merged,
            duplicates_skipped=duplicates_skipped,
            errors=errors,
            merged_pairs=merged_pairs,
            processing_time_seconds=processing_time
        )

    def _find_duplicate_groups(self, items: List[EngineeringKnowledgeItem]) -> List[DuplicateGroup]:
        """Find groups of duplicate items.

        Uses a greedy clustering approach: for each item, find all similar items
        that haven't been grouped yet.
        """
        # Limit comparisons to avoid O(n^2) explosion on large datasets
        if len(items) > 1000:
            # For large datasets, we could use blocking/clustering techniques
            # For now, we'll process in batches
            items = items[:self.config.max_comparisons_per_run]
            logger.warning(f"Limiting consolidation to {len(items)} items for performance")

        grouped_items: set[str] = set()
        duplicate_groups: List[DuplicateGroup] = []

        for i, item in enumerate(items):
            if item.id in grouped_items:
                continue

            # Find all items similar to this one
            duplicates: List[str] = []
            similarities: dict[str, float] = {}

            for j, other_item in enumerate(items[i+1:], i+1):
                if other_item.id in grouped_items:
                    continue

                similarity = self._calculate_similarity(item, other_item)

                if similarity >= self.config.title_similarity_threshold:
                    duplicates.append(other_item.id)
                    similarities[other_item.id] = similarity

            if duplicates:
                # This item and its duplicates form a group
                # Choose the best item as primary based on preferences
                candidates = [item] + [self.storage.get(dup_id) for dup_id in duplicates if self.storage.get(dup_id)]
                candidates = [c for c in candidates if c is not None]

                primary = self._select_best_candidate(candidates)
                primary_id = primary.id

                # Remove primary from duplicates list if it's there
                if primary_id in duplicates:
                    duplicates.remove(primary_id)
                    del similarities[primary_id]

                # Mark all items in group as grouped
                grouped_items.add(primary_id)
                for dup_id in duplicates:
                    grouped_items.add(dup_id)

                duplicate_groups.append(DuplicateGroup(
                    primary_id=primary_id,
                    duplicate_ids=duplicates,
                    similarity_scores=similarities,
                    merge_reason=f"Similarity >= {self.config.title_similarity_threshold}"
                ))
            else:
                # No duplicates found for this item, mark as processed
                grouped_items.add(item.id)

        return duplicate_groups

    def _calculate_similarity(self, item1: EngineeringKnowledgeItem, item2: EngineeringKnowledgeItem) -> float:
        """Calculate similarity between two knowledge items."""
        # Title similarity (most important)
        title_sim = SequenceMatcher(None, item1.title.lower(), item2.title.lower()).ratio()

        # If titles are very different, they're likely not duplicates
        if title_sim < 0.5:
            return 0.0

        # Content similarity
        content_sim = SequenceMatcher(None,
                                    (item1.content or "").lower(),
                                    (item2.content or "").lower()).ratio()

        # Summary similarity
        summary_sim = SequenceMatcher(None,
                                    (item1.summary or "").lower(),
                                    (item2.summary or "").lower()).ratio()

        # Weighted combination
        # Title is most important, then content, then summary
        similarity = (title_sim * 0.5) + (content_sim * 0.3) + (summary_sim * 0.2)

        # Boost if same domain and type
        if item1.domain == item2.domain:
            similarity += 0.1
        if item1.knowledge_type == item2.knowledge_type:
            similarity += 0.1

        return min(similarity, 1.0)

    def _select_best_candidate(self, candidates: List[EngineeringKnowledgeItem]) -> EngineeringKnowledgeItem:
        """Select the best candidate from a list of potential duplicates.

        Uses configured preferences to choose which item to keep as primary.
        """
        def score_candidate(item: EngineeringKnowledgeItem) -> float:
            score = 0.0

            # Confidence
            if self.config.prefer_higher_confidence:
                score += item.confidence * 0.3

            # Recency (newer is better)
            if self.config.prefer_newer:
                try:
                    from datetime import datetime, timezone
                    updated = datetime.fromisoformat(item.updated_at.replace("Z", "+00:00"))
                    # Normalize to 0-1 range assuming items are from last 2 years
                    days_old = (datetime.now(timezone.utc) - updated).days
                    recency_score = max(0.0, 1.0 - (days_old / 730))  # 2 years = 730 days
                    score += recency_score * 0.2
                except Exception:
                    score += 0.1  # Neutral if date parsing fails

            # Validation status (validated is better)
            if self.config.prefer_higher_validation:
                validation_scores = {
                    ValidationStatus.VALIDATED: 1.0,
                    ValidationStatus.PENDING: 0.5,
                    ValidationStatus.LOW_CONFIDENCE: 0.2,
                    ValidationStatus.CONFLICT: 0.3,
                    ValidationStatus.DUPLICATE: 0.1,
                    ValidationStatus.REJECTED: 0.0,
                }
                score += validation_scores.get(item.validation_status, 0.5) * 0.2

            # Completeness
            if self.config.prefer_more_complete:
                completeness = 0.0
                if item.title: completeness += 0.2
                if item.summary: completeness += 0.2
                if item.content and len(item.content) > 100: completeness += 0.2
                if item.tags: completeness += 0.15
                if item.sub_category: completeness += 0.1
                if item.language: completeness += 0.05
                if item.frameworks: completeness += 0.05
                score += completeness * 0.2

            return score

        # Return the candidate with the highest score
        return max(candidates, key=score_candidate)

    def _merge_duplicate_group(self, group: DuplicateGroup) -> bool:
        """Merge a group of duplicate items into the primary item.

        Returns:
            True if merge was successful, False otherwise.
        """
        primary = self.storage.get(group.primary_id)
        if not primary:
            logger.error(f"Primary item {group.primary_id} not found")
            return False

        # Get all duplicate items
        duplicates = []
        for dup_id in group.duplicate_ids:
            dup = self.storage.get(dup_id)
            if dup:
                duplicates.append(dup)
            else:
                logger.warning(f"Duplicate item {dup_id} not found, skipping")

        if not duplicates:
            logger.warning(f"No valid duplicates found for group {group.primary_id}")
            return False

        try:
            # Merge attributes from duplicates into primary
            self._merge_into_primary(primary, duplicates)

            # Update primary item
            primary.version += 1
            primary.updated_at = datetime.now(timezone.utc).isoformat()

            # Save the updated primary
            self.storage.update(primary)

            # Delete duplicate items
            for dup in duplicates:
                self.storage.delete(dup.id)

            logger.info(f"Merged {len(duplicates)} duplicates into {primary.id}")
            return True

        except Exception as e:
            logger.error(f"Failed to merge duplicate group {group.primary_id}: {e}")
            return False

    def _merge_into_primary(self, primary: EngineeringKnowledgeItem, duplicates: List[EngineeringKnowledgeItem]) -> None:
        """Merge duplicate items into the primary item."""
        # Merge tags
        if self.config.merge_tags:
            all_tags = set(primary.tags)
            for dup in duplicates:
                all_tags.update(dup.tags)
            primary.tags = list(all_tags)

        # Merge related items
        if self.config.merge_related_items:
            all_related = set(primary.related_items)
            for dup in duplicates:
                all_related.update(dup.related_items)
                # Also add the duplicate ID itself as related (since it's been merged)
                all_related.add(dup.id)
            primary.related_items = list(all_related)

        # Merge source metadata
        if self.config.merge_source_metadata:
            if not primary.source_metadata:
                primary.source_metadata = {}

            # Add merge history
            if "merge_history" not in primary.source_metadata:
                primary.source_metadata["merge_history"] = []

            merge_record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "merged_ids": [dup.id for dup in duplicates],
                "reason": "duplicate_consolidation"
            }
            primary.source_metadata["merge_history"].append(merge_record)

        # Merge prerequisites
        all_prereqs = set(primary.prerequisites)
        for dup in duplicates:
            all_prereqs.update(dup.prerequisites)
        primary.prerequisites = list(all_prereqs)

        # Merge supersedes
        all_supersedes = set(primary.supersedes)
        for dup in duplicates:
            all_supersedes.update(dup.supersedes)
        primary.supersedes = list(all_supersedes)

        # Update confidence - weighted average based on validation status
        # Give more weight to validated/higher confidence items
        total_weight = 0.0
        weighted_confidence = 0.0

        # Add primary
        weight = 1.0
        if primary.validation_status == ValidationStatus.VALIDATED:
            weight = 2.0
        elif primary.validation_status == ValidationStatus.PENDING:
            weight = 1.0
        else:
            weight = 0.5

        weighted_confidence += primary.confidence * weight
        total_weight += weight

        # Add duplicates
        for dup in duplicates:
            weight = 1.0
            if dup.validation_status == ValidationStatus.VALIDATED:
                weight = 2.0
            elif dup.validation_status == ValidationStatus.PENDING:
                weight = 1.0
            else:
                weight = 0.5

            weighted_confidence += dup.confidence * weight
            total_weight += weight

        if total_weight > 0:
            primary.confidence = min(weighted_confidence / total_weight, 1.0)

        # If primary content is sparse, try to enrich from duplicates
        if len(primary.content.strip()) < 100:  # Arbitrary threshold
            # Find the duplicate with the longest content
            best_dup = max(duplicates, key=lambda d: len(d.content or ""), default=None)
            if best_dup and len(best_dup.content or "") > len(primary.content or ""):
                # Don't replace entirely, but append unique information
                # Simple approach: if primary is much shorter, use the duplicate's content
                if len(best_dup.content or "") > len(primary.content or "") * 2:
                    primary.content = best_dup.content
                    primary.summary = best_dup.summary or primary.summary

        # Update title if primary title is poor and we have a better one
        if len(primary.title.strip()) < 10:
            # Find duplicate with longest title
            best_dup = max(duplicates, key=lambda d: len(d.title or ""), default=None)
            if best_dup and len(best_dup.title.strip()) > len(primary.title.strip()):
                primary.title = best_dup.title

    def find_duplicates_for_item(self, item_id: str, threshold: float = 0.8) -> List[tuple[str, float]]:
        """Find potential duplicates for a specific item.

        Args:
            item_id: ID of the item to check
            threshold: Similarity threshold (0-1)

        Returns:
            List of (item_id, similarity_score) tuples for potential duplicates
        """
        item = self.storage.get(item_id)
        if not item:
            return []

        duplicates = []
        all_items = list(self.storage._items.values())

        for other in all_items:
            if other.id == item_id:
                continue

            similarity = self._calculate_similarity(item, other)
            if similarity >= threshold:
                duplicates.append((other.id, similarity))

        # Sort by similarity descending
        duplicates.sort(key=lambda x: x[1], reverse=True)
        return duplicates

    def get_consolidation_stats(self) -> dict[str, any]:
        """Get statistics about the current state that might indicate need for consolidation."""
        all_items = list(self.storage._items.values())

        if not all_items:
            return {
                "total_items": 0,
                "potential_duplicates": 0,
                "avg_items_per_domain": 0,
                "domains": {}
            }

        # Group by domain
        by_domain: dict[str, list[EngineeringKnowledgeItem]] = {}
        for item in all_items:
            domain = item.domain.value
            if domain not in by_domain:
                by_domain[domain] = []
            by_domain[domain].append(item)

        # Estimate potential duplicates (very rough)
        potential_duplicates = 0
        for domain, items in by_domain.items():
            if len(items) > 1:
                # Very rough estimate: if n items, max n*(n-1)/2 pairs
                # But we'll just use a simpler heuristic
                potential_duplicates += max(0, len(items) - 1)  # At least n-1 potential duplicates per domain

        return {
            "total_items": len(all_items),
            "potential_duplicates": potential_duplicates,
            "avg_items_per_domain": len(all_items) / len(by_domain) if by_domain else 0,
            "domains": {domain: len(items) for domain, items in by_domain.items()}
        }


def create_consolidation_engine(
    config: Optional[ConsolidationConfig] = None,
    storage_path: Optional[str] = None
) -> ConsolidationEngine:
    """Factory function to create a consolidation engine.

    Args:
        config: Configuration for the consolidation engine
        storage_path: Path to knowledge storage

    Returns:
        Configured ConsolidationEngine instance
    """
    return ConsolidationEngine(config, storage_path)