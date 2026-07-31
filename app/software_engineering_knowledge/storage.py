"""Storage layer for Software Engineering Knowledge.

Provides persistent storage for EngineeringKnowledgeItem objects with
CRUD operations, versioning, and atomic writes.
"""

import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.software_engineering_knowledge.models import (
    EngineeringExpertise,
    EngineeringKnowledgeItem,
    EngineeringKnowledgeType,
    ValidationStatus,
    KnowledgeSource,
    EngineeringDomain,
)


class EngineeringKnowledgeStorage:
    """Persistent storage for engineering knowledge items.

    Features:
    - Atomic writes via temp file + rename
    - Version tracking with optimistic locking
    - Full-text search index
    - Category and tag indexes
    - Automatic backup on corruption
    """

    def __init__(self, storage_dir: Path):
        """Initialize storage in the given directory."""
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self.items_file = self.storage_dir / "items.json"
        self.index_file = self.storage_dir / "indexes.json"
        self.backup_dir = self.storage_dir / "backups"
        self.backup_dir.mkdir(exist_ok=True)

        # In-memory indexes for fast lookup
        self._items: Dict[str, EngineeringKnowledgeItem] = {}
        self._by_domain: Dict[EngineeringDomain, List[str]] = {}
        self._by_type: Dict[EngineeringKnowledgeType, List[str]] = {}
        self._by_source: Dict[KnowledgeSource, List[str]] = {}
        self._by_tag: Dict[str, List[str]] = {}
        self._by_category: Dict[str, List[str]] = {}
        self._by_validation: Dict[ValidationStatus, List[str]] = {}

        self._load()

    def _load(self) -> None:
        """Load items from disk and rebuild indexes."""
        if not self.items_file.exists():
            return

        try:
            with open(self.items_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            for item_data in data.get("items", []):
                try:
                    item = EngineeringKnowledgeItem.from_dict(item_data)
                    self._add_to_indexes(item)
                except Exception:
                    continue

        except json.JSONDecodeError:
            # Attempt recovery from backup
            self._recover_from_backup()

        # Load indexes if available
        self._load_indexes()

    def _load_indexes(self) -> None:
        """Load pre-built indexes from disk."""
        if not self.index_file.exists():
            return
        try:
            with open(self.index_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._by_domain = {EngineeringDomain(k): v for k, v in data.get("by_domain", {}).items()}
            self._by_type = {EngineeringKnowledgeType(k): v for k, v in data.get("by_type", {}).items()}
            self._by_source = {KnowledgeSource(k): v for k, v in data.get("by_source", {}).items()}
            self._by_tag = data.get("by_tag", {})
            self._by_category = data.get("by_category", {})
            self._by_validation = {ValidationStatus(k): v for k, v in data.get("by_validation", {}).items()}
        except Exception:
            pass

    def _save_indexes(self) -> None:
        """Save indexes to disk."""
        try:
            data = {
                "by_domain": {k.value: v for k, v in self._by_domain.items()},
                "by_type": {k.value: v for k, v in self._by_type.items()},
                "by_source": {k.value: v for k, v in self._by_source.items()},
                "by_tag": self._by_tag,
                "by_category": self._by_category,
                "by_validation": {k.value: v for k, v in self._by_validation.items()},
            }
            temp = self.storage_dir / "indexes.json.tmp"
            with open(temp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            temp.replace(self.index_file)
        except Exception:
            pass

    def _recover_from_backup(self) -> None:
        """Attempt to recover from latest backup."""
        backups = sorted(self.backup_dir.glob("items_*.json"), reverse=True)
        for backup in backups:
            try:
                with open(backup, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for item_data in data.get("items", []):
                    try:
                        item = EngineeringKnowledgeItem.from_dict(item_data)
                        self._add_to_indexes(item)
                    except Exception:
                        continue
                break
            except Exception:
                continue

    def _backup(self) -> None:
        """Create a timestamped backup."""
        try:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            backup_file = self.backup_dir / f"items_{timestamp}.json"
            items_data = [item.to_dict() for item in self._items.values()]
            data = {"items": items_data, "version": 1}
            with open(backup_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            # Cleanup old backups (keep last 10)
            backups = sorted(self.backup_dir.glob("items_*.json"))
            for old in backups[:-10]:
                old.unlink()
        except Exception:
            pass

    def _add_to_indexes(self, item: EngineeringKnowledgeItem) -> None:
        """Add item to all indexes."""
        self._items[item.id] = item

        # By domain
        self._by_domain.setdefault(item.domain, []).append(item.id)

        # By type
        self._by_type.setdefault(item.knowledge_type, []).append(item.id)

        # By source
        self._by_source.setdefault(item.source, []).append(item.id)

        # By tags
        for tag in item.tags:
            self._by_tag.setdefault(tag.lower(), []).append(item.id)

        # By sub-category
        if item.sub_category:
            self._by_category.setdefault(item.sub_category.lower(), []).append(item.id)

        # By validation status
        self._by_validation.setdefault(item.validation_status, []).append(item.id)

    def _remove_from_indexes(self, item: EngineeringKnowledgeItem) -> None:
        """Remove item from all indexes."""
        self._items.pop(item.id, None)

        for idx_dict in [self._by_domain, self._by_type, self._by_source, self._by_validation]:
            for key, ids in idx_dict.items():
                if item.id in ids:
                    ids.remove(item.id)

        for tag in item.tags:
            tag_lower = tag.lower()
            if tag_lower in self._by_tag and item.id in self._by_tag[tag_lower]:
                self._by_tag[tag_lower].remove(item.id)

        if item.sub_category:
            cat_lower = item.sub_category.lower()
            if cat_lower in self._by_category and item.id in self._by_category[cat_lower]:
                self._by_category[cat_lower].remove(item.id)

    def _save(self) -> None:
        """Save all items to disk atomically."""
        self._backup()

        items_data = [item.to_dict() for item in self._items.values()]
        data = {
            "items": items_data,
            "version": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        # Ensure storage directory exists
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        temp = self.storage_dir / "items.json.tmp"
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        temp.replace(self.items_file)

        self._save_indexes()

    # === CRUD Operations ===

    def create(self, item: EngineeringKnowledgeItem) -> EngineeringKnowledgeItem:
        """Create a new knowledge item.

        Args:
            item: The knowledge item to create. ID will be generated if not provided.

        Returns:
            The created item with assigned ID and timestamps.
        """
        if not item.id:
            item.id = f"eng_{uuid.uuid4().hex[:12]}"

        now = datetime.now(timezone.utc).isoformat()
        item.created_at = now
        item.updated_at = now

        self._add_to_indexes(item)
        self._save()
        return item

    def get(self, item_id: str) -> Optional[EngineeringKnowledgeItem]:
        """Get a knowledge item by ID."""
        return self._items.get(item_id)

    def update(self, item: EngineeringKnowledgeItem, expected_version: Optional[int] = None) -> EngineeringKnowledgeItem:
        """Update an existing knowledge item with optimistic locking.

        Args:
            item: The updated item (must have existing ID)
            expected_version: If provided, update only if current version matches

        Returns:
            The updated item

        Raises:
            ValueError: If item doesn't exist or version conflict
        """
        existing = self._items.get(item.id)
        if not existing:
            raise ValueError(f"Item {item.id} not found")

        if expected_version is not None and existing.version != expected_version:
            raise ValueError(f"Version conflict: expected {expected_version}, current {existing.version}")

        item.version = existing.version + 1
        item.updated_at = datetime.now(timezone.utc).isoformat()
        item.created_at = existing.created_at
        item.created_by = existing.created_by

        self._remove_from_indexes(existing)
        self._add_to_indexes(item)
        self._save()
        return item

    def delete(self, item_id: str) -> bool:
        """Delete a knowledge item.

        Args:
            item_id: ID of item to delete

        Returns:
            True if deleted, False if not found
        """
        item = self._items.get(item_id)
        if not item:
            return False

        self._remove_from_indexes(item)
        self._save()
        return True

    # === Query Operations ===

    def list_all(self, limit: int = 100, offset: int = 0) -> List[EngineeringKnowledgeItem]:
        """List all items with pagination."""
        items = list(self._items.values())
        items.sort(key=lambda i: i.updated_at, reverse=True)
        return items[offset : offset + limit]

    def get_by_domain(self, domain: EngineeringDomain, limit: int = 50) -> List[EngineeringKnowledgeItem]:
        """Get items by domain."""
        ids = self._by_domain.get(domain, [])
        items = [self._items[i] for i in ids if i in self._items]
        items.sort(key=lambda i: i.confidence, reverse=True)
        return items[:limit]

    def get_by_type(self, knowledge_type: EngineeringKnowledgeType, limit: int = 50) -> List[EngineeringKnowledgeItem]:
        """Get items by knowledge type."""
        ids = self._by_type.get(knowledge_type, [])
        items = [self._items[i] for i in ids if i in self._items]
        items.sort(key=lambda i: i.confidence, reverse=True)
        return items[:limit]

    def get_by_source(self, source: KnowledgeSource, limit: int = 50) -> List[EngineeringKnowledgeItem]:
        """Get items by source."""
        ids = self._by_source.get(source, [])
        items = [self._items[i] for i in ids if i in self._items]
        items.sort(key=lambda i: i.confidence, reverse=True)
        return items[:limit]

    def get_by_tag(self, tag: str, limit: int = 50) -> List[EngineeringKnowledgeItem]:
        """Get items by tag (case-insensitive)."""
        ids = self._by_tag.get(tag.lower(), [])
        items = [self._items[i] for i in ids if i in self._items]
        items.sort(key=lambda i: i.confidence, reverse=True)
        return items[:limit]

    def get_by_category(self, sub_category: str, limit: int = 50) -> List[EngineeringKnowledgeItem]:
        """Get items by sub-category (case-insensitive)."""
        ids = self._by_category.get(sub_category.lower(), [])
        items = [self._items[i] for i in ids if i in self._items]
        items.sort(key=lambda i: i.confidence, reverse=True)
        return items[:limit]

    def get_by_validation(self, status: ValidationStatus, limit: int = 50) -> List[EngineeringKnowledgeItem]:
        """Get items by validation status."""
        ids = self._by_validation.get(status, [])
        items = [self._items[i] for i in ids if i in self._items]
        items.sort(key=lambda i: i.updated_at, reverse=True)
        return items[:limit]

    def search(self, query: str, limit: int = 20) -> List[EngineeringKnowledgeItem]:
        """Full-text search across title, summary, content, tags.

        Simple keyword matching - can be enhanced with full-text index.
        """
        query_lower = query.lower()
        query_terms = query_lower.split()

        scored = []
        for item in self._items.values():
            score = 0
            searchable = f"{item.title} {item.summary} {item.content} {' '.join(item.tags)} {item.sub_category}".lower()

            for term in query_terms:
                if term in searchable:
                    # Weight: title > summary > tags > content
                    if term in item.title.lower():
                        score += 10
                    elif term in item.summary.lower():
                        score += 5
                    elif term in item.tags:
                        score += 3
                    else:
                        score += 1

            if score > 0:
                scored.append((score, item))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:limit]]

    def get_recent(self, hours: int = 24, limit: int = 50) -> List[EngineeringKnowledgeItem]:
        """Get recently updated items."""
        cutoff = datetime.now(timezone.utc).timestamp() - (hours * 3600)
        items = []
        for item in self._items.values():
            try:
                updated = datetime.fromisoformat(item.updated_at.replace("Z", "+00:00")).timestamp()
                if updated >= cutoff:
                    items.append(item)
            except Exception:
                continue
        items.sort(key=lambda i: i.updated_at, reverse=True)
        return items[:limit]

    def get_high_confidence(self, min_confidence: float = 0.8, limit: int = 50) -> List[EngineeringKnowledgeItem]:
        """Get items with high confidence."""
        items = [i for i in self._items.values() if i.confidence >= min_confidence]
        items.sort(key=lambda i: i.confidence, reverse=True)
        return items[:limit]

    # === Statistics ===

    def count(self) -> int:
        """Total item count."""
        return len(self._items)

    def count_by_domain(self) -> Dict[EngineeringDomain, int]:
        """Count items per domain."""
        return {domain: len(ids) for domain, ids in self._by_domain.items()}

    def count_by_type(self) -> Dict[EngineeringKnowledgeType, int]:
        """Count items per knowledge type."""
        return {ktype: len(ids) for ktype, ids in self._by_type.items()}

    def count_by_source(self) -> Dict[KnowledgeSource, int]:
        """Count items per source."""
        return {source: len(ids) for source, ids in self._by_source.items()}

    def count_by_validation(self) -> Dict[ValidationStatus, int]:
        """Count items per validation status."""
        return {status: len(ids) for status, ids in self._by_validation.items()}

    # === Expertise Storage ===

    def save_expertise(self, expertise: EngineeringExpertise) -> EngineeringExpertise:
        """Save an expertise item."""
        expertise_file = self.storage_dir / "expertise.json"
        expertise_list = []

        if expertise_file.exists():
            try:
                with open(expertise_file, "r", encoding="utf-8") as f:
                    expertise_list = json.load(f)
            except Exception:
                pass

        # Update or add
        found = False
        for i, e in enumerate(expertise_list):
            if e.get("id") == expertise.id:
                expertise_list[i] = expertise.to_dict()
                found = True
                break

        if not found:
            expertise_list.append(expertise.to_dict())

        temp = expertise_file.with_suffix(".tmp")
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(expertise_list, f, indent=2)
        temp.replace(expertise_file)
        return expertise

    def get_expertise(self, expertise_id: str) -> Optional[EngineeringExpertise]:
        """Get an expertise item by ID."""
        expertise_file = self.storage_dir / "expertise.json"
        if not expertise_file.exists():
            return None
        try:
            with open(expertise_file, "r", encoding="utf-8") as f:
                expertise_list = json.load(f)
            for e in expertise_list:
                if e.get("id") == expertise_id:
                    return EngineeringExpertise.from_dict(e)
        except Exception:
            pass
        return None

    def list_expertise(self, domain: Optional[EngineeringDomain] = None) -> List[EngineeringExpertise]:
        """List all expertise items, optionally filtered by domain."""
        expertise_file = self.storage_dir / "expertise.json"
        if not expertise_file.exists():
            return []
        try:
            with open(expertise_file, "r", encoding="utf-8") as f:
                expertise_list = json.load(f)
            results = []
            for e in expertise_list:
                exp = EngineeringExpertise.from_dict(e)
                if domain is None or exp.domain == domain:
                    results.append(exp)
            results.sort(key=lambda e: e.confidence, reverse=True)
            return results
        except Exception:
            return []


# === Singleton access ===

_default_storage: Optional[EngineeringKnowledgeStorage] = None


def get_knowledge_storage(storage_path: Optional[str] = None) -> EngineeringKnowledgeStorage:
    """Get or create the global knowledge storage instance."""
    global _default_storage
    if _default_storage is None:
        path = Path(storage_path) if storage_path else Path("data/software_engineering_knowledge")
        _default_storage = EngineeringKnowledgeStorage(path)
    return _default_storage