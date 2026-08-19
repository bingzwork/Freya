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
import re
from typing import Any, Dict, List, Optional

from app.memory.unified_retrieval import UnifiedRetrieval, RetrievalQuery, RetrievalResult
from app.intelligence.intelligence import Intelligence, AnswerabilityAssessment, ContextEvaluation, GoalContext
from app.capabilities.router import CapabilityResult, CapabilityRouter, NoCapabilityError
from app.core.llm_stack import LLMStack
from app.core.priority_llm import LLMPriority
from app.core.logger import logger
from app.intent import IntentType
from app.research.intelligence import RequestSemanticAnalyzer


def _classify_conversational_request(query: str) -> Optional[str]:
    """Return a narrow conversational category before knowledge/research routing.

    This is intentionally phrase- and token-based rather than a broad keyword
    list. Explicit freshness or research language always bypasses the gate.
    """
    normalized = " ".join(str(query or "").lower().strip().split())
    if not normalized:
        return None
    if re.search(r"\b(?:search|research|browse|verify|fact[ -]?check|latest|newest|current|currently|today|recent|recently|find\s+(?:sources|recent|current)|look\s+(?:this\s+)?up)\b", normalized):
        return None
    # Preserve the dedicated self-knowledge route before the broader
    # stable-explanation matcher below.
    if re.fullmatch(r"(?:what(?:'s| is) your name|who are you|are you freya)[!.? ]*", normalized):
        return "identity"
    # Stable explanatory questions should use the local chat/LLM path rather
    # than entering task planning or external research. Explicit task verbs
    # remain outside this gate so requests such as "what is ... and build ..."
    # still reach the normal planner/capability flow.
    if (
        re.fullmatch(
            r"(?:what\s+is|what\s+are|who\s+is|who\s+was|why\s+is|how\s+does|how\s+do)\s+[^?!.]{1,160}[?!.]*",
            normalized,
        )
        and not re.search(
            r"\b(?:can\s+you|please|write|build|make|implement|fix|debug|install|run|create|compare|design)\b",
            normalized,
        )
    ):
        return "stable_explanation"
    if re.fullmatch(r"(?:what(?:'s| is) your name|who are you|are you freya|tell me about yourself)[?.!] *", normalized):
        return "identity"
    if re.fullmatch(r"(?:what can you do|what are your capabilities|what capabilities do you have|can you help me)[?.!] *", normalized):
        return "capabilities"
    if re.fullmatch(r"(?:hello|hi|hey|good morning|good afternoon|good evening)[!.? ]*", normalized):
        return "greeting"
    if re.fullmatch(r"(?:how are you(?: doing)?|are you okay|what(?:'s| is) up)[?.! ]*", normalized):
        return "social"
    if re.fullmatch(r"(?:thank you|thanks|you're welcome|you are welcome|goodbye|bye)[!.? ]*", normalized):
        return "courtesy"
    return None


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
    routing_metadata: Dict[str, Any] = field(default_factory=dict)
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
            "routing_metadata": self.routing_metadata,
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

        conversational_intent = _classify_conversational_request(query)
        if conversational_intent:
            reasoning.append(f"Conversational gate matched: {conversational_intent}")
            if conversational_intent in {"identity", "capabilities"}:
                target = "show_identity" if conversational_intent == "identity" else "show_capabilities"
                try:
                    result = self._capability_router.execute_named(target, query, **dict(context or {}))
                    return ResolutionResult(
                        action="capability",
                        capability_name=target,
                        capability_confidence=1.0,
                        capability_result=result,
                        routing_metadata={"conversational_intent": conversational_intent, "suppress_research": True, "authoritative_internal": True},
                        reasoning=reasoning,
                    )
                except NoCapabilityError as error:
                    reasoning.append(f"Local conversational capability unavailable: {error}")
            if conversational_intent == "stable_explanation":
                local_results = self._unified_retrieval.retrieve(
                    RetrievalQuery(query=query, context=context or {}, max_results=10, min_score=0.2)
                )
                learned_results = [
                    result for result in local_results
                    if result.source in {"lessons", "semantic", "experience", "knowledge"}
                ]
                if learned_results:
                    reasoning.append("Local learned knowledge hit; model fallback suppressed")
                    return ResolutionResult(
                        action="answer",
                        answer=self._format_answer_from_results(query, learned_results),
                        confidence=max(result.score for result in learned_results),
                        sources=list(dict.fromkeys(result.source for result in learned_results)),
                        routing_metadata={
                            "conversational_intent": conversational_intent,
                            "suppress_research": True,
                            "local_knowledge_reuse": True,
                            "model_fallback_suppressed": True,
                        },
                        reasoning=reasoning,
                    )
            return ResolutionResult(

                action="llm_fallback",
                llm_prompt=query,
                llm_priority=LLMPriority.CHAT,
                llm_context={"conversational_intent": conversational_intent, "suppress_research": True, "allow_ungrounded_fallback": True},
                routing_metadata={"conversational_intent": conversational_intent, "suppress_research": True},
                reasoning=reasoning,
            )

        direct_matches = self._capability_router.find_matching(query, intent_type.value if intent_type is not None else None)
        explicit_matches = [
            item for item in direct_matches
            if item[1] >= 0.95
        ]
        authoritative_names = {
            "show_identity",
            "show_capabilities",
            "capability_introspection",
        }
        authoritative_matches = list(dict.fromkeys(
            [item for item in direct_matches if item[0] in authoritative_names]
            + explicit_matches
        ))
        if authoritative_matches:
            name, confidence = authoritative_matches[0]
            result = self._capability_router.execute_named(name, query, **dict(context or {}))
            return ResolutionResult(action="capability", capability_name=name, capability_confidence=confidence, capability_result=result, routing_metadata={"authoritative_internal": True, "authoritative_source": "CapabilityRegistry"})

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

        routing_metadata = self._research_routing_metadata(answerability)
        intent_str = intent_type.value if intent_type is not None else answerability.recommended_action
        capability_matches = self._capability_router.find_matching(query, intent_str)
        local_capability_matches = [match for match in capability_matches if match[0] != "research_capability"]

        # Step 3: Fresh, explicit, or insufficient external lookups use the
        # existing registered ResearchCapability before a local answer or LLM
        # fallback can produce stale or unsupported information.
        if routing_metadata["needs_external_information"] and not local_capability_matches:
            reasoning.append(
                "DECISION: External research required "
                f"({routing_metadata['research_reason'] or 'knowledge requirement'})"
            )
            return self._route_to_research_capability(
                query=query,
                context=context,
                answerability=answerability,
                routing_metadata=routing_metadata,
                reasoning=reasoning,
            )

        # Step 4: Check if Freya can answer directly
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
                routing_metadata=routing_metadata,
                reasoning=reasoning,
            )

        # Step 5: Check if a local capability can handle this
        reasoning.append("Step 4: Knowledge insufficient - checking CapabilityRouter...")
        if local_capability_matches:
            capability_matches = local_capability_matches

        if capability_matches:
            best_name, best_conf = capability_matches[0]
            reasoning.append(f"  Found matching capability: {best_name} (confidence: {best_conf:.2f})")
            try:
                capability_context = dict(context or {})
                capability_context.pop("intent_type", None)
                cap_result = self._capability_router.route(query, intent_str, **capability_context)
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
                        routing_metadata=routing_metadata,
                        reasoning=reasoning,
                    )
                else:
                    reasoning.append(f"  Capability execution failed: {cap_result.message}")
            except NoCapabilityError:
                reasoning.append("  NoCapabilityError raised during execution (should not happen after find_matching)")

        # Step 6: No capability - fallback to LLM
        reasoning.append("Step 5: No local capability available - preparing LLM fallback...")
        llm_decision = self._intelligence.decide_next_action(query, context)
        llm_priority = self._determine_llm_priority(intent_type)
        llm_context = dict(llm_decision.get("context_for_llm", {}) or {})
        # Preserve the evidence already retrieved by the target knowledge-first
        # path for AnswerVerifier; no new routing component is introduced.
        evidence_results = answerability.context_evaluation.retrieved_results if answerability.context_evaluation else retrieved_results
        llm_context["retrieved_results"] = [
            result.to_dict() if hasattr(result, "to_dict") else {
                "content": getattr(result, "content", str(result)),
                "source": getattr(result, "source", "unknown"),
                "source_id": getattr(result, "source_id", "unknown"),
                "score": getattr(result, "score", 0.0),
            }
            for result in evidence_results
        ]
        llm_context["knowledge_first"] = True
        llm_context["knowledge_sufficient"] = False
        llm_context["allow_ungrounded_fallback"] = not (
            bool(getattr(answerability, "requires_fresh_information", False))
            or bool(getattr(answerability, "explicit_research_request", False))
        )
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
            routing_metadata=routing_metadata,
            reasoning=reasoning,
        )

    def _research_routing_metadata(self, answerability: AnswerabilityAssessment) -> Dict[str, Any]:
        """Normalize answerability research signals for routing and observability."""
        return {
            "needs_external_information": bool(
                getattr(answerability, "needs_external_information", False)
            ),
            "requires_fresh_information": bool(
                getattr(answerability, "requires_fresh_information", False)
            ),
            "explicit_research_request": bool(
                getattr(answerability, "explicit_research_request", False)
            ),
            "local_knowledge_sufficient": bool(
                getattr(answerability, "local_knowledge_sufficient", answerability.can_answer)
            ),
            "research_reason": getattr(answerability, "research_reason", None),
        }

    def _route_to_research_capability(
        self,
        *,
        query: str,
        context: Optional[Dict[str, Any]],
        answerability: AnswerabilityAssessment,
        routing_metadata: Dict[str, Any],
        reasoning: List[str],
    ) -> ResolutionResult:
        """Invoke the one registered research capability through CapabilityRouter."""
        research_context = dict(context or {})
        semantic = RequestSemanticAnalyzer.analyze(query, context=research_context)
        research_mode = semantic.execution_mode
        research_context.update(
            {
                "capability_action": self._research_action_for(query, routing_metadata),
                "mode": research_mode,
                "topic": query,
                "claim": self._claim_from_query(query),
                "semantic": semantic.to_dict(),
                "intent": semantic.intent,
                "routing_metadata": routing_metadata,
            }
        )

        try:
            result = self._capability_router.execute_named(
                "research_capability",
                query,
                **research_context,
            )
            if result.success:
                reasoning.append("ResearchCapability completed through CapabilityRouter")
            else:
                reasoning.append("ResearchCapability returned a safe failure; local fallback is not fabricated")
        except NoCapabilityError as error:
            result = CapabilityResult(
                success=False,
                message="Current research is unavailable, so I could not verify that information.",
                capability_name="research_capability",
            )
            reasoning.append(f"ResearchCapability is not registered: {error}")

        return ResolutionResult(
            action="capability",
            capability_name="research_capability",
            capability_confidence=1.0,
            capability_result=result,
            context_evaluation=answerability.context_evaluation,
            goal_context=answerability.goal_context,
            answerability_assessment=answerability,
            routing_metadata=routing_metadata,
            reasoning=reasoning,
        )

    @staticmethod
    def _research_mode_for(query: str, routing_metadata: Dict[str, Any]) -> str:
        import re

        value = str(query or "").lower()
        explicit_image = re.search(r"\b(?:show|give\s+me|fetch|send)\b.{0,50}\b(?:photo(?:s)?|picture(?:s)?|image(?:s)?)\b", value) or re.search(r"\bfind\b.{0,60}\b(?:photo(?:s)?|picture(?:s)?|image(?:s)?)\s+of\b", value) or re.search(r"\b(?:photo(?:s)?|picture(?:s)?|image(?:s)?)\s+of\b", value) or re.search(r"\bwhat does .* look like\b", value)
        if explicit_image and not re.search(r"\bphoto\s+printer\b", value):
            return "IMAGE_SEARCH"
        if re.search(r"\b(?:deeply|in depth|deep research|investigate|thoroughly|multi[- ]source|comprehensively)\b", value):
            return "DEEP_RESEARCH"
        return "FAST_SEARCH"

    @staticmethod
    def _research_action_for(query: str, routing_metadata: Dict[str, Any]) -> str:

        query_lower = query.lower()
        if routing_metadata.get("explicit_research_request") and any(
            phrase in query_lower for phrase in ("verify", "fact check", "fact-check")
        ):
            return "verify_claim"
        return "research_topic"

    @staticmethod
    def _claim_from_query(query: str) -> str:
        """Remove a leading verification directive while preserving the user claim."""
        import re

        claim = re.sub(r"^\s*(?:please\s+)?(?:verify|fact[ -]?check)\s+(?:whether\s+)?", "", query, flags=re.IGNORECASE)
        return claim.strip() or query.strip()

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
        if llm_context.get("allow_ungrounded_fallback"):
            evidence_instruction = (
                "Use the supplied context when relevant. For ordinary questions, answer directly "
                "from your general knowledge when the context is insufficient. Do not present "
                "time-sensitive claims as current unless supported by fresh research."
            )
        else:
            evidence_instruction = (
                "Use only claims supported by the supplied evidence. If the evidence is insufficient, "
                "explicitly state that the answer is unverified rather than presenting unsupported "
                "details as established knowledge."
            )
        prompt = f"""{context_str}
User Query: {query}
Based on the above context from Freya's internal knowledge systems, provide a helpful answer.
{evidence_instruction}
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
