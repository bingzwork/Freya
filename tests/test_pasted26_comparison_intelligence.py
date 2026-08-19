from types import SimpleNamespace

from app.research.capability import ResearchCapability, WebPage
from app.research.comparison_intelligence import ComparisonIntelligenceEngine, SufficiencyStatus
from app.research.intelligence import RequestSemanticAnalyzer, ResearchIntent


def test_contextual_entity_completion_resolves_short_second_side_without_placeholder():
    semantic = RequestSemanticAnalyzer.analyze("rtx 3050 vs 5050")
    assert semantic.intent == ResearchIntent.TECHNICAL_COMPARISON.value
    engine = ComparisonIntelligenceEngine()
    entities = engine.resolve(semantic)
    assert [item.canonical_name for item in entities] == ["NVIDIA GeForce RTX 3050", "NVIDIA GeForce RTX 5050"]
    assert all("Item" not in item.canonical_name for item in entities)


def test_entity_resolution_generalizes_across_categories():
    engine = ComparisonIntelligenceEngine()
    cases = {
        "iPhone 16 vs 17": ("Apple iPhone 16", "Apple iPhone 17"),
        "Galaxy S24 vs S25": ("Samsung Galaxy S24", "Samsung Galaxy S25"),
        "Ryzen 7600 vs 9600X": ("AMD Ryzen 7600", "AMD Ryzen 9600X"),
        "PlayStation 5 vs 5 Pro": ("Sony PlayStation 5", "Sony PlayStation 5 Pro"),
    }
    for query, expected in cases.items():
        semantic = RequestSemanticAnalyzer.analyze(query)
        resolved = engine.resolve(semantic)
        assert tuple(item.canonical_name for item in resolved) == expected


def test_comparison_plan_queries_each_entity_and_direct_matchup():
    engine = ComparisonIntelligenceEngine()
    semantic = RequestSemanticAnalyzer.analyze("rtx 3050 vs 5050")
    entities = engine.resolve(semantic)
    plan = engine.build_plan(semantic, entities)
    queries = [item["query"].lower() for item in plan.queries]
    assert any("rtx 3050" in query and "official" in query for query in queries)
    assert any("rtx 5050" in query and "official" in query for query in queries)
    assert any("vs" in query and "benchmark" in query for query in queries)
    assert all("item b" not in query for query in queries)


def test_claim_extraction_rejects_navigation_and_untyped_random_text():
    engine = ComparisonIntelligenceEngine()
    semantic = RequestSemanticAnalyzer.analyze("rtx 3050 vs 5050")
    entities = engine.resolve(semantic)
    facts = [
        {"claim": "Skip to main content Compare GeForce RTX 3050 with other GPUs", "source_url": "https://example.test/a", "source_title": "Navigation", "source_role": "BENCHMARK", "confidence": 0.9},
        {"claim": "NVIDIA GeForce RTX 3050 has 8 GB of VRAM", "source_url": "https://example.test/spec", "source_title": "RTX 3050 specifications", "source_role": "OFFICIAL_PRODUCT", "confidence": 0.9},
        {"claim": "NVIDIA GeForce RTX 3050 scored 82 FPS at 1080p High", "source_url": "https://example.test/bench", "source_title": "RTX 3050 benchmark", "source_role": "BENCHMARK", "confidence": 0.8},
        {"claim": "NVIDIA GeForce RTX 3050 + unrelated marketing text", "source_url": "https://example.test/random", "source_title": "Random", "source_role": "GENERAL_WEB", "confidence": 0.9},
    ]
    claims = engine.extract_claims(facts, entities, "gpu")
    assert any(claim.property == "vram" for claim in claims)
    assert any(claim.property == "performance" for claim in claims)
    assert not any("Skip to" in claim.direct_quote for claim in claims)
    assert not any("unrelated marketing" in claim.direct_quote for claim in claims)


