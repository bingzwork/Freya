from app.free_image_research_providers import validate_image_candidates, _overfetch_limit
from app.research.capability import ResearchCapability
from app.research.intelligence import RequestSemanticAnalyzer, ResearchIntent
from app.research.web_adapter import ResearchMode


def _image(index: int, title: str = "River Lynn photo"):
    return {
        "title": f"{title} {index}",
        "image_url": f"https://images.example.test/river-lynn-{index}.jpg",
        "thumbnail_url": f"https://images.example.test/river-lynn-{index}.jpg",
        "source_page_url": f"https://source.example.test/river-lynn-{index}",
        "source_domain": "source.example.test",
        "snippet": title,
        "width": 1200,
        "height": 800,
        "asset_type": "photo",
    }


def test_semantic_contract_extracts_requested_count_and_image_response_type():
    semantic = RequestSemanticAnalyzer.analyze("Find me 10 photos of River Lynn")
    assert semantic.requested_count == 10
    assert semantic.response_type == "image_results"
    assert semantic.execution_mode == ResearchMode.IMAGE_SEARCH.value
    assert semantic.intent == ResearchIntent.IMAGE_SEARCH.value


def test_follow_up_count_keeps_image_search_contract():
    semantic = RequestSemanticAnalyzer.analyze("show me 5 more")
    assert semantic.requested_count == 5
    assert semantic.response_type == "image_results"
    assert semantic.execution_mode == ResearchMode.IMAGE_SEARCH.value
    assert semantic.operation == "find_more_photos"
    assert semantic.is_follow_up is False  # count-only continuation is tracked by the UI image-history seam


def test_image_validation_deduplicates_excludes_and_rejects_mismatch():
    unrelated = _image(3, "Unrelated mountain")
    unrelated["image_url"] = "https://images.example.test/unrelated-mountain-3.jpg"
    unrelated["thumbnail_url"] = unrelated["image_url"]
    unrelated["source_page_url"] = "https://source.example.test/unrelated-mountain-3"
    candidates = [_image(1), _image(1), _image(2), unrelated, {"title": "River Lynn", "image_url": "https://images.example.test/tiny.png", "source_page_url": "https://source.example.test/tiny", "width": 32, "height": 32}]
    validated, metrics = validate_image_candidates(
        "River Lynn",
        candidates,
        limit=10,
        exclude_urls=["https://images.example.test/river-lynn-2.jpg"],
    )
    urls = [item["image_url"] for item in validated]
    assert urls == ["https://images.example.test/river-lynn-1.jpg"]
    assert metrics["duplicates"] >= 1
    assert metrics["excluded_previous"] == 1
    assert metrics["rejected_mismatch"] >= 1 or metrics["rejected_weak_asset"] >= 1


def test_image_action_attempts_requested_count_and_reports_count_gap_without_faking_satisfaction():
    class Provider:
        def search(self, query, limit):
            return {"image_results": [_image(index) for index in range(1, 4)]}

    capability = ResearchCapability()
    capability.image_search_provider = Provider()
    result = capability.action_image_search({"query": "River Lynn", "requested_count": 10})
    assert result["requested_count"] == 10
    assert len(result["image_results"]) == 3
    assert result["metrics"]["returned_count"] == 3
    assert result["metrics"]["coverage_gap"] == "COUNT_GAP"
    assert result["success"] is True


def test_overfetch_is_bounded():
    assert _overfetch_limit(1) == 8
    assert _overfetch_limit(10) == 30
    assert _overfetch_limit(30) == 50
    assert _overfetch_limit(100) == 50


def test_image_action_returns_requested_count_when_provider_can_fill_it():
    class Provider:
        def search(self, query, limit):
            return {"image_results": [_image(index) for index in range(1, 11)]}

    capability = ResearchCapability()
    capability.image_search_provider = Provider()
    result = capability.action_image_search({"query": "River Lynn", "requested_count": 10})
    assert len(result["image_results"]) == 10
    assert result["metrics"]["returned_count"] == 10
    assert result["metrics"]["coverage_gap"] == ""
    assert len({item["image_url"] for item in result["image_results"]}) == 10


if __name__ == "__main__":
    raise SystemExit("Run with pytest")


# Keep the import visible to type-checkers and make the test's architectural intent explicit.
assert ResearchIntent.IMAGE_SEARCH.value == "IMAGE_SEARCH"
assert ResearchMode.IMAGE_SEARCH.value == "IMAGE_SEARCH"


def test_cpu_comparison_does_not_inherit_amd_family_for_intel_core_shorthand():
    from app.research.comparison_intelligence import ComparisonIntelligenceEngine

    semantic = RequestSemanticAnalyzer.analyze("ryzen 7 5700x vs i5 14400")
    resolved = ComparisonIntelligenceEngine().resolve(semantic)
    assert [item.canonical_name for item in resolved] == ["AMD Ryzen 7 5700X", "Intel Core i5-14400"]
    assert [item.manufacturer for item in resolved] == ["AMD", "Intel"]
    assert all("AMD Ryzen" not in item.canonical_name for item in resolved[1:])


def test_cpu_comparison_queries_preserve_independent_manufacturers():
    from app.research.comparison_intelligence import ComparisonIntelligenceEngine

    semantic = RequestSemanticAnalyzer.analyze("ryzen 7 5700x vs i5 14400")
    engine = ComparisonIntelligenceEngine()
    resolved = engine.resolve(semantic)
    plan = engine.build_plan(semantic, resolved)
    queries = [item["query"] for item in plan.queries]
    assert any("Intel Core i5-14400 official specifications" in query for query in queries)
    assert any("AMD Ryzen 7 5700X vs Intel Core i5-14400" in query for query in queries)
    assert not any("AMD Ryzen i5" in query for query in queries)


def test_comparison_answer_is_plain_composition_not_raw_markdown_table():
    from app.research.capability import ResearchCapability
    from app.research.comparison_intelligence import ComparisonState, ComparisonIntelligenceEngine

    semantic = RequestSemanticAnalyzer.analyze("ryzen 7 5700x vs i5 14400")
    engine = ComparisonIntelligenceEngine()
    resolved = engine.resolve(semantic)
    plan = engine.build_plan(semantic, resolved)
    matrix = engine.build_matrix(resolved, plan.dimensions, [])
    answer = ResearchCapability._render_partial_comparison(ComparisonState(list(resolved), plan.category, plan, matrix=matrix))
    assert "**" not in answer
    assert "| Dimension |" not in answer
    assert "AMD Ryzen 7 5700X" in answer
    assert "Intel Core i5-14400" in answer


def test_formatter_hides_provider_diagnostics_from_research_answer():
    from app.capabilities.formatter import ResponseFormatter
    from app.capabilities.router import CapabilityResult

    result = CapabilityResult(
        success=True,
        capability_name="research_capability",
        data={"answer": "A grounded partial comparison.", "uncertainty": ["Trafilatura page read failed: HTTPError", "DDGSException No usable public page results remained after filtering"]},
    )
    rendered = ResponseFormatter().format(result)
    assert "HTTPError" not in rendered
    assert "DDGSException" not in rendered
    assert "Some public sources were unavailable or unreadable" in rendered
