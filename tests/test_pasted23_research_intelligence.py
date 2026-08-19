from app.research.intelligence import (
    EvidenceClassifier,
    EvidenceType,
    PriceType,
    RequestSemanticAnalyzer,
    ResearchIntent,
    ResearchStrategySelector,
    SynthesisEngine,
)


def test_latest_named_gpu_update_is_news_and_self_contained():
    model = RequestSemanticAnalyzer.analyze("Find the latest update of NVIDIA GPU")
    assert model.intent == ResearchIntent.NEWS_RESEARCH.value
    assert model.execution_mode == "DEEP_RESEARCH"
    assert any("nvidia" in entity.lower() and "gpu" in entity.lower() for entity in model.entities)
    assert not model.shopping
    assert not model.uses_shopping_context


def test_rtx_comparison_is_not_shopping():
    model = RequestSemanticAnalyzer.analyze("Compare RTX 5060 vs RX 9060 XT")
    assert model.intent == ResearchIntent.TECHNICAL_COMPARISON.value
    assert model.execution_mode == "DEEP_RESEARCH"
    assert model.shopping is False
    assert set(model.entities) >= {"RTX 5060", "RX 9060 XT"}
    assert "performance" in model.comparison_dimensions


def test_shopping_request_retains_marketplace_and_price_goal():
    model = RequestSemanticAnalyzer.analyze("Find the cheapest photo printer only on Shopee")
    assert model.intent == ResearchIntent.SHOPPING_PRICE_SEARCH.value
    assert model.shopping is True
    assert model.price_lookup is True
    assert model.requested_domain == "shopee.ph"
    assert "hard_marketplace_constraint" in model.constraints


def test_typed_followup_can_use_shopping_context_but_named_news_cannot():
    followup = RequestSemanticAnalyzer.analyze("Show me another photo")
    news = RequestSemanticAnalyzer.analyze("What is the latest NVIDIA GPU update?")
    assert followup.intent == ResearchIntent.IMAGE_SEARCH.value
    assert followup.uses_shopping_context is True
    assert news.intent == ResearchIntent.NEWS_RESEARCH.value
    assert news.uses_shopping_context is False


def test_evidence_roles_restrict_benchmark_price_and_listing_fields():
    benchmark = EvidenceClassifier.classify({
        "url": "https://www.tomshardware.com/pc-components/gpus/rtx-review",
        "title": "RTX 5060 benchmark review",
        "content": "Benchmark results report $299 MSRP under a defined test methodology.",
    })
    listing = EvidenceClassifier.classify({
        "url": "https://shopee.ph/photo-printer-i.123.456",
        "title": "Canon photo printer",
        "content": "Price: ₱5999 Sold by: Verified Store In stock Add to cart",
    })
    assert benchmark["evidence_type"] in {EvidenceType.BENCHMARK.value, EvidenceType.REVIEW.value}
    assert benchmark["commerce_verified"] is False
    assert benchmark["price_type"] in {PriceType.MSRP.value, PriceType.REFERENCE_PRICE.value}
    assert "seller" not in benchmark["allowed_fields"]
    assert listing["evidence_type"] == EvidenceType.MARKETPLACE_LISTING.value
    assert listing["commerce_verified"] is True
    assert listing["price_type"] == PriceType.CURRENT_LISTING_PRICE.value
    assert "seller" in listing["allowed_fields"]


def test_news_query_planning_has_recent_and_official_roles():
    model = RequestSemanticAnalyzer.analyze("Find the latest update of NVIDIA GPU")
    queries = ResearchStrategySelector.build_queries(model, max_queries=4)
    assert len(queries) == 4
    assert any("latest news" in query for query in queries)
    assert any("official" in query for query in queries)


def test_comparison_synthesis_does_not_invent_a_cheapest_listing():
    model = RequestSemanticAnalyzer.analyze("Compare RTX 5060 vs RX 9060 XT")
    facts = [
        {"claim": "RTX 5060 benchmark performance was measured under a defined test methodology.", "source_title": "Benchmark Review", "evidence_type": EvidenceType.BENCHMARK.value},
        {"claim": "RX 9060 XT has a different memory configuration and benchmark result.", "source_title": "Independent Review", "evidence_type": EvidenceType.REVIEW.value},
    ]
    result = SynthesisEngine.synthesize(model, facts, [], [], [])
    assert "Technical comparison" in result["answer"]
    assert "cheapest" not in result["answer"].lower()
    assert "seller" not in result["answer"].lower()
    assert "performance" in result["answer"].lower()


def test_news_synthesis_preserves_date_uncertainty_instead_of_fabricating_dates():
    model = RequestSemanticAnalyzer.analyze("Find the latest update of NVIDIA GPU")
    result = SynthesisEngine.synthesize(model, [{"claim": "NVIDIA announced a new graphics initiative.", "source_title": "News source"}], [], [], [])
    assert "date not exposed" in result["answer"]
    assert result["answer_plan"] == "news_developments"
