import asyncio

from app.research.capability import WebSearchTool


class FailingImporter:
    async def search(self, query, max_results=5):
        raise RuntimeError("primary unavailable")


def test_search_falls_back_to_secondary_provider(monkeypatch):
    monkeypatch.setattr(
        WebSearchTool,
        "_duckduckgo_fallback",
        staticmethod(lambda query, max_results: {
            "success": True,
            "query": query,
            "results": [{"title": "Fallback result", "url": "https://example.com", "snippet": "evidence", "source": "duckduckgo_html"}],
            "errors": [],
            "provider": "duckduckgo_html",
        }),
    )
    result = asyncio.run(WebSearchTool(importer=FailingImporter()).search_async("freya", 3))
    assert result["success"] is True
    assert result["provider"] == "duckduckgo_html"
    assert result["results"][0]["title"] == "Fallback result"
    assert result["errors"] == ["primary unavailable"]
