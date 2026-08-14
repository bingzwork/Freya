"""
AnswerRepairLoop - Retries LLM fallback answers with corrective context.

Implements the AnswerRepairLoop from TARGET_ARCHITECTURE.md Section 8:
V1 (AnswerVerifier) →|"Invalid / Low Confidence"| AR (AnswerRepairLoop)
AR →|"Retry w/ Corrective Context (Attempt < Max)"| D2 (PriorityLLMProvider)
AR →|"Retries Exhausted"| SF1 (AnswerSafeFailure) → Low-Confidence Disclosure → RESULT
"""

import logging
from typing import Optional, TYPE_CHECKING

from app.core.config import Config, RepairPolicyConfig
from app.core.priority_llm import PriorityLLMProvider, LLMPriority
from app.core.logger import logger

if TYPE_CHECKING:
    from app.verification.answer_verifier import AnswerVerifier


class AnswerRepairLoop:
    """
    Repairs invalid/low-confidence LLM fallback answers by retrying with corrective context.

    Flow:
    1. AnswerVerifier rejects an answer (returns None) or marks it low-confidence
    2. AnswerRepairLoop builds corrective prompt with failure reason + original context
    3. Retries with PriorityLLMProvider (D2) up to max_attempts
    4. If any retry passes AnswerVerifier, return verified answer
    5. If all retries exhausted, invoke AnswerSafeFailure (SF1) - low-confidence disclosure
    """

    def __init__(
        self,
        priority_llm: PriorityLLMProvider,
        answer_verifier: 'AnswerVerifier',
        max_attempts: int | None = None,
        prompt_policy: str | None = None,
        policy: RepairPolicyConfig | None = None,
    ):
        """
        Initialize the AnswerRepairLoop.

        Args:
            priority_llm: The PriorityLLMProvider (D2) to use for retries
            answer_verifier: The AnswerVerifier (V1) to validate retries
            max_attempts: Optional explicit retry override for dependency-injected callers.
            prompt_policy: Optional explicit prompt-policy override for dependency-injected callers.
            policy: Validated repair policy; defaults to the application configuration.
        """
        configured_policy = policy or Config().repair_policy
        if max_attempts is not None or prompt_policy is not None:
            configured_policy = RepairPolicyConfig(
                max_attempts=(
                    configured_policy.max_attempts
                    if max_attempts is None
                    else max_attempts
                ),
                prompt_policy=(
                    configured_policy.prompt_policy
                    if prompt_policy is None
                    else prompt_policy
                ),
            )
        self._priority_llm = priority_llm
        self._answer_verifier = answer_verifier
        self._policy = configured_policy
        self._max_attempts = self._policy.max_attempts
        self._system_prompt = self._select_system_prompt(self._policy.prompt_policy)

        logger.info(
            "[AnswerRepairLoop] Initialized with "
            f"max_attempts={self._max_attempts}, prompt_policy={self._policy.prompt_policy}"
        )

    @staticmethod
    def _select_system_prompt(prompt_policy: str) -> str:
        if prompt_policy == "concise":
            return (
                "You are Freya, an expert software engineering assistant. "
                "Answer the user's question directly in concise, complete sentences. "
                "Do not create plans or execute tasks unless explicitly asked to do so."
            )
        return """You are Freya, an expert software engineering assistant.
Answer the user's question directly and concisely. Do not create plans or execute tasks
unless explicitly asked to do so."""

    def attempt_repair(
        self,
        original_answer: str,
        prompt: str,
        context: Optional[dict] = None,
        failure_reason: str = "Answer did not meet quality thresholds"
    ) -> Optional[str]:
        """
        Attempt to repair an invalid answer by retrying with corrective context.

        Args:
            original_answer: The answer that failed verification
            prompt: The original user prompt
            context: Optional context from the original request
            failure_reason: Why the original answer was rejected

        Returns:
            Verified answer string if any retry succeeds, otherwise None
        """
        # Build the corrective prompt
        corrective_prompt = self._build_corrective_prompt(
            original_answer=original_answer,
            prompt=prompt,
            context=context,
            failure_reason=failure_reason
        )

        for attempt in range(1, self._max_attempts + 1):
            logger.debug(f"[AnswerRepairLoop] Repair attempt {attempt}/{self._max_attempts}")

            # Get new answer from PriorityLLMProvider (D2)
            new_answer = self._priority_llm.ask(
                prompt=corrective_prompt,
                system=self._system_prompt,
                priority=LLMPriority.CHAT,
            )

            # Verify the new answer without creating a nested repair loop.
            repair_context = dict(context or {})
            repair_context["_repair_attempt"] = True
            verified = self._answer_verifier.verify_fallback_answer(
                answer=new_answer,
                prompt=prompt,
                context=repair_context,
            )

            if verified is not None:
                logger.info(f"[AnswerRepairLoop] Repair succeeded on attempt {attempt}")
                return verified

            # Update failure reason for next iteration
            failure_reason = f"Previous attempt failed verification: {new_answer[:200]}"
            corrective_prompt = self._build_corrective_prompt(
                original_answer=new_answer,
                prompt=prompt,
                context=context,
                failure_reason=failure_reason
            )

        logger.warning(f"[AnswerRepairLoop] All {self._max_attempts} repair attempts exhausted")
        return None

    def _build_corrective_prompt(
        self,
        original_answer: str,
        prompt: str,
        context: Optional[dict],
        failure_reason: str
    ) -> str:
        """Build a corrective prompt for the LLM to try again."""
        context_parts = [
            "=== PREVIOUS ATTEMPT (REJECTED) ===",
            f"User Query: {prompt}",
            f"Your Previous Answer: {original_answer}",
            f"Rejection Reason: {failure_reason}",
            "",
            "=== INSTRUCTIONS ===",
            "Your previous answer was rejected. Please provide a better answer that:",
            "1. Directly addresses the user's question",
            "2. Is factually accurate and specific (not generic)",
            "3. Does not contain failure phrases like 'I don't know', 'I cannot', 'As an AI', etc.",
            "4. Has clear, complete sentences with proper structure",
            "5. Is concise but complete",
            "",
            "Try again with an improved answer:",
        ]

        if context:
            context_parts.insert(3, f"Context: {context}")

        return "\n".join(context_parts)


