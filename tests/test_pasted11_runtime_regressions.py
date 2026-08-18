import sys
from pathlib import Path

ROOT = Path(r"C:\AI Projects\Freya")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_named_photo_request_is_image_intent():
    from ui_server import _image_search_query, _is_image_search_request
    query = "find me photo's of marriane nalam"
    assert _is_image_search_request(query)
    assert _image_search_query(query).lower() == "marriane nalam"


def test_goddess_photo_request_is_image_intent():
    from ui_server import _image_search_query, _is_image_search_request
    query = "find me photos of goddess freya"
    assert _is_image_search_request(query)
    assert _image_search_query(query).lower() == "goddess freya"


def test_comparison_is_freshness_sensitive():
    from ui_server import _is_freshness_sensitive_request
    assert _is_freshness_sensitive_request("RTX 4060 vs RTX 5060")
    assert not _is_freshness_sensitive_request("What is a GPU?")


def test_image_search_uses_free_provider_chain_without_bing_key():
    from types import SimpleNamespace
    from app.research.capability import ResearchCapability
    capability = ResearchCapability()
    capability.image_research = SimpleNamespace(search_text=lambda query, limit=8: SimpleNamespace(success=False, candidates=[], provider="free_image_research", error="browser providers unavailable"))
    result = capability.action_image_search({"query": "goddess freya", "max_results": 5})
    assert result["success"] is False
    assert result["image_results"] == []
    assert result["provider"] == "free_image_research"
    assert "bing" not in str(result).lower()
    assert "path" not in str(result).lower()


def test_malformed_image_record_is_skipped():
    from app.research.capability import ResearchCapability
    capability = ResearchCapability()

    class Provider:
        def search(self, query, *, limit=8):
            return [{"path": "C:/private/file.jpg"}, {"title": "usable", "image_url": "https://cdn.example/image.jpg", "url": "https://example.com/page"}]

    capability.image_search_provider = Provider()
    result = capability.action_image_search({"query": "goddess freya", "max_results": 5})
    assert result["success"] is True
    assert len(result["image_results"]) == 1
    assert result["image_results"][0]["image_url"].startswith("https://")
