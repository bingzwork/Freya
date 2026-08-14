"""
AnswerVerifier - Verifies LLM fallback answers for validity and learning potential.

This component implements the AnswerVerifier from TARGET_ARCHITECTURE.md Section 8.
It validates LLM fallback answers and determines if they should be:
1. Returned to the user as valid answers
2. Sent to the AnswerRepairLoop for retry with corrective context (up to max attempts)
3. If repair exhausted → AnswerSafeFailure (low-confidence disclosure + log knowledge gap)

This is specifically for LLM fallback answers, separate from ExecutionVerifier
which is used by ExecutionEngine for plan verification.
"""

from typing import Optional
from dataclasses import dataclass
from datetime import datetime, timezone
import re

from app.core.config import RepairPolicyConfig
from app.core.logger import logger
from app.learning.pipeline import LearningPipeline
from app.learning.models import LearningCandidate, LearningCandidateType
from app.verification.answer_repair_loop import AnswerRepairLoop, AnswerSafeFailure


@dataclass
class VerificationResult:
    """Result of answer verification."""
    is_valid_answer: bool
    answer: Optional[str] = None  # The validated answer to return to user
    learning_candidate: Optional[LearningCandidate] = None  # Learning candidate to send to pipeline
    reason: str = ""  # Explanation of the verification decision


