"""Freya Intelligence Module.

Implements the core intelligence components per TARGET_ARCHITECTURE.md:
# G1: Reasoning + Decision Logic
# G2: Confidence / Answerability (evaluate if knowledge is sufficient)
# G3: Context + Goal Awareness

This module does NOT call LLMs directly and does NOT implement routing.
It provides clean APIs for evaluating available context, goal context,
and answerability based on retrieved Freya knowledge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.memory.unified_retrieval import UnifiedRetrieval, RetrievalQuery, RetrievalResult
from app.memory.goals.manager import GoalStorage
from app.memory.conversation_memory import ConversationMemory


@dataclass
class ContextEvaluation:
    """Evaluation of available context for a given query."""
    query: str
    retrieved_results: List[RetrievalResult] = field(default_factory=list)
    total_score: float = 0.0
    source_coverage: Dict[str, int] = field(default_factory=dict)
    has_conversation_context: bool = False
    has_working_memory: bool = False
    has_project_knowledge: bool = False
    has_experience: bool = False
    has_lessons: bool = False
    has_goal_context: bool = False
    is_sufficient: bool = False
    confidence: float = 0.0
    reasoning: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "retrieved_count": len(self.retrieved_results),
            "total_score": self.total_score,
            "source_coverage": self.source_coverage,
            "has_conversation_context": self.has_conversation_context,
            "has_working_memory": self.has_working_memory,
            "has_project_knowledge": self.has_project_knowledge,
            "has_experience": self.has_experience,
            "has_lessons": self.has_lessons,
            "has_goal_context": self.has_goal_context,
            "is_sufficient": self.is_sufficient,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
        }


@dataclass
class GoalContext:
    """Current goal context from the goal system."""
    active_goal: Optional[Dict[str, Any]] = None
    queued_goals: List[Dict[str, Any]] = field(default_factory=list)
    is_blocked: bool = False
    progress_percentage: float = 0.0
    has_active_goal: bool = False
    reasoning: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "has_active_goal": self.has_active_goal,
            "active_goal": self.active_goal,
            "queued_goals": self.queued_goals,
            "is_blocked": self.is_blocked,
            "progress_percentage": self.progress_percentage,
            "reasoning": self.reasoning,
        }


@dataclass
class AnswerabilityAssessment:
    """Assessment of whether Freya can answer the query from internal knowledge."""
    query: str
    can_answer: bool = False
    confidence: float = 0.0
    context_evaluation: Optional[ContextEvaluation] = None
    goal_context: Optional[GoalContext] = None
    missing_information: List[str] = field(default_factory=list)
    recommended_action: str = "insufficient_knowledge"
    needs_external_information: bool = False
    requires_fresh_information: bool = False
    explicit_research_request: bool = False
    local_knowledge_sufficient: bool = False
    research_reason: Optional[str] = None
    reasoning: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "can_answer": self.can_answer,
            "confidence": self.confidence,
            "recommended_action": self.recommended_action,
            "needs_external_information": self.needs_external_information,
            "requires_fresh_information": self.requires_fresh_information,
            "explicit_research_request": self.explicit_research_request,
            "local_knowledge_sufficient": self.local_knowledge_sufficient,
            "research_reason": self.research_reason,
            "missing_information": self.missing_information,
            "reasoning": self.reasoning,
            "context_evaluation": self.context_evaluation.to_dict() if self.context_evaluation else None,
            "goal_context": self.goal_context.to_dict() if self.goal_context else None,
        }


class Intelligence:
    """Freya Intelligence core - evaluates context, goals, and answerability."""

    MIN_CONFIDENCE_THRESHOLD = 0.4
    MIN_SCORE_FOR_ANSWER = 2.0
    GOOD_SCORE_THRESHOLD = 5.0
    EXCELLENT_SCORE_THRESHOLD = 10.0
    MIN_SOURCE_COVERAGE = 2

    def __init__(self, unified_retrieval: UnifiedRetrieval, goal_storage: GoalStorage, conversation_memory: ConversationMemory):
        self._unified_retrieval = unified_retrieval
        self._goal_storage = goal_storage
        self._conversation_memory = conversation_memory

    def evaluate_context(self, query: str, context: Optional[Dict[str, Any]] = None) -> ContextEvaluation:
        retrieval_query = RetrievalQuery(query=query, context=context or {}, max_results=20, min_score=0.1)
        results = self._unified_retrieval.retrieve(retrieval_query)

        source_coverage = {}
        for r in results:
            source_coverage[r.source] = source_coverage.get(r.source, 0) + 1

        total_score = sum(r.score for r in results)

        has_conversation = "conversation" in source_coverage
        has_working = "working" in source_coverage
        has_project = "project" in source_coverage
        has_experience = "experience" in source_coverage
        has_lessons = "lessons" in source_coverage
        has_goals = "goals" in source_coverage

        conversation_turns = self._conversation_memory.get_history(limit=10)
        has_conversation_context = len(conversation_turns) > 0

        reasoning = []
        reasoning.append("Retrieved {} results from {} memory sources".format(len(results), len(source_coverage)))
        reasoning.append("Total relevance score: {:.2f}".format(total_score))
        source_str = ", ".join("{} ({})".format(k, v) for k, v in source_coverage.items()) or "none"
        reasoning.append("Sources: {}".format(source_str))

        is_sufficient = self._is_context_sufficient(total_score, len(source_coverage), has_conversation_context, has_working, has_project)
        confidence = self._calculate_context_confidence(total_score, len(source_coverage), has_conversation_context, has_working)

        if is_sufficient:
            reasoning.append("Context evaluated as SUFFICIENT for reasoning")
        else:
            reasoning.append("Context evaluated as INSUFFICIENT - may need external knowledge")

        return ContextEvaluation(query=query, retrieved_results=results, total_score=total_score, source_coverage=source_coverage, has_conversation_context=has_conversation_context, has_working_memory=has_working, has_project_knowledge=has_project, has_experience=has_experience, has_lessons=has_lessons, has_goal_context=has_goals, is_sufficient=is_sufficient, confidence=confidence, reasoning=reasoning)

    def get_goal_context(self) -> GoalContext:
        reasoning = []
        active_goal_data = self._goal_storage.get_active_goal_context()

        if active_goal_data:
            reasoning.append("Active goal: {} (progress: {:.1f}%)".format(active_goal_data.get("name"), active_goal_data.get("progress", {}).get("percentage", 0)))
            queued = self._goal_storage.get_next_eligible_goals(limit=5)
            queued_goals = [{"goal_id": g["goal_id"], "name": g["name"], "description": g["description"], "priority": g["priority"], "is_blocked": g["is_blocked"]} for g in queued]
            reasoning.append("Queued goals: {}".format(len(queued_goals)))
            is_blocked = active_goal_data.get("is_blocked", False)
            if is_blocked:
                reasoning.append("Active goal is BLOCKED: {}".format(active_goal_data.get("blocking_reasons", [])))
            return GoalContext(active_goal=active_goal_data, queued_goals=queued_goals, is_blocked=is_blocked, progress_percentage=active_goal_data.get("progress", {}).get("percentage", 0), has_active_goal=True, reasoning=reasoning)
        else:
            reasoning.append("No active goal set")
            return GoalContext(has_active_goal=False, reasoning=reasoning)

    def assess_answerability(self, query: str, context: Optional[Dict[str, Any]] = None) -> AnswerabilityAssessment:
        reasoning = []
        context_eval = self.evaluate_context(query, context)
        reasoning.extend(context_eval.reasoning)
        goal_ctx = self.get_goal_context()
        reasoning.extend(goal_ctx.reasoning)

        can_answer = False
        confidence = 0.0
        missing_info = []
        recommended_action = "insufficient_knowledge"

        factors = {"has_high_relevance_results": context_eval.total_score >= self.GOOD_SCORE_THRESHOLD, "has_multiple_sources": len(context_eval.source_coverage) >= self.MIN_SOURCE_COVERAGE, "has_conversation_context": context_eval.has_conversation_context, "has_working_memory": context_eval.has_working_memory, "has_project_knowledge": context_eval.has_project_knowledge, "has_experience": context_eval.has_experience, "has_lessons": context_eval.has_lessons, "has_active_goal": goal_ctx.has_active_goal}
        score = sum(1 for v in factors.values() if v)
        reasoning.append("Answerability factors met: {}/{}".format(score, len(factors)))

        if context_eval.total_score >= self.EXCELLENT_SCORE_THRESHOLD:
            confidence = 0.9
        elif context_eval.total_score >= self.GOOD_SCORE_THRESHOLD:
            confidence = 0.7
        elif context_eval.total_score >= self.MIN_SCORE_FOR_ANSWER:
            confidence = 0.5
        else:
            confidence = 0.3

        if len(context_eval.source_coverage) >= 3:
            confidence = min(confidence + 0.1, 1.0)

        if not context_eval.has_conversation_context:
            confidence *= 0.8

        if confidence >= self.MIN_CONFIDENCE_THRESHOLD and context_eval.is_sufficient:
            can_answer = True
            recommended_action = "answer"
            reasoning.append("ASSESSMENT: Can answer from internal knowledge")
        elif context_eval.total_score >= self.MIN_SCORE_FOR_ANSWER:
            recommended_action = "use_capability"
            missing_info.append("Specific procedural knowledge or tools needed")
            reasoning.append("ASSESSMENT: Partial knowledge - capabilities may help")
        elif len(context_eval.source_coverage) > 0:
            recommended_action = "use_llm"
            missing_info.append("Insufficient relevant knowledge in memory")
            reasoning.append("ASSESSMENT: Some knowledge but insufficient - LLM fallback recommended")
        else:
            recommended_action = "use_llm"
            missing_info.append("No relevant knowledge found in any memory system")
            reasoning.append("ASSESSMENT: No relevant knowledge - LLM fallback required")

        research_metadata = self._assess_external_information_requirements(
            query,
            local_knowledge_sufficient=can_answer,
            context=context,
        )
        reasoning.extend(research_metadata["reasoning"])
        return AnswerabilityAssessment(
            query=query,
            can_answer=can_answer,
            confidence=confidence,
            context_evaluation=context_eval,
            goal_context=goal_ctx,
            missing_information=missing_info,
            recommended_action=recommended_action,
            needs_external_information=research_metadata["needs_external_information"],
            requires_fresh_information=research_metadata["requires_fresh_information"],
            explicit_research_request=research_metadata["explicit_research_request"],
            local_knowledge_sufficient=can_answer,
            research_reason=research_metadata["research_reason"],
            reasoning=reasoning,
        )

    def _assess_external_information_requirements(
        self,
        query: str,
        *,
        local_knowledge_sufficient: bool,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Determine whether a conversational lookup needs canonical web research.

        Freshness and explicit user direction are strong signals, but the final
        decision also incorporates answerability and whether the message is an
        information-seeking request.  This keeps stable explanations local while
        allowing unknown entity and relationship questions to use research.
        """
        import re

        normalized = " ".join(query.lower().strip().split())
        request_context = context or {}
        explicit_patterns = (
            r"\bresearch\b",
            r"\bsearch(?:\s+the\s+web)?\b",
            r"\blook\s+(?:this\s+)?up\b",
            r"\bverify\b",
            r"\bfact[ -]?check\b",
            r"\bcompare\s+(?:current\s+)?sources\b",
            r"\bfind\s+(?:information|recent|current)\b",
        )
        fresh_patterns = (
            r"\b(?:latest|newest|current|currently|today|recent|recently|news)\b",
            r"\b(?:price|cost|market|trading)\b",
            r"\bweather\b",
            r"\b(?:score|result|schedule|release|update|updated|benchmark|specification|specs|generation|availability|version)\b",
            r"\b(?:last night|this week|this month|this year)\b",
            r"\b(?:vs\.?|versus|compare|comparison)\b",
        )
        explicit_research_request = any(re.search(pattern, normalized) for pattern in explicit_patterns)
        requires_fresh_information = any(re.search(pattern, normalized) for pattern in fresh_patterns)

        information_prefix = re.match(
            r"^(?:what|who|when|where|which|why|how|tell me|find information|can you tell me)\b",
            normalized,
        )
        intent_type = str(request_context.get("intent_type", "")).lower()
        is_information_request = bool(information_prefix or "?" in query)
        if re.search(r"\b(?:vs\.?|versus|compare|comparison|price|cost|benchmark|specs?|specification|release|availability|version|generation)\b", normalized):
            is_information_request = True
        if intent_type in {"question", "chat"} and not is_information_request:
            is_information_request = normalized.startswith(("find ", "verify ", "research ", "search ", "look up "))

        named_entity_shape = bool(
            re.search(r"\b[A-Z][A-Za-z0-9]*(?:[A-Z][A-Za-z0-9]*)+\b", query)
            or re.search(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b", query)
        )
        relationship_lookup = bool(re.match(r"^(?:who|when|where)\b", normalized)) or any(
            phrase in normalized
            for phrase in ("ceo", "founder", "headquarters", "president", "owner")
        )
        stable_explanation = bool(
            re.match(r"^(?:what is|explain|define|how does|how do|why does|why is)\b", normalized)
        ) and not (named_entity_shape or relationship_lookup or requires_fresh_information)
        external_lookup_can_help = (
            is_information_request
            and not stable_explanation
            and (relationship_lookup or named_entity_shape)
        )

        reasoning: List[str] = []
        if explicit_research_request:
            reasoning.append("Research routing: explicit external research request")
            research_reason = "explicit external research request"
        elif requires_fresh_information:
            reasoning.append("Research routing: query requires fresh or time-sensitive information")
            research_reason = "fresh or time-sensitive information requested"
        elif not local_knowledge_sufficient and external_lookup_can_help:
            reasoning.append("Research routing: local knowledge is insufficient for an entity or relationship lookup")
            research_reason = "local knowledge is insufficient for an external lookup"
        else:
            research_reason = None
            if local_knowledge_sufficient:
                reasoning.append("Research routing: local knowledge is sufficient")
            elif stable_explanation:
                reasoning.append("Research routing: stable explanatory question remains on the local fallback path")
            else:
                reasoning.append("Research routing: no external-information requirement identified")

        return {
            "needs_external_information": bool(
                explicit_research_request
                or requires_fresh_information
                or (not local_knowledge_sufficient and external_lookup_can_help)
            ),
            "requires_fresh_information": requires_fresh_information,
            "explicit_research_request": explicit_research_request,
            "research_reason": research_reason,
            "reasoning": reasoning,
        }

    def decide_next_action(self, query: str, context: Optional[Dict[str, Any]] = None):
        assessment = self.assess_answerability(query, context)
        decision = {"query": query, "recommended_action": assessment.recommended_action, "confidence": assessment.confidence, "can_answer_directly": assessment.can_answer, "context_sufficient": assessment.context_evaluation.is_sufficient if assessment.context_evaluation else False, "goal_context": assessment.goal_context.to_dict() if assessment.goal_context else {}, "missing_information": assessment.missing_information, "needs_external_information": assessment.needs_external_information, "requires_fresh_information": assessment.requires_fresh_information, "explicit_research_request": assessment.explicit_research_request, "local_knowledge_sufficient": assessment.local_knowledge_sufficient, "research_reason": assessment.research_reason, "reasoning": assessment.reasoning, "timestamp": datetime.now(timezone.utc).isoformat()}
        if assessment.recommended_action == "answer":
            decision["answer_source"] = "internal_knowledge"
            decision["knowledge_sources"] = list(assessment.context_evaluation.source_coverage.keys()) if assessment.context_evaluation else []
        elif assessment.recommended_action == "use_capability":
            decision["answer_source"] = "capability_system"
            decision["knowledge_sources"] = list(assessment.context_evaluation.source_coverage.keys()) if assessment.context_evaluation else []
            decision["required_capabilities"] = self._infer_required_capabilities(query, assessment.context_evaluation)
        elif assessment.recommended_action == "use_llm":
            decision["answer_source"] = "llm_fallback"
            decision["knowledge_sources"] = list(assessment.context_evaluation.source_coverage.keys()) if assessment.context_evaluation else []
            decision["context_for_llm"] = self._prepare_llm_context(assessment)
        return decision

    def _is_context_sufficient(self, total_score: float, source_count: int, has_conversation: bool, has_working: bool, has_project: bool) -> bool:
        if total_score >= self.GOOD_SCORE_THRESHOLD and source_count >= 2:
            return True
        if total_score >= self.MIN_SCORE_FOR_ANSWER and source_count >= 3:
            return True
        if has_working and total_score >= self.MIN_SCORE_FOR_ANSWER * 0.5:
            return True
        return False

    def _calculate_context_confidence(self, total_score: float, source_count: int, has_conversation: bool, has_working: bool) -> float:
        base_confidence = 0.0
        base_confidence += min(total_score / 20.0, 0.5)
        base_confidence += min(source_count * 0.075, 0.3)
        if has_conversation:
            base_confidence += 0.1
        if has_working:
            base_confidence += 0.1
        return min(base_confidence, 1.0)

    def _infer_required_capabilities(self, query: str, context_eval):
        capabilities = []
        query_lower = query.lower()
        if any(kw in query_lower for kw in ["file", "read", "write", "edit", "create", "delete", "list", "find"]):
            capabilities.append("file_operations")
        if any(kw in query_lower for kw in ["code", "function", "class", "refactor", "debug", "implement", "test"]):
            capabilities.append("code_operations")
        if any(kw in query_lower for kw in ["git", "commit", "branch", "merge", "push", "pull", "diff"]):
            capabilities.append("git_operations")
        if any(kw in query_lower for kw in ["search", "find", "research", "investigate", "lookup"]):
            capabilities.append("search")
        if any(kw in query_lower for kw in ["project", "build", "run", "test", "deploy", "configure"]):
            capabilities.append("project_operations")
        return list(set(capabilities))

    def _prepare_llm_context(self, assessment):
        context = {}
        if assessment.context_evaluation:
            top_results = assessment.context_evaluation.retrieved_results[:10]
            context["retrieved_knowledge"] = [{"source": r.source, "content": r.content[:500], "score": r.score} for r in top_results]
            context["memory_sources"] = list(assessment.context_evaluation.source_coverage.keys())
        if assessment.goal_context and assessment.goal_context.has_active_goal:
            context["active_goal"] = {"name": assessment.goal_context.active_goal.get("name"), "description": assessment.goal_context.active_goal.get("description"), "progress": assessment.goal_context.progress_percentage}
        recent = self._conversation_memory.get_history(limit=5)
        context["recent_conversation"] = [{"role": t.role, "content": t.content[:300]} for t in recent]
        return context


def create_intelligence(unified_retrieval, goal_storage, conversation_memory):
    return Intelligence(unified_retrieval=unified_retrieval, goal_storage=goal_storage, conversation_memory=conversation_memory)
