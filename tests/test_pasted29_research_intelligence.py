from app.research.capability import ResearchCapability
from app.research.intelligence import (
    FeedbackClassifier,
    ResearchStrategySelector,
    RequestSemanticAnalyzer,
    SourceQualityProfileStore,
    SynthesisEngine,
)


def test_news_uses_news_vertical_plan():
    semantic = RequestSemanticAnalyzer.analyze("What is the latest news about NVIDIA?")
    plan = ResearchStrategySelector.vertical_plan(semantic)
    assert plan["vertical"] == "NEWS"
    assert "publication date" in plan["extraction_requirements"]
    assert "primary_reporting" in plan["source_priorities"]


def test_software_question_uses_official_or_repository_vertical():
    semantic = RequestSemanticAnalyzer.analyze("How does the FastAPI library handle middleware? Check the repository.")
    plan = ResearchStrategySelector.vertical_plan(semantic)
    assert plan["vertical"] in {"SOFTWARE_REPOSITORIES", "OFFICIAL_DOCUMENTATION"}
    assert plan["verification_rules"]


def test_marketplace_vertical_requires_listing_fields():
    semantic = RequestSemanticAnalyzer.analyze("Find the cheapest RTX 5060 on Shopee")
    plan = ResearchStrategySelector.vertical_plan(semantic)
    assert plan["vertical"] == "MARKETPLACES"
    assert "listing URL" in plan["extraction_requirements"]
    assert "verify actual product page" in plan["verification_rules"]


def test_source_profile_tracks_operational_history_without_permanent_truth():
    profiles = SourceQualityProfileStore()
    profiles.observe("https://docs.example/python", source_type="OFFICIAL_DOCUMENTATION", authority_score=0.9, extracted=True, relevant=True, verified=True)
    profiles.observe("https://docs.example/python", extracted=False, rate_limited=True)
    profile = profiles.get("docs.example")
    assert profile.extraction_successes == 1
    assert profile.extraction_failures == 1
    assert profile.verification_successes == 1
    assert profile.rate_limit_failures == 1
    assert profile.authority_score < 0.9
    assert "ranking_bonus" in profile.to_dict()


def test_inline_citations_follow_supporting_claim_source():
    answer = SynthesisEngine.attach_inline_citations(
        "Python 3.12 is supported by the official documentation.",
        [{"claim": "Python 3.12 is supported by the official documentation.", "source_url": "https://docs.example/python"}],
        [{"url": "https://docs.example/python", "title": "Python documentation"}],
    )
    assert "[1]" in answer
    assert "Sources:" in answer
    assert "https://docs.example/python" in answer


def test_feedback_classifier_separates_correction_source_and_preference():
    assert FeedbackClassifier.classify("That answer is wrong") ["type"] == "FACTUAL_CORRECTION"
    assert FeedbackClassifier.classify("Use a better source next time") ["type"] == "SOURCE_FEEDBACK"
    assert FeedbackClassifier.classify("I prefer concise answers") ["type"] == "USER_PREFERENCE"
    assert FeedbackClassifier.classify("The command failed") ["type"] == "EXECUTION_FEEDBACK"


def test_feedback_correction_enters_learning_pipeline_only_as_unverified_candidate():
    class Pipeline:
        def __init__(self):
            self.candidate = None

        def run(self, candidate):
            self.candidate = candidate
            return type("Result", (), {"final_decision": type("Decision", (), {"value": "no"})()})()

    capability = ResearchCapability()
    pipeline = Pipeline()
    capability.set_learning_pipeline(pipeline)
    result = capability.action_record_feedback({"feedback": "That answer is wrong", "context": {"research_result": {"topic": "x"}}})
    assert result["success"] is True
    assert result["accepted"] is False
    assert pipeline.candidate.raw_observation["verification_status"] == "unverified"
    assert pipeline.candidate.metadata["verified"] is False