class AnswerVerifier:
    """
    Verifies LLM fallback answers for validity and learning potential.

    This component ensures that only verified, high-quality answers from
    the local LLM fallback are returned to users. Invalid answers are sent
    to the AnswerRepairLoop for retry with corrective context. If repair
    is exhausted, AnswerSafeFailure provides low-confidence disclosure.
    """

    def __init__(
        self,
        learning_pipeline: Optional[LearningPipeline] = None,
        priority_llm=None,  # PriorityLLMProvider for AnswerRepairLoop
        repair_policy: Optional[RepairPolicyConfig] = None,
    ):
        """
        Initialize the AnswerVerifier.

        Args:
            learning_pipeline: The learning pipeline to send candidates to. It
                may be late-bound after target-order initialization.
            priority_llm: Optional PriorityLLMProvider for AnswerRepairLoop (D2)
            repair_policy: Optional validated repair policy for AnswerRepairLoop
        """
        self._learning_pipeline: Optional[LearningPipeline] = learning_pipeline
        self._priority_llm = priority_llm

        # Initialize repair loop if priority_llm provided
        if priority_llm:
            self._repair_loop = AnswerRepairLoop(
                priority_llm=priority_llm,
                answer_verifier=self,
                policy=repair_policy,
            )
            self._safe_failure = AnswerSafeFailure(learning_pipeline)
        else:
            self._repair_loop = None
            self._safe_failure = None

        logger.info(f"[AnswerVerifier] Initialized (repair_loop={'enabled' if self._repair_loop else 'disabled'})")

    def set_learning_pipeline(self, learning_pipeline: LearningPipeline) -> None:
        """Late-bind the target LearningPipeline after its ordered construction."""
        self._learning_pipeline = learning_pipeline
        if self._safe_failure is None:
            self._safe_failure = AnswerSafeFailure(learning_pipeline)
        else:
            self._safe_failure.set_learning_pipeline(learning_pipeline)

    def _submit_learning_candidate(self, candidate: LearningCandidate) -> None:
        """Submit only after the learning boundary is available."""
        if self._learning_pipeline is None:
            logger.warning("[AnswerVerifier] Learning candidate dropped before pipeline binding")
            return
        self._learning_pipeline.run(candidate)

    def verify_fallback_answer(
        self,
        answer: str,
        prompt: str,
        context: Optional[dict] = None
    ) -> Optional[str]:
        """
        Verify an LLM fallback answer.

        Args:
            answer: The raw answer from the LLM fallback
            prompt: The original prompt that generated this answer
            context: Optional context information

        Returns:
            The verified answer string if valid, otherwise None.
            If AnswerRepairLoop is enabled, invalid answers trigger repair attempts.
            If repair is exhausted, AnswerSafeFailure returns low-confidence disclosure.
        """
        # Handle empty or None answers
        if not answer or not answer.strip():
            return None

        answer = answer.strip()

        # The target fallback path supplies local retrieval evidence. Require
        # grounding there; preserve quality-only behavior for legacy direct use.
        if self._is_valid_answer(answer, prompt) and self._is_grounded_in_local_evidence(answer, context):
            # Valid answer: return it to the user
            # Also check if it has learning value for the pipeline (optional)
            if self._has_learning_value(answer, prompt):
                learning_candidate = self._create_learning_candidate(
                    answer, prompt, context, is_valid_answer=True
                )
                self._submit_learning_candidate(learning_candidate)
            return answer
        else:
            # Not a valid answer - attempt repair if repair loop is available
            if self._repair_loop:
                logger.debug(f"[AnswerVerifier] Answer failed verification, attempting repair...")
                repaired = self._repair_loop.attempt_repair(
                    original_answer=answer,
                    prompt=prompt,
                    context=context,
                    failure_reason="Answer did not meet quality thresholds"
                )
                if repaired:
                    return repaired

                # Repair exhausted - handle safe failure
                if self._safe_failure:
                    return self._safe_failure.handle_exhausted_retries(
                        original_answer=answer,
                        prompt=prompt,
                        context=context,
                        attempts=self._repair_loop._max_attempts
                    )

            # No repair loop or repair failed - send to learning pipeline as candidate
            if self._has_learning_value(answer, prompt):
                learning_candidate = self._create_learning_candidate(
                    answer, prompt, context, is_valid_answer=False
                )
                self._submit_learning_candidate(learning_candidate)

            # Return None to indicate no valid answer
            return None

    def _is_grounded_in_local_evidence(self, answer: str, context: Optional[dict]) -> bool:
        """Check a fallback draft against evidence from UnifiedRetrieval."""
        if not context or not context.get("knowledge_first"):
            return True
        evidence = context.get("retrieved_results") or context.get("evidence") or []
        if not evidence:
            return False
        evidence_text = " ".join(
            str(item.get("content", item) if isinstance(item, dict) else item)
            for item in evidence
        ).lower()
        answer_tokens = {
            token for token in re.findall(r"[a-z0-9]{4,}", answer.lower())
            if token not in {"that", "this", "with", "from", "your", "about", "have", "will", "they", "them"}
        }
        evidence_tokens = set(re.findall(r"[a-z0-9]{4,}", evidence_text))
        if not answer_tokens or not evidence_tokens:
            return False
        return len(answer_tokens & evidence_tokens) / max(1, len(answer_tokens)) >= 0.12

    def _is_valid_answer(self, answer: str, prompt: str) -> bool:
        """
        Determine if an answer is valid for direct return to user.

        Args:
            answer: The answer to validate
            prompt: The original prompt

        Returns:
            True if answer meets quality thresholds for user consumption
        """
        # Length checks - too short is likely incomplete, too long may be rambling
        if len(answer) < 10:
            return False
        if len(answer) > 2000:  # Reasonable upper bound for direct answers
            return False

        # Check for obvious failure patterns
        failure_patterns = [
            "I don't know",
            "I'm not sure",
            "I cannot",
            "I'm unable",
            "As an AI",
            "I apologize",
            "I do not have",
            "I am not able",
            "I don't have enough",
            "I need more information",
            "I don't have access",
            "I cannot provide",
            "I'm not able to",
            "I don't have the capability",
            "I don't possess",
            "I lack the",
            "I'm not equipped",
            "I don't have sufficient",
        ]

        answer_lower = answer.lower()
        for pattern in failure_patterns:
            if pattern in answer_lower:
                return False

        # Check for coherent structure - should have sentences
        if answer.count('.') < 1 and len(answer) > 50:
            # Long answer with no periods is likely incoherent
            return False

        # Additional quality checks could go here
        # For now, basic heuristic: if it passes the above, it's valid

        return True

    def _has_learning_value(self, answer: str, prompt: str) -> bool:
        """
        Determine if an answer has learning value even if not yet valid for direct use.

        Args:
            answer: The answer to evaluate
            prompt: The original prompt

        Returns:
            True if answer should be sent to learning pipeline
        """
        # Even invalid answers might have learning value
        # But we don't want to send everything - only potentially useful attempts

        # Too short - unlikely to have useful learning value
        if len(answer) < 20:
            return False

        # Too long - might be noisy or repetitive
        if len(answer) > 1500:
            return False

        # Check if it at least attempts to address the prompt
        # Simple heuristic: contains some words from the prompt
        prompt_words = set(prompt.lower().split())
        answer_words = set(answer.lower().split())
        common_words = prompt_words.intersection(answer_words)

        # If they share very few content words, probably not a good learning example
        # Filter out common stop words
        stop_words = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
                     "of", "with", "by", "is", "are", "was", "were", "be", "been", "being",
                     "have", "has", "had", "do", "does", "did", "will", "would", "should",
                     "could", "may", "might", "must", "can", "this", "that", "these", "those"}

        meaningful_prompt_words = prompt_words - stop_words
        meaningful_answer_words = answer_words - stop_words
        meaningful_common = meaningful_prompt_words.intersection(meaningful_answer_words)

        if len(meaningful_prompt_words) > 0:
            overlap_ratio = len(meaningful_common) / len(meaningful_prompt_words)
            # If less than 10% overlap with meaningful words, probably not addressing the prompt
            if overlap_ratio < 0.1:
                return False

        # If we got here, it has potential learning value
        return True

    def _create_learning_candidate(
        self,
        answer: str,
        prompt: str,
        context: Optional[dict],
        is_valid_answer: bool
    ) -> LearningCandidate:
        """
        Create a learning candidate from an answer.

        Args:
            answer: The answer text
            prompt: The original prompt
            context: Optional context
            is_valid_answer: Whether this answer was deemed valid

        Returns:
            LearningCandidate for the learning pipeline
        """
        candidate_type = LearningCandidateType.ANSWER_VERIFICATION

        # Prepare raw observation
        raw_observation = {
            "answer": answer,
            "prompt": prompt,
            "is_valid_answer": is_valid_answer,
            "answer_length": len(answer),
            "word_count": len(answer.split())
        }

        # Prepare context
        verification_context = {
            "verification_timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "AnswerVerifier",
            "verification_stage": "fallback_answer_evaluation"
        }

        if context:
            verification_context.update(context)

        return LearningCandidate(
            candidate_type=candidate_type,
            source_component="AnswerVerifier",
            raw_observation=raw_observation,
            context=verification_context,
            tags=["answer_verification", "llm_fallback"] +
                 (["valid_answer"] if is_valid_answer else ["needs_improvement"])
        )