class AnswerSafeFailure:
    """
    Handles the case when AnswerRepairLoop exhausts all retries.

    Implements the AnswerSafeFailure (SF1) from TARGET_ARCHITECTURE.md:
    SF1 →|"Low-Confidence Disclosure"| RESULT
    SF1 →|"Log Knowledge Gap"| LP (LearningPipeline)
    """

    def __init__(self, learning_pipeline=None):
        self._learning_pipeline = learning_pipeline
        logger.info("[AnswerSafeFailure] Initialized")

    def set_learning_pipeline(self, learning_pipeline) -> None:
        """Late-bind LearningPipeline after target-order initialization."""
        self._learning_pipeline = learning_pipeline

    def handle_exhausted_retries(
        self,
        original_answer: str,
        prompt: str,
        context: Optional[dict] = None,
        attempts: int = 3
    ) -> str:
        """
        Handle exhausted repair attempts - return low-confidence disclosure.

        Args:
            original_answer: The last attempted answer
            prompt: The original user prompt
            context: Optional context
            attempts: Number of attempts made

        Returns:
            Low-confidence disclosure message for the user
        """
        # Log knowledge gap to learning pipeline
        try:
            from app.learning.models import LearningCandidate, LearningCandidateType
            candidate = LearningCandidate(
                candidate_type=LearningCandidateType.ANSWER_VERIFICATION,
                source_component="AnswerSafeFailure",
                raw_observation={
                    "prompt": prompt,
                    "final_answer": original_answer,
                    "attempts": attempts,
                    "exhausted": True,
                },
                context={
                    "stage": "safe_failure",
                    "verification_stage": "answer_repair_exhausted",
                    **(context or {})
                },
                tags=["answer_verification", "llm_fallback", "exhausted", "knowledge_gap"]
            )
            if self._learning_pipeline is None:
                logger.warning("[AnswerSafeFailure] Learning pipeline is not bound; knowledge gap retained only in logs")
            else:
                self._learning_pipeline.run(candidate)
        except Exception as e:
            logger.warning(f"[AnswerSafeFailure] Failed to log knowledge gap: {e}")

        # Return honest low-confidence disclosure
        return (
            "I don't have enough reliable information to give you a confident answer to that. "
            "My internal knowledge doesn't contain sufficient detail on this topic, "
            "and my local model fallback couldn't produce a verified response after multiple attempts. "
            "You might want to rephrase the question or provide more context."
        )