def test_matrix_partitions_entities_and_marks_missing_side():
    engine = ComparisonIntelligenceEngine()
    semantic = RequestSemanticAnalyzer.analyze("rtx 3050 vs 5050")
    entities = engine.resolve(semantic)
    claims = engine.extract_claims([
        {"claim": "NVIDIA GeForce RTX 3050 has 8 GB of VRAM", "source_url": "https://example.test/a", "source_title": "A", "source_role": "OFFICIAL_PRODUCT", "confidence": 0.9}
    ], entities, "gpu")
    matrix = engine.build_matrix(entities, ["vram", "performance"], claims)
    assert matrix.cells["NVIDIA GeForce RTX 3050"]["vram"].claims
    assert not matrix.cells["NVIDIA GeForce RTX 5050"]["vram"].claims
    assert matrix.sufficiency == SufficiencyStatus.PARTIAL_BUT_USEFUL
    assert any("RTX 5050" in item for item in matrix.missing_evidence)
    assert matrix.gap_queries


def test_conflict_requires_same_entity_property_conditions_and_two_sources():
    engine = ComparisonIntelligenceEngine()
    semantic = RequestSemanticAnalyzer.analyze("rtx 3050 vs 5050")
    entities = engine.resolve(semantic)
    claims = engine.extract_claims([
        {"claim": "NVIDIA GeForce RTX 3050 has 8 GB of VRAM", "source_url": "https://example.test/a", "source_title": "A", "source_role": "OFFICIAL_PRODUCT", "confidence": 0.9},
        {"claim": "NVIDIA GeForce RTX 3050 has 4 GB of VRAM", "source_url": "https://example.test/b", "source_title": "B", "source_role": "REVIEW", "confidence": 0.9},
        {"claim": "NVIDIA GeForce RTX 3050 scored 70 FPS at 1080p Medium", "source_url": "https://example.test/c", "source_title": "C", "source_role": "BENCHMARK", "confidence": 0.9},
        {"claim": "NVIDIA GeForce RTX 3050 scored 90 FPS at 1440p Ultra", "source_url": "https://example.test/d", "source_title": "D", "source_role": "BENCHMARK", "confidence": 0.9},
    ], entities, "gpu")
    conflicts = engine.detect_conflicts(claims)
    assert any(item["property"] == "vram" for item in conflicts)
    assert not any(item["property"] == "performance" for item in conflicts)


def test_research_capability_comparison_path_returns_no_item_placeholders(monkeypatch):
    capability = ResearchCapability()
    pages = {
        "https://example.test/3050": WebPage("https://example.test/3050", "RTX 3050 specifications", "NVIDIA GeForce RTX 3050 has 8 GB of VRAM and uses 130 W power.", "2026-01-01T00:00:00Z"),
        "https://example.test/5050": WebPage("https://example.test/5050", "RTX 5050 specifications", "NVIDIA GeForce RTX 5050 has 8 GB of VRAM and uses 130 W power.", "2026-01-01T00:00:00Z"),
    }

    def fake_search(inputs):
        query = str(inputs.get("query", ""))
        if "3050" in query:
            url = "https://example.test/3050"
        elif "5050" in query:
            url = "https://example.test/5050"
        else:
            url = "https://example.test/3050"
        return {"success": True, "results": [{"title": pages[url].title, "url": url, "snippet": pages[url].content},], "errors": []}

    monkeypatch.setattr(capability, "action_search_web", fake_search)
    monkeypatch.setattr(capability, "action_read_page", lambda inputs: {"success": True, "page": pages[inputs["url"]].to_dict()})
    monkeypatch.setattr(capability, "_invoke", lambda stage, **kwargs: {"score": 0.9} if stage == "evaluate" else [{"claim": kwargs["page"]["content"], "evidence": kwargs["page"]["content"], "source_url": kwargs["page"]["url"], "source_title": kwargs["page"]["title"], "retrieved_at": kwargs["page"]["retrieved_at"], "confidence": 0.9}] if stage == "facts" else [])
    result = capability.action_research_topic({"topic": "rtx 3050 vs 5050", "max_queries": 5, "max_sources": 4})
    answer = result["data"]["answer"]
    assert "Item A" not in answer and "Item B" not in answer
    assert result["data"]["resolved_entities"] == ["NVIDIA GeForce RTX 3050", "NVIDIA GeForce RTX 5050"]
    assert result["data"]["comparison_plan"]["queries"]
    assert result["data"]["evidence_matrix"]["entities"] == ["NVIDIA GeForce RTX 3050", "NVIDIA GeForce RTX 5050"]
