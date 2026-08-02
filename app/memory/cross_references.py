"""Cross-Memory References for Freya AI.

This module implements cross-references between different memory types,
enabling traceability from lessons to experiences to goals to project entries.

Features:
- Bidirectional links between memory entries
- Cross-memory graph traversal
- Reference types: source, derived, related, contradicts, supersedes
- Query API for finding connected memories
- Automatic reference inference from content overlap
"""

import json
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple, Union
from enum import Enum
from collections import defaultdict
import hashlib

# Shared infrastructure imports
from app.core.events import get_event_bus
from app.core.background_jobs import get_job_service
from app.core.background_jobs import JobTriggerConfig, JobTriggerType, JobPriority
from app.core.observability import get_observability_hub
from app.core.observability import HealthStatus, HealthResult, HealthCheck, ComponentInfo, ComponentType


class ReferenceType(Enum):
    """Types of cross-memory references."""
    SOURCE = "source"              # This entry was the source for the target
    DERIVED = "derived"            # This entry was derived from the target
    RELATED = "related"            # Semantically related
    CONTRADICTS = "contradicts"    # This entry contradicts the target
    SUPERSEDES = "supersedes"      # This entry replaces/supersedes the target
    EXAMPLE_OF = "example_of"      # This entry is an example of the target
    PREREQUISITE = "prerequisite"  # This entry is a prerequisite for the target
    CAUSED = "caused"              # This entry caused the target (e.g., lesson from failure)
    FIXED = "fixed"                # This entry fixed the target issue


class MemoryType(Enum):
    """Memory system types."""
    CONVERSATION = "conversation"
    WORKING = "working"
    PROJECT = "project"
    EXPERIENCE = "experience"
    LESSONS = "lessons"
    GOALS = "goals"
    TASK = "task"
    LONG_TERM = "long_term"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    KNOWLEDGE = "knowledge"


@dataclass
class CrossReference:
    """A cross-reference between two memory entries."""
    reference_id: str
    source_memory: str
    source_id: str
    target_memory: str
    target_id: str
    reference_type: str
    confidence: float = 1.0
    description: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CrossReference":
        return cls(**data)

    def reverse(self) -> "CrossReference":
        """Create the reverse reference."""
        reverse_types = {
            ReferenceType.SOURCE.value: ReferenceType.DERIVED.value,
            ReferenceType.DERIVED.value: ReferenceType.SOURCE.value,
            ReferenceType.RELATED.value: ReferenceType.RELATED.value,
            ReferenceType.CONTRADICTS.value: ReferenceType.CONTRADICTS.value,
            ReferenceType.SUPERSEDES.value: ReferenceType.DERIVED.value,
            ReferenceType.EXAMPLE_OF.value: ReferenceType.SOURCE.value,
            ReferenceType.PREREQUISITE.value: ReferenceType.DERIVED.value,
            ReferenceType.CAUSED.value: ReferenceType.DERIVED.value,
            ReferenceType.FIXED.value: ReferenceType.SOURCE.value,
        }
        return CrossReference(
            reference_id=f"ref_{hashlib.md5(f'{self.target_id}{self.source_id}{datetime.now().isoformat()}'.encode()).hexdigest()[:12]}",
            source_memory=self.target_memory,
            source_id=self.target_id,
            target_memory=self.source_memory,
            target_id=self.source_id,
            reference_type=reverse_types.get(self.reference_type, ReferenceType.RELATED.value),
            confidence=self.confidence,
            description=f"Reverse of: {self.description}",
            metadata={"reverse_of": self.reference_id},
        )


