from pathlib import Path
from unittest.mock import Mock

from PIL import Image

from app.research.capability import ResearchCapability
from app.research.osint import OSINTCapability, WebSearchCapability


def test_advanced_query_generation_is_bounded_and_deduplicated():
    queries = WebSearchCapability.build_advanced_queries("Ada Lovelace", {"sites": ["example.org"], "file_types": ["pdf"], "years": ["1843"], "aliases": ["Augusta Ada"]})
    assert queries[0] == "Ada Lovelace"
    assert '"Ada Lovelace"' in queries
    assert any("site:example.org" in query for query in queries)
    assert any("filetype:pdf" in query for query in queries)
    assert len(queries) <= 10


def test_osint_reuses_web_search_for_multiple_paths():
    search = Mock()
    search.search.side_effect = lambda query, max_results=5, advanced=None: {"success": True, "results": [{"title": query, "url": f"https://example.org/{len(search.search.call_args_list)}", "provenance": {"query": query}}], "errors": []}
    result = OSINTCapability(search).cross_site_research("Ada Lovelace", max_results=4, depth=1)
    assert result["success"] is True
    assert search.search.call_count >= 2
    assert result["provenance"]


def test_archive_search_uses_public_url_and_graceful_failure(monkeypatch):
    web = WebSearchCapability(Mock())
    response = Mock(status_code=200)
    response.json.return_value = [["timestamp", "original", "statuscode", "digest"], ["20200101000000", "https://example.org", "200", "x"]]
    monkeypatch.setattr("app.research.osint.requests.get", lambda *args, **kwargs: response)
    result = web.archive_search("https://example.org")
    assert result["success"] is True
    assert result["results"][0]["result_type"] == "archive"
    blocked = web.archive_search("http://127.0.0.1")
    assert blocked["success"] is False


def test_reverse_image_search_does_not_claim_identity(tmp_path: Path):
    image = tmp_path / "sample.png"
    Image.new("RGB", (4, 3), "white").save(image)
    provider = Mock()
    provider.search.return_value = [{"url": "https://example.org/image", "similarity": 0.9}]
    result = OSINTCapability(Mock(), reverse_image_provider=provider).reverse_image_search(str(image))
    assert result["success"] is True
    assert "not identity confirmation" in result["warning"]


def test_image_intelligence_extracts_metadata(tmp_path: Path):
    image = tmp_path / "sign.png"
    Image.new("RGB", (12, 8), "white").save(image)
    result = OSINTCapability(Mock()).image_intelligence(str(image))
    assert result["success"] is True
    assert result["clues"]["width"] == 12
    assert result["clues"]["height"] == 8


def test_research_capability_exposes_nested_actions():
    capability = ResearchCapability()
    assert capability.supports_action("advanced_search")
    assert capability.supports_action("cross_site_research")
    assert capability.supports_action("reverse_image_search")
    assert capability.supports_action("image_intelligence")
