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

from typing import Any, Optional
from dataclasses import dataclass, field
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
    rejection_evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GroundingCheck:
    """Claim-level assessment against local retrieval evidence."""

    is_grounded: bool
    evidence: list[str] = field(default_factory=list)


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
        # every material claim to have a supporting evidence record there; retain
        # quality-only behaviour for legacy direct use with no knowledge context.
        grounding = self._check_claims_against_local_evidence(answer, context)
        if self._is_valid_answer(answer, prompt) and grounding.is_grounded:
            # Valid answer: return it to the user
            # Also check if it has learning value for the pipeline (optional)
            if self._has_learning_value(answer, prompt):
                learning_candidate = self._create_learning_candidate(
                    answer, prompt, context, is_valid_answer=True,
                    rejection_evidence=grounding.evidence,
                )
                self._submit_learning_candidate(learning_candidate)
            return answer

        rejection_context = dict(context or {})
        rejection_context["claim_verification"] = grounding.evidence
        failure_reason = "; ".join(grounding.evidence) or "Answer did not meet quality thresholds"

        # Not a valid answer - attempt repair only for the original fallback.
        # Repair attempts re-enter this verifier with a marker so a failed repair
        # returns to the bounded outer loop instead of recursively starting one.
        if self._repair_loop and not rejection_context.get("_repair_attempt"):
            logger.debug("[AnswerVerifier] Answer failed verification, attempting repair...")
            repaired = self._repair_loop.attempt_repair(
                original_answer=answer,
                prompt=prompt,
                context=rejection_context,
                failure_reason=failure_reason,
            )
            if repaired:
                return repaired

            # Repair exhausted - handle safe failure with the claim evidence.
            if self._safe_failure:
                return self._safe_failure.handle_exhausted_retries(
                    original_answer=answer,
                    prompt=prompt,
                    context=rejection_context,
                    attempts=self._repair_loop._max_attempts,
                )

        # No repair loop or repair failed - send to learning pipeline as candidate
        if self._has_learning_value(answer, prompt):
            learning_candidate = self._create_learning_candidate(
                answer,
                prompt,
                rejection_context,
                is_valid_answer=False,
                rejection_evidence=grounding.evidence,
            )
            self._submit_learning_candidate(learning_candidate)

        # Return None to indicate no valid answer
        return None

    def handle_provider_failure(
        self,
        prompt: str,
        context: Optional[dict] = None,
        reason: str = "Local model provider unavailable.",
    ) -> Optional[str]:
        """Convert a bounded provider failure into the normal safe-failure path."""
        failure_context = dict(context or {})
        failure_context["provider_outcome"] = reason
        if self._safe_failure is not None:
            return self._safe_failure.handle_exhausted_retries(
                original_answer="",
                prompt=prompt,
                context=failure_context,
                attempts=0,
            )
        logger.warning("[AnswerVerifier] Provider failure before learning pipeline binding: %s", reason)
        return None

    def _is_grounded_in_local_evidence(self, answer: str, context: Optional[dict]) -> bool:
        """Compatibility predicate for callers that only need a grounded/not-grounded value."""
        return self._check_claims_against_local_evidence(answer, context).is_grounded

    def _check_claims_against_local_evidence(
        self,
        answer: str,
        context: Optional[dict],
    ) -> GroundingCheck:
        """Require each answer claim to be supported by one local evidence record.

        The former whole-answer token ratio allowed a single familiar word to
        validate unrelated statements.  This compact deterministic check keeps
        the local-only policy while recording the supporting evidence source or
        the exact rejected claim for repair and learning.
        """
        if not context or not context.get("knowledge_first"):
            return GroundingCheck(True, ["No knowledge-first evidence required for legacy direct use."])

        raw_evidence = context.get("retrieved_results") or context.get("evidence") or []
        evidence_records = self._normalise_evidence(raw_evidence)
        if not evidence_records:
            return GroundingCheck(False, ["Rejected: no local retrieval evidence was supplied."])

        claims = self._material_claims(answer)
        if not claims:
            return GroundingCheck(False, ["Rejected: the fallback answer contains no verifiable claim."])

        findings: list[str] = []
        unsupported: list[str] = []
        for claim in claims:
            supporting_source = self._find_supporting_evidence(claim, evidence_records)
            if supporting_source is None:
                unsupported.append(claim)
                continue
            findings.append(f"Supported claim '{claim}' by {supporting_source}.")

        if unsupported:
            findings.extend(f"Rejected unsupported claim '{claim}'." for claim in unsupported)
            return GroundingCheck(False, findings)
        return GroundingCheck(True, findings)

    @staticmethod
    def _normalise_evidence(evidence: list[Any]) -> list[tuple[str, str]]:
        """Return non-empty (source, content) tuples from router evidence shapes."""
        records: list[tuple[str, str]] = []
        for index, item in enumerate(evidence, start=1):
            if isinstance(item, dict):
                content = item.get("content") or item.get("text") or ""
                source = item.get("source_id") or item.get("source") or f"evidence-{index}"
            else:
                content = getattr(item, "content", item)
                source = getattr(item, "source_id", None) or getattr(item, "source", None) or f"evidence-{index}"
            content_text = str(content).strip()
            if content_text:
                records.append((str(source), content_text))
        return records

    @staticmethod
    def _material_claims(answer: str) -> list[str]:
        """Split prose into independently checkable, non-trivial claims."""
        candidates = re.split(r"(?<=[.!?])\s+|[\n;]+", answer.strip())
        return [
            candidate.strip(" -•\t")
            for candidate in candidates
            if len(re.findall(r"[a-z0-9]{3,}", candidate.lower())) >= 2
        ]

    @staticmethod
    def _find_supporting_evidence(
        claim: str,
        evidence_records: list[tuple[str, str]],
    ) -> Optional[str]:
        """Return the evidence source that covers a claim, if one exists."""
        ignored = {
            "that", "this", "with", "from", "your", "about", "have", "will", "they", "them",
            "which", "where", "when", "into", "their", "there", "would", "could", "should",
        }
        claim_normalised = re.sub(r"\s+", " ", claim.lower()).strip(" .!?")
        claim_tokens = {
            token for token in re.findall(r"[a-z0-9]{3,}", claim_normalised)
            if token not in ignored
        }
        if not claim_tokens:
            return None

        for source, evidence_text in evidence_records:
            evidence_normalised = re.sub(r"\s+", " ", evidence_text.lower())
            if claim_normalised in evidence_normalised:
                return source
            evidence_tokens = set(re.findall(r"[a-z0-9]{3,}", evidence_normalised))
            matched_tokens = claim_tokens & evidence_tokens
            required_matches = 1 if len(claim_tokens) <= 2 else 2
            coverage = len(matched_tokens) / len(claim_tokens)
            if len(matched_tokens) >= required_matches and coverage >= 0.60:
                return source
        return None

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
        is_valid_answer: bool,
        rejection_evidence: Optional[list[str]] = None,
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
            "word_count": len(answer.split()),
            "claim_verification": rejection_evidence or [],
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