from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

from app.core.logger import logger


class ResearchTaskIntent(str, Enum):
    KNOWLEDGE_QUERY = "KNOWLEDGE_QUERY"
    RESEARCH_QUERY = "RESEARCH_QUERY"
    DEEP_RESEARCH_TASK = "DEEP_RESEARCH_TASK"
    ARCHITECTURE_STUDY_TASK = "ARCHITECTURE_STUDY_TASK"
    RESEARCH_AND_LEARNING_TASK = "RESEARCH_AND_LEARNING_TASK"
    IMPLEMENTATION_TASK = "IMPLEMENTATION_TASK"


@dataclass(frozen=True)
class TaskRequestSemantic:
    intent: str
    query: str
    target: str = ""
    study_requested: bool = False
    learning_requested: bool = False
    implementation_requested: bool = False
    fresh_external_inspection_required: bool = False
    substantial_scope: bool = False
    compare_with_freya: bool = False
    output_goal: str = "answer"
    constraints: List[str] = field(default_factory=list)

    @property
    def requires_task(self) -> bool:
        return self.intent in {
            ResearchTaskIntent.DEEP_RESEARCH_TASK.value,
            ResearchTaskIntent.ARCHITECTURE_STUDY_TASK.value,
            ResearchTaskIntent.RESEARCH_AND_LEARNING_TASK.value,
        }

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self) | {"requires_task": self.requires_task}


