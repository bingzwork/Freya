from __future__ import annotations

from types import SimpleNamespace

from app.research.capability import ResearchCapability, WebPage, WebPageReader, WebSearchTool
from app.research.web_adapter import (
    AdapterOutcome,
    DeepResearchCoordinator,
    DDGSProvider,
    ResearchLimits,
    ResearchMode,
    TrafilaturaPageReader,
)


def test_research_modes_are_explicit_and_query_inference_is_bounded():
    assert ResearchMode.coerce("FAST_SEARCH", "anything") is ResearchMode.FAST_SEARCH
    assert ResearchMode.coerce("DEEP_RESEARCH", "anything") is ResearchMode.DEEP_RESEARCH
    assert ResearchMode.coerce(None, "Research this deeply across multiple sources") is ResearchMode.DEEP_RESEARCH
    assert ResearchMode.coerce(None, "Show me a photo of Mount Fuji") is ResearchMode.IMAGE_SEARCH
    limits = ResearchLimits.from_inputs({"max_queries": 99, "max_sources": 99, "max_duration": 999}, deep=True)
    assert limits.max_queries == 8
    assert limits.max_sources == 20
    assert limits.max_duration_seconds == 180.0


def test_deep_query_planner_generates_primary_and_follow_up_queries():
    queries = DeepResearchCoordinator.build_queries("Intel newest desktop architecture", max_queries=4)
    assert queries[0] == "Intel newest desktop architecture"
    assert any("official" in query.lower() for query in queries[1:])
    follow_up = DeepResearchCoordinator.choose_follow_up_queries(
        "best 32GB DDR5 RAM under 6000 Philippines",
        covered_text="I found purchase prices and speed, but the pages did not provide ownership details.",
    )
    assert follow_up
    assert any("warranty" in query.lower() for query in follow_up)


def test_ddgs_provider_normalizes_text_and_image_records_without_network(monkeypatch):
    class FakeDDGS:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def text(self, _query, **_kwargs):
            return [{"title": "Official page", "href": "https://example.org/page", "body": "Primary evidence"}]

        def images(self, _query, **_kwargs):
            return [{"title": "GALAX RTX 5060", "image": "https://cdn.example.org/gpu.jpg", "thumbnail": "https://cdn.example.org/thumb.jpg", "url": "https://example.org/gpu", "width": 640, "height": 480}]

    monkeypatch.setattr("ddgs.DDGS", FakeDDGS)
    provider = DDGSProvider(timeout_seconds=3)
    text = provider.search("gpu", max_results=3)
    images = provider.search_images("GALAX RTX 5060", limit=2)
    assert text.success is True
    assert text.results[0]["url"] == "https://example.org/page"
    assert images.success is True
    assert images.results[0]["image_url"].endswith("gpu.jpg")
    assert images.results[0]["width"] == 640


def test_trafilatura_page_reader_normalizes_document(monkeypatch):
    class Response:
        url = "https://example.org/article"
        text = "<html><article>Readable</article></html>"

        def raise_for_status(self):
            return None

    document = SimpleNamespace(
        title="Example article",
        text="A sufficiently long extracted article body " * 10,
        author="Author",
        date="2026-08-19",
        sitename="Example",
        links=[{"text": "source", "url": "https://example.org/source"}],
        images=[{"src": "https://example.org/image.jpg"}],
    )
    monkeypatch.setattr("requests.get", lambda *args, **kwargs: Response())
    monkeypatch.setattr("trafilatura.bare_extraction", lambda *args, **kwargs: document)
    result = TrafilaturaPageReader().read("https://example.org/article")
    assert result.success is True
    assert result.results[0]["title"] == "Example article"
    assert result.results[0]["source_metadata"]["author"] == "Author"
    assert result.results[0]["source_metadata"]["links"]


def test_production_search_prefers_adapter_but_explicit_importer_remains_deterministic():
    class Adapter:
        def search(self, _query, *, max_results=5):
            return AdapterOutcome(True, "fake_maintained", results=[{"title": "Adapter", "url": "https://example.org", "snippet": "evidence"}])

    class Importer:
        async def search(self, _query, max_results=5):
            return [{"title": "Injected", "url": "https://example.net", "snippet": "test"}]

    assert WebSearchTool(adapter=SimpleNamespace(search=Adapter().search)).search("x")["provider"] == "fake_maintained"
    assert WebSearchTool(Importer()).search("x")["provider"] == "internet_research_importer"


