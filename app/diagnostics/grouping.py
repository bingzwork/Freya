"""Deterministic diagnostic deduplication and conservative causal grouping."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


class CausalRelation:
    KNOWN_CAUSE = "KNOWN_CAUSE"
    LIKELY_CAUSE = "LIKELY_CAUSE"
    RELATED = "RELATED"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class DiagnosticEvent:
    event_id: str
    source: str
    failure_type: str
    component: str
    operation: str = ""
    message: str = ""
    fingerprint: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    dependencies: List[str] = field(default_factory=list)
    workflow_id: str = ""
    causal_parent: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def stable_key(self) -> str:
        raw = "|".join((self.source, self.failure_type, self.component, self.operation, self.fingerprint))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class DiagnosticOccurrence:
    representative: DiagnosticEvent
    occurrences: List[DiagnosticEvent] = field(default_factory=list)

    @property
    def occurrence_count(self) -> int:
        return len(self.occurrences)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.representative.stable_key(),
            "representative": self.representative.__dict__,
            "occurrence_count": self.occurrence_count,
            "timestamps": [item.timestamp for item in self.occurrences],
            "event_ids": [item.event_id for item in self.occurrences],
        }


@dataclass
class CausalGroup:
    group_id: str
    root: DiagnosticOccurrence
    symptoms: List[DiagnosticOccurrence] = field(default_factory=list)
    relation: str = CausalRelation.UNRESOLVED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "group_id": self.group_id,
            "relation": self.relation,
            "root": self.root.to_dict(),
            "symptoms": [item.to_dict() for item in self.symptoms],
        }


@dataclass
class DiagnosticGroupingReport:
    occurrences: List[DiagnosticOccurrence]
    groups: List[CausalGroup]
    repair_proposals: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "occurrences": [item.to_dict() for item in self.occurrences],
            "groups": [item.to_dict() for item in self.groups],
            "repair_proposals": list(self.repair_proposals),
        }


class DiagnosticGrouper:
    def __init__(self, *, time_window_seconds: float = 60.0, dependencies: Optional[Mapping[str, Sequence[str]]] = None) -> None:
        self.time_window_seconds = time_window_seconds
        self.dependencies = {name: set(values) for name, values in (dependencies or {}).items()}

    def group(self, events: Iterable[DiagnosticEvent]) -> DiagnosticGroupingReport:
        ordered = sorted(events, key=lambda event: (event.timestamp, event.event_id))
        by_key: Dict[str, DiagnosticOccurrence] = {}
        for event in ordered:
            occurrence = by_key.setdefault(event.stable_key(), DiagnosticOccurrence(event))
            occurrence.occurrences.append(event)
        occurrences = sorted(by_key.values(), key=lambda item: self._root_sort_key(item, by_key.values()))
        groups: List[CausalGroup] = []
        assigned: set[str] = set()
        for occurrence in occurrences:
            if occurrence.representative.stable_key() in assigned:
                continue
            symptoms: List[DiagnosticOccurrence] = []
            relation = CausalRelation.UNRESOLVED
            root = occurrence
            for candidate in occurrences:
                if candidate is occurrence or candidate.representative.stable_key() in assigned:
                    continue
                relationship = self._relationship(root.representative, candidate.representative)
                if relationship:
                    symptoms.append(candidate)
                    relation = relationship if relation == CausalRelation.UNRESOLVED else relation
                    assigned.add(candidate.representative.stable_key())
            assigned.add(root.representative.stable_key())
            group_id = "group_" + hashlib.sha256(root.representative.stable_key().encode()).hexdigest()[:10]
            groups.append(CausalGroup(group_id, root, sorted(symptoms, key=lambda item: item.representative.stable_key()), relation))
        proposals = [group.root.representative.component + ":" + group.root.representative.failure_type for group in groups]
        return DiagnosticGroupingReport(occurrences, groups, proposals)

    def _root_sort_key(
        self,
        occurrence: DiagnosticOccurrence,
        all_occurrences: Iterable[DiagnosticOccurrence],
    ) -> tuple[int, str]:
        """Prefer findings with explicit or dependency evidence downstream."""
        event = occurrence.representative
        others = [item.representative for item in all_occurrences if item is not occurrence]
        is_explicit_root = any(other.causal_parent == event.event_id for other in others)
        is_dependency_root = any(
            event.component in self.dependencies.get(other.component, set())
            or event.component in other.dependencies
            for other in others
        )
        return (0 if is_explicit_root or is_dependency_root else 1, event.stable_key())

    def _relationship(self, root: DiagnosticEvent, symptom: DiagnosticEvent) -> Optional[str]:
        if symptom.causal_parent == root.event_id:
            return CausalRelation.KNOWN_CAUSE
        if root.component in self.dependencies.get(symptom.component, set()) or root.component in symptom.dependencies:
            return CausalRelation.LIKELY_CAUSE
        if root.workflow_id and root.workflow_id == symptom.workflow_id and self._within_window(root, symptom):
            return CausalRelation.RELATED
        return None

    def _within_window(self, first: DiagnosticEvent, second: DiagnosticEvent) -> bool:
        try:
            left = datetime.fromisoformat(first.timestamp.replace("Z", "+00:00"))
            right = datetime.fromisoformat(second.timestamp.replace("Z", "+00:00"))
            return abs((right - left).total_seconds()) <= self.time_window_seconds
        except (TypeError, ValueError):
            return False


__all__ = ["CausalRelation", "DiagnosticEvent", "DiagnosticOccurrence", "CausalGroup", "DiagnosticGroupingReport", "DiagnosticGrouper"]