class ResearchTaskSemanticAnalyzer:
    """General study/learning semantic gate; it is not tied to a browser vendor."""

    _STUDY_RE = re.compile(r"\b(?:study|analy[sz]e|understand|inspect|review|reverse[- ]engineer|read)\b", re.I)
    _DEEP_RE = re.compile(r"\b(?:deep(?:ly)?|entire|whole|current architecture|codebase|repository|system|framework|project|documentation|architecture)\b", re.I)
    _LEARN_RE = re.compile(r"\b(?:learn|remember|retain|useful patterns?|lessons?)\b", re.I)
    _IMPLEMENT_RE = re.compile(r"\b(?:implement|improve|modify|change|fix|build|use what you learned|apply the learned)\b", re.I)
    _FRESH_RE = re.compile(r"\b(?:current|latest|entire current|repository|github|documentation|codebase|inspect)\b", re.I)

    @classmethod
    def analyze(cls, query: str) -> TaskRequestSemantic:
        text = " ".join(str(query or "").split()).strip()
        lower = text.lower()
        implementation = bool(cls._IMPLEMENT_RE.search(text)) and bool(re.search(r"\b(?:freya|code|implementation|browser|system|this)\b", lower))
        study = bool(cls._STUDY_RE.search(text)) or bool(re.search(r"\bresearch\s+deep(?:ly)?\b", lower))
        deep_scope = bool(cls._DEEP_RE.search(text))
        learning = bool(cls._LEARN_RE.search(text))
        substantial = study and deep_scope
        compare = bool(re.search(r"\b(?:compare|what\s+freya\s+can\s+use|improve\s+freya)\b", lower))
        target = cls._target(text)
        fresh = bool(cls._FRESH_RE.search(text))
        if implementation:
            intent, goal = ResearchTaskIntent.IMPLEMENTATION_TASK.value, "implementation_plan"
        elif study and learning:
            intent, goal = ResearchTaskIntent.RESEARCH_AND_LEARNING_TASK.value, "verified_reusable_lessons"
        elif study and substantial:
            intent, goal = ResearchTaskIntent.ARCHITECTURE_STUDY_TASK.value, "structured_architecture_report"
        elif study:
            intent, goal = ResearchTaskIntent.RESEARCH_QUERY.value, "bounded_research_report"
        elif re.search(r"\b(?:research|search|look up|find sources?)\b", lower):
            intent, goal = ResearchTaskIntent.RESEARCH_QUERY.value, "research_report"
        else:
            intent, goal = ResearchTaskIntent.KNOWLEDGE_QUERY.value, "answer"
        if learning and not study and not implementation:
            intent, goal = ResearchTaskIntent.RESEARCH_AND_LEARNING_TASK.value, "verified_reusable_lessons"
            substantial = True
        constraints = []
        if fresh:
            constraints.append("fresh_external_inspection")
        if compare:
            constraints.append("compare_with_freya")
        if learning:
            constraints.append("explicit_learning_only")
        return TaskRequestSemantic(intent=intent, query=text, target=target, study_requested=study, learning_requested=learning, implementation_requested=implementation, fresh_external_inspection_required=fresh, substantial_scope=substantial, compare_with_freya=compare, output_goal=goal, constraints=constraints)

    @staticmethod
    def _target(query: str) -> str:
        cleaned = re.sub(r"^\s*(?:please\s+)?(?:study|analyze|analyse|understand|inspect|review|research|read)\s+", "", query, flags=re.I)
        cleaned = re.sub(r"\s+(?:and\s+)?(?:learn|remember|retain)\b.*$", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\s+(?:and\s+)?(?:what|which)\s+freya\s+can\s+use.*$", "", cleaned, flags=re.I)
        return cleaned.strip(" .?!")[:240]


def _jsonable(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _jsonable(value.to_dict())
    if hasattr(value, "value") and not isinstance(value, (str, int, float, bool, dict, list, tuple)):
        return _jsonable(value.value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _publish(name: str, data: Dict[str, Any]) -> None:
    try:
        from app.core.events import Event, get_event_bus
        get_event_bus().publish(Event(name=name, data=data, source="research_task_learning"))
    except Exception:
        logger.debug("Study event unavailable: %s", name)


class ResearchTaskLearningOrchestrator:
    """Connects knowledge-first escalation, bounded research, verification, and learning."""

    def __init__(self, system: Any, capability_router: Any):
        self.system = system
        self.router = capability_router

    def run(self, semantic: TaskRequestSemantic, *, timeout_seconds: float = 180.0) -> Dict[str, Any]:
        if not semantic.requires_task:
            return {"success": False, "intent": semantic.intent, "message": "This request does not require a study task."}
        job_service = getattr(getattr(self.system, "infra", None), "job_service", None)
        metadata = {
            "safe_title": f"Study {semantic.target or semantic.query[:100]}",
            "task_title": f"Study {semantic.target or semantic.query[:100]}",
            "task_type": semantic.intent,
            "origin": "user_research_task",
            "research_task": True,
            "learning_requested": semantic.learning_requested,
            "fresh_external_inspection_required": semantic.fresh_external_inspection_required,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        _publish("research.task.created", {"intent": semantic.intent, "title": metadata["safe_title"], "learning_requested": semantic.learning_requested})
        if job_service is None or not callable(getattr(job_service, "add_job", None)):
            return self._execute(semantic, metadata)
        holder: Dict[str, Any] = {}
        def work() -> Dict[str, Any]:
            result = self._execute(semantic, metadata)
            holder["result"] = result
            return result
        try:
            job_id = job_service.add_job(work, name=metadata["safe_title"], tags={"kind": "research_task", "intent": semantic.intent}, metadata=metadata)
        except Exception as exc:
            return {"success": False, "intent": semantic.intent, "task_status": "FAILED", "message": f"The study task could not be queued: {exc}"}
        deadline = time.monotonic() + max(10.0, float(timeout_seconds))
        while time.monotonic() < deadline:
            if "result" in holder:
                return {**holder["result"], "task_id": job_id, "task_status": "COMPLETED" if holder["result"].get("success") else "FAILED"}
            job = job_service.get_job(job_id) if callable(getattr(job_service, "get_job", None)) else None
            status = getattr(getattr(job, "status", None), "value", getattr(job, "status", ""))
            if status in {"failed", "cancelled"}:
                return {"success": False, "intent": semantic.intent, "task_id": job_id, "task_status": status.upper(), "message": str(getattr(job, "last_error", None) or "Study task did not complete.")}
            time.sleep(0.2)
        return {"success": False, "intent": semantic.intent, "task_id": job_id, "task_status": "TIMEOUT", "message": "The bounded study task is still running; no unverified learning was stored."}

    def _execute(self, semantic: TaskRequestSemantic, metadata: Dict[str, Any]) -> Dict[str, Any]:
        _publish("research.task.activity", {"activity": "SEARCHING", "title": metadata["safe_title"], "intent": semantic.intent})
        query = semantic.query
        try:
            result = self.router.execute_capability(
                "research_capability", query, capability_action="research_topic", topic=query,
                mode="DEEP_RESEARCH", max_queries=2, max_sources=6, max_pages=6, max_duration=90,
                original_request=query, task_intent=semantic.intent, study_scope=semantic.to_dict(),
            )
        except Exception as exc:
            return {"success": False, "intent": semantic.intent, "task_status": "FAILED", "message": f"Study research failed: {exc}"}
        data = getattr(result, "data", None) if result is not None else None
        data = data if isinstance(data, dict) else {}
        raw = data.get("data", data) if isinstance(data, dict) else {}
        facts = raw.get("key_findings") or raw.get("facts") or []
        findings = self._structured_findings(facts, semantic, raw)
        verified = [item for item in findings if item["verification_status"] == "verified" and item["usefulness"] not in {"not_needed", "needs_more_verification"}]
        # Durable learning receives a compact, representative subset rather than
        # every raw fact returned by a multi-source study.
        learnable = verified[:8]
        learning = self._learn(learnable, semantic) if semantic.learning_requested else {"requested": False, "accepted": 0, "rejected": 0, "stored": 0, "status": "NOT_REQUESTED"}
        success = bool(getattr(result, "success", False)) and (not semantic.learning_requested or learning.get("stored", 0) > 0 or not verified)
        _publish("research.task.activity", {"activity": "LEARNING" if semantic.learning_requested else "SUCCESS", "title": metadata["safe_title"], "verified_findings": len(verified), "learning_candidates": len(learnable), "stored_lessons": learning.get("stored", 0)})
        return {"success": success, "intent": semantic.intent, "task_status": "COMPLETED" if success else "PARTIAL", "message": self._report(semantic, findings, learning, raw), "findings": findings, "learning": learning, "research": {"source_count": raw.get("source_count", len(raw.get("sources", []) or [])), "partial": bool(raw.get("partial")), "semantic": raw.get("semantic", {})}}

    @staticmethod
    def _structured_findings(facts: Sequence[Any], semantic: TaskRequestSemantic, raw: Dict[str, Any]) -> List[Dict[str, Any]]:
        conflicts = bool(raw.get("conflicts"))
        output = []
        seen = set()
        for item in facts[:24] if isinstance(facts, list) else []:
            record = item if isinstance(item, dict) else _jsonable(item)
            claim = str(record.get("claim") or record.get("evidence") or "").strip()
            if not claim or claim.lower() in seen:
                continue
            seen.add(claim.lower())
            confidence = float(record.get("confidence") or 0.0)
            verified = bool(record.get("source_url") or record.get("source_title")) and confidence >= 0.45 and not conflicts
            usefulness = "needs_more_verification" if not verified else ("useful_for_freya" if semantic.compare_with_freya else "reusable_knowledge")
            output.append({"finding": claim, "usefulness": usefulness, "verification_status": "verified" if verified else "needs_more_verification", "confidence": confidence, "provenance": {"source_url": record.get("source_url", ""), "source_title": record.get("source_title", ""), "published_date": record.get("published_date", ""), "evidence_type": record.get("evidence_type", "")}, "relationship_to_freya": "candidate_pattern" if semantic.compare_with_freya else "not_assessed"})
        return output

    def _learn(self, findings: Sequence[Dict[str, Any]], semantic: TaskRequestSemantic) -> Dict[str, Any]:
        pipeline = getattr(self.system, "learning_pipeline", None)
        if pipeline is None:
            return {"requested": True, "accepted": 0, "rejected": len(findings), "stored": 0, "status": "REJECTED", "reason": "LearningPipeline unavailable"}
        from app.learning.models import LearningCandidate, LearningCandidateType
        accepted = rejected = stored = 0
        results = []
        for finding in findings:
            candidate = LearningCandidate(candidate_type=LearningCandidateType.MANUAL_INPUT, source_component="ResearchTaskLearning", raw_observation={"verified": True, "usefulness": finding["usefulness"], "finding": finding["finding"]}, context={"provenance": finding["provenance"], "target": semantic.target, "task_intent": semantic.intent}, tags=["research", "study", "provenance-preserved"], metadata={"source_project": semantic.target, "verification_status": "verified", "distilled": True})
            try:
                result = pipeline.run(candidate)
                decision = getattr(getattr(result, "final_decision", None), "value", getattr(result, "final_decision", None))
                stored_count = len(getattr(result, "items_stored_via_memory_coordinator", []) or [])
                if decision == "yes":
                    accepted += 1
                else:
                    rejected += 1
                stored += stored_count
                results.append(_jsonable(result))
            except Exception as exc:
                rejected += 1
                results.append({"error": str(exc)})
        status = "STORED" if stored else "REJECTED" if rejected else "NO_VERIFIED_CANDIDATES"
        return {"requested": True, "accepted": accepted, "rejected": rejected, "stored": stored, "status": status, "results": results}

    @staticmethod
    def _report(semantic: TaskRequestSemantic, findings: Sequence[Dict[str, Any]], learning: Dict[str, Any], raw: Dict[str, Any]) -> str:
        verified = [item for item in findings if item["verification_status"] == "verified"]
        lines = [f"I completed a bounded {('architecture study' if semantic.substantial_scope else 'research task')} for {semantic.target or semantic.query}.", "", f"Verified findings: {len(verified)} of {len(findings)}."]
        for item in verified[:6]:
            lines.append(f"- {item['finding']} ({item['usefulness']})")
        if semantic.learning_requested:
            lines.extend(["", f"Learning result: {learning.get('status')}; accepted {learning.get('accepted', 0)}, rejected {learning.get('rejected', 0)}, stored {learning.get('stored', 0)} reusable lesson(s)."])
            if not learning.get("stored"):
                lines.append("No durable lesson is claimed because the existing learning admission or storage path did not accept a verified candidate.")
        else:
            lines.append("Learning was not requested, so these findings were reported but not submitted for durable storage.")
        if raw.get("partial"):
            lines.append("The study was partial; inaccessible or failed sources are not treated as learned facts.")
        return "\n".join(lines)


__all__ = ["ResearchTaskIntent", "TaskRequestSemantic", "ResearchTaskSemanticAnalyzer", "ResearchTaskLearningOrchestrator"]
