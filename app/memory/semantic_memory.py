"""Semantic Memory for Freya AI.

This module provides a persistent knowledge base for general programming concepts,
best practices, language rules, algorithms, patterns, and technical knowledge
that applies across projects. Unlike episodic/project memory, this stores
generalized, reusable knowledge.
"""

import json
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional, Union
from enum import Enum


class KnowledgeCategory(Enum):
    """Categories of semantic knowledge."""
    LANGUAGE_RULE = "language_rule"        # e.g., "Python uses indentation for blocks"
    BEST_PRACTICE = "best_practice"        # e.g., "Use context managers for file I/O"
    DESIGN_PATTERN = "design_pattern"      # e.g., "Singleton pattern implementation"
    ALGORITHM = "algorithm"                # e.g., "Binary search implementation"
    API_REFERENCE = "api_reference"        # e.g., "requests.get() parameters"
    ERROR_HANDLING = "error_handling"      # e.g., "How to handle ConnectionError"
    SECURITY = "security"                  # e.g., "Always validate user input"
    PERFORMANCE = "performance"            # e.g., "Use list comprehension over loops"
    TESTING = "testing"                    # e.g., "pytest fixture patterns"
    DEBUGGING = "debugging"                # e.g., "Common causes of Segmentation Fault"
    ARCHITECTURE = "architecture"          # e.g., "Microservices vs monolith tradeoffs"
    TOOL_USAGE = "tool_usage"              # e.g., "Docker build optimization"
    DEPENDENCY = "dependency"              # e.g., "requests version compatibility"
    CUSTOM = "custom"


class ConfidenceLevel(Enum):
    """Confidence levels for knowledge entries."""
    LOW = 0.3       # Heuristic, needs verification
    MEDIUM = 0.6    # Observed pattern, reasonably reliable
    HIGH = 0.8      # Well-established practice, documented
    VERIFIED = 1.0  # Explicitly confirmed by user or authoritative source


@dataclass
class SemanticEntry:
    """A single entry in semantic memory."""
    entry_id: str
    category: str
    title: str
    content: str
    # Structured fields for common knowledge types
    language: Optional[str] = None          # e.g., "python", "javascript"
    tags: List[str] = field(default_factory=list)
    confidence: float = 0.8
    source: str = "inferred"                # user, inferred, documentation, training
    examples: List[Dict[str, str]] = field(default_factory=list)  # [{"code": "...", "explanation": "..."}]
    related_concepts: List[str] = field(default_factory=list)     # Links to other entry IDs
    prerequisites: List[str] = field(default_factory=list)        # Required knowledge
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    access_count: int = 0
    last_accessed: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SemanticEntry":
        return cls(**data)


