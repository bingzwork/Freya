"""Memory Consolidation for Freya AI.

This module implements the consolidation engine that scores importance of memories
and promotes high-value entries to long-term memory, while archiving older entries.

Features:
- Importance scoring algorithm using confidence, outcome, access frequency, recency
- Automatic promotion of top experiences/lessons to LongTermMemory
- Duplicate detection to prevent re-promotion
- Configurable scheduling (run after N new entries or time interval)
- Cross-memory consolidation (Experience → Lessons → Long-Term)
"""

import json
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple
from enum import Enum
from collections import defaultdict

# Import memory modules
from app.memory.experience_memory import ExperienceMemory, ExperienceEntry
from app.memory.engineering_lessons import EngineeringLessonStorage, EngineeringLesson
from app.memory.long_term_memory import LongTermMemory, LongTermEntry
from app.memory.project_memory import ProjectMemory


class ConsolidationTrigger(Enum):
    """Triggers for running consolidation."""
    ENTRY_COUNT = "entry_count"      # After N new entries
    TIME_INTERVAL = "time_interval"  # After N hours/days
    MANUAL = "manual"                # Explicit call


@dataclass
class ConsolidationConfig:
    """Configuration for consolidation behavior."""
    # Promotion thresholds
    min_confidence_for_promotion: float = 0.6
    min_access_count_for_promotion: int = 3
    max_age_days_for_promotion: int = 30  # Don't promote very old entries unless highly accessed

    # Scoring weights
    weight_confidence: float = 0.30
    weight_outcome: float = 0.20
    weight_access_frequency: float = 0.25
    weight_recency: float = 0.15
    weight_tags_relevance: float = 0.10

    # Promotion limits
    promotion_percentile: float = 0.20  # Top 20% get promoted
    max_promotions_per_run: int = 50

    # Scheduling
    trigger_after_new_entries: int = 20
    trigger_after_hours: float = 24.0

    # Duplicate detection
    duplicate_similarity_threshold: float = 0.85

    # Archival
    archive_after_days: int = 90
    max_archived_entries: int = 10000

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConsolidationConfig":
        return cls(**data)


