"""
KnowledgeFirstResolver - Core component for knowledge-first routing.

Implements the knowledge-first resolution path per TARGET_ARCHITECTURE.md:
UnifiedRouter -> KnowledgeFirstResolver -> UnifiedRetrieval -> Intelligence answerability decision

Flow:
1. Query UnifiedRetrieval for relevant knowledge/experience
2. Use Intelligence to assess answerability from retrieved context
3. If Freya can answer -> return answer decision
4. If insufficient -> check CapabilityRouter for local capability
5. If capability exists -> route to CapabilityRouter
6. If no capability -> fallback to PriorityLLMProvider (LLM Stack)
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.memory.unified_retrieval import UnifiedRetrieval, RetrievalQuery, RetrievalResult
from app.intelligence.intelligence import Intelligence, AnswerabilityAssessment, ContextEvaluation, GoalContext
from app.capabilities.router import CapabilityRouter, NoCapabilityError
from app.core.llm_stack import LLMStack
from app.core.priority_llm import LLMPriority
from app.core.logger import logger
from app.intent import IntentType


@dataclass
class ResolutionResult:
    """Result of knowledge-first resolution."""
    action: str
    answer: Optional[str] = None
    confidence: float = 0.0
    sources: List[str] = field(default_factory=list)
    capability_name: Optional[str] = None
    capability_confidence: float = 0.0
    capability_result: Any = None
    llm_prompt: Optional[str] = None
    llm_priority: LLMPriority = LLMPriority.BACKGROUND
    llm_context: Dict[str, Any] = field(default_factory=dict)
    control_command: Optional[str] = None
    context_evaluation: Optional[ContextEvaluation] = None
    goal_context: Optional[GoalContext] = None
    answerability_assessment: Optional[AnswerabilityAssessment] = None
    reasoning: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "answer": self.answer,
            "confidence": self.confidence,
            "sources": self.sources,
            "capability_name": self.capability_name,
            "capability_confidence": self.capability_confidence,
            "llm_priority": self.llm_priority.name if self.llm_priority else None,
            "control_command": self.control_command,
            "reasoning": self.reasoning,
            "context_evaluation": self.context_evaluation.to_dict() if self.context_evaluation else None,
            "goal_context": self.goal_context.to_dict() if self.goal_context else None,
        }


class KnowledgeFirstResolver:
    """
    Resolves queries using Freya's internal knowledge first, then capabilities, then LLM fallback.

    This implements the "Can Freya Answer?" decision from TARGET_ARCHITECTURE.md Section 5.
    """

    def __init__(
        self,
        unified_retrieval: UnifiedRetrieval,
        intelligence: Intelligence,
        capability_router: CapabilityRouter,
        llm_stack: LLMStack,
    ):
        self._unified_retrieval = unified_retrieval
        self._intelligence = intelligence
        self._capability_router = capability_router
        self._llm_stack = llm_stack

        logger.info("[KnowledgeFirstResolver] Initialized with knowledge-first routing")

    def resolve(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        intent_type: Optional[IntentType] = None,
    ) -> ResolutionResult:
        reasoning = [f"Resolving query: '{query[:100]}...'"]

        # Step 1: Retrieve knowledge from Freya's memory systems
        reasoning.append("Step 1: Retrieving from UnifiedRetrieval...")
        retrieval_query = RetrievalQuery(
            query=query,
            context=context or {},
            max_results=20,
            min_score=0.1,
        )
        retrieved_results = self._unified_retrieval.retrieve(retrieval_query)
        reasoning.append(f"  Retrieved {len(retrieved_results)} results")

        # Step 2: Assess answerability using Intelligence
        reasoning.append("Step 2: Assessing answerability with Intelligence...")
        answerability = self._intelligence.assess_answerability(query, context)
        reasoning.extend(answerability.reasoning)

        # Step 3: Check if Freya can answer directly
        if answerability.can_answer:
            reasoning.append("DECISION: Freya CAN answer from internal knowledge")
            answer = self._format_answer_from_results(query, answerability.context_evaluation.retrieved_results)
            return ResolutionResult(
                action="answer",
                answer=answer,
                confidence=answerability.confidence,
                sources=list(answerability.context_evaluation.source_coverage.keys()),
                context_evaluation=answerability.context_evaluation,
                goal_context=answerability.goal_context,
                answerability_assessment=answerability,
                reasoning=reasoning,
            )

        # Step 4: Check if a local capability can handle this
        reasoning.append("Step 3: Knowledge insufficient - checking CapabilityRouter...")
        if intent_type is not None:
            intent_str = intent_type.value
        else:
            intent_str = answerability.recommended_action

        capability_matches = self._capability_router.find_matching(query, intent_str)

        if capability_matches:
            best_name, best_conf = capability_matches[0]
            reasoning.append(f"  Found matching capability: {best_name} (confidence: {best_conf:.2f})")
            try:
                cap_result = self._capability_router.route(query, intent_str, **context)
                if cap_result.success:
                    reasoning.append(f"  Capability executed successfully: {cap_result.message[:100] if cap_result.message else 'OK'}")
                    return ResolutionResult(
                        action="capability",
                        capability_name=best_name,
                        capability_confidence=best_conf,
                        capability_result=cap_result,
                        context_evaluation=answerability.context_evaluation,
                        goal_context=answerability.goal_context,
                        answerability_assessment=answerability,
                        reasoning=reasoning,
                    )
                else:
                    reasoning.append(f"  Capability execution failed: {cap_result.message}")
            except NoCapabilityError:
                reasoning.append("  NoCapabilityError raised during execution (should not happen after find_matching)")

        # Step 5: No capability - fallback to LLM
        reasoning.append("Step 4: No local capability available - preparing LLM fallback...")
        llm_decision = self._intelligence.decide_next_action(query, context)
        llm_priority = self._determine_llm_priority(intent_type)
        llm_context = llm_decision.get("context_for_llm", {})
        llm_prompt = self._build_llm_prompt(query, answerability, llm_context)
        reasoning.append(f"  LLM fallback prepared with priority: {llm_priority.name}")
        return ResolutionResult(
            action="llm_fallback",
            llm_prompt=llm_prompt,
            llm_priority=llm_priority,
            llm_context=llm_context,
            context_evaluation=answerability.context_evaluation,
            goal_context=answerability.goal_context,
            answerability_assessment=answerability,
            reasoning=reasoning,
        )

    def _format_answer_from_results(self, query: str, results: List[RetrievalResult]) -> str:
        if not results:
            return "I don't have specific information about that in my memory."
        by_source = {}
        for r in results[:10]:
            by_source.setdefault(r.source, []).append(r)
        parts = []
        if "working" in by_source:
            for r in by_source["working"][:3]:
                parts.append(r.content)
        if "conversation" in by_source:
            for r in by_source["conversation"][:3]:
                parts.append(r.content)
        if "project" in by_source:
            for r in by_source["project"][:2]:
                parts.append(r.content)
        if "experience" in by_source:
            for r in by_source["experience"][:2]:
                parts.append(r.content)
        if "lessons" in by_source:
            for r in by_source["lessons"][:2]:
                parts.append(r.content)
        if "goals" in by_source:
            for r in by_source["goals"][:2]:
                parts.append(r.content)
        for source, src_results in by_source.items():
            if source not in ["working", "conversation", "project", "experience", "lessons", "goals"]:
                for r in src_results[:2]:
                    parts.append(r.content)
        if not parts:
            return "I found some related information but couldn't form a complete answer."
        return "\n\n".join(parts)

    def _determine_llm_priority(self, intent_type: Optional[IntentType]) -> LLMPriority:
        if intent_type == IntentType.CONVERSATIONAL_CONTROL:
            return LLMPriority.CHAT
        elif intent_type == IntentType.CHAT:
            return LLMPriority.CHAT
        elif intent_type == IntentType.QUESTION:
            return LLMPriority.CHAT
        elif intent_type == IntentType.SYSTEM_STATUS:
            return LLMPriority.CHAT
        else:
            return LLMPriority.AUTONOMY_THINK

    def _build_llm_prompt(
        self,
        query: str,
        answerability: AnswerabilityAssessment,
        llm_context: Dict[str, Any]
    ) -> str:
        context_parts = []
        if answerability.context_evaluation and answerability.context_evaluation.retrieved_results:
            context_parts.append("=== Relevant Knowledge from Freya's Memory ===")
            for r in answerability.context_evaluation.retrieved_results[:8]:
                context_parts.append(f"[{r.source}] {r.content[:500]}")
            context_parts.append("")
        if answerability.goal_context and answerability.goal_context.has_active_goal:
            context_parts.append("=== Active Goal ===")
            goal = answerability.goal_context.active_goal
            context_parts.append(f"Goal: {goal.get('name', 'Unknown')}")
            context_parts.append(f"Description: {goal.get('description', 'N/A')}")
            context_parts.append(f"Progress: {answerability.goal_context.progress_percentage:.1f}%")
            context_parts.append("")
        if "recent_conversation" in llm_context:
            context_parts.append("=== Recent Conversation ===")
            for turn in llm_context["recent_conversation"][-3:]:
                context_parts.append(f"{turn['role']}: {turn['content']}")
            context_parts.append("")
        context_str = "\n".join(context_parts)
        prompt = f"""{context_str}
User Query: {query}

Based on the above context from Freya's internal knowledge systems, provide a helpful answer.
If the context is insufficient, acknowledge the limitation and provide your best general response.
"""
        return prompt


def create_knowledge_first_resolver(
    unified_retrieval: UnifiedRetrieval,
    intelligence: Intelligence,
    capability_router: CapabilityRouter,
    llm_stack: LLMStack,
) -> KnowledgeFirstResolver:
    """Factory function to create KnowledgeFirstResolver."""
    return KnowledgeFirstResolver(
        unified_retrieval=unified_retrieval,
        intelligence=intelligence,
        capability_router=capability_router,
        llm_stack=llm_stack,
    )
