"""Deterministic runtime classification and distillation for validated learning.

The distillers deliberately operate only on LearningPipeline-validated evidence. They
normalize reusable knowledge, observed experiences, and procedural skills without
calling an LLM or accepting raw conversation output as durable memory.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

from .models import (
    DistilledLearning,
    LearningCandidate,
    LearningClassification,
    LearnedItemType,
)


class LearningClassifier:
    """Prefer explicit metadata and stable source signals over semantic inference."""

    _TYPE_KEYS = ("learning_type", "type", "artifact_type", "memory_type")
    _SKILL_CATEGORIES = {
        "skill", "strategy", "workflow", "procedure", "troubleshooting",
        "bug_fix", "pattern", "anti_pattern", "decision", "guideline",
        "standard", "playbook",
    }
    _EXPERIENCE_CATEGORIES = {
        "experience", "execution_outcome", "observation", "incident",
        "repair", "failure", "success", "event_pattern",
    }
    _SKILL_TERMS = {
        "strategy", "workflow", "procedure", "playbook", "runbook",
        "troubleshoot", "repair", "steps", "precondition", "validation",
    }
    _EXPERIENCE_TERMS = {
        "attempt", "failed", "failure", "succeeded", "success", "observed",
        "outcome", "verification", "result", "repair", "incident",
    }

    def classify(
        self, candidate: LearningCandidate, item: Dict[str, Any]
    ) -> LearningClassification:
        metadata = item.get("metadata") or {}
        for container in (item, metadata, candidate.metadata or {}):
            for key in self._TYPE_KEYS:
                explicit = container.get(key)
                parsed = self._parse_type(explicit)
                if parsed is not None:
                    return LearningClassification(
                        item=item,
                        learning_type=parsed,
                        reason=f"explicit {key} metadata",
                    )

        category = str(item.get("category", "")).strip().lower()
        if category in self._SKILL_CATEGORIES:
            return LearningClassification(item, LearnedItemType.SKILL, "skill category")
        if category in self._EXPERIENCE_CATEGORIES:
            return LearningClassification(item, LearnedItemType.EXPERIENCE, "experience category")

        if candidate.candidate_type.value == "execution_outcome":
            return LearningClassification(
                item, LearnedItemType.EXPERIENCE, "execution outcome candidate"
            )

        structured_fields = set(metadata) | set(item)
        if structured_fields.intersection(
            {"action", "result", "outcome", "failure_reason", "successful_repair", "verification"}
        ):
            return LearningClassification(
                item, LearnedItemType.EXPERIENCE, "observed action/outcome fields"
            )

        text = self._normalized_text(
            " ".join(str(value) for value in (item.get("title", ""), item.get("content", "")))
        )
        words = set(text.split())
        if words.intersection(self._SKILL_TERMS):
            return LearningClassification(item, LearnedItemType.SKILL, "procedural language")
        if words.intersection(self._EXPERIENCE_TERMS):
            return LearningClassification(item, LearnedItemType.EXPERIENCE, "observed outcome language")
        return LearningClassification(item, LearnedItemType.KNOWLEDGE, "declarative default")

    @staticmethod
    def _parse_type(value: Any) -> LearnedItemType | None:
        if isinstance(value, LearnedItemType):
            return value
        if value is None:
            return None
        normalized = str(value).strip().lower()
        aliases = {
            "fact": LearnedItemType.KNOWLEDGE,
            "semantic": LearnedItemType.KNOWLEDGE,
            "declarative": LearnedItemType.KNOWLEDGE,
            "event": LearnedItemType.EXPERIENCE,
            "lesson": LearnedItemType.EXPERIENCE,
            "procedure": LearnedItemType.SKILL,
            "strategy": LearnedItemType.SKILL,
            "workflow": LearnedItemType.SKILL,
        }
        if normalized in aliases:
            return aliases[normalized]
        try:
            return LearnedItemType(normalized)
        except ValueError:
            return None

    @staticmethod
    def _normalized_text(value: str) -> str:
        return re.sub(r"\s+", " ", value.lower()).strip()


class _BaseDistiller:
    """Shared compaction, provenance, and evidence helpers for deterministic distillers."""

    @staticmethod
    def _compact(value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()

    def _provenance(
        self, candidate: LearningCandidate, item: Dict[str, Any]
    ) -> Dict[str, Any]:
        metadata = item.get("metadata") or {}
        evidence_ids = self._as_list(metadata.get("evidence_ids") or metadata.get("evidence_id"))
        if candidate.id not in evidence_ids:
            evidence_ids.append(candidate.id)
        return {
            "source_candidate_id": candidate.id,
            "source_component": candidate.source_component,
            "source_session_id": candidate.source_session_id,
            "source": item.get("source", "learning_pipeline"),
            "evidence_ids": evidence_ids,
            "evidence": metadata.get("evidence"),
            "candidate_timestamp": (
                candidate.timestamp.isoformat()
                if hasattr(candidate.timestamp, "isoformat")
                else str(candidate.timestamp)
            ),
        }

    @staticmethod
    def _as_list(value: Any) -> List[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return list(value)
        if isinstance(value, (tuple, set)):
            return list(value)
        return [value]

    def _base_metadata(
        self, candidate: LearningCandidate, item: Dict[str, Any]
    ) -> Dict[str, Any]:
        metadata = dict(item.get("metadata") or {})
        metadata.update(self._provenance(candidate, item))
        return metadata


class KnowledgeDistiller(_BaseDistiller):
    """Distill reusable factual, semantic, conceptual, and declarative knowledge."""

    def distill(self, candidate: LearningCandidate, item: Dict[str, Any]) -> DistilledLearning:
        metadata = self._base_metadata(candidate, item)
        title = self._compact(item.get("title")) or self._compact(item.get("content"))[:120]
        content = self._compact(item.get("content"))
        category = self._compact(item.get("category")) or "custom"
        tags = sorted(set(["learned", "knowledge", *candidate.tags, *item.get("tags", [])]))
        metadata.update(
            {
                "distiller": "KnowledgeDistiller",
                "original_category": item.get("category", ""),
                "evidence_count": max(1, len(metadata["evidence_ids"])),
            }
        )
        return DistilledLearning(
            learning_type=LearnedItemType.KNOWLEDGE,
            title=title,
            content=content,
            category=category,
            confidence=float(item.get("confidence", 0.0)),
            source=str(item.get("source", "learning_pipeline")),
            tags=tags,
            metadata=metadata,
        )


class ExperienceDistiller(_BaseDistiller):
    """Extract bounded situation/action/outcome/lesson structure from real observations."""

    def distill(self, candidate: LearningCandidate, item: Dict[str, Any]) -> DistilledLearning:
        item_metadata = item.get("metadata") or {}
        metadata = self._base_metadata(candidate, item)
        context = self._compact(
            item_metadata.get("context")
            or item_metadata.get("problem")
            or candidate.context.get("problem")
            or candidate.context.get("context")
            or candidate.raw_observation.get("task")
            or "the observed task"
        )
        action = self._compact(
            item_metadata.get("action")
            or item_metadata.get("approach")
            or item_metadata.get("successful_repair")
            or item.get("content")
        )
        result = self._compact(
            item_metadata.get("result")
            or item_metadata.get("outcome")
            or candidate.raw_observation.get("result")
            or candidate.raw_observation.get("outcome")
            or ("execution succeeded" if item_metadata.get("execution_success") is True else "")
            or ("execution failed" if item_metadata.get("execution_success") is False else "")
        )
        failure_reason = self._compact(
            item_metadata.get("failure_reason")
            or item_metadata.get("error")
            or candidate.raw_observation.get("error")
        )
        successful_repair = self._compact(item_metadata.get("successful_repair"))
        verification = item_metadata.get("verification") or candidate.raw_observation.get("verification")
        lesson = self._compact(item.get("content"))
        description_parts = [f"Context: {context}.", f"Action: {action}."]
        if result:
            description_parts.append(f"Result: {result}.")
        if failure_reason:
            description_parts.append(f"Failure reason: {failure_reason}.")
        if successful_repair:
            description_parts.append(f"Successful repair: {successful_repair}.")
        description_parts.append(f"Lesson: {lesson}")
        metadata.update(
            {
                "distiller": "ExperienceDistiller",
                "experience": {
                    "context": context,
                    "action": action,
                    "result": result,
                    "failure_reason": failure_reason,
                    "successful_repair": successful_repair,
                    "verification": verification,
                },
                "evidence_count": max(1, len(metadata["evidence_ids"])),
            }
        )
        outcome = "neutral"
        if item_metadata.get("execution_success") is True or item_metadata.get("success") is True:
            outcome = "positive"
        elif item_metadata.get("execution_success") is False or item_metadata.get("success") is False or failure_reason:
            outcome = "negative"
        metadata["outcome"] = outcome
        return DistilledLearning(
            learning_type=LearnedItemType.EXPERIENCE,
            title=self._compact(item.get("title")) or f"Experience: {context}",
            content=" ".join(description_parts),
            category=self._compact(item.get("category")) or "experience",
            confidence=float(item.get("confidence", 0.0)),
            source=str(item.get("source", "learning_pipeline")),
            tags=sorted(set(["learned", "experience", *candidate.tags, *item.get("tags", [])])),
            metadata=metadata,
        )


class SkillDistiller(_BaseDistiller):
    """Generate bounded reusable strategies with validation and evidence links."""

    _REUSE_SIGNALS = {"strategy", "workflow", "procedure", "skill", "reusable", "playbook"}

    def should_derive_from_experience(self, experience: DistilledLearning) -> bool:
        metadata = experience.metadata
        if metadata.get("evidence_count", 1) >= 2:
            return True
        values: Iterable[Any] = [*experience.tags, metadata.get("derive_skill"), metadata.get("reusable")]
        return any(str(value).strip().lower() in self._REUSE_SIGNALS or value is True for value in values)

    def distill(self, candidate: LearningCandidate, item: Dict[str, Any]) -> DistilledLearning:
        return self._build(candidate, item, None)

    def distill_from_experience(
        self, candidate: LearningCandidate, experience: DistilledLearning
    ) -> DistilledLearning:
        return self._build(candidate, experience.to_memory_item(), experience)

    def _build(
        self,
        candidate: LearningCandidate,
        item: Dict[str, Any],
        experience: DistilledLearning | None,
    ) -> DistilledLearning:
        item_metadata = item.get("metadata") or {}
        metadata = self._base_metadata(candidate, item)
        experience_data = item_metadata.get("experience", {})
        applicability = self._compact(
            item_metadata.get("applicability")
            or item_metadata.get("context")
            or experience_data.get("context")
            or candidate.context.get("problem")
            or "the matching task context"
        )
        instructions = self._compact(
            item_metadata.get("instructions")
            or item_metadata.get("procedure")
            or item_metadata.get("action")
            or experience_data.get("action")
            or item.get("content")
        )
        validation = self._compact(
            item_metadata.get("validation")
            or item_metadata.get("verification")
            or experience_data.get("verification")
            or experience_data.get("result")
            or "verify the observed result before considering the strategy successful"
        )
        failure_handling = self._compact(
            item_metadata.get("failure_handling")
            or item_metadata.get("successful_repair")
            or experience_data.get("successful_repair")
            or experience_data.get("failure_reason")
        )
        content = f"Use when: {applicability}. Instructions: {instructions}. Validation: {validation}."
        if failure_handling:
            content += f" Failure handling: {failure_handling}."

        evidence_count = max(1, len(metadata["evidence_ids"]))
        incoming_confidence = float(item.get("confidence", 0.0))
        # A single event may suggest a low-confidence skill, but cannot create a
        # highly trusted procedure until corroborating evidence reinforces it.
        confidence_cap = 1.0 if evidence_count >= 2 else 0.6
        confidence = min(incoming_confidence, confidence_cap)
        metadata.update(
            {
                "distiller": "SkillDistiller",
                "skill": {
                    "applicability": applicability,
                    "instructions": instructions,
                    "validation": validation,
                    "failure_handling": failure_handling,
                },
                "evidence_count": evidence_count,
                "requires_reinforcement": evidence_count < 2,
            }
        )
        if experience is not None:
            metadata["derived_from_experience"] = experience.title
        return DistilledLearning(
            learning_type=LearnedItemType.SKILL,
            title=self._compact(item.get("title")) or f"Strategy for {applicability}",
            content=content,
            category="skill",
            confidence=confidence,
            source=str(item.get("source", "learning_pipeline")),
            tags=sorted(set(["learned", "skill", *candidate.tags, *item.get("tags", [])])),
            metadata=metadata,
        )


__all__ = [
    "ExperienceDistiller",
    "KnowledgeDistiller",
    "LearningClassifier",
    "SkillDistiller",
]