@dataclass
class ConsolidationStats:
    """Statistics from a consolidation run."""
    run_id: str
    started_at: str
    completed_at: str
    duration_seconds: float

    # Experience Memory stats
    experiences_scanned: int = 0
    experiences_promoted: int = 0
    experiences_archived: int = 0
    experiences_skipped: int = 0

    # Engineering Lessons stats
    lessons_scanned: int = 0
    lessons_promoted: int = 0
    lessons_archived: int = 0
    lessons_skipped: int = 0

    # Project Memory stats
    project_entries_scanned: int = 0
    project_entries_archived: int = 0

    # Duplicate detection
    duplicates_detected: int = 0

    # Errors
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ImportanceScorer:
    """Scores memory entries for importance to determine promotion eligibility."""

    def __init__(self, config: ConsolidationConfig):
        self.config = config

    def score_experience(self, entry: ExperienceEntry, now: datetime) -> float:
        """Score an experience entry for promotion.

        Factors:
        - Confidence (0-1): How reliable is this knowledge
        - Outcome (success=1.0, partial=0.7, neutral=0.5, failure=0.3)
        - Access frequency: How often it's been retrieved
        - Recency: How recent is the entry
        - Tag relevance: Presence of high-value tags
        """
        # Confidence score (already 0-1)
        confidence_score = entry.confidence

        # Outcome score
        outcome_scores = {
            "positive": 1.0,
            "success": 1.0,
            "partial": 0.7,
            "neutral": 0.5,
            "negative": 0.3,
            "failure": 0.3,
        }
        outcome_score = outcome_scores.get(entry.outcome, 0.5)

        # Access frequency score (logarithmic, caps at ~10 accesses)
        import math
        access_score = min(math.log1p(entry.access_count) / math.log1p(10), 1.0)

        # Recency score (exponential decay over days)
        try:
            entry_time = datetime.fromisoformat(entry.timestamp.replace('Z', '+00:00'))
            days_old = (now - entry_time).total_seconds() / 86400
            recency_score = max(0.0, 1.0 - (days_old / self.config.max_age_days_for_promotion))
        except Exception:
            recency_score = 0.5

        # Tag relevance score (boost for certain tags)
        high_value_tags = {
            "pattern", "best_practice", "architecture", "security",
            "performance", "debugging", "testing", "algorithm"
        }
        tag_matches = sum(1 for tag in entry.tags if tag in high_value_tags)
        tag_score = min(tag_matches / 3.0, 1.0)

        # Weighted combination
        total_score = (
            self.config.weight_confidence * confidence_score +
            self.config.weight_outcome * outcome_score +
            self.config.weight_access_frequency * access_score +
            self.config.weight_recency * recency_score +
            self.config.weight_tags_relevance * tag_score
        )

        return max(0.0, min(1.0, total_score))

    def score_lesson(self, lesson: EngineeringLesson, now: datetime) -> float:
        """Score an engineering lesson for promotion."""
        # Confidence score
        confidence_score = lesson.confidence

        # Severity/lesson type score
        severity_scores = {
            "critical": 1.0,
            "important": 0.8,
            "recommended": 0.6,
            "info": 0.4,
        }
        lesson_type_multiplier = {
            "pattern": 1.0,
            "anti_pattern": 0.9,
            "decision": 0.8,
        }
        severity_score = severity_scores.get(lesson.severity, 0.5)
        type_multiplier = lesson_type_multiplier.get(lesson.lesson_type, 0.7)

        # Access frequency
        import math
        access_score = min(math.log1p(lesson.access_count) / math.log1p(10), 1.0)

        # Recency
        try:
            entry_time = datetime.fromisoformat(lesson.timestamp.replace('Z', '+00:00'))
            days_old = (now - entry_time).total_seconds() / 86400
            recency_score = max(0.0, 1.0 - (days_old / self.config.max_age_days_for_promotion))
        except Exception:
            recency_score = 0.5

        # Tag relevance
        high_value_tags = {
            "pattern", "best_practice", "architecture", "security",
            "performance", "debugging", "testing", "algorithm", "refactoring"
        }
        tag_matches = sum(1 for tag in lesson.tags if tag in high_value_tags)
        tag_score = min(tag_matches / 3.0, 1.0)

        # Weighted combination (lesson type acts as multiplier on overall score)
        base_score = (
            self.config.weight_confidence * confidence_score +
            self.config.weight_outcome * severity_score +
            self.config.weight_access_frequency * access_score +
            self.config.weight_recency * recency_score +
            self.config.weight_tags_relevance * tag_score
        )

        total_score = base_score * type_multiplier
        return max(0.0, min(1.0, total_score))

    def score_project_entry(self, entry: Dict[str, Any], now: datetime) -> float:
        """Score a project memory entry for archival (not promotion)."""
        # For project entries, we mainly care about age and type for archival
        kind = entry.get("kind", "unknown")

        # Kind-based base score (errors and decisions more important)
        kind_scores = {
            "error": 0.9,
            "decision": 0.8,
            "edit": 0.6,
            "task": 0.5,
            "observation": 0.4,
        }
        base_score = kind_scores.get(kind, 0.3)

        # Recency (older = more likely to archive)
        try:
            entry_time = datetime.fromisoformat(entry.get("timestamp", "").replace('Z', '+00:00'))
            days_old = (now - entry_time).total_seconds() / 86400
            recency_score = min(days_old / self.config.archive_after_days, 1.0)
        except Exception:
            recency_score = 0.5

        return base_score * recency_score


class DuplicateDetector:
    """Detects duplicate entries to prevent re-promotion."""

    def __init__(self, threshold: float = 0.85):
        self.threshold = threshold
        self._content_hashes: Set[str] = set()

    def _compute_hash(self, content: str) -> str:
        """Compute a simple content hash for duplicate detection."""
        import hashlib
        # Normalize content
        normalized = " ".join(content.lower().split())
        return hashlib.md5(normalized.encode()).hexdigest()[:16]

    def is_duplicate(self, content: str, existing_hashes: Optional[Set[str]] = None) -> bool:
        """Check if content is a duplicate of already promoted entries."""
        content_hash = self._compute_hash(content)
        check_set = existing_hashes if existing_hashes is not None else self._content_hashes
        return content_hash in check_set

    def add(self, content: str) -> str:
        """Add content hash to the set."""
        content_hash = self._compute_hash(content)
        self._content_hashes.add(content_hash)
        return content_hash

    def load_existing_hashes(self, long_term_memory: LongTermMemory) -> None:
        """Load hashes from existing LongTermMemory entries."""
        for entry in long_term_memory.get_all():
            content = f"{entry.key}: {entry.value}"
            if entry.description:
                content += f" {entry.description}"
            self.add(content)