@dataclass
class MemoryNode:
    """A node in the cross-memory graph."""
    memory_type: str
    entry_id: str
    title: str
    summary: str
    timestamp: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def full_id(self) -> str:
        return f"{self.memory_type}:{self.entry_id}"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CrossMemoryGraph:
    """Graph of cross-memory references for traversal and querying."""

    def __init__(self):
        self._nodes: Dict[str, MemoryNode] = {}  # full_id -> node
        self._edges: Dict[str, List[CrossReference]] = defaultdict(list)  # source_full_id -> refs
        self._reverse_edges: Dict[str, List[CrossReference]] = defaultdict(list)  # target_full_id -> refs
        self._lock = threading.RLock()

    def add_node(self, node: MemoryNode) -> None:
        """Add or update a node."""
        with self._lock:
            self._nodes[node.full_id] = node

    def add_reference(self, ref: CrossReference) -> None:
        """Add a cross-reference (edge)."""
        with self._lock:
            source_full = f"{ref.source_memory}:{ref.source_id}"
            target_full = f"{ref.target_memory}:{ref.target_id}"

            self._edges[source_full].append(ref)
            self._reverse_edges[target_full].append(ref)

            # Ensure nodes exist
            if source_full not in self._nodes:
                self._nodes[source_full] = MemoryNode(
                    memory_type=ref.source_memory,
                    entry_id=ref.source_id,
                    title="",
                    summary="",
                    timestamp=ref.created_at,
                )
            if target_full not in self._nodes:
                self._nodes[target_full] = MemoryNode(
                    memory_type=ref.target_memory,
                    entry_id=ref.target_id,
                    title="",
                    summary="",
                    timestamp=ref.created_at,
                )

            # Add reverse reference automatically
            reverse_ref = ref.reverse()
            self._edges[target_full].append(reverse_ref)
            self._reverse_edges[source_full].append(reverse_ref)

    def get_outgoing(self, memory_type: str, entry_id: str) -> List[CrossReference]:
        """Get all outgoing references from an entry."""
        with self._lock:
            full_id = f"{memory_type}:{entry_id}"
            return self._edges.get(full_id, []).copy()

    def get_incoming(self, memory_type: str, entry_id: str) -> List[CrossReference]:
        """Get all incoming references to an entry."""
        with self._lock:
            full_id = f"{memory_type}:{entry_id}"
            return self._reverse_edges.get(full_id, []).copy()

    def get_all_references(self, memory_type: str, entry_id: str) -> List[CrossReference]:
        """Get all references (both directions) for an entry."""
        with self._lock:
            outgoing = self.get_outgoing(memory_type, entry_id)
            incoming = self.get_incoming(memory_type, entry_id)
            return outgoing + incoming

    def get_connected(
        self,
        memory_type: str,
        entry_id: str,
        reference_types: Optional[List[str]] = None,
        target_memory_types: Optional[List[str]] = None,
        max_depth: int = 1,
    ) -> List[Tuple[CrossReference, MemoryNode]]:
        """Get connected nodes up to max_depth."""
        with self._lock:
            results = []
            visited = set()
            queue = [(f"{memory_type}:{entry_id}", 0)]

            while queue:
                current_full, depth = queue.pop(0)
                if current_full in visited or depth > max_depth:
                    continue
                visited.add(current_full)

                # Get outgoing references
                for ref in self._edges.get(current_full, []):
                    if reference_types and ref.reference_type not in reference_types:
                        continue
                    if target_memory_types and ref.target_memory not in target_memory_types:
                        continue

                    target_node = self._nodes.get(f"{ref.target_memory}:{ref.target_id}")
                    if target_node:
                        results.append((ref, target_node))

                    if depth < max_depth:
                        queue.append((f"{ref.target_memory}:{ref.target_id}", depth + 1))

            return results

    def find_path(
        self,
        source_memory: str,
        source_id: str,
        target_memory: str,
        target_id: str,
        max_depth: int = 3,
    ) -> Optional[List[CrossReference]]:
        """Find a path between two entries."""
        with self._lock:
            from collections import deque

            start = f"{source_memory}:{source_id}"
            goal = f"{target_memory}:{target_id}"

            if start == goal:
                return []

            visited = {start}
            queue = deque([(start, [])])

            while queue:
                current, path = queue.popleft()
                if len(path) >= max_depth:
                    continue

                for ref in self._edges.get(current, []):
                    next_full = f"{ref.target_memory}:{ref.target_id}"
                    new_path = path + [ref]

                    if next_full == goal:
                        return new_path

                    if next_full not in visited:
                        visited.add(next_full)
                        queue.append((next_full, new_path))

            return None

    def get_stats(self) -> Dict[str, Any]:
        """Get graph statistics."""
        with self._lock:
            ref_types = defaultdict(int)
            memory_pairs = defaultdict(int)

            for refs in self._edges.values():
                for ref in refs:
                    ref_types[ref.reference_type] += 1
                    pair = f"{ref.source_memory}->{ref.target_memory}"
                    memory_pairs[pair] += 1

            return {
                "nodes": len(self._nodes),
                "edges": sum(len(refs) for refs in self._edges.values()),
                "reference_types": dict(ref_types),
                "memory_pairs": dict(memory_pairs),
                "memory_types": list(set(n.memory_type for n in self._nodes.values())),
            }


