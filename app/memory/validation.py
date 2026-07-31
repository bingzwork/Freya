"""Knowledge Validation for Freya AI.

This module validates newly acquired knowledge before it enters the Knowledge Base,
ensuring only trustworthy, accurate information is stored.

Features:
- Source identification and tracking
- Cross-reference against existing knowledge
- Conflict detection (outdated docs, contradictions, multi-source disagreements)
- Source reliability evaluation with weighted hierarchy
- Confidence calculation with configurable thresholds
- Storage decision (auto-store, delay, reject, manual review)
- Complete validation metadata for traceability

Integration:
- Works with SemanticMemory, ExperienceMemory, EngineeringLessons, LongTermMemory
- Uses CrossMemoryReferences for conflict/derivation tracking
- Reuses KnowledgeRetrieval source quality scores
- Compatible with ConsolidationEngine promotion pipeline
"""

import json
import threading
import hashlib
import difflib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple, Union
from enum import Enum
from collections import defaultdict

# Import memory systems
from app.memory.semantic_memory import SemanticMemory, SemanticEntry, KnowledgeCategory
from app.memory.experience_memory import ExperienceMemory, ExperienceEntry
from app.memory.engineering_lessons import EngineeringLessonStorage, EngineeringLesson
from app.memory.long_term_memory import LongTermMemory, LongTermEntry
from app.memory.cross_references import (
    CrossMemoryReferences,
    CrossReference,
    ReferenceType,
    MemoryType,
)
from app.knowledge_retrieval.models import KnowledgeSourceType
from app.knowledge_retrieval.sources import create_adapters_from_agent


class ValidationSourceType(Enum):
    """Types of knowledge sources for validation."""
    OFFICIAL_DOCUMENTATION = "official_documentation"
    SOURCE_CODE = "source_code"
    STANDARDS_SPECIFICATIONS = "standards_specifications"
    VENDOR_DOCUMENTATION = "vendor_documentation"
    MULTIPLE_INDEPENDENT_SOURCES = "multiple_independent_sources"
    STRONGER_LLM = "stronger_llm"
    COMMUNITY_DISCUSSIONS = "community_discussions"
    SINGLE_ARTICLE_BLOG = "single_article_blog"
    USER_PROVIDED = "user_provided"
    EXISTING_KNOWLEDGE_BASE = "existing_knowledge_base"
    EXPERIENCE_MEMORY = "experience_memory"
    ENGINEERING_LESSONS = "engineering_lessons"
    SEMANTIC_MEMORY = "semantic_memory"
    LONG_TERM_MEMORY = "long_term_memory"
    UNKNOWN = "unknown"


class ConflictType(Enum):
    """Types of conflicts detected during validation."""
    SOURCES_DISAGREE = "sources_disagree"
    OUTDATED_DOCUMENTATION = "outdated_documentation"
    DOCS_VS_SOURCE_CODE = "docs_vs_source_code"
    MULTIPLE_VERSIONS = "multiple_versions"
    MULTIPLE_OFFICIAL_REFS = "multiple_official_refs"
    KB_CONTRADICTION = "kb_contradiction"
    LLM_CONFLICT = "llm_conflict"
    VERSION_MISMATCH = "version_mismatch"


class ValidationStatus(Enum):
    """Validation status for knowledge items."""
    PENDING = "pending"                 # Not yet validated
    VALIDATED = "validated"             # High confidence, no conflicts
    HIGH_CONFIDENCE = "high_confidence" # High confidence, minor concerns
    MODERATE_CONFIDENCE = "moderate_confidence"  # Moderate confidence
    LOW_CONFIDENCE = "low_confidence"   # Low confidence
    CONFLICT_DETECTED = "conflict_detected"  # Has unresolved conflicts
    DUPLICATE = "duplicate"             # Duplicate of existing knowledge
    REJECTED = "rejected"               # Below threshold, do not store
    MANUAL_REVIEW = "manual_review"     # Requires human review


class StorageDecision(Enum):
    """Storage decision after validation."""
    AUTO_STORE = "auto_store"           # Store automatically
    DELAY_STORE = "delay_store"         # Delay, gather more evidence
    REJECT = "reject"                   # Do not store
    MANUAL_REVIEW = "manual_review"     # Require human approval


# Source reliability hierarchy (higher = more reliable)
DEFAULT_SOURCE_RELIABILITY: Dict[ValidationSourceType, float] = {
    ValidationSourceType.OFFICIAL_DOCUMENTATION: 0.95,
    ValidationSourceType.SOURCE_CODE: 0.90,
    ValidationSourceType.STANDARDS_SPECIFICATIONS: 0.93,
    ValidationSourceType.VENDOR_DOCUMENTATION: 0.85,
    ValidationSourceType.MULTIPLE_INDEPENDENT_SOURCES: 0.88,
    ValidationSourceType.STRONGER_LLM: 0.75,
    ValidationSourceType.USER_PROVIDED: 0.90,
    ValidationSourceType.EXISTING_KNOWLEDGE_BASE: 0.92,
    ValidationSourceType.ENGINEERING_LESSONS: 0.85,
    ValidationSourceType.SEMANTIC_MEMORY: 0.90,
    ValidationSourceType.LONG_TERM_MEMORY: 0.85,
    ValidationSourceType.EXPERIENCE_MEMORY: 0.75,
    ValidationSourceType.COMMUNITY_DISCUSSIONS: 0.60,
    ValidationSourceType.SINGLE_ARTICLE_BLOG: 0.50,
    ValidationSourceType.UNKNOWN: 0.40,
}


# Confidence thresholds
class ConfidenceThresholds:
    VERIFIED = 0.95      # 95-100%
    HIGH = 0.80          # 80-94%
    MODERATE = 0.60      # 60-79%
    LOW = 0.40           # 40-59%
    REJECT = 0.40        # Below 40% -> do not store


@dataclass
class ValidationSource:
    """A single source contributing to a knowledge item."""
    source_type: ValidationSourceType
    identifier: str                    # URL, file path, memory entry ID, etc.
    content: str                       # Relevant excerpt or summary
    confidence: float = 1.0            # Source's own confidence (if applicable)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)
    reliability: Optional[float] = None  # Computed reliability score

    def __post_init__(self):
        if self.reliability is None:
            self.reliability = DEFAULT_SOURCE_RELIABILITY.get(self.source_type, 0.5)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["source_type"] = self.source_type.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ValidationSource":
        data = data.copy()
        data["source_type"] = ValidationSourceType(data["source_type"])
        return cls(**data)


@dataclass
class ValidationConflict:
    """A conflict detected between sources or with existing knowledge."""
    conflict_id: str
    conflict_type: ConflictType
    description: str
    involved_sources: List[str]                # Source identifiers
    involved_entries: List[str] = field(default_factory=list)  # Existing KB entry IDs
    severity: float = 0.5                      # 0-1, how serious
    detected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    resolved: bool = False
    resolution: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["conflict_type"] = self.conflict_type.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ValidationConflict":
        data = data.copy()
        data["conflict_type"] = ConflictType(data["conflict_type"])
        return cls(**data)


@dataclass
class ValidationResult:
    """Complete validation result for a knowledge item."""
    validation_id: str
    knowledge_item_id: str                  # ID of the knowledge being validated
    title: str
    content: str
    category: str

    # Sources
    sources: List[ValidationSource] = field(default_factory=list)

    # Cross-references
    cross_references: List[str] = field(default_factory=list)  # Related KB entry IDs

    # Conflicts
    conflicts: List[ValidationConflict] = field(default_factory=list)

    # Scores
    source_reliability_score: float = 0.0      # Weighted avg of source reliabilities
    agreement_score: float = 0.0               # How much sources agree
    freshness_score: float = 1.0               # How recent the information is
    kb_consistency_score: float = 1.0          # Consistency with existing KB
    overall_confidence: float = 0.0            # Final confidence (0-1)

    # Decision
    validation_status: ValidationStatus = ValidationStatus.PENDING
    storage_decision: StorageDecision = StorageDecision.MANUAL_REVIEW

    # Metadata
    validated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    reviewer: str = "ai"                       # "ai" or "user"
    validation_notes: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["sources"] = [s.to_dict() for s in self.sources]
        data["conflicts"] = [c.to_dict() for c in self.conflicts]
        data["validation_status"] = self.validation_status.value
        data["storage_decision"] = self.storage_decision.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ValidationResult":
        data = data.copy()
        data["sources"] = [ValidationSource.from_dict(s) for s in data.get("sources", [])]
        data["conflicts"] = [ValidationConflict.from_dict(c) for c in data.get("conflicts", [])]
        data["validation_status"] = ValidationStatus(data["validation_status"])
        data["storage_decision"] = StorageDecision(data["storage_decision"])
        return cls(**data)


@dataclass
class ValidationConfig:
    """Configuration for validation behavior."""
    # Source reliability (can be customized)
    source_reliability: Dict[ValidationSourceType, float] = field(default_factory=lambda: DEFAULT_SOURCE_RELIABILITY.copy())

    # Confidence thresholds
    verified_threshold: float = ConfidenceThresholds.VERIFIED
    high_confidence_threshold: float = ConfidenceThresholds.HIGH
    moderate_confidence_threshold: float = ConfidenceThresholds.MODERATE
    low_confidence_threshold: float = ConfidenceThresholds.LOW
    reject_threshold: float = ConfidenceThresholds.REJECT

    # Weights for confidence calculation
    weight_source_reliability: float = 0.30
    weight_agreement: float = 0.25
    weight_freshness: float = 0.15
    weight_kb_consistency: float = 0.20
    weight_num_sources: float = 0.10

    # Conflict thresholds
    conflict_severity_threshold: float = 0.6  # Above this = conflict_detected status
    similarity_for_conflict: float = 0.7      # Topic similarity to consider conflict

    # Agreement detection
    min_sources_for_agreement: int = 2
    agreement_similarity_threshold: float = 0.75

    # Freshness (days)
    freshness_half_life_days: int = 365

    # Storage decision rules
    auto_store_min_confidence: float = 0.80
    auto_store_max_conflicts: int = 0
    delay_store_min_confidence: float = 0.40
    manual_review_confidence_range: Tuple[float, float] = (0.70, 0.80)

    # Cross-reference
    max_cross_refs: int = 10
    cross_ref_min_similarity: float = 0.3

    # Duplicate detection
    duplicate_similarity_threshold: float = 0.85

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["source_reliability"] = {k.value: v for k, v in self.source_reliability.items()}
        data["manual_review_confidence_range"] = list(self.manual_review_confidence_range)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ValidationConfig":
        data = data.copy()
        data["source_reliability"] = {ValidationSourceType(k): v for k, v in data.get("source_reliability", {}).items()}
        data["manual_review_confidence_range"] = tuple(data.get("manual_review_confidence_range", [0.70, 0.80]))
        return cls(**data)


class KnowledgeValidator:
    """Main knowledge validation engine."""

    def __init__(
        self,
        config: Optional[ValidationConfig] = None,
        storage_path: str = "data/memory/validation_results.json",
        cross_refs: Optional[CrossMemoryReferences] = None,
        semantic_memory: Optional[SemanticMemory] = None,
        experience_memory: Optional[ExperienceMemory] = None,
        engineering_lessons: Optional[EngineeringLessonStorage] = None,
        long_term_memory: Optional[LongTermMemory] = None,
    ):
        self.config = config or ValidationConfig()
        self.storage_path = Path(storage_path)
        self._lock = threading.RLock()

        # Memory systems (injected for integration)
        self.cross_refs = cross_refs
        self.semantic_memory = semantic_memory
        self.experience_memory = experience_memory
        self.engineering_lessons = engineering_lessons
        self.long_term_memory = long_term_memory

        # State
        self._validation_results: Dict[str, ValidationResult] = {}
        self._load()

    def _generate_validation_id(self) -> str:
        return f"val_{hashlib.md5(f'{datetime.now().isoformat()}'.encode()).hexdigest()[:12]}"

    def _generate_conflict_id(self) -> str:
        return f"conf_{hashlib.md5(f'{datetime.now().isoformat()}'.encode()).hexdigest()[:12]}"

    def _save(self) -> None:
        """Save validation results to disk."""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.storage_path.with_suffix(".tmp")
        try:
            data = {
                "results": [r.to_dict() for r in self._validation_results.values()],
                "version": 1,
            }
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            temp_path.replace(self.storage_path)
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            raise

    def _load(self) -> None:
        """Load validation results from disk."""
        if not self.storage_path.exists():
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._validation_results = {}
            for result_data in data.get("results", []):
                result = ValidationResult.from_dict(result_data)
                self._validation_results[result.validation_id] = result
        except Exception:
            self._validation_results = {}

    def validate(
        self,
        knowledge_id: str,
        title: str,
        content: str,
        category: str,
        sources: List[ValidationSource],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        """Validate a knowledge item comprehensively.

        Performs:
        1. Source identification & reliability scoring
        2. Cross-reference against existing knowledge
        3. Conflict detection
        4. Confidence calculation
        5. Storage decision
        6. Metadata recording
        """
        with self._lock:
            validation_id = self._generate_validation_id()
            now = datetime.now(timezone.utc).isoformat()

            # 1. Source reliability scoring
            source_reliability_score = self._calculate_source_reliability(sources)

            # 2. Cross-reference existing knowledge
            cross_refs = self._cross_reference_knowledge(title, content, category)

            # 3. Agreement scoring (do sources agree?)
            agreement_score = self._calculate_agreement(sources)

            # 4. Freshness scoring
            freshness_score = self._calculate_freshness(sources)

            # 5. KB consistency scoring
            kb_consistency_score = self._calculate_kb_consistency(title, content, category, cross_refs)

            # 6. Conflict detection
            conflicts = self._detect_conflicts(
                title, content, category, sources, cross_refs
            )

            # 7. Overall confidence calculation
            overall_confidence = self._calculate_confidence(
                source_reliability_score=source_reliability_score,
                agreement_score=agreement_score,
                freshness_score=freshness_score,
                kb_consistency_score=kb_consistency_score,
                num_sources=len(sources),
                conflicts=conflicts,
            )

            # 8. Determine validation status
            validation_status = self._determine_validation_status(
                overall_confidence, conflicts
            )

            # 9. Determine storage decision
            storage_decision = self._determine_storage_decision(
                overall_confidence, conflicts, validation_status
            )

            # 10. Build validation notes
            validation_notes = self._build_validation_notes(
                sources, cross_refs, conflicts, overall_confidence
            )

            # Create result
            result = ValidationResult(
                validation_id=validation_id,
                knowledge_item_id=knowledge_id,
                title=title,
                content=content,
                category=category,
                sources=sources,
                cross_references=cross_refs,
                conflicts=conflicts,
                source_reliability_score=source_reliability_score,
                agreement_score=agreement_score,
                freshness_score=freshness_score,
                kb_consistency_score=kb_consistency_score,
                overall_confidence=overall_confidence,
                validation_status=validation_status,
                storage_decision=storage_decision,
                validated_at=now,
                reviewer="ai",
                validation_notes=validation_notes,
                metadata=metadata or {},
            )

            # Store result
            self._validation_results[validation_id] = result
            self._save()

            # If auto-store, also add cross-references
            if storage_decision == StorageDecision.AUTO_STORE and self.cross_refs:
                self._record_cross_references(knowledge_id, title, content, category, cross_refs, sources)

            return result

    def _calculate_source_reliability(self, sources: List[ValidationSource]) -> float:
        """Calculate weighted average reliability of all sources."""
        if not sources:
            return 0.0

        total_weight = 0.0
        weighted_sum = 0.0

        for source in sources:
            reliability = self.config.source_reliability.get(source.source_type, 0.5)
            # Weight by source's own confidence
            weight = source.confidence
            weighted_sum += reliability * weight
            total_weight += weight

        return weighted_sum / total_weight if total_weight > 0 else 0.0

    def _cross_reference_knowledge(
        self, title: str, content: str, category: str
    ) -> List[str]:
        """Cross-reference against existing knowledge bases to find related entries."""
        cross_refs = []

        # Collect all knowledge from available memory systems
        all_entries: List[Tuple[str, str, str]] = []  # (memory_type, entry_id, content)

        if self.semantic_memory:
            entries = self.semantic_memory.search(title, limit=20)
            for e in entries:
                searchable = f"{e.title} {e.content}"
                similarity = self._similarity(f"{title} {content}", searchable)
                if similarity >= self.config.cross_ref_min_similarity:
                    all_entries.append(("semantic", e.entry_id, searchable))
                    cross_refs.append(e.entry_id)

        if self.experience_memory:
            entries = self.experience_memory.search(keyword=title, limit=20)
            for e in entries:
                searchable = f"{e.title} {e.description}"
                similarity = self._similarity(f"{title} {content}", searchable)
                if similarity >= self.config.cross_ref_min_similarity:
                    all_entries.append(("experience", e.id, searchable))
                    cross_refs.append(e.id)

        if self.engineering_lessons:
            entries = self.engineering_lessons.search(keyword=title, limit=20)
            for e in entries:
                searchable = f"{e.title} {e.description} {e.rationale}"
                similarity = self._similarity(f"{title} {content}", searchable)
                if similarity >= self.config.cross_ref_min_similarity:
                    all_entries.append(("lessons", e.id, searchable))
                    cross_refs.append(e.id)

        if self.long_term_memory:
            entries = self.long_term_memory.search(query=title, limit=20)
            for e in entries:
                searchable = f"{e.key} {e.value} {e.description}"
                similarity = self._similarity(f"{title} {content}", searchable)
                if similarity >= self.config.cross_ref_min_similarity:
                    all_entries.append(("long_term", f"{e.category}.{e.key}", searchable))
                    cross_refs.append(f"{e.category}.{e.key}")

        # Limit cross-references
        return cross_refs[:self.config.max_cross_refs]

    def _calculate_agreement(self, sources: List[ValidationSource]) -> float:
        """Calculate how much sources agree with each other."""
        if len(sources) < self.config.min_sources_for_agreement:
            return 0.5  # Neutral - not enough sources to determine agreement

        # Compare all pairs of sources
        similarities = []
        for i, s1 in enumerate(sources):
            for s2 in sources[i+1:]:
                sim = self._similarity(s1.content, s2.content)
                similarities.append(sim)

        if not similarities:
            return 0.5

        avg_similarity = sum(similarities) / len(similarities)
        return min(avg_similarity, 1.0)

    def _calculate_freshness(self, sources: List[ValidationSource]) -> float:
        """Calculate freshness score based on source timestamps."""
        if not sources:
            return 0.5

        now = datetime.now(timezone.utc)
        freshness_scores = []

        for source in sources:
            try:
                source_time = datetime.fromisoformat(source.timestamp.replace('Z', '+00:00'))
                days_old = (now - source_time).total_seconds() / 86400
                # Exponential decay with configurable half-life
                freshness = 2 ** (-days_old / self.config.freshness_half_life_days)
                freshness_scores.append(freshness)
            except Exception:
                freshness_scores.append(0.5)

        return sum(freshness_scores) / len(freshness_scores) if freshness_scores else 0.5

    def _calculate_kb_consistency(
        self,
        title: str,
        content: str,
        category: str,
        cross_refs: List[str],
    ) -> float:
        """Calculate consistency with existing knowledge base."""
        if not cross_refs:
            return 1.0  # No existing knowledge to conflict with

        # Check for contradictions with cross-referenced entries
        conflicts = 0
        total_checked = 0

        for ref_id in cross_refs:
            total_checked += 1
            # Try to get the referenced entry and check for contradictions
            entry_content = self._get_entry_content(ref_id)
            entry_title = self._get_entry_title(ref_id)
            if entry_content and entry_title:
                # If similar topic but very different content, might be contradiction
                title_sim = self._similarity(title, entry_title)
                content_sim = self._similarity(content, entry_content)
                if title_sim > self.config.similarity_for_conflict and content_sim < 0.4:
                    conflicts += 1

        if total_checked == 0:
            return 1.0

        consistency = 1.0 - (conflicts / total_checked)
        return max(consistency, 0.0)

    def _get_entry_title(self, entry_id: str) -> Optional[str]:
        """Get title of a cross-referenced entry."""
        # Check different memory systems
        if self.semantic_memory:
            entry = self.semantic_memory.get_by_id(entry_id)
            if entry:
                return entry.title

        if self.experience_memory:
            entry = self.experience_memory.get(entry_id)
            if entry:
                return entry.title

        if self.engineering_lessons:
            entry = self.engineering_lessons.get(entry_id)
            if entry:
                return entry.title

        if self.long_term_memory:
            # entry_id format: "category.key"
            if "." in entry_id:
                cat, key = entry_id.split(".", 1)
                entry = self.long_term_memory.get_entry(cat, key)
                if entry:
                    return entry.key  # Use key as title for LTM

        return None

    def _get_entry_content(self, entry_id: str) -> Optional[str]:
        """Get content of a cross-referenced entry."""
        # Check different memory systems
        if self.semantic_memory:
            entry = self.semantic_memory.get_by_id(entry_id)
            if entry:
                return f"{entry.title} {entry.content}"

        if self.experience_memory:
            entry = self.experience_memory.get(entry_id)
            if entry:
                return f"{entry.title} {entry.description}"

        if self.engineering_lessons:
            entry = self.engineering_lessons.get(entry_id)
            if entry:
                return f"{entry.title} {entry.description} {entry.rationale}"

        if self.long_term_memory:
            # entry_id format: "category.key"
            if "." in entry_id:
                cat, key = entry_id.split(".", 1)
                entry = self.long_term_memory.get_entry(cat, key)
                if entry:
                    return f"{entry.key} {entry.value} {entry.description}"

        return None

    def _detect_conflicts(
        self,
        title: str,
        content: str,
        category: str,
        sources: List[ValidationSource],
        cross_refs: List[str],
    ) -> List[ValidationConflict]:
        """Detect conflicts between sources and with existing knowledge."""
        conflicts = []

        # 1. Sources disagree with each other
        if len(sources) >= 2:
            for i, s1 in enumerate(sources):
                for s2 in sources[i+1:]:
                    sim = self._similarity(s1.content, s2.content)
                    # Same topic (high title sim) but different content
                    title_sim = self._similarity(s1.content[:100], s2.content[:100])
                    if title_sim > self.config.similarity_for_conflict and sim < 0.5:
                        conflict = ValidationConflict(
                            conflict_id=self._generate_conflict_id(),
                            conflict_type=ConflictType.SOURCES_DISAGREE,
                            description=f"Sources disagree: {s1.identifier} vs {s2.identifier}",
                            involved_sources=[s1.identifier, s2.identifier],
                            severity=1.0 - sim,
                            metadata={"source1_type": s1.source_type.value, "source2_type": s2.source_type.value}
                        )
                        conflicts.append(conflict)

        # 2. Conflict with existing KB entries
        for ref_id in cross_refs:
            entry_content = self._get_entry_content(ref_id)
            if entry_content:
                title_sim = self._similarity(title, ref_id)
                content_sim = self._similarity(content, entry_content)
                if title_sim > self.config.similarity_for_conflict and content_sim < 0.4:
                    conflict = ValidationConflict(
                        conflict_id=self._generate_conflict_id(),
                        conflict_type=ConflictType.KB_CONTRADICTION,
                        description=f"Contradicts existing knowledge: {ref_id}",
                        involved_sources=[s.identifier for s in sources],
                        involved_entries=[ref_id],
                        severity=1.0 - content_sim,
                        metadata={"existing_entry": ref_id}
                    )
                    conflicts.append(conflict)

        # 3. Check for outdated documentation (source is docs, but code differs)
        doc_sources = [s for s in sources if s.source_type == ValidationSourceType.OFFICIAL_DOCUMENTATION]
        code_sources = [s for s in sources if s.source_type == ValidationSourceType.SOURCE_CODE]

        for doc in doc_sources:
            for code in code_sources:
                sim = self._similarity(doc.content, code.content)
                title_sim = self._similarity(doc.content[:100], code.content[:100])
                if title_sim > self.config.similarity_for_conflict and sim < 0.6:
                    conflict = ValidationConflict(
                        conflict_id=self._generate_conflict_id(),
                        conflict_type=ConflictType.DOCS_VS_SOURCE_CODE,
                        description=f"Documentation vs source code mismatch: {doc.identifier} vs {code.identifier}",
                        involved_sources=[doc.identifier, code.identifier],
                        severity=1.0 - sim,
                        metadata={}
                    )
                    conflicts.append(conflict)

        # 4. Multiple versions of same fact
        version_sources = defaultdict(list)
        for s in sources:
            # Look for version indicators in content
            version_key = self._extract_version_key(s.content)
            if version_key:
                version_sources[version_key].append(s)

        for version, vers_sources in version_sources.items():
            if len(vers_sources) > 1:
                # Multiple sources for same version - check if they agree
                for i, s1 in enumerate(vers_sources):
                    for s2 in vers_sources[i+1:]:
                        sim = self._similarity(s1.content, s2.content)
                        if sim < 0.7:
                            conflict = ValidationConflict(
                                conflict_id=self._generate_conflict_id(),
                                conflict_type=ConflictType.MULTIPLE_VERSIONS,
                                description=f"Conflicting info for version {version}: {s1.identifier} vs {s2.identifier}",
                                involved_sources=[s1.identifier, s2.identifier],
                                severity=1.0 - sim,
                                metadata={"version": version}
                            )
                            conflicts.append(conflict)

        return conflicts

    def _extract_version_key(self, content: str) -> Optional[str]:
        """Extract version identifier from content if present."""
        import re
        # Look for version patterns like v1.2.3, version 2.0, etc.
        patterns = [
            r'v?\d+\.\d+(\.\d+)?',
            r'version\s+\d+\.\d+',
            r'release\s+\d+\.\d+',
        ]
        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                return match.group(0)
        return None

    def _calculate_confidence(
        self,
        source_reliability_score: float,
        agreement_score: float,
        freshness_score: float,
        kb_consistency_score: float,
        num_sources: int,
        conflicts: List[ValidationConflict],
    ) -> float:
        """Calculate overall confidence score."""
        # Base weighted score
        base_score = (
            self.config.weight_source_reliability * source_reliability_score +
            self.config.weight_agreement * agreement_score +
            self.config.weight_freshness * freshness_score +
            self.config.weight_kb_consistency * kb_consistency_score +
            self.config.weight_num_sources * min(num_sources / 5.0, 1.0)
        )

        # Apply conflict penalties
        conflict_penalty = 0.0
        for conflict in conflicts:
            conflict_penalty += conflict.severity * 0.15  # Up to 15% penalty per conflict

        final_score = base_score * (1.0 - min(conflict_penalty, 0.6))  # Cap penalty at 60%

        return max(0.0, min(1.0, final_score))

    def _determine_validation_status(
        self,
        confidence: float,
        conflicts: List[ValidationConflict],
    ) -> ValidationStatus:
        """Determine validation status from confidence and conflicts."""
        # Check for serious conflicts
        serious_conflicts = [c for c in conflicts if c.severity >= self.config.conflict_severity_threshold]
        if serious_conflicts:
            return ValidationStatus.CONFLICT_DETECTED

        if confidence >= self.config.verified_threshold:
            return ValidationStatus.VALIDATED
        elif confidence >= self.config.high_confidence_threshold:
            return ValidationStatus.HIGH_CONFIDENCE
        elif confidence >= self.config.moderate_confidence_threshold:
            return ValidationStatus.MODERATE_CONFIDENCE
        elif confidence >= self.config.low_confidence_threshold:
            return ValidationStatus.LOW_CONFIDENCE
        else:
            return ValidationStatus.REJECTED

    def _determine_storage_decision(
        self,
        confidence: float,
        conflicts: List[ValidationConflict],
        status: ValidationStatus,
    ) -> StorageDecision:
        """Determine storage decision."""
        serious_conflicts = [c for c in conflicts if c.severity >= self.config.conflict_severity_threshold]

        # Reject if below threshold
        if confidence < self.config.reject_threshold:
            return StorageDecision.REJECT

        # Require manual review for conflicts
        if serious_conflicts:
            return StorageDecision.MANUAL_REVIEW

        # Auto-store if high confidence and no conflicts
        if confidence >= self.config.auto_store_min_confidence and not serious_conflicts:
            return StorageDecision.AUTO_STORE

        # Delay if in manual review range
        if self.config.manual_review_confidence_range[0] <= confidence < self.config.auto_store_min_confidence:
            return StorageDecision.MANUAL_REVIEW

        # Delay store for lower confidence
        return StorageDecision.DELAY_STORE

    def _build_validation_notes(
        self,
        sources: List[ValidationSource],
        cross_refs: List[str],
        conflicts: List[ValidationConflict],
        confidence: float,
    ) -> str:
        """Build human-readable validation notes."""
        notes = []

        notes.append(f"Validated against {len(sources)} source(s).")
        if cross_refs:
            notes.append(f"Cross-referenced with {len(cross_refs)} existing knowledge entr(ies).")

        if conflicts:
            notes.append(f"⚠️ {len(conflicts)} conflict(s) detected:")
            for c in conflicts[:3]:  # Show first 3
                notes.append(f"  - {c.conflict_type.value}: {c.description}")
            if len(conflicts) > 3:
                notes.append(f"  ... and {len(conflicts) - 3} more")

        notes.append(f"Overall confidence: {confidence:.1%}")

        source_types = [s.source_type.value for s in sources]
        notes.append(f"Sources: {', '.join(set(source_types))}")

        return "\n".join(notes)

    def _record_cross_references(
        self,
        knowledge_id: str,
        title: str,
        content: str,
        category: str,
        cross_refs: List[str],
        sources: List[ValidationSource],
    ) -> None:
        """Record cross-references in the cross-memory graph."""
        if not self.cross_refs:
            return

        try:
            # Add node for this knowledge
            self.cross_refs.add_node(
                memory_type=MemoryType.KNOWLEDGE.value,
                entry_id=knowledge_id,
                title=title,
                summary=content[:200],
                metadata={"category": category, "validated": True}
            )

            # Add references to cross-referenced entries
            for ref_id in cross_refs:
                # Determine reference type based on relationship
                ref_memory_type = self._guess_memory_type(ref_id)
                self.cross_refs.add_reference(
                    source_memory=MemoryType.KNOWLEDGE.value,
                    source_id=knowledge_id,
                    target_memory=ref_memory_type,
                    target_id=ref_id,
                    reference_type=ReferenceType.RELATED,
                    confidence=0.7,
                    description=f"Cross-referenced during validation",
                )

            # Add source references
            for source in sources:
                if source.source_type in [
                    ValidationSourceType.EXPERIENCE_MEMORY,
                    ValidationSourceType.ENGINEERING_LESSONS,
                    ValidationSourceType.SEMANTIC_MEMORY,
                    ValidationSourceType.LONG_TERM_MEMORY,
                ]:
                    source_memory_type = self._map_source_to_memory_type(source.source_type)
                    self.cross_refs.add_reference(
                        source_memory=source_memory_type,
                        source_id=source.identifier,
                        target_memory=MemoryType.KNOWLEDGE.value,
                        target_id=knowledge_id,
                        reference_type=ReferenceType.SOURCE,
                        confidence=source.reliability or 0.5,
                        description=f"Source for validated knowledge",
                    )
        except Exception:
            # Don't fail validation if cross-reference recording fails
            pass

    def _guess_memory_type(self, entry_id: str) -> str:
        """Guess memory type from entry ID format."""
        if entry_id.startswith("sem_"):
            return MemoryType.SEMANTIC.value
        elif entry_id.startswith("exp_"):
            return MemoryType.EXPERIENCE.value
        elif entry_id.startswith("lesson_"):
            return MemoryType.LESSONS.value
        elif "." in entry_id and not entry_id.startswith("exp_"):
            return MemoryType.LONG_TERM.value
        return MemoryType.KNOWLEDGE.value

    def _map_source_to_memory_type(self, source_type: ValidationSourceType) -> str:
        """Map validation source type to memory type."""
        mapping = {
            ValidationSourceType.EXPERIENCE_MEMORY: MemoryType.EXPERIENCE.value,
            ValidationSourceType.ENGINEERING_LESSONS: MemoryType.LESSONS.value,
            ValidationSourceType.SEMANTIC_MEMORY: MemoryType.SEMANTIC.value,
            ValidationSourceType.LONG_TERM_MEMORY: MemoryType.LONG_TERM.value,
        }
        return mapping.get(source_type, MemoryType.KNOWLEDGE.value)

    def _similarity(self, text1: str, text2: str) -> float:
        """Calculate text similarity using difflib."""
        if not text1 or not text2:
            return 0.0
        return difflib.SequenceMatcher(None, text1.lower(), text2.lower()).ratio()

    def get_validation_result(self, validation_id: str) -> Optional[ValidationResult]:
        """Get a validation result by ID."""
        with self._lock:
            return self._validation_results.get(validation_id)

    def get_all_validations(
        self,
        status: Optional[ValidationStatus] = None,
        limit: int = 50,
    ) -> List[ValidationResult]:
        """Get all validation results, optionally filtered by status."""
        with self._lock:
            results = list(self._validation_results.values())
            if status:
                results = [r for r in results if r.validation_status == status]
            results.sort(key=lambda x: x.validated_at, reverse=True)
            return results[:limit]

    def get_pending_validations(self) -> List[ValidationResult]:
        """Get validations requiring manual review."""
        with self._lock:
            return [
                r for r in self._validation_results.values()
                if r.storage_decision in [StorageDecision.MANUAL_REVIEW, StorageDecision.DELAY_STORE]
            ]

    def approve_validation(self, validation_id: str, reviewer: str = "user") -> bool:
        """Approve a validation for storage (manual review)."""
        with self._lock:
            result = self._validation_results.get(validation_id)
            if not result:
                return False

            if result.storage_decision != StorageDecision.MANUAL_REVIEW:
                return False

            result.storage_decision = StorageDecision.AUTO_STORE
            result.validation_status = ValidationStatus.VALIDATED
            result.reviewer = reviewer
            result.validated_at = datetime.now(timezone.utc).isoformat()
            result.validation_notes += f"\n\nApproved by {reviewer} at {result.validated_at}"

            self._save()
            return True

    def reject_validation(self, validation_id: str, reviewer: str = "user", reason: str = "") -> bool:
        """Reject a validation."""
        with self._lock:
            result = self._validation_results.get(validation_id)
            if not result:
                return False

            result.storage_decision = StorageDecision.REJECT
            result.validation_status = ValidationStatus.REJECTED
            result.reviewer = reviewer
            result.validated_at = datetime.now(timezone.utc).isoformat()
            result.validation_notes += f"\n\nRejected by {reviewer}: {reason}"

            self._save()
            return True

    def resolve_conflict(
        self,
        validation_id: str,
        conflict_id: str,
        resolution: str,
    ) -> bool:
        """Mark a conflict as resolved."""
        with self._lock:
            result = self._validation_results.get(validation_id)
            if not result:
                return False

            for conflict in result.conflicts:
                if conflict.conflict_id == conflict_id:
                    conflict.resolved = True
                    conflict.resolution = resolution
                    self._save()
                    return True
            return False

    def get_stats(self) -> Dict[str, Any]:
        """Get validation statistics."""
        with self._lock:
            total = len(self._validation_results)
            if total == 0:
                return {"total_validations": 0}

            by_status = defaultdict(int)
            by_decision = defaultdict(int)
            total_confidence = 0.0
            total_conflicts = 0
            auto_stored = 0
            manual_reviews = 0
            rejected = 0

            for result in self._validation_results.values():
                by_status[result.validation_status.value] += 1
                by_decision[result.storage_decision.value] += 1
                total_confidence += result.overall_confidence
                total_conflicts += len(result.conflicts)

                if result.storage_decision == StorageDecision.AUTO_STORE:
                    auto_stored += 1
                elif result.storage_decision == StorageDecision.MANUAL_REVIEW:
                    manual_reviews += 1
                elif result.storage_decision == StorageDecision.REJECT:
                    rejected += 1

            return {
                "total_validations": total,
                "by_status": dict(by_status),
                "by_decision": dict(by_decision),
                "avg_confidence": total_confidence / total,
                "total_conflicts_detected": total_conflicts,
                "auto_stored": auto_stored,
                "pending_manual_review": manual_reviews,
                "rejected": rejected,
            }

    def export_validations(self) -> Dict[str, Any]:
        """Export all validation results."""
        with self._lock:
            return {
                "results": [r.to_dict() for r in self._validation_results.values()],
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "version": 1,
            }


def create_knowledge_validator(
    config: Optional[ValidationConfig] = None,
    storage_path: str = "data/memory/validation_results.json",
    cross_refs: Optional[CrossMemoryReferences] = None,
    semantic_memory: Optional[SemanticMemory] = None,
    experience_memory: Optional[ExperienceMemory] = None,
    engineering_lessons: Optional[EngineeringLessonStorage] = None,
    long_term_memory: Optional[LongTermMemory] = None,
) -> KnowledgeValidator:
    """Factory function to create KnowledgeValidator with sensible defaults."""
    return KnowledgeValidator(
        config=config,
        storage_path=storage_path,
        cross_refs=cross_refs,
        semantic_memory=semantic_memory,
        experience_memory=experience_memory,
        engineering_lessons=engineering_lessons,
        long_term_memory=long_term_memory,
    )


# Convenience functions for common source types

def create_source_from_documentation(
    url: str,
    content: str,
    confidence: float = 0.9,
) -> ValidationSource:
    """Create a validation source from official documentation."""
    return ValidationSource(
        source_type=ValidationSourceType.OFFICIAL_DOCUMENTATION,
        identifier=url,
        content=content,
        confidence=confidence,
        reliability=DEFAULT_SOURCE_RELIABILITY[ValidationSourceType.OFFICIAL_DOCUMENTATION],
    )


def create_source_from_code(
    file_path: str,
    content: str,
    confidence: float = 0.95,
) -> ValidationSource:
    """Create a validation source from source code."""
    return ValidationSource(
        source_type=ValidationSourceType.SOURCE_CODE,
        identifier=file_path,
        content=content,
        confidence=confidence,
        reliability=DEFAULT_SOURCE_RELIABILITY[ValidationSourceType.SOURCE_CODE],
    )


def create_source_from_standards(
    spec_name: str,
    content: str,
    confidence: float = 0.9,
) -> ValidationSource:
    """Create a validation source from standards/specifications."""
    return ValidationSource(
        source_type=ValidationSourceType.STANDARDS_SPECIFICATIONS,
        identifier=spec_name,
        content=content,
        confidence=confidence,
        reliability=DEFAULT_SOURCE_RELIABILITY[ValidationSourceType.STANDARDS_SPECIFICATIONS],
    )


def create_source_from_vendor_docs(
    vendor: str,
    url: str,
    content: str,
    confidence: float = 0.8,
) -> ValidationSource:
    """Create a validation source from vendor documentation."""
    return ValidationSource(
        source_type=ValidationSourceType.VENDOR_DOCUMENTATION,
        identifier=f"{vendor}: {url}",
        content=content,
        confidence=confidence,
        reliability=DEFAULT_SOURCE_RELIABILITY[ValidationSourceType.VENDOR_DOCUMENTATION],
    )


def create_source_from_multiple_sources(
    sources: List[Tuple[str, str]],  # List of (identifier, content)
    confidence: float = 0.85,
) -> List[ValidationSource]:
    """Create validation sources from multiple independent sources."""
    return [
        ValidationSource(
            source_type=ValidationSourceType.MULTIPLE_INDEPENDENT_SOURCES,
            identifier=identifier,
            content=content,
            confidence=confidence,
            reliability=DEFAULT_SOURCE_RELIABILITY[ValidationSourceType.MULTIPLE_INDEPENDENT_SOURCES],
        )
        for identifier, content in sources
    ]


def create_source_from_llm(
    model_name: str,
    content: str,
    confidence: float = 0.7,
) -> ValidationSource:
    """Create a validation source from a stronger LLM response."""
    return ValidationSource(
        source_type=ValidationSourceType.STRONGER_LLM,
        identifier=f"LLM: {model_name}",
        content=content,
        confidence=confidence,
        reliability=DEFAULT_SOURCE_RELIABILITY[ValidationSourceType.STRONGER_LLM],
    )


def create_source_from_community(
    platform: str,
    url: str,
    content: str,
    confidence: float = 0.6,
) -> ValidationSource:
    """Create a validation source from community discussions."""
    return ValidationSource(
        source_type=ValidationSourceType.COMMUNITY_DISCUSSIONS,
        identifier=f"{platform}: {url}",
        content=content,
        confidence=confidence,
        reliability=DEFAULT_SOURCE_RELIABILITY[ValidationSourceType.COMMUNITY_DISCUSSIONS],
    )


def create_source_from_article(
    url: str,
    content: str,
    confidence: float = 0.5,
) -> ValidationSource:
    """Create a validation source from a single article/blog post."""
    return ValidationSource(
        source_type=ValidationSourceType.SINGLE_ARTICLE_BLOG,
        identifier=url,
        content=content,
        confidence=confidence,
        reliability=DEFAULT_SOURCE_RELIABILITY[ValidationSourceType.SINGLE_ARTICLE_BLOG],
    )


def create_source_from_user(
    content: str,
    confidence: float = 0.95,
) -> ValidationSource:
    """Create a validation source from user-provided information."""
    return ValidationSource(
        source_type=ValidationSourceType.USER_PROVIDED,
        identifier="user_input",
        content=content,
        confidence=confidence,
        reliability=DEFAULT_SOURCE_RELIABILITY[ValidationSourceType.USER_PROVIDED],
    )


def create_source_from_memory(
    entry_id: str,
    content: str,
    source_type: ValidationSourceType,
    confidence: float = 0.8,
) -> ValidationSource:
    """Create a validation source from existing memory entry."""
    return ValidationSource(
        source_type=source_type,
        identifier=entry_id,
        content=content,
        confidence=confidence,
        reliability=DEFAULT_SOURCE_RELIABILITY.get(source_type, 0.5),
    )