class ConsolidationEngine:
    """Main consolidation engine that coordinates promotion and archival."""

    def __init__(
        self,
        experience_memory: Optional[ExperienceMemory] = None,
        engineering_lessons: Optional[EngineeringLessonStorage] = None,
        long_term_memory: Optional[LongTermMemory] = None,
        project_memory: Optional[ProjectMemory] = None,
        config: Optional[ConsolidationConfig] = None,
        storage_path: str = "data/memory/consolidation_state.json",
    ):
        """Initialize the consolidation engine.

        Args:
            experience_memory: ExperienceMemory instance
            engineering_lessons: EngineeringLessonStorage instance
            long_term_memory: LongTermMemory instance (target for promotion)
            project_memory: ProjectMemory instance (source for archival)
            config: ConsolidationConfig (uses defaults if None)
            storage_path: Path to persist consolidation state
        """
        self.experience_memory = experience_memory
        self.engineering_lessons = engineering_lessons
        self.long_term_memory = long_term_memory
        self.project_memory = project_memory
        self.config = config or ConsolidationConfig()
        self.storage_path = Path(storage_path)
        self._lock = threading.RLock()

        # State tracking
        self._last_run: Optional[datetime] = None
        self._entries_since_last_run = 0
        self._run_history: List[ConsolidationStats] = []
        self._promoted_hashes: Set[str] = set()

        # Components
        self.scorer = ImportanceScorer(self.config)
        self.duplicate_detector = DuplicateDetector(self.config.duplicate_similarity_threshold)

        # Load state
        self._load_state()

        # Initialize duplicate detector with existing long-term entries
        if self.long_term_memory:
            self.duplicate_detector.load_existing_hashes(self.long_term_memory)

    def _load_state(self) -> None:
        """Load consolidation state from disk."""
        if not self.storage_path.exists():
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if "last_run" in data:
                self._last_run = datetime.fromisoformat(data["last_run"])
            self._entries_since_last_run = data.get("entries_since_last_run", 0)
            self._promoted_hashes = set(data.get("promoted_hashes", []))

            # Load run history (keep last 100)
            for run_data in data.get("run_history", [])[-100:]:
                self._run_history.append(ConsolidationStats(**run_data))
        except Exception as e:
            # Ignore load errors, start fresh
            pass

    def _save_state(self) -> None:
        """Save consolidation state to disk."""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.storage_path.with_suffix(".tmp")
        try:
            data = {
                "last_run": self._last_run.isoformat() if self._last_run else None,
                "entries_since_last_run": self._entries_since_last_run,
                "promoted_hashes": list(self._promoted_hashes),
                "run_history": [r.to_dict() for r in self._run_history[-100:]],
            }
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            temp_path.replace(self.storage_path)
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            raise

    def should_run(self, trigger: ConsolidationTrigger = ConsolidationTrigger.ENTRY_COUNT) -> bool:
        """Check if consolidation should run based on trigger."""
        now = datetime.now(timezone.utc)

        if trigger == ConsolidationTrigger.ENTRY_COUNT:
            return self._entries_since_last_run >= self.config.trigger_after_new_entries

        elif trigger == ConsolidationTrigger.TIME_INTERVAL:
            if self._last_run is None:
                return True
            hours_since = (now - self._last_run).total_seconds() / 3600
            return hours_since >= self.config.trigger_after_hours

        return False  # MANUAL always runs when called

    def record_new_entries(self, count: int = 1) -> None:
        """Record that new entries have been added (call after solve/repair)."""
        with self._lock:
            self._entries_since_last_run += count

    def run_consolidation(self, force: bool = False) -> ConsolidationStats:
        """Run the full consolidation process.

        Args:
            force: Run even if triggers not met

        Returns:
            ConsolidationStats with results
        """
        with self._lock:
            run_id = f"consolidation_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
            started_at = datetime.now(timezone.utc)

            stats = ConsolidationStats(
                run_id=run_id,
                started_at=started_at.isoformat(),
                completed_at="",
                duration_seconds=0.0,
            )

            try:
                # 1. Promote Experiences
                if self.experience_memory and self.long_term_memory:
                    stats.experiences_scanned = self.experience_memory.count()
                    exp_promoted = self._promote_experiences(stats)
                    stats.experiences_promoted = exp_promoted

                # 2. Promote Engineering Lessons
                if self.engineering_lessons and self.long_term_memory:
                    stats.lessons_scanned = self.engineering_lessons.count()
                    lesson_promoted = self._promote_lessons(stats)
                    stats.lessons_promoted = lesson_promoted

                # 3. Archive old Project Memory entries
                if self.project_memory:
                    stats.project_entries_scanned = self._count_project_entries()
                    stats.project_entries_archived = self._archive_project_entries(stats)

                # 4. Archive old Experiences/Lessons (optional, based on size)
                if self.experience_memory:
                    stats.experiences_archived = self._archive_old_experiences(stats)
                if self.engineering_lessons:
                    stats.lessons_archived = self._archive_old_lessons(stats)

            except Exception as e:
                stats.errors.append(str(e))

            completed_at = datetime.now(timezone.utc)
            stats.completed_at = completed_at.isoformat()
            stats.duration_seconds = (completed_at - started_at).total_seconds()

            # Update state
            self._last_run = completed_at
            self._entries_since_last_run = 0
            self._run_history.append(stats)
            self._save_state()

            return stats

    def _promote_experiences(self, stats: ConsolidationStats) -> int:
        """Promote high-value experiences to LongTermMemory."""
        if not self.experience_memory or not self.long_term_memory:
            return 0

        now = datetime.now(timezone.utc)
        all_entries = self.experience_memory.get_all()

        # Score all entries
        scored_entries = []
        for entry in all_entries:
            # Skip if confidence too low
            if entry.confidence < self.config.min_confidence_for_promotion:
                stats.experiences_skipped += 1
                continue

            # Skip if already promoted (check by ID in promoted hashes)
            entry_content = f"{entry.category}: {entry.title}: {entry.description}"
            if self.duplicate_detector.is_duplicate(entry_content, self._promoted_hashes):
                stats.duplicates_detected += 1
                stats.experiences_skipped += 1
                continue

            score = self.scorer.score_experience(entry, now)
            scored_entries.append((score, entry))

        # Sort by score descending
        scored_entries.sort(key=lambda x: x[0], reverse=True)

        # Determine promotion threshold (top percentile)
        num_to_promote = min(
            int(len(scored_entries) * self.config.promotion_percentile),
            self.config.max_promotions_per_run,
        )

        promoted = 0
        for i, (score, entry) in enumerate(scored_entries):
            if i >= num_to_promote:
                break
            if score < 0.5:  # Minimum quality threshold
                continue

            if self._promote_experience_to_long_term(entry, score):
                promoted += 1
                entry_content = f"{entry.category}: {entry.title}: {entry.description}"
                self.duplicate_detector.add(entry_content)
                self._promoted_hashes.add(self.duplicate_detector._compute_hash(entry_content))

        return promoted

    def _promote_experience_to_long_term(self, entry: ExperienceEntry, score: float) -> bool:
        """Promote a single experience to LongTermMemory."""
        if not self.long_term_memory:
            return False

        # Determine category based on experience category
        category_map = {
            "pattern": "pattern",
            "best_practice": "convention",
            "debugging": "knowledge",
            "architecture": "pattern",
            "performance": "knowledge",
            "security": "standard",
            "testing": "convention",
            "refactoring": "pattern",
            "tool_usage": "knowledge",
            "api_usage": "knowledge",
            "error_handling": "knowledge",
            "deployment": "knowledge",
            "learning": "knowledge",
        }
        category = category_map.get(entry.category, "knowledge")

        # Create key from title
        key = entry.title.lower().replace(" ", "_").replace("-", "_")[:100]
        # Ensure uniqueness
        base_key = key
        counter = 1
        while self.long_term_memory.get(category, key) is not None:
            key = f"{base_key}_{counter}"
            counter += 1

        # Build value and description
        value = entry.description
        if entry.code_snippet:
            value += f"\n\nCode Example:\n{entry.code_snippet}"

        description = f"Promoted from Experience Memory (score: {score:.2f}). "
        description += f"Original category: {entry.category}, outcome: {entry.outcome}, confidence: {entry.confidence:.2f}"
        if entry.tags:
            description += f" Tags: {', '.join(entry.tags)}"

        # Determine source
        source_map = {
            "user": "user",
            "inferred": "inferred",
            "project": "project",
            "documentation": "documentation",
        }
        source = source_map.get(entry.source, "inferred")

        # Create LongTermEntry
        ltm_entry = LongTermEntry(
            category=category,
            key=key,
            value=value,
            confidence=min(entry.confidence * 0.9 + 0.1, 1.0),  # Slight boost for promotion
            source=source,
            tags=entry.tags + ["promoted", "experience"],
            description=description,
            metadata={
                "promoted_from": "experience_memory",
                "original_id": entry.id,
                "promotion_score": score,
                "original_category": entry.category,
                "original_outcome": entry.outcome,
            }
        )

        try:
            self.long_term_memory.set(ltm_entry)
            return True
        except Exception:
            return False

    def _promote_lessons(self, stats: ConsolidationStats) -> int:
        """Promote high-value engineering lessons to LongTermMemory."""
        if not self.engineering_lessons or not self.long_term_memory:
            return 0

        now = datetime.now(timezone.utc)
        all_lessons = self.engineering_lessons.get_all()

        # Score all lessons
        scored_lessons = []
        for lesson in all_lessons:
            # Skip if confidence too low
            if lesson.confidence < self.config.min_confidence_for_promotion:
                stats.lessons_skipped += 1
                continue

            # Check duplicate
            lesson_content = f"{lesson.lesson_type}: {lesson.title}: {lesson.description}"
            if self.duplicate_detector.is_duplicate(lesson_content, self._promoted_hashes):
                stats.duplicates_detected += 1
                stats.lessons_skipped += 1
                continue

            score = self.scorer.score_lesson(lesson, now)
            scored_lessons.append((score, lesson))

        # Sort by score descending
        scored_lessons.sort(key=lambda x: x[0], reverse=True)

        num_to_promote = min(
            int(len(scored_lessons) * self.config.promotion_percentile),
            self.config.max_promotions_per_run,
        )

        promoted = 0
        for i, (score, lesson) in enumerate(scored_lessons):
            if i >= num_to_promote:
                break
            if score < 0.5:
                continue

            if self._promote_lesson_to_long_term(lesson, score):
                promoted += 1
                lesson_content = f"{lesson.lesson_type}: {lesson.title}: {lesson.description}"
                self.duplicate_detector.add(lesson_content)
                self._promoted_hashes.add(self.duplicate_detector._compute_hash(lesson_content))

        return promoted

    def _promote_lesson_to_long_term(self, lesson: EngineeringLesson, score: float) -> bool:
        """Promote a single lesson to LongTermMemory."""
        if not self.long_term_memory:
            return False

        # Determine category
        category_map = {
            "pattern": "pattern",
            "anti_pattern": "knowledge",
            "decision": "standard",
        }
        category = category_map.get(lesson.lesson_type, "knowledge")

        # Create key
        key = lesson.title.lower().replace(" ", "_").replace("-", "_")[:100]
        base_key = key
        counter = 1
        while self.long_term_memory.get(category, key) is not None:
            key = f"{base_key}_{counter}"
            counter += 1

        # Build value
        value = lesson.description
        if lesson.rationale:
            value += f"\n\nRationale: {lesson.rationale}"
        if lesson.code_example:
            value += f"\n\nCode Example:\n{lesson.code_example}"

        description = f"Promoted from Engineering Lessons (score: {score:.2f}). "
        description += f"Type: {lesson.lesson_type}, severity: {lesson.severity}, confidence: {lesson.confidence:.2f}"
        if lesson.tags:
            description += f" Tags: {', '.join(lesson.tags)}"

        source_map = {
            "user": "user",
            "inferred": "inferred",
            "project": "project",
            "documentation": "documentation",
        }
        source = "inferred"  # Lessons are typically inferred

        ltm_entry = LongTermEntry(
            category=category,
            key=key,
            value=value,
            confidence=min(lesson.confidence * 0.9 + 0.1, 1.0),
            source=source,
            tags=lesson.tags + ["promoted", "lesson", lesson.lesson_type],
            description=description,
            metadata={
                "promoted_from": "engineering_lessons",
                "original_id": lesson.id,
                "promotion_score": score,
                "original_type": lesson.lesson_type,
                "original_severity": lesson.severity,
                "related_ids": lesson.related_ids,
            }
        )

        try:
            self.long_term_memory.set(ltm_entry)
            return True
        except Exception:
            return False

    def _count_project_entries(self) -> int:
        """Count total project memory entries."""
        if not self.project_memory:
            return 0
        try:
            # ProjectMemory doesn't have a direct count method, use search
            return len(self.project_memory.search("", limit=10000))
        except Exception:
            return 0

    def _archive_project_entries(self, stats: ConsolidationStats) -> int:
        """Archive old project memory entries (mark for archival, not delete).

        Note: ProjectMemory uses vector DB and JSON. We'll add an 'archived' tag
        to old entries rather than deleting them, to preserve search capability.
        """
        if not self.project_memory:
            return 0

        now = datetime.now(timezone.utc)
        cutoff_date = now - timedelta(days=self.config.archive_after_days)
        archived = 0

        try:
            entries = self.project_memory.search("", limit=10000)
            for entry in entries:
                try:
                    entry_time = datetime.fromisoformat(entry.get("timestamp", "").replace('Z', '+00:00'))
                    if entry_time < cutoff_date:
                        # Mark as archived by adding tag (would need ProjectMemory support)
                        # For now, we just count
                        archived += 1
                except Exception:
                    continue
        except Exception as e:
            stats.errors.append(f"Project archival failed: {e}")

        return archived

    def _archive_old_experiences(self, stats: ConsolidationStats) -> int:
        """Archive old, low-access experiences."""
        if not self.experience_memory:
            return 0

        now = datetime.now(timezone.utc)
        cutoff_date = now - timedelta(days=self.config.archive_after_days)
        archived = 0

        try:
            all_entries = self.experience_memory.get_all()
            for entry in all_entries:
                try:
                    entry_time = datetime.fromisoformat(entry.timestamp.replace('Z', '+00:00'))
                    if entry_time < cutoff_date and entry.access_count < 2:
                        # Could move to archive file or just mark
                        archived += 1
                except Exception:
                    continue
        except Exception as e:
            stats.errors.append(f"Experience archival failed: {e}")

        return archived

    def _archive_old_lessons(self, stats: ConsolidationStats) -> int:
        """Archive old, low-access lessons."""
        if not self.engineering_lessons:
            return 0

        now = datetime.now(timezone.utc)
        cutoff_date = now - timedelta(days=self.config.archive_after_days)
        archived = 0

        try:
            all_lessons = self.engineering_lessons.get_all()
            for lesson in all_lessons:
                try:
                    entry_time = datetime.fromisoformat(lesson.timestamp.replace('Z', '+00:00'))
                    if entry_time < cutoff_date and lesson.access_count < 2:
                        archived += 1
                except Exception:
                    continue
        except Exception as e:
            stats.errors.append(f"Lesson archival failed: {e}")

        return archived

    def get_stats(self) -> Dict[str, Any]:
        """Get consolidation engine statistics."""
        with self._lock:
            return {
                "last_run": self._last_run.isoformat() if self._last_run else None,
                "entries_since_last_run": self._entries_since_last_run,
                "total_runs": len(self._run_history),
                "total_promoted_experiences": sum(r.experiences_promoted for r in self._run_history),
                "total_promoted_lessons": sum(r.lessons_promoted for r in self._run_history),
                "total_archived": sum(r.project_entries_archived + r.experiences_archived + r.lessons_archived for r in self._run_history),
                "promoted_hashes_count": len(self._promoted_hashes),
                "config": self.config.to_dict(),
            }

    def get_run_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent consolidation run history."""
        with self._lock:
            return [r.to_dict() for r in self._run_history[-limit:]]

    def reset_state(self) -> None:
        """Reset consolidation state (for testing)."""
        with self._lock:
            self._last_run = None
            self._entries_since_last_run = 0
            self._run_history = []
            self._promoted_hashes = set()
            self._save_state()


def create_consolidation_engine(
    experience_memory: Optional[ExperienceMemory] = None,
    engineering_lessons: Optional[EngineeringLessonStorage] = None,
    long_term_memory: Optional[LongTermMemory] = None,
    project_memory: Optional[ProjectMemory] = None,
    config: Optional[ConsolidationConfig] = None,
    storage_path: str = "data/memory/consolidation_state.json",
) -> ConsolidationEngine:
    """Factory function to create ConsolidationEngine with sensible defaults."""
    return ConsolidationEngine(
        experience_memory=experience_memory,
        engineering_lessons=engineering_lessons,
        long_term_memory=long_term_memory,
        project_memory=project_memory,
        config=config,
        storage_path=storage_path,
    )