"""
Persistent project memory with semantic similarity search capabilities.

This module provides project-level memory that persists between sessions,
including support for semantic similarity search using sentence transformers
and an optional persistent vector database (FAISS).
"""

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, List, Dict, Any, Optional

if TYPE_CHECKING:
    from app.vector_db import VectorDB

# Try to import optional dependencies
try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    np = None  # Placeholder

try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False

# Try to import VectorDB
try:
    from app.vector_db import VectorDB, FAISS_AVAILABLE as VECTOR_DB_AVAILABLE
except ImportError:
    VECTOR_DB_AVAILABLE = False
    VectorDB = None

from app.core.file_allowlist import FileAllowlist, get_file_allowlist, FileOperation, AccessRule

# Shared infrastructure imports
from app.core.events import get_event_bus
from app.core.background_jobs import get_job_service
from app.core.background_jobs import JobTriggerConfig, JobTriggerType, JobPriority
from app.core.observability import get_observability_hub
from app.core.observability import HealthStatus, HealthResult, HealthCheck, ComponentInfo, ComponentType


class ProjectMemory:
    def __init__(
        self,
        workspace: str = ".",
        relative_path: str = "data/memory/freya_memory.json",
        limit: int = 200,
        use_vector_db: bool = True,
        vector_db_name: str = "project_memory",
        file_allowlist: Optional[FileAllowlist] = None,
        event_bus: Optional[object] = None,
        job_service: Optional[object] = None,
        observability: Optional[object] = None,
    ):
        """
        Initialize enhanced project memory with similarity search capabilities.

        Args:
            workspace: Workspace directory path
            relative_path: Relative path to memory file within workspace
            limit: Maximum number of entries to keep in memory
            use_vector_db: Whether to use persistent vector database for embeddings
            vector_db_name: Name for the vector database (used in data/vector_db/)
            file_allowlist: Optional FileAllowlist for access validation
            event_bus: Optional EventBus instance (uses global if not provided)
            job_service: Optional BackgroundJobService instance (uses global if not provided)
            observability: Optional ObservabilityHub instance (uses global if not provided)
        """
        self.workspace = Path(workspace).resolve()
        self.path = self.workspace / relative_path
        self.limit = limit
        self.use_vector_db = use_vector_db and VECTOR_DB_AVAILABLE
        self.file_allowlist = file_allowlist or get_file_allowlist()

        # Shared infrastructure
        self._event_bus = event_bus or get_event_bus()
        self._job_service = job_service or get_job_service()
        self._observability = observability or get_observability_hub()

        # Configure allowlist for this workspace
        self._configure_allowlist_for_workspace()

        # Initialize embedding model if available
        self.embedding_model = None
        self._embedding_dimension = 384  # Default for all-MiniLM-L6-v2
        if SENTENCE_TRANSFORMERS_AVAILABLE:
            try:
                self.embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
                self._embedding_dimension = self.embedding_model.get_sentence_embedding_dimension()
            except Exception:
                # If model loading fails, continue without embedding capabilities
                self.embedding_model = None

        # Initialize vector database for persistent embeddings
        self._vector_db = None
        if self.use_vector_db and self.embedding_model is not None:
            try:
                vector_db_path = self.workspace / "data" / "vector_db" / f"{vector_db_name}.faiss"
                # Validate write access for vector DB directory
                self.file_allowlist.require_allowed(vector_db_path.parent, FileOperation.WRITE, "ProjectMemory.vector_db")
                self._vector_db = VectorDB(
                    index_path=vector_db_path,
                    embedding_dim=self._embedding_dimension,
                    normalize=True,
                )
            except Exception:
                # Fall back to in-memory cache if vector DB fails
                self._vector_db = None

        # Cache for embeddings to avoid recomputation (fallback when vector DB not used)
        self._embeddings_cache: dict[str, Any] = {}

        # Register with observability
        self._register_with_observability()

        # Schedule periodic persistence
        self._schedule_persistence()

    def _register_with_observability(self) -> None:
        """Register this subsystem with the shared ObservabilityHub."""
        if self._observability:
            self._observability.add_health_check(HealthCheck(
                name="project_memory_health",
                component="memory.project",
                check_func=self._health_check,
                interval_seconds=60.0,
            ))

            # Register component
            self._observability.register_component(ComponentInfo(
                name="ProjectMemory",
                component_type=ComponentType.SERVICE,
                version="1.0.0",
                description="Project-level memory with semantic similarity search",
                metadata={},
            ))

    def _health_check(self) -> HealthResult:
        """Health check for ProjectMemory."""
        entries = self._load()
        entry_count = len(entries)
        has_embeddings = self.embedding_model is not None
        has_vector_db = self._vector_db is not None

        return HealthResult(
            name="project_memory_health",
            component="memory.project",
            status=HealthStatus.HEALTHY,
            message=f"{entry_count} entries, embeddings: {has_embeddings}, vector_db: {has_vector_db}",
            details={
                "entry_count": entry_count,
                "has_embeddings": has_embeddings,
                "has_vector_db": has_vector_db,
                "limit": self.limit,
            },
        )

    def _publish_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Publish an event to the EventBus."""
        try:
            self._event_bus.emit(event_type, data)
        except Exception:
            # Don't let event publishing break the system
            pass

    def _schedule_persistence(self, interval_seconds: int = 300) -> None:
        """Schedule periodic persistence (force save to disk)."""
        # Check if job already exists to avoid duplicate scheduling
        existing_job = self._job_service.get_job("project_memory_persist")
        if existing_job:
            return

        trigger = JobTriggerConfig(
            type=JobTriggerType.RECURRING,
            interval_seconds=interval_seconds,
        )
        self._job_service.schedule(
            job_id="project_memory_persist",
            func=lambda: self._save(self._load()),
            trigger=trigger,
            name="Project Memory Persistence",
            priority=JobPriority.LOW,
        )

    def _configure_allowlist_for_workspace(self):
        """Configure the file allowlist with workspace-specific rules."""
        workspace_str = str(self.workspace)

        # Add rule for workspace root directory
        self.file_allowlist.add_rule(AccessRule(
            pattern=workspace_str,
            operations={FileOperation.LIST, FileOperation.READ},
            description=f"Workspace root directory: {workspace_str}",
            tags={"type": "workspace_root", "workspace": workspace_str},
        ))

        # Add rules for workspace directory contents
        self.file_allowlist.add_rule(AccessRule(
            pattern=f"{workspace_str}/**",
            operations={FileOperation.READ, FileOperation.WRITE, FileOperation.CREATE, FileOperation.MODIFY, FileOperation.DELETE, FileOperation.LIST},
            description=f"Full access to workspace contents: {workspace_str}",
            tags={"type": "workspace", "workspace": workspace_str},
        ))

        # Add rules for common project directories
        common_dirs = [
            "data/**",
            "logs/**",
            "cache/**",
            "tmp/**",
            "temp/**",
            ".freya/**",
        ]
        for dir_pattern in common_dirs:
            full_pattern = f"{workspace_str}/{dir_pattern}"
            self.file_allowlist.add_rule(AccessRule(
                pattern=full_pattern,
                operations={FileOperation.READ, FileOperation.WRITE, FileOperation.CREATE, FileOperation.MODIFY, FileOperation.DELETE, FileOperation.LIST},
                description=f"Project directory: {dir_pattern}",
                tags={"type": "project_dir", "workspace": workspace_str},
            ))

    def _extract_text_for_embedding(self, entry: dict) -> str:
        """
        Extract text from a memory entry for embedding computation.
        """
        kind = entry.get("kind", "")
        content = entry.get("content", {})

        if kind == "edit":
            parts = [
                content.get("task", ""),
                content.get("operation_type", ""),
                content.get("file", ""),
                content.get("diff_summary", ""),
            ]
        elif kind == "task":
            parts = [
                content.get("request", ""),
                content.get("outcome", ""),
            ]
        elif kind == "decision":
            parts = [
                content.get("decision", ""),
                content.get("rationale", ""),
            ]
        elif kind == "solved_task" or kind == "unsolved_task":
            parts = [
                content.get("task", ""),
                content.get("solution_summary", ""),
                f"iterations:{content.get('iterations', 0)}",
            ]
        else:
            parts = [json.dumps(content, ensure_ascii=False)]

        text = " ".join(str(part).strip() for part in parts if part)
        return text.strip()

    def _compute_embedding(self, text: str):
        """Compute embedding for text using the sentence transformer model."""
        if self.embedding_model is None:
            if NUMPY_AVAILABLE:
                return np.zeros(self._embedding_dimension)
            else:
                return [0.0] * self._embedding_dimension

        embedding = self.embedding_model.encode(
            [text],
            convert_to_numpy=True,
            normalize_embeddings=True,
        )[0]
        return embedding

    def _get_embeddings_for_entries(self, entries: list[dict]) -> list:
        """Get embeddings for a list of memory entries."""
        if self.embedding_model is None:
            if NUMPY_AVAILABLE:
                return [np.zeros(self._embedding_dimension) for _ in entries]
            else:
                return [[0.0] * self._embedding_dimension for _ in entries]

        texts_to_embed = []
        for entry in entries:
            text_to_embed = self._extract_text_for_embedding(entry)
            texts_to_embed.append(text_to_embed)

        if texts_to_embed:
            batch_embeddings = self.embedding_model.encode(
                texts_to_embed,
                convert_to_numpy=True,
                normalize_embeddings=True,
            )
            return list(batch_embeddings)
        else:
            return []

    def _get_entries_with_vector_ids(self, kind: Optional[str] = None) -> tuple[list[dict], list[int]]:
        """
        Get entries and their corresponding vector DB IDs.
        Rebuilds the vector DB if entries have changed.
        """
        all_entries = self._load()
        if kind:
            entries = [e for e in all_entries if e.get("kind") == kind]
        else:
            entries = all_entries

        # If we have a vector DB, check if we need to rebuild
        if self._vector_db is not None and entries:
            # Simple check: if vector DB size doesn't match entries count, rebuild
            # This could be more sophisticated with a hash or timestamp check
            expected_size = len(entries)
            if self._vector_db.size() != expected_size:
                self._rebuild_vector_db(entries)

        return entries, list(range(len(entries)))

    def _rebuild_vector_db(self, entries: list[dict]) -> None:
        """Rebuild the vector database from a list of entries."""
        if self._vector_db is None or self.embedding_model is None:
            return

        # Clear existing vectors
        self._vector_db.clear()

        # Compute embeddings for all entries
        embeddings = self._get_embeddings_for_entries(entries)

        # Add to vector DB with metadata
        metadata_list = []
        for entry in entries:
            metadata_list.append({
                "timestamp": entry.get("timestamp", ""),
                "kind": entry.get("kind", ""),
                "content": entry.get("content", {}),
            })

        # Add batch to vector DB
        if embeddings:
            self._vector_db.add_batch(embeddings, metadata_list)

    def record(self, kind: str, content: dict[str, Any]) -> dict[str, Any]:
        """Record a new memory entry."""
        if not isinstance(content, dict):
            raise TypeError("Memory content must be a dictionary.")

        entries = self._load()
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            "content": content,
        }
        entries.append(entry)
        self._save(entries[-self.limit :])

        # Publish event
        self._publish_event("memory.project_recorded", {
            "kind": kind,
            "content": content,
        })

        # Update vector DB if we're using it
        if self._vector_db is not None:
            # Rebuild the vector DB with the new entries
            all_entries = self._load()
            self._rebuild_vector_db(all_entries)

        # Clear embedding cache since data changed
        self._embeddings_cache.clear()
        return entry

    def record_edit(self, task: str, operation_type: str, file_path: str, diff_summary: str = "") -> dict[str, Any]:
        """Record an edit operation performed on a file."""
        content = {
            "task": task,
            "operation_type": operation_type,
            "file": file_path,
            "diff_summary": diff_summary,
        }
        return self.record("edit", content)

    def recent(self, limit: int = 5) -> list[dict]:
        """Return the most recent memory entries."""
        return self._load()[-limit:]

    def recent_edits(self, limit: int = 5) -> list[dict]:
        """Return the most recent edit records."""
        all_entries = self._load()
        edits = [e for e in all_entries if e.get("kind") == "edit"]
        return edits[-limit:]

    def context(self, limit: int = 5, max_characters: int = 2_000) -> str:
        """Get a formatted string of recent memories for context."""
        lines = [
            f"- {entry['kind']}: {json.dumps(entry['content'], ensure_ascii=False)}"
            for entry in self.recent(limit)
        ]
        return "\n".join(lines)[:max_characters]

    def search(self, keyword: str, limit: int = 10) -> list[dict]:
        """Return entries whose content contains the keyword (case-insensitive)."""
        keyword_lower = keyword.lower()
        matches = []
        for entry in self._load():
            content_str = json.dumps(entry["content"], ensure_ascii=False).lower()
            if keyword_lower in content_str:
                matches.append(entry)
        return matches[-limit:] if limit else matches

    def similar_edit(
        self,
        task: str,
        limit: int = 5,
        threshold: float = 0.3,
    ) -> list[dict]:
        """Find past edit operations similar to the given task using semantic similarity."""
        if self.embedding_model is None:
            return self.search(task, limit=limit)

        # Use vector DB if available
        if self._vector_db is not None and not self._vector_db.is_empty():
            query_embedding = self._compute_embedding(task)
            results = self._vector_db.search(query_embedding, limit=limit * 2, threshold=threshold)

            # Filter for edit entries
            edit_results = []
            all_entries = self._load()
            for id, score, metadata in results:
                if id < len(all_entries):
                    entry = all_entries[id].copy()
                    if entry.get("kind") == "edit":
                        entry["_similarity_score"] = score
                        edit_results.append(entry)

            return edit_results[:limit]

        # Fallback to in-memory computation
        all_entries = self._load()
        edit_entries = [e for e in all_entries if e.get("kind") == "edit"]

        if not edit_entries:
            return []

        edit_embeddings = self._get_embeddings_for_entries(edit_entries)
        task_embedding = self._compute_embedding(task)

        similarities = []
        for i, embedding in enumerate(edit_embeddings):
            if NUMPY_AVAILABLE:
                similarity = float(np.dot(embedding, task_embedding))
            else:
                # Manual dot product for lists
                if hasattr(embedding, '__iter__') and hasattr(task_embedding, '__iter__'):
                    similarity = float(sum(a * b for a, b in zip(embedding, task_embedding)))
                else:
                    similarity = 0.0
            similarities.append((i, similarity))

        filtered = [(idx, score) for idx, score in similarities if score >= threshold]
        filtered.sort(key=lambda x: x[1], reverse=True)

        results = []
        for idx, score in filtered[:limit]:
            entry = edit_entries[idx].copy()
            # Add similarity score to the result for reference
            entry["_similarity_score"] = score
            results.append(entry)

        return results

    def similar_search(
        self,
        query: str,
        kind: str = None,
        limit: int = 5,
        threshold: float = 0.3,
    ) -> list[dict]:
        """Search for memory entries similar to the query using semantic similarity."""
        if self.embedding_model is None:
            # Fallback to text search
            if kind:
                results = [e for e in self._load() if e.get("kind") == kind]
                # Then do text search within filtered results
                keyword_lower = query.lower()
                matches = [
                    e for e in results
                    if keyword_lower in json.dumps(e["content"], ensure_ascii=False).lower()
                ]
                return matches[-limit:] if limit else matches
            else:
                return self.search(query, limit=limit)

        # Use vector DB if available
        if self._vector_db is not None and not self._vector_db.is_empty():
            query_embedding = self._compute_embedding(query)
            results = self._vector_db.search(query_embedding, limit=limit * 2, threshold=threshold)

            all_entries = self._load()
            filtered_results = []
            for id, score, metadata in results:
                if id < len(all_entries):
                    entry = all_entries[id].copy()
                    # Filter by kind if specified
                    if kind and entry.get("kind") != kind:
                        continue
                    entry["_similarity_score"] = score
                    filtered_results.append(entry)

            return filtered_results[:limit]

        # Fallback to in-memory computation
        all_entries = self._load()
        if kind:
            entries = [e for e in all_entries if e.get("kind") == kind]
        else:
            entries = all_entries

        if not entries:
            return []

        # Get embeddings for all entries
        embeddings = self._get_embeddings_for_entries(entries)

        # Get embedding for the query
        query_embedding = self._compute_embedding(query)

        # Compute cosine similarities
        similarities = []
        for i, embedding in enumerate(embeddings):
            if NUMPY_AVAILABLE:
                similarity = float(np.dot(embedding, query_embedding))
            else:
                # Manual dot product for lists
                if hasattr(embedding, '__iter__') and hasattr(query_embedding, '__iter__'):
                    similarity = float(sum(a * b for a, b in zip(embedding, query_embedding)))
                else:
                    similarity = 0.0
            similarities.append((i, float(similarity)))

        # Filter by threshold and sort by similarity (descending)
        filtered = [(idx, score) for idx, score in similarities if score >= threshold]
        filtered.sort(key=lambda x: x[1], reverse=True)

        # Get the top results
        results = []
        for idx, score in filtered[:limit]:
            entry = entries[idx].copy()
            # Add similarity score to the result for reference
            entry["_similarity_score"] = score
            results.append(entry)

        return results

    def _load(self) -> list[dict]:
        """Load memory entries from disk."""
        # Validate read access
        self.file_allowlist.require_allowed(self.path, FileOperation.READ, "ProjectMemory._load")

        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return data if isinstance(data, list) else []

    def _save(self, entries: list[dict]) -> None:
        """Save memory entries to disk."""
        # Validate write access
        self.file_allowlist.require_allowed(self.path, FileOperation.WRITE, "ProjectMemory._save")

        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.path)