class CrossMemoryReferences:
    """Main manager for cross-memory references."""

    def __init__(
        self,
        storage_path: str = "data/memory/cross_references.json",
        auto_infer: bool = True,
        event_bus: Optional[object] = None,
        job_service: Optional[object] = None,
        observability: Optional[object] = None,
    ):
        """Initialize cross-memory references.

        Args:
            storage_path: Path to persist references
            auto_infer: Automatically infer references from content overlap
            event_bus: Optional EventBus instance (uses global if not provided)
            job_service: Optional BackgroundJobService instance (uses global if not provided)
            observability: Optional ObservabilityHub instance (uses global if not provided)
        """
        self.storage_path = Path(storage_path)
        self.auto_infer = auto_infer
        self._lock = threading.RLock()

        self.graph = CrossMemoryGraph()
        self._references: Dict[str, CrossReference] = {}  # reference_id -> ref
        self._entry_to_refs: Dict[str, Set[str]] = defaultdict(set)  # full_id -> set of ref_ids

        # Shared infrastructure
        self._event_bus = event_bus or get_event_bus()
        self._job_service = job_service or get_job_service()
        self._observability = observability or get_observability_hub()

        # Register with observability
        self._register_with_observability()

        # Schedule periodic save
        self._schedule_persistence()

        self._load()

    def _register_with_observability(self) -> None:
        """Register this subsystem with the shared ObservabilityHub."""
        if self._observability:
            self._observability.add_health_check(HealthCheck(
                name="cross_references_health",
                component="memory",
                check_func=self._health_check,
                interval_seconds=60.0,
            ))

            # Register component
            self._observability.register_component(ComponentInfo(
                name="CrossMemoryReferences",
                component_type=ComponentType.SERVICE,
                version="1.0.0",
                description="Cross-memory reference management and graph traversal",
                metadata={},
            ))

    def _health_check(self) -> HealthResult:
        """Health check for CrossMemoryReferences."""
        stats = self.get_stats()
        return HealthResult(
            name="cross_references_health",
            component="memory",
            status=HealthStatus.HEALTHY,
            message=f"{stats['nodes']} nodes, {stats['edges']} edges",
            details=stats,
        )

    def _publish_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Publish an event to the EventBus."""
        try:
            self._event_bus.emit(event_type, data)
        except Exception:
            # Don't let event publishing break the system
            pass

    def _schedule_persistence(self, interval_seconds: int = 300) -> None:
        """Schedule periodic persistence."""
        # Guard against duplicate scheduling (e.g., in tests where multiple instances created)
        if self._job_service.get_job("cross_references_persist") is not None:
            return

        trigger = JobTriggerConfig(
            type=JobTriggerType.RECURRING,
            interval_seconds=interval_seconds,
        )
        self._job_service.schedule(
            job_id="cross_references_persist",
            func=self._save,
            trigger=trigger,
            name="Cross References Persistence",
            priority=JobPriority.LOW,
        )

    def is_available(self) -> bool:
        """Check if the cross-memory references system is available."""
        return self.graph.get_stats()["nodes"] > 0

    def _generate_ref_id(self) -> str:
        return f"ref_{hashlib.md5(f'{datetime.now().isoformat()}'.encode()).hexdigest()[:12]}"

    def _full_id(self, memory_type: str, entry_id: str) -> str:
        return f"{memory_type}:{entry_id}"

    def add_reference(
        self,
        source_memory: str,
        source_id: str,
        target_memory: str,
        target_id: str,
        reference_type: Union[str, ReferenceType],
        confidence: float = 1.0,
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CrossReference:
        """Add a cross-reference between two memory entries."""
        with self._lock:
            if isinstance(reference_type, ReferenceType):
                reference_type = reference_type.value

            ref = CrossReference(
                reference_id=self._generate_ref_id(),
                source_memory=source_memory,
                source_id=source_id,
                target_memory=target_memory,
                target_id=target_id,
                reference_type=reference_type,
                confidence=confidence,
                description=description,
                metadata=metadata or {},
            )

            self._references[ref.reference_id] = ref
            self.graph.add_reference(ref)

            # Track for quick lookup
            source_full = self._full_id(source_memory, source_id)
            target_full = self._full_id(target_memory, target_id)
            self._entry_to_refs[source_full].add(ref.reference_id)
            self._entry_to_refs[target_full].add(ref.reference_id)

            # Also add reverse reference ID
            for edge in self.graph._edges[target_full]:
                if edge.target_memory == source_memory and edge.target_id == source_id:
                    self._entry_to_refs[source_full].add(edge.reference_id)
                    self._entry_to_refs[target_full].add(edge.reference_id)
                    break

            self._save()

            # Publish event
            self._publish_event("memory.cross_reference_added", {
                "reference_id": ref.reference_id,
                "source_memory": source_memory,
                "source_id": source_id,
                "target_memory": target_memory,
                "target_id": target_id,
                "reference_type": reference_type,
                "confidence": confidence,
            })

            return ref

    def add_node(
        self,
        memory_type: str,
        entry_id: str,
        title: str,
        summary: str,
        timestamp: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MemoryNode:
        """Add or update a node in the graph."""
        with self._lock:
            node = MemoryNode(
                memory_type=memory_type,
                entry_id=entry_id,
                title=title,
                summary=summary,
                timestamp=timestamp or datetime.now(timezone.utc).isoformat(),
                metadata=metadata or {},
            )
            self.graph.add_node(node)

            # Publish event
            self._publish_event("memory.node_added", {
                "memory_type": memory_type,
                "entry_id": entry_id,
                "title": title,
            })

            return node

    def get_references(
        self,
        memory_type: str,
        entry_id: str,
        reference_types: Optional[List[str]] = None,
    ) -> List[CrossReference]:
        """Get all references for an entry."""
        with self._lock:
            refs = self.graph.get_all_references(memory_type, entry_id)
            if reference_types:
                refs = [r for r in refs if r.reference_type in reference_types]
            return refs

    def get_connected_entries(
        self,
        memory_type: str,
        entry_id: str,
        reference_types: Optional[List[str]] = None,
        target_memory_types: Optional[List[str]] = None,
        max_depth: int = 1,
    ) -> List[Tuple[CrossReference, MemoryNode]]:
        """Get connected entries with their references."""
        with self._lock:
            return self.graph.get_connected(
                memory_type, entry_id, reference_types, target_memory_types, max_depth
            )

    def find_connection_path(
        self,
        source_memory: str,
        source_id: str,
        target_memory: str,
        target_id: str,
        max_depth: int = 3,
    ) -> Optional[List[CrossReference]]:
        """Find a path of references between two entries."""
        with self._lock:
            return self.graph.find_path(source_memory, source_id, target_memory, target_id, max_depth)

    def infer_references_from_content(
        self,
        source_memory: str,
        source_id: str,
        source_content: str,
        target_memories: Dict[str, List[Tuple[str, str]]],  # memory_type -> [(entry_id, content)]
        min_similarity: float = 0.3,
    ) -> List[CrossReference]:
        """Infer references based on content similarity.

        Args:
            source_memory: Source memory type
            source_id: Source entry ID
            source_content: Source entry content
            target_memories: Dict of memory_type -> list of (entry_id, content)
            min_similarity: Minimum Jaccard similarity to create reference

        Returns:
            List of created references
        """
        if not self.auto_infer:
            return []

        created = []
        source_words = set(source_content.lower().split())

        for target_memory, entries in target_memories.items():
            for target_id, target_content in entries:
                target_words = set(target_content.lower().split())

                # Jaccard similarity
                intersection = source_words & target_words
                union = source_words | target_words
                similarity = len(intersection) / len(union) if union else 0

                if similarity >= min_similarity:
                    # Determine reference type based on memory types
                    ref_type = self._infer_reference_type(source_memory, target_memory)

                    ref = self.add_reference(
                        source_memory=source_memory,
                        source_id=source_id,
                        target_memory=target_memory,
                        target_id=target_id,
                        reference_type=ref_type,
                        confidence=min(similarity * 1.5, 1.0),
                        description=f"Inferred from content similarity ({similarity:.2f})",
                        metadata={"similarity": similarity, "inferred": True},
                    )
                    created.append(ref)

        return created

    def _infer_reference_type(self, source: str, target: str) -> str:
        """Infer reference type from memory type pair."""
        # Define likely relationships
        type_map = {
            ("experience", "lessons"): ReferenceType.SOURCE,
            ("lessons", "experience"): ReferenceType.DERIVED,
            ("experience", "long_term"): ReferenceType.SOURCE,
            ("lessons", "long_term"): ReferenceType.SOURCE,
            ("project", "experience"): ReferenceType.SOURCE,
            ("project", "lessons"): ReferenceType.SOURCE,
            ("episodic", "experience"): ReferenceType.SOURCE,
            ("episodic", "lessons"): ReferenceType.SOURCE,
            ("task", "project"): ReferenceType.RELATED,
            ("goals", "task"): ReferenceType.SOURCE,
            ("semantic", "experience"): ReferenceType.PREREQUISITE,
            ("semantic", "lessons"): ReferenceType.PREREQUISITE,
        }

        return type_map.get((source, target), ReferenceType.RELATED).value

    def remove_reference(self, reference_id: str) -> bool:
        """Remove a reference."""
        with self._lock:
            ref = self._references.pop(reference_id, None)
            if not ref:
                return False

            source_full = self._full_id(ref.source_memory, ref.source_id)
            target_full = self._full_id(ref.target_memory, ref.target_id)

            # Remove from graph edges
            self.graph._edges[source_full] = [
                r for r in self.graph._edges[source_full] if r.reference_id != reference_id
            ]
            self.graph._reverse_edges[target_full] = [
                r for r in self.graph._reverse_edges[target_full] if r.reference_id != reference_id
            ]

            # Remove reverse reference too
            reverse_id = f"{target_full}->{source_full}"
            for ref_list in [self.graph._edges[target_full], self.graph._reverse_edges[source_full]]:
                for r in ref_list:
                    if r.target_memory == ref.source_memory and r.target_id == ref.source_id:
                        reverse_id = r.reference_id
                        break

            self._references.pop(reverse_id, None)
            self.graph._edges[target_full] = [
                r for r in self.graph._edges[target_full] if r.reference_id != reverse_id
            ]
            self.graph._reverse_edges[source_full] = [
                r for r in self.graph._reverse_edges[source_full] if r.reference_id != reverse_id
            ]

            self._entry_to_refs[source_full].discard(reference_id)
            self._entry_to_refs[target_full].discard(reference_id)

            self._save()

            # Publish event
            self._publish_event("memory.cross_reference_removed", {
                "reference_id": reference_id,
                "source_memory": ref.source_memory,
                "source_id": ref.source_id,
                "target_memory": ref.target_memory,
                "target_id": ref.target_id,
            })

            return True

    def get_entry_references(self, memory_type: str, entry_id: str) -> List[str]:
        """Get all reference IDs for an entry."""
        with self._lock:
            return list(self._entry_to_refs.get(self._full_id(memory_type, entry_id), set()))

    def get_stats(self) -> Dict[str, Any]:
        """Get cross-reference statistics."""
        with self._lock:
            return self.graph.get_stats()

    def _save(self) -> None:
        """Save references to disk."""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.storage_path.with_suffix(".tmp")
        try:
            data = {
                "references": [r.to_dict() for r in self._references.values()],
                "nodes": [n.to_dict() for n in self.graph._nodes.values()],
            }
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            temp_path.replace(self.storage_path)
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            raise

    def _load(self) -> None:
        """Load references from disk."""
        if not self.storage_path.exists():
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for ref_data in data.get("references", []):
                ref = CrossReference.from_dict(ref_data)
                self._references[ref.reference_id] = ref
                self.graph.add_reference(ref)

                source_full = self._full_id(ref.source_memory, ref.source_id)
                target_full = self._full_id(ref.target_memory, ref.target_id)
                self._entry_to_refs[source_full].add(ref.reference_id)
                self._entry_to_refs[target_full].add(ref.reference_id)

            for node_data in data.get("nodes", []):
                node = MemoryNode(**node_data)
                self.graph.add_node(node)
        except Exception:
            pass

    def export_graph(self, format: str = "json") -> Any:
        """Export the cross-memory graph for analysis."""
        with self._lock:
            if format == "json":
                return {
                    "nodes": [n.to_dict() for n in self.graph._nodes.values()],
                    "edges": [r.to_dict() for r in self._references.values()],
                }
            elif format == "graphml":
                # Simple GraphML export
                lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                         '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
                         '  <graph id="cross_memory" edgedefault="directed">']

                for node in self.graph._nodes.values():
                    lines.append(f'    <node id="{node.full_id}">')
                    lines.append(f'      <data key="memory_type">{node.memory_type}</data>')
                    lines.append(f'      <data key="title">{node.title}</data>')
                    lines.append('    </node>')

                for ref in self._references.values():
                    lines.append(f'    <edge source="{ref.source_memory}:{ref.source_id}" target="{ref.target_memory}:{ref.target_id}">')
                    lines.append(f'      <data key="type">{ref.reference_type}</data>')
                    lines.append(f'      <data key="confidence">{ref.confidence}</data>')
                    lines.append('    </edge>')

                lines.extend(['  </graph>', '</graphml>'])
                return "\n".join(lines)

            return None


def create_cross_memory_references(
    storage_path: str = "data/memory/cross_references.json",
    auto_infer: bool = True,
) -> CrossMemoryReferences:
    """Factory function to create CrossMemoryReferences."""
    return CrossMemoryReferences(storage_path=storage_path, auto_infer=auto_infer)


# Convenience functions for common reference patterns

def link_experience_to_lesson(
    cross_refs: CrossMemoryReferences,
    experience_id: str,
    lesson_id: str,
    confidence: float = 1.0,
) -> CrossReference:
    """Link an experience as the source of a lesson."""
    return cross_refs.add_reference(
        source_memory="experience",
        source_id=experience_id,
        target_memory="lessons",
        target_id=lesson_id,
        reference_type=ReferenceType.SOURCE,
        confidence=confidence,
        description="Experience that led to this lesson",
    )


def link_lesson_to_long_term(
    cross_refs: CrossMemoryReferences,
    lesson_id: str,
    long_term_key: str,
    confidence: float = 1.0,
) -> CrossReference:
    """Link a lesson as the source of a long-term memory entry."""
    return cross_refs.add_reference(
        source_memory="lessons",
        source_id=lesson_id,
        target_memory="long_term",
        target_id=long_term_key,
        reference_type=ReferenceType.SOURCE,
        confidence=confidence,
        description="Lesson promoted to long-term memory",
    )


def link_project_to_experience(
    cross_refs: CrossMemoryReferences,
    project_timestamp: str,
    experience_id: str,
    confidence: float = 0.8,
) -> CrossReference:
    """Link a project memory entry as source of an experience."""
    return cross_refs.add_reference(
        source_memory="project",
        source_id=project_timestamp,
        target_memory="experience",
        target_id=experience_id,
        reference_type=ReferenceType.SOURCE,
        confidence=confidence,
        description="Project event that generated this experience",
    )


def link_episodic_to_lesson(
    cross_refs: CrossMemoryReferences,
    episodic_id: str,
    lesson_id: str,
    confidence: float = 0.9,
) -> CrossReference:
    """Link an episodic event (e.g., failure) as cause of a lesson."""
    return cross_refs.add_reference(
        source_memory="episodic",
        source_id=episodic_id,
        target_memory="lessons",
        target_id=lesson_id,
        reference_type=ReferenceType.CAUSED,
        confidence=confidence,
        description="Event that caused this lesson to be learned",
    )


def link_goal_to_task(
    cross_refs: CrossMemoryReferences,
    goal_id: str,
    task_id: str,
    confidence: float = 1.0,
) -> CrossReference:
    """Link a goal as source of a task."""
    return cross_refs.add_reference(
        source_memory="goals",
        source_id=goal_id,
        target_memory="task",
        target_id=task_id,
        reference_type=ReferenceType.SOURCE,
        confidence=confidence,
        description="Goal that spawned this task",
    )


def link_semantic_as_prerequisite(
    cross_refs: CrossMemoryReferences,
    semantic_id: str,
    target_memory: str,
    target_id: str,
    confidence: float = 0.7,
) -> CrossReference:
    """Link a semantic memory entry as prerequisite for another entry."""
    return cross_refs.add_reference(
        source_memory="semantic",
        source_id=semantic_id,
        target_memory=target_memory,
        target_id=target_id,
        reference_type=ReferenceType.PREREQUISITE,
        confidence=confidence,
        description="Fundamental knowledge required for this entry",
    )