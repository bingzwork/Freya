import pytest

from app.core.config import Config, LearningPolicyConfig, RepairPolicyConfig
from app.core.config_hot_reload import ConfigValidator
from app.learning.models import LearningCandidate, LearningCandidateType, ObservedData, ValidationResult
from app.learning.pipeline import LearningPipeline
from app.verification.answer_repair_loop import AnswerRepairLoop


class RecordingLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def ask(self, *, prompt, system, priority):
        self.calls.append({"prompt": prompt, "system": system, "priority": priority})
        return self.responses.pop(0)


class RejectingVerifier:
    def verify_fallback_answer(self, *, answer, prompt, context):
        return None


@pytest.fixture
def clear_policy_environment(monkeypatch):
    for key in (
        "LEARNING_MIN_RELEVANCE",
        "LEARNING_MIN_NOVELTY",
        "LEARNING_MIN_ACTIONABILITY",
        "LEARNING_MIN_CONFIDENCE",
        "LEARNING_WORTH_REMEMBERING_THRESHOLD",
        "LEARNING_MIN_ITEMS_FOR_STORAGE",
        "ANSWER_REPAIR_MAX_ATTEMPTS",
        "ANSWER_REPAIR_PROMPT_POLICY",
    ):
        monkeypatch.delenv(key, raising=False)


def test_policy_defaults_preserve_current_safe_behavior(clear_policy_environment):
    config = Config()

    assert config.learning_policy == LearningPolicyConfig(
        min_relevance=0.3,
        min_novelty=0.2,
        min_actionability=0.2,
        min_confidence=0.1,
        worth_remembering_threshold=0.4,
        min_items_for_storage=1,
    )
    assert config.repair_policy == RepairPolicyConfig(max_attempts=3, prompt_policy="standard")


def test_learning_pipeline_uses_configured_thresholds():
    policy = LearningPolicyConfig(
        min_relevance=0.8,
        min_novelty=0.2,
        min_actionability=0.2,
        min_confidence=0.6,
        worth_remembering_threshold=0.75,
        min_items_for_storage=1,
    )
    pipeline = LearningPipeline(memory_coordinator=object(), policy=policy)
    candidate = LearningCandidate(
        source_component="source",
        candidate_type=LearningCandidateType.ANSWER_VERIFICATION,
    )
    observed = ObservedData(
        candidate_id=candidate.id,
        structured_observation={"source_component": "source"},
        extracted_signals=["source:source", "type:answer_verification"],
        confidence=0.5,
    )

    assert pipeline._evaluate(candidate, observed).has_learning_potential is False

    validated = ValidationResult(
        candidate_id=candidate.id,
        validated_items=[
            {
                "title": "Configured threshold",
                "content": "This learning item is otherwise valid.",
                "category": "test",
                "source": "test",
                "confidence": 0.7,
            }
        ],
        rejected_items=[],
    )
    result = pipeline._worth_remembering(candidate, validated)

    assert result.decision.value == "no"
    assert result.metadata["threshold"] == 0.75


def test_answer_repair_loop_respects_configured_attempt_count():
    llm = RecordingLLM(["invalid answer.", "invalid answer."])
    loop = AnswerRepairLoop(
        priority_llm=llm,
        answer_verifier=RejectingVerifier(),
        policy=RepairPolicyConfig(max_attempts=2, prompt_policy="standard"),
    )

    assert loop.attempt_repair("initial invalid answer.", "What changed?") is None
    assert len(llm.calls) == 2
    assert loop._max_attempts == 2


def test_answer_repair_loop_uses_configured_prompt_policy():
    llm = RecordingLLM(["invalid answer."])
    loop = AnswerRepairLoop(
        priority_llm=llm,
        answer_verifier=RejectingVerifier(),
        policy=RepairPolicyConfig(max_attempts=1, prompt_policy="concise"),
    )

    loop.attempt_repair("initial invalid answer.", "What changed?")

    assert loop._policy.prompt_policy == "concise"
    assert "concise, complete sentences" in llm.calls[0]["system"]


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: LearningPolicyConfig(min_relevance=-0.1), "between 0 and 1"),
        (lambda: LearningPolicyConfig(worth_remembering_threshold=1.1), "between 0 and 1"),
        (lambda: RepairPolicyConfig(max_attempts=0), "between 1 and 10"),
        (lambda: RepairPolicyConfig(prompt_policy=""), "must be one of"),
        (lambda: RepairPolicyConfig(prompt_policy="unsupported"), "must be one of"),
    ],
)
def test_invalid_policy_values_are_rejected(factory, message):
    with pytest.raises(ValueError, match=message):
        factory()


def test_invalid_environment_policy_is_rejected_and_hot_reload_validator_flags_it(monkeypatch):
    monkeypatch.setenv("ANSWER_REPAIR_MAX_ATTEMPTS", "-1")

    with pytest.raises(ValueError, match="between 1 and 10"):
        Config()

    invalid = ConfigValidator.validate_all(
        {
            "LEARNING_MIN_RELEVANCE": "1.1",
            "ANSWER_REPAIR_MAX_ATTEMPTS": "-1",
            "ANSWER_REPAIR_PROMPT_POLICY": "unsupported",
        }
    )
    assert invalid == [
        "LEARNING_MIN_RELEVANCE",
        "ANSWER_REPAIR_MAX_ATTEMPTS",
        "ANSWER_REPAIR_PROMPT_POLICY",
    ]