class SemanticMemory:
    """Persistent semantic memory for general programming knowledge.

    Features:
    - Category-based organization (language rules, patterns, algorithms, etc.)
    - Confidence scoring for knowledge reliability
    - Source tracking (user-taught, inferred, documentation, training)
    - Code examples with explanations
    - Cross-references between related concepts
    - Prerequisites for learning ordering
    - Language-specific tagging
    - Search by category, tags, language, confidence, text
    - Access tracking for importance estimation
    - Thread-safe atomic JSON persistence
    - Configurable limits with LRU-like eviction

    Example usage:
        semantic = SemanticMemory(workspace=".")

        # Store a language rule
        semantic.set(
            category=KnowledgeCategory.LANGUAGE_RULE,
            title="Python indentation",
            content="Python uses indentation (4 spaces recommended) to define code blocks instead of braces.",
            language="python",
            tags=["syntax", "basics"],
            confidence=ConfidenceLevel.VERIFIED.value,
            source="documentation"
        )

        # Store a design pattern with example
        semantic.set(
            category=KnowledgeCategory.DESIGN_PATTERN,
            title="Singleton Pattern",
            content="Ensure a class has only one instance and provide global access to it.",
            language="python",
            tags=["creational", "pattern"],
            examples=[{
                "code": "class Singleton:\\n    _instance = None\\n    def __new__(cls):\\n        if cls._instance is None:\\n            cls._instance = super().__new__(cls)\\n        return cls._instance",
                "explanation": "Classic singleton using __new__ override"
            }],
            confidence=ConfidenceLevel.HIGH.value,
            source="training"
        )

        # Store best practice
        semantic.set(
            category=KnowledgeCategory.BEST_PRACTICE,
            title="Use context managers for resources",
            content="Always use 'with' statements for file I/O, database connections, locks, etc. to ensure proper cleanup.",
            language="python",
            tags=["resource-management", "cleanup"],
            confidence=ConfidenceLevel.VERIFIED.value,
            source="user"
        )

        # Query
        python_basics = semantic.get_by_category("language_rule", language="python")
        patterns = semantic.search("singleton", category="design_pattern")
    """

    def __init__(
        self,
        workspace: str = ".",
        storage_path: str = "data/memory/semantic_memory.json",
        max_entries: int = 5000,
    ):
        """Initialize Semantic Memory.

        Args:
            workspace: Project workspace directory
            storage_path: Relative path to storage file within workspace
            max_entries: Maximum number of entries to keep
        """
        self.workspace = Path(workspace).resolve()
        self.storage_path = self.workspace / storage_path
        self.max_entries = max_entries
        self._lock = threading.RLock()
        self._entries: Dict[str, SemanticEntry] = {}  # entry_id -> entry
        self._load()

    def _generate_timestamp(self) -> str:
        """Generate a timestamp with timezone."""
        return datetime.now(timezone.utc).isoformat()

    def _generate_entry_id(self) -> str:
        """Generate a unique entry ID."""
        import uuid
        return f"sem_{uuid.uuid4().hex[:12]}"

    def _ensure_storage_dir(self) -> None:
        """Ensure the storage directory exists."""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

    def _save(self) -> None:
        """Save all entries to storage (atomic write)."""
        self._ensure_storage_dir()
        temp_path = self.storage_path.with_suffix(".tmp")
        try:
            data = {
                "entries": [e.to_dict() for e in self._entries.values()],
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
        """Load entries from storage file."""
        if not self.storage_path.exists():
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._entries = {}
            for entry_data in data.get("entries", []):
                entry = SemanticEntry.from_dict(entry_data)
                self._entries[entry.entry_id] = entry
        except Exception:
            self._entries = {}

    def _enforce_limit(self) -> None:
        """Enforce max_entries by removing least accessed/oldest entries."""
        if len(self._entries) <= self.max_entries:
            return

        # Sort by access_count (asc) then last_accessed (asc), remove least used
        sorted_entries = sorted(
            self._entries.items(),
            key=lambda x: (x[1].access_count, x[1].last_accessed or x[1].created_at)
        )

        to_remove = len(self._entries) - self.max_entries
        for entry_id, _ in sorted_entries[:to_remove]:
            del self._entries[entry_id]

    def set(
        self,
        category: Union[str, KnowledgeCategory],
        title: str,
        content: str,
        language: Optional[str] = None,
        tags: Optional[List[str]] = None,
        confidence: float = 0.8,
        source: str = "inferred",
        examples: Optional[List[Dict[str, str]]] = None,
        related_concepts: Optional[List[str]] = None,
        prerequisites: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SemanticEntry:
        """Store or update a knowledge entry.

        Args:
            category: Knowledge category (KnowledgeCategory enum or string)
            title: Brief title/topic
            content: Detailed explanation/knowledge content
            language: Programming language (if language-specific)
            tags: Tags for categorization
            confidence: Confidence level (0-1)
            source: Source of knowledge (user, inferred, documentation, training)
            examples: List of {"code": "...", "explanation": "..."} dicts
            related_concepts: List of related entry IDs
            prerequisites: List of prerequisite entry IDs
            metadata: Additional structured data

        Returns:
            The created/updated SemanticEntry
        """
        with self._lock:
            now = self._generate_timestamp()
            composite_key = self._make_key(category, title)

            if composite_key in self._entries:
                # Update existing
                entry = self._entries[composite_key]
                entry.content = content
                entry.language = language
                if tags is not None:
                    entry.tags = tags
                entry.confidence = confidence
                entry.source = source
                if examples is not None:
                    entry.examples = examples
                if related_concepts is not None:
                    entry.related_concepts = related_concepts
                if prerequisites is not None:
                    entry.prerequisites = prerequisites
                if metadata:
                    entry.metadata.update(metadata)
                entry.updated_at = now
            else:
                # Create new
                if isinstance(category, KnowledgeCategory):
                    category_str = category.value
                else:
                    category_str = str(category)

                entry = SemanticEntry(
                    entry_id=composite_key,  # Use composite key as entry ID for consistent lookup
                    category=category_str,
                    title=title,
                    content=content,
                    language=language,
                    tags=tags or [],
                    confidence=confidence,
                    source=source,
                    examples=examples or [],
                    related_concepts=related_concepts or [],
                    prerequisites=prerequisites or [],
                    created_at=now,
                    updated_at=now,
                    metadata=metadata or {},
                )
                self._entries[composite_key] = entry

            self._enforce_limit()
            self._save()
            return entry

    def _make_key(self, category: Union[str, KnowledgeCategory], title: str) -> str:
        """Create composite key for storage (category + normalized title)."""
        if isinstance(category, KnowledgeCategory):
            category = category.value
        # Normalize title for key
        normalized = title.lower().strip().replace(" ", "_").replace("-", "_")
        return f"{category}.{normalized}"

    def get(self, category: Union[str, KnowledgeCategory], title: str) -> Optional[SemanticEntry]:
        """Get a knowledge entry by category and title."""
        with self._lock:
            key = self._make_key(category, title)
            entry = self._entries.get(key)
            if entry:
                entry.access_count += 1
                entry.last_accessed = self._generate_timestamp()
            return entry

    def get_by_id(self, entry_id: str) -> Optional[SemanticEntry]:
        """Get an entry by its ID."""
        with self._lock:
            entry = self._entries.get(entry_id)
            if entry:
                entry.access_count += 1
                entry.last_accessed = self._generate_timestamp()
            return entry

    def get_by_category(
        self,
        category: Union[str, KnowledgeCategory],
        language: Optional[str] = None,
        min_confidence: float = 0.0,
        limit: int = 50,
    ) -> List[SemanticEntry]:
        """Get all entries in a category."""
        with self._lock:
            if isinstance(category, KnowledgeCategory):
                category = category.value

            results = []
            for entry in self._entries.values():
                if entry.category != category:
                    continue
                if language and entry.language != language:
                    continue
                if entry.confidence < min_confidence:
                    continue
                results.append(entry)

            # Sort by confidence desc, access_count desc
            results.sort(key=lambda e: (e.confidence, e.access_count), reverse=True)
            return results[:limit]

    def search(
        self,
        query: Optional[str] = None,
        category: Optional[Union[str, KnowledgeCategory]] = None,
        language: Optional[str] = None,
        tags: Optional[List[str]] = None,
        min_confidence: float = 0.0,
        source: Optional[str] = None,
        limit: int = 50,
    ) -> List[SemanticEntry]:
        """Search entries with various filters."""
        with self._lock:
            results = []
            query_lower = query.lower() if query else None

            for entry in self._entries.values():
                # Category filter
                if category:
                    cat_val = category.value if isinstance(category, KnowledgeCategory) else category
                    if entry.category != cat_val:
                        continue

                # Language filter
                if language and entry.language != language:
                    continue

                # Confidence filter
                if entry.confidence < min_confidence:
                    continue

                # Source filter
                if source and entry.source != source:
                    continue

                # Tags filter (all must match)
                if tags and not all(tag in entry.tags for tag in tags):
                    continue

                # Text query
                if query_lower:
                    searchable = f"{entry.title} {entry.content} {' '.join(entry.tags)}".lower()
                    # Also search examples
                    for ex in entry.examples:
                        searchable += f" {ex.get('code', '')} {ex.get('explanation', '')}"
                    if query_lower not in searchable:
                        continue

                results.append(entry)

            # Sort by relevance: confidence desc, access_count desc
            results.sort(key=lambda e: (e.confidence, e.access_count), reverse=True)
            return results[:limit]

    def get_related(self, entry_id: str) -> List[SemanticEntry]:
        """Get entries linked via related_concepts."""
        with self._lock:
            entry = self._entries.get(entry_id)
            if not entry:
                return []
            results = []
            for rel_id in entry.related_concepts:
                rel_entry = self._entries.get(rel_id)
                if rel_entry:
                    results.append(rel_entry)
            return results

    def get_prerequisites(self, entry_id: str) -> List[SemanticEntry]:
        """Get prerequisite entries for a given entry."""
        with self._lock:
            entry = self._entries.get(entry_id)
            if not entry:
                return []
            results = []
            for pre_id in entry.prerequisites:
                pre_entry = self._entries.get(pre_id)
                if pre_entry:
                    results.append(pre_entry)
            return results

    def add_related(self, entry_id: str, related_id: str) -> bool:
        """Add a cross-reference between entries."""
        with self._lock:
            entry = self._entries.get(entry_id)
            related = self._entries.get(related_id)
            if not entry or not related:
                return False
            if related_id not in entry.related_concepts:
                entry.related_concepts.append(related_id)
                entry.updated_at = self._generate_timestamp()
            # Also add reverse reference
            if entry_id not in related.related_concepts:
                related.related_concepts.append(entry_id)
                related.updated_at = self._generate_timestamp()
            self._save()
            return True

    def update_metadata(self, entry_id: str, metadata: Dict[str, Any]) -> bool:
        """Update metadata for an existing entry."""
        with self._lock:
            entry = self._entries.get(entry_id)
            if not entry:
                return False
            entry.metadata.update(metadata)
            entry.updated_at = self._generate_timestamp()
            self._save()
            return True

    def add_tags(self, entry_id: str, tags: List[str]) -> bool:
        """Add tags to an existing entry."""
        with self._lock:
            entry = self._entries.get(entry_id)
            if not entry:
                return False
            for tag in tags:
                if tag not in entry.tags:
                    entry.tags.append(tag)
            entry.updated_at = self._generate_timestamp()
            self._save()
            return True

    def delete(self, entry_id: str) -> bool:
        """Delete an entry."""
        with self._lock:
            if entry_id in self._entries:
                del self._entries[entry_id]
                self._save()
                return True
            return False

    def get_all_categories(self) -> List[str]:
        """Get all unique categories."""
        with self._lock:
            return sorted(set(e.category for e in self._entries.values()))

    def get_all_languages(self) -> List[str]:
        """Get all unique languages."""
        with self._lock:
            return sorted(set(e.language for e in self._entries.values() if e.language))

    def get_all_sources(self) -> List[str]:
        """Get all unique sources."""
        with self._lock:
            return sorted(set(e.source for e in self._entries.values()))

    def get_all_tags(self) -> List[str]:
        """Get all unique tags."""
        with self._lock:
            tags = set()
            for entry in self._entries.values():
                tags.update(entry.tags)
            return sorted(tags)

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about semantic memory."""
        with self._lock:
            categories: Dict[str, int] = {}
            languages: Dict[str, int] = {}
            sources: Dict[str, int] = {}
            confidence_sum = 0

            for entry in self._entries.values():
                categories[entry.category] = categories.get(entry.category, 0) + 1
                if entry.language:
                    languages[entry.language] = languages.get(entry.language, 0) + 1
                sources[entry.source] = sources.get(entry.source, 0) + 1
                confidence_sum += entry.confidence

            return {
                "total_entries": len(self._entries),
                "categories": categories,
                "languages": languages,
                "sources": sources,
                "avg_confidence": confidence_sum / len(self._entries) if self._entries else 0,
                "max_entries": self.max_entries,
            }

    def export(self) -> Dict[str, Any]:
        """Export all entries for backup or transfer."""
        with self._lock:
            return {
                "entries": [e.to_dict() for e in self._entries.values()],
                "version": 1,
                "exported_at": self._generate_timestamp(),
            }

    def import_data(self, data: Dict[str, Any], merge: bool = True) -> int:
        """Import entries from exported data."""
        with self._lock:
            if not merge:
                self._entries = {}

            imported = 0
            for entry_data in data.get("entries", []):
                try:
                    entry = SemanticEntry.from_dict(entry_data)
                    key = self._make_key(entry.category, entry.title)
                    if key in self._entries:
                        # Merge: keep higher confidence
                        if entry.confidence > self._entries[key].confidence:
                            self._entries[key] = entry
                    else:
                        self._entries[key] = entry
                    imported += 1
                except Exception:
                    pass

            self._enforce_limit()
            self._save()
            return imported

    def __len__(self) -> int:
        return len(self._entries)

    def is_empty(self) -> bool:
        return len(self._entries) == 0


def create_semantic_memory(
    workspace: str = ".",
    storage_path: Optional[str] = None,
    max_entries: int = 5000,
) -> SemanticMemory:
    """Factory function to create SemanticMemory with sensible defaults."""
    if storage_path is None:
        storage_path = "data/memory/semantic_memory.json"
    return SemanticMemory(
        workspace=workspace,
        storage_path=storage_path,
        max_entries=max_entries,
    )