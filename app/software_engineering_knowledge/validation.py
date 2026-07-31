"""Knowledge Validation for Software Engineering Knowledge.

Validates knowledge items for:
- Confidence scoring
- Duplicate detection
- Conflict detection
- Source reliability tracking
- Consistency checking
"""

import difflib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from app.software_engineering_knowledge.models import (
    EngineeringDomain,
    EngineeringKnowledgeItem,
    EngineeringKnowledgeType,
    KnowledgeSource,
    ValidationResult,
    ValidationStatus,
)
from app.software_engineering_knowledge.storage import get_knowledge_storage
from app.knowledge_retrieval.calibration import get_calibration_manager


@dataclass
class ValidationConfig:
    """Configuration for validation behavior."""
    # Confidence thresholds
    min_confidence_for_validated: float = 0.7
    high_confidence_threshold: float = 0.85

    # Duplicate detection
    duplicate_similarity_threshold: float = 0.85  # Title/content similarity
    check_duplicates_on_create: bool = True
    check_duplicates_on_update: bool = True

    # Conflict detection
    conflict_similarity_threshold: float = 0.7  # Similar topic, different content
    check_conflicts: bool = True

    # Source reliability
    source_reliability: Dict[KnowledgeSource, float] = field(default_factory=lambda: {
        KnowledgeSource.PROJECT_CODE: 0.85,
        KnowledgeSource.DOCUMENTATION: 0.90,
        KnowledgeSource.EXPERIENCE_MEMORY: 0.75,
        KnowledgeSource.ENGINEERING_LESSONS: 0.85,
        KnowledgeSource.REFLECTION: 0.70,
        KnowledgeSource.EXTERNAL_DOCS: 0.80,
        KnowledgeSource.INTERNET_RESEARCH: 0.60,
        KnowledgeSource.USER_INPUT: 0.95,
        KnowledgeSource.LLM_TRAINING: 0.65,
        KnowledgeSource.SYNTHESIZED: 0.75,
        KnowledgeSource.UNKNOWN: 0.50,
    })

    # Validation requirements
    require_title: bool = True
    require_content: bool = True
    min_content_length: int = 50


class KnowledgeValidator:
    """Validates engineering knowledge items."""

    def __init__(self, config: Optional[ValidationConfig] = None, storage_path: Optional[str] = None):
        self.config = config or ValidationConfig()
        self.storage = get_knowledge_storage(storage_path) if storage_path else get_knowledge_storage()
        self.calibration_mgr = get_calibration_manager()

    def validate(self, item: EngineeringKnowledgeItem) -> ValidationResult:
        """Validate a single knowledge item comprehensively.

        Checks:
        1. Basic requirements (title, content length)
        2. Confidence calibration
        3. Duplicate detection
        4. Conflict detection
        4. Source reliability
        5. Cross-reference validity
        """
        conflicts = []
        duplicates = []
        notes = []

        # 1. Basic validation
        basic_valid, basic_notes = self._validate_basic(item)
        notes.extend(basic_notes)

        if not basic_valid:
            return ValidationResult(
                is_valid=False,
                confidence=0.0,
                validation_status=ValidationStatus.REJECTED,
                notes="; ".join(notes),
            )

        # 2. Calibrate confidence
        calibrated_confidence = self._calibrate_confidence(item)
        notes.append(f"Calibrated confidence: {calibrated_confidence:.2f}")

        # 3. Check duplicates
        if self.config.check_duplicates_on_create or (
            self.config.check_duplicates_on_update and item.version > 1
        ):
            duplicates = self._find_duplicates(item)
            if duplicates:
                notes.append(f"Found {len(duplicates)} potential duplicates")

        # 4. Check conflicts
        if self.config.check_conflicts:
            conflicts = self._find_conflicts(item)
            if conflicts:
                notes.append(f"Found {len(conflicts)} potential conflicts")

        # 5. Determine validation status
        status, final_confidence = self._determine_status(
            item, calibrated_confidence, duplicates, conflicts
        )

        # 6. Validate cross-references
        ref_notes = self._validate_references(item)
        notes.extend(ref_notes)

        return ValidationResult(
            is_valid=status != ValidationStatus.REJECTED,
            confidence=final_confidence,
            validation_status=status,
            conflicts=conflicts,
            duplicates=duplicates,
            notes="; ".join(notes),
            metadata={
                "calibrated_confidence": calibrated_confidence,
                "source_reliability": self.config.source_reliability.get(item.source, 0.5),
                "basic_checks_passed": basic_valid,
            },
        )

    def _validate_basic(self, item: EngineeringKnowledgeItem) -> Tuple[bool, List[str]]:
        """Check basic requirements."""
        notes = []
        valid = True

        if self.config.require_title and not item.title.strip():
            valid = False
            notes.append("Missing required title")

        if self.config.require_content and not item.content.strip():
            valid = False
            notes.append("Missing required content")

        if len(item.content.strip()) < self.config.min_content_length:
            valid = False
            notes.append(f"Content too short (min {self.config.min_content_length} chars)")

        if item.confidence < 0 or item.confidence > 1:
            valid = False
            notes.append("Confidence must be between 0 and 1")

        if item.version < 1:
            valid = False
            notes.append("Version must be >= 1")

        return valid, notes

    def _calibrate_confidence(self, item: EngineeringKnowledgeItem) -> float:
        """Calibrate confidence using retrieval calibration system."""
        source_type = item.source.value
        try:
            return self.calibration_mgr.calibrate(item.confidence, source_type)
        except Exception:
            return item.confidence

    def _find_duplicates(self, item: EngineeringKnowledgeItem) -> List[str]:
        """Find potential duplicate items in storage."""
        duplicates = []

        # Search for similar items
        candidates = self.storage.search(item.title, limit=20)
        candidates += self.storage.search(item.content[:100], limit=20)

        seen = set()
        for candidate in candidates:
            if candidate.id == item.id or candidate.id in seen:
                continue

            # Check title similarity
            title_sim = self._similarity(item.title.lower(), candidate.title.lower())

            # Check content similarity (first 200 chars)
            content_sim = self._similarity(
                item.content[:200].lower(), candidate.content[:200].lower()
            )

            # Combined similarity
            similarity = max(title_sim, content_sim * 0.7)

            if similarity >= self.config.duplicate_similarity_threshold:
                duplicates.append(candidate.id)
                seen.add(candidate.id)

        return duplicates

    def _find_conflicts(self, item: EngineeringKnowledgeItem) -> List[str]:
        """Find potential conflicting items (similar topic, contradictory content)."""
        conflicts = []

        # Search for items on similar topics
        candidates = self.storage.search(item.title, limit=30)
        candidates += self.storage.get_by_tag(item.domain.value.replace("_", " "), limit=20)

        for candidate in candidates:
            if candidate.id == item.id:
                continue

            # Check if same domain and overlapping tags
            if candidate.domain != item.domain:
                continue

            tag_overlap = set(item.tags) & set(candidate.tags)
            if not tag_overlap:
                continue

            # Check content similarity (moderate - same topic but different content)
            content_sim = self._similarity(
                item.content.lower(), candidate.content.lower()
            )

            # Title similarity
            title_sim = self._similarity(item.title.lower(), candidate.title.lower())

            # Conflict if: similar title/topic (title_sim high) but different content (content_sim low)
            # This suggests contradictory information on same topic
            if title_sim > self.config.conflict_similarity_threshold and content_sim < 0.5:
                conflicts.append(candidate.id)

        return conflicts

    def _similarity(self, text1: str, text2: str) -> float:
        """Calculate text similarity using difflib."""
        if not text1 or not text2:
            return 0.0
        return difflib.SequenceMatcher(None, text1, text2).ratio()

    def _determine_status(
        self,
        item: EngineeringKnowledgeItem,
        calibrated_confidence: float,
        duplicates: List[str],
        conflicts: List[str],
    ) -> Tuple[ValidationStatus, float]:
        """Determine validation status and final confidence."""
        source_reliability = self.config.source_reliability.get(item.source, 0.5)

        # Start with calibrated confidence adjusted by source reliability
        final_confidence = calibrated_confidence * source_reliability

        # Apply penalties
        if duplicates:
            # Reduce confidence for duplicates
            final_confidence *= 0.8
            if len(duplicates) > 2:
                final_confidence *= 0.9

        if conflicts:
            # Conflicts reduce confidence more
            final_confidence *= 0.7
            if len(conflicts) > 2:
                final_confidence *= 0.8

        # Determine status
        if final_confidence >= self.config.high_confidence_threshold and not conflicts:
            status = ValidationStatus.VALIDATED
        elif final_confidence >= self.config.min_confidence_for_validated:
            status = ValidationStatus.VALIDATED
        elif duplicates:
            status = ValidationStatus.DUPLICATE
        elif conflicts:
            status = ValidationStatus.CONFLICT
        elif calibrated_confidence < 0.3:
            status = ValidationStatus.LOW_CONFIDENCE
        else:
            status = ValidationStatus.PENDING

        return status, final_confidence

    def _validate_references(self, item: EngineeringKnowledgeItem) -> List[str]:
        """Validate cross-references to other knowledge items."""
        notes = []

        # Check related_items exist
        for ref_id in item.related_items:
            if not self.storage.get(ref_id):
                notes.append(f"Broken reference: related item {ref_id} not found")

        # Check prerequisites exist
        for ref_id in item.prerequisites:
            if not self.storage.get(ref_id):
                notes.append(f"Broken reference: prerequisite {ref_id} not found")

        # Check supersedes exist
        for ref_id in item.supersedes:
            if not self.storage.get(ref_id):
                notes.append(f"Broken reference: superseded item {ref_id} not found")

        return notes

    def validate_batch(self, items: List[EngineeringKnowledgeItem]) -> List[ValidationResult]:
        """Validate multiple items."""
        return [self.validate(item) for item in items]

    def get_validation_stats(self) -> Dict[str, Any]:
        """Get validation statistics across all items."""
        all_items = list(self.storage._items.values())

        stats = {
            "total": len(all_items),
            "by_status": {},
            "avg_confidence": 0.0,
            "conflicts_detected": 0,
            "duplicates_detected": 0,
        }

        if not all_items:
            return stats

        total_conf = 0
        for item in all_items:
            status = item.validation_status.value
            stats["by_status"][status] = stats["by_status"].get(status, 0) + 1
            total_conf += item.confidence

        stats["avg_confidence"] = total_conf / len(all_items)

        # Estimate conflicts/duplicates (would be expensive to compute fully)
        stats["conflicts_detected"] = stats["by_status"].get("conflict", 0)
        stats["duplicates_detected"] = stats["by_status"].get("duplicate", 0)

        return stats


class ConfidenceScorer:
    """Advanced confidence scoring using multiple signals."""

    def __init__(self, storage_path: Optional[str] = None):
        self.storage = get_knowledge_storage(storage_path) if storage_path else get_knowledge_storage()
        self.calibration_mgr = get_calibration_mgr()

    def score_item(self, item: EngineeringKnowledgeItem) -> Tuple[float, Dict[str, float]]:
        """Score a knowledge item using multiple signals.

        Returns:
            Tuple of (final_score, signal_breakdown)
        """
        signals = {}

        # Signal 1: Source reliability
        source_reliability = {
            KnowledgeSource.USER_INPUT: 0.95,
            KnowledgeSource.ENGINEERING_LESSONS: 0.85,
            KnowledgeSource.DOCUMENTATION: 0.90,
            KnowledgeSource.PROJECT_CODE: 0.85,
            KnowledgeSource.EXPERIENCE_MEMORY: 0.75,
            KnowledgeSource.REFLECTION: 0.70,
            KnowledgeSource.EXTERNAL_DOCS: 0.80,
            KnowledgeSource.SYNTHESIZED: 0.75,
            KnowledgeSource.LLM_TRAINING: 0.65,
            KnowledgeSource.INTERNET_RESEARCH: 0.60,
            KnowledgeSource.UNKNOWN: 0.50,
        }
        signals["source_reliability"] = source_reliability.get(item.source, 0.5)

        # Signal 2: Content completeness
        completeness = 0.0
        if item.title: completeness += 0.2
        if item.summary: completeness += 0.2
        if item.content and len(item.content) > 100: completeness += 0.2
        if item.tags: completeness += 0.15
        if item.sub_category: completeness += 0.1
        if item.language: completeness += 0.1
        if item.frameworks: completeness += 0.05
        signals["completeness"] = min(completeness, 1.0)

        # Signal 3: Usage/success history
        if item.access_count > 0:
            success_rate = item.success_count / max(item.access_count, 1)
            signals["usage_success"] = success_rate
        else:
            signals["usage_success"] = 0.5

        # Signal 4: Version maturity (higher version = more refined)
        signals["version_maturity"] = min(item.version / 10.0, 1.0)

        # Signal 5: Cross-reference richness
        ref_count = len(item.related_items) + len(item.prerequisites) + len(item.supersedes)
        signals["cross_references"] = min(ref_count / 5.0, 1.0)

        # Signal 6: Recency (exponential decay, 1 year half-life)
        try:
            from datetime import datetime, timezone
            updated = datetime.fromisoformat(item.updated_at.replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - updated).days
            signals["recency"] = 2 ** (-age_days / 365.0)
        except Exception:
            signals["recency"] = 0.5

        # Weighted combination
        weights = {
            "source_reliability": 0.25,
            "completeness": 0.15,
            "usage_success": 0.20,
            "version_maturity": 0.10,
            "cross_references": 0.15,
            "recency": 0.15,
        }

        final_score = sum(signals[k] * weights[k] for k in weights)

        return final_score, signals


def get_calibration_mgr():
    """Get calibration manager (lazy import)."""
    from app.knowledge_retrieval.calibration import get_calibration_manager
    return get_calibration_manager()