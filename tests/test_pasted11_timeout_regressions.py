import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(r"C:\AI Projects\Freya")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_bounded_call_times_out():
    from ui_server import _bounded_call
    started = time.monotonic()
    try:
        _bounded_call(time.sleep, 0.2, 5)
    except TimeoutError:
        pass
    else:
        raise AssertionError("bounded call did not time out")
    assert time.monotonic() - started < 1.5


def test_primary_search_timeout_falls_through(monkeypatch):
    from app.research.capability import WebSearchTool

    class HangingImporter:
        async def search(self, query, max_results=5):
            await asyncio.sleep(20)
            return []

    monkeypatch.setenv("FREYA_SEARCH_PROVIDER_TIMEOUT", "3")
    monkeypatch.setattr(WebSearchTool, "_duckduckgo_fallback", staticmethod(lambda query, max_results: {"success": True, "query": query, "results": [], "errors": ["fallback intentionally empty"], "provider": "test_fallback"}))
    result = WebSearchTool(HangingImporter()).search("bounded timeout", max_results=2)
    assert result["provider"] == "test_fallback"
    assert result["success"] is True
    assert result["errors"]