def test_image_search_requires_entity_match_and_preserves_media_metadata():
    research = ResearchCapability()

    class Provider:
        def search(self, _query, *, limit=4):
            return [{
                "title": "GALAX GeForce RTX 5060 EX",
                "image_url": "https://cdn.example.org/galax-5060.jpg",
                "source_page_url": "https://galax.com/rtx-5060",
                "source_domain": "galax.com",
            }]

    research.image_search_provider = Provider()
    found = research.action_image_search({"query": "GALAX RTX 5060", "limit": 2})
    missing = research.action_image_search({"query": "NVIDIA RTX 5090", "limit": 2})
    assert found["success"] is True
    assert found["image_results"][0]["match_confidence"] >= 0.5
    assert found["image_results"][0]["source_page_url"] == "https://galax.com/rtx-5060"
    assert missing["success"] is False
    assert missing["image_results"] == []


def test_research_topic_dispatches_deep_mode_through_canonical_action():
    research = ResearchCapability()
    calls = []

    def deep(inputs):
        calls.append(inputs)
        return {"success": True, "mode": ResearchMode.DEEP_RESEARCH.value, "data": {"research_mode": ResearchMode.DEEP_RESEARCH.value}}

    research.action_deep_research = deep
    result = research.action_research_topic({"topic": "Research Intel deeply across multiple sources"})
    assert result["success"] is True
    assert result["mode"] == ResearchMode.DEEP_RESEARCH.value
    assert calls[0]["mode"] == ResearchMode.DEEP_RESEARCH.value


def test_page_reader_preserves_explicit_importer_compatibility():
    item = SimpleNamespace(
        title="Injected page",
        content="Readable page content with enough detail.",
        source_uri="https://example.org/page",
        source_metadata={"fetch_timestamp": "2026-08-15T00:00:00+00:00"},
    )

    class Importer:
        async def import_from_url(self, _url):
            return SimpleNamespace(success=True, items=[item], errors=[])

    result = WebPageReader(Importer()).read("https://example.org/page")
    assert result["success"] is True
    assert result["page"].title == "Injected page"


def test_bounded_deep_research_reads_multiple_sources_and_returns_stopping_metadata(monkeypatch):
    research = ResearchCapability()
    searched = []
    read = []

    def fake_search(inputs):
        query = inputs["query"]
        searched.append(query)
        number = len(searched)
        return {
            "success": True,
            "results": [{"title": f"Source {number}", "url": f"https://source{number}.example.org/page", "snippet": "evidence"}],
            "attempts": [{"provider": "fake", "success": True}],
            "errors": [],
        }

    def fake_read(inputs):
        url = inputs["url"]
        read.append(url)
        return {"success": True, "page": {"url": url, "title": "Source", "content": "Readable evidence content.", "retrieved_at": "2026-08-19T00:00:00+00:00", "source_metadata": {}}}

    def fake_invoke(stage, **kwargs):
        if stage == "evaluate":
            return {"score": 0.9, "authority": "primary"}
        if stage == "facts":
            return [{"claim": f"Claim from {kwargs['page']['url']}", "evidence": "evidence", "source_url": kwargs["page"]["url"], "source_title": "Source", "retrieved_at": "2026-08-19T00:00:00+00:00", "confidence": 0.8}]
        if stage == "cross_reference":
            return {"corroborating_claims": [], "conflicting_claims": [], "uncertainty": [], "confidence": 0.7}
        if stage == "citations":
            return [{"title": "Source", "url": "https://source1.example.org/page", "snippet": "evidence"}]
        return {}

    monkeypatch.setattr(research, "action_search_web", fake_search)
    monkeypatch.setattr(research, "action_read_page", fake_read)
    monkeypatch.setattr(research, "_invoke", fake_invoke)
    result = research.action_deep_research({"topic": "Research Intel architecture deeply", "max_queries": 3, "max_pages": 3, "max_duration": 30})
    data = result["data"]
    assert result["success"] is True
    assert len(searched) >= 2
    assert len(read) >= 2
    assert data["research_mode"] == "DEEP_RESEARCH"
    assert data["source_count"] >= 2
    assert data["stopping_reason"]
    assert data["limits"]["max_pages"] == 3


def test_photo_printer_is_not_misclassified_as_image_search():
    assert ResearchMode.coerce(None, "Find me a cheap printer for photo printing") is ResearchMode.FAST_SEARCH
    assert ResearchMode.coerce(None, "Show me a photo of a GALAX RTX 5060") is ResearchMode.IMAGE_SEARCH


def test_ui_shopping_image_followup_refuses_without_verified_winner(monkeypatch):
    import ui_server

    session = "p22-no-winner"
    ui_server._set_shopping_state(session, {"active_topic": "photo printer", "site_constraint": "shopee.ph", "winner": None, "candidates": []})
    answer, images = ui_server._known_product_image_followup("Show me a photo of the cheapest one.", session)
    assert "verified product winner" in answer
    assert "shopee.ph" in answer
    assert images == []
