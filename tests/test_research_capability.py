from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from app.capabilities.registration_bridge import CapabilityRegistrationBridge
from app.capabilities.router import CapabilityRouter
from app.core.tool_manager import ToolManager
from app.orchestrator.capability_registry import CapabilityRegistry, reset_capability_registry
from app.orchestrator.capabilities import create_all_capabilities
from app.research.capability import (
    CitationManager,
    CrossReference,
    Fact,
    FactExtractor,
    ResearchCapability,
    SourceEvaluator,
    WebPage,
    WebPageReader,
    WebSearchTool,
    validate_public_url,
)


@pytest.fixture(autouse=True)
def reset_registry():
    reset_capability_registry()
    yield
    reset_capability_registry()


class FakeSearch:
    def __init__(self, results=None):
        self.results = results or []
        self.calls = []

    def search(self, query, max_results=5):
        self.calls.append((query, max_results))
        return {"success": True, "query": query, "results": self.results[:max_results], "errors": []}


class FakeReader:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def read(self, url):
        self.calls.append(url)
        page = self.pages.get(url)
        if page is None:
            return {"success": False, "url": url, "page": None, "error": "unavailable"}
        return {"success": True, "url": url, "page": page.to_dict(), "error": None}


@pytest.fixture
def research_with_tools(tmp_path):
    research = ResearchCapability()
    results = [
        {"title": "Official source", "url": "https://docs.example.org/standard", "snippet": "official evidence", "source": "docs.example.org", "rank": 1, "relevance": 1.0},
        {"title": "Independent source", "url": "https://research.example.net/article", "snippet": "independent evidence", "source": "research.example.net", "rank": 2, "relevance": 0.5},
    ]
    pages = {
        results[0]["url"]: WebPage(
            url=results[0]["url"],
            title=results[0]["title"],
            content="The protocol supports encrypted transport. It requires version 2 for production deployments.",
            retrieved_at="2026-08-15T00:00:00+00:00",
            source_metadata={"fetch_timestamp": "2026-08-15T00:00:00+00:00"},
        ),
        results[1]["url"]: WebPage(
            url=results[1]["url"],
            title=results[1]["title"],
            content="Independent testing confirms the protocol supports encrypted transport. It recommends version 2 for production deployments.",
            retrieved_at="2026-08-15T00:00:00+00:00",
            source_metadata={"fetch_timestamp": "2026-08-15T00:00:00+00:00"},
        ),
    }
    search = FakeSearch(results)
    reader = FakeReader(pages)
    research.search_tool = search
    research.page_reader = reader
    research.set_tool_manager(ToolManager(str(tmp_path)))
    return research, search, reader


def test_research_capability_is_executable_and_in_factory():
    capabilities = create_all_capabilities()
    research = next(capability for capability in capabilities if capability.name == "research_capability")
    assert isinstance(research, ResearchCapability)
    assert research.is_executable()
    assert research.metadata.safe_query is True
    assert research.metadata.required_collaborators == ["tool_manager"]
    assert {"search_web", "read_page", "research_topic", "compare_sources", "verify_claim"}.issubset(
        research.metadata.supported_actions
    )


def test_research_capability_registers_in_canonical_registry_and_routes_through_tool_manager(tmp_path, monkeypatch):
    registry = CapabilityRegistry()
    research = ResearchCapability()
    fake_search = FakeSearch([{"title": "Result", "url": "https://example.org", "snippet": "snippet"}])
    research.search_tool = fake_search
    tool_manager = ToolManager(str(tmp_path))
    research.set_tool_manager(tool_manager)
    assert registry.register(research, registered_by="test")
    registry.start()

    router = CapabilityRouter()
    bridge = CapabilityRegistrationBridge(registry=registry, router=router, tool_manager=tool_manager)
    bridge.sync()

    result = router.execute_named("research_capability", query="search the web")
    assert result.success is True
    assert result.data["results"][0]["url"] == "https://example.org"
    assert "research::web_search" in tool_manager.tools
    assert "capability::research_capability" in tool_manager.tools
    assert fake_search.calls == [("search the web", 5)]


def test_web_search_is_lightweight_and_reuses_importer_search(monkeypatch):
    calls = []

    class Importer:
        async def search(self, query, max_results=5):
            calls.append((query, max_results))
            return [{"title": "A", "url": "https://example.org", "snippet": "S", "source": "example.org", "rank": 1, "relevance": 1.0}]

    result = WebSearchTool(Importer()).search("Freya architecture", max_results=3)
    assert result["success"] is True
    assert result["results"][0]["title"] == "A"
    assert calls == [("Freya architecture", 3)]


def test_web_page_reader_reuses_importer_and_preserves_page_provenance():
    item = SimpleNamespace(
        title="A page",
        content="Readable page content with enough detail.",
        source_uri="https://example.org/page",
        source_metadata={"fetch_timestamp": "2026-08-15T00:00:00+00:00"},
    )
    calls = []

    class Importer:
        async def import_from_url(self, url):
            calls.append(url)
            return SimpleNamespace(success=True, items=[item], errors=[])

    result = WebPageReader(Importer()).read("https://example.org/page")
    assert result["success"] is True
    assert result["page"].url == "https://example.org/page"
    assert result["page"].retrieved_at == "2026-08-15T00:00:00+00:00"
    assert calls == ["https://example.org/page"]


def test_invalid_and_private_urls_are_blocked():
    assert validate_public_url("not-a-url")[0] is False
    assert validate_public_url("file:///etc/passwd")[0] is False
    assert validate_public_url("http://127.0.0.1:8000")[0] is False
    assert validate_public_url("https://example.org")[0] is True


def test_source_evaluator_returns_structured_quality():
    page = WebPage(
        url="https://docs.python.org/3/library/asyncio.html",
        title="Asyncio documentation",
        content="Official documentation describes asynchronous execution.",
        retrieved_at="2026-08-15T00:00:00+00:00",
    )
    quality = SourceEvaluator().evaluate(page, query="asynchronous execution")
    assert quality.score > 0
    assert quality.authority == "authoritative"
    assert quality.source_type in {"primary", "secondary/unclear"}
    assert isinstance(quality.to_dict()["uncertainty"], list)


def test_fact_extraction_retains_source_provenance():
    page = WebPage(
        url="https://example.org/evidence",
        title="Evidence page",
        content="The system uses a bounded retry policy. This behavior is documented for production use.",
        retrieved_at="2026-08-15T00:00:00+00:00",
    )
    facts = FactExtractor().extract(page, query="retry policy")
    assert facts
    assert facts[0].source_url == page.url
    assert facts[0].source_title == page.title
    assert facts[0].retrieved_at == page.retrieved_at
    assert facts[0].evidence


def test_cross_reference_surfaces_corroboration_and_conflict():
    facts = [
        Fact("The limit is 10 requests per second.", "The limit is 10 requests per second.", "https://a.example", "A", "t1"),
        Fact("The limit is 10 requests per second.", "The limit is 10 requests per second.", "https://b.example", "B", "t2"),
        Fact("The limit is 5 requests per second.", "The limit is 5 requests per second.", "https://c.example", "C", "t3"),
    ]
    comparison = CrossReference().compare(facts, claims_to_check=["The limit is 10 requests per second.", "An unsupported claim"])
    assert comparison.corroborating_claims
    assert comparison.conflicting_claims
    assert "An unsupported claim" in comparison.unsupported_claims
    assert comparison.uncertainty


def test_citation_manager_never_validates_fabricated_evidence():
    facts = [Fact("A supported claim", "A supported claim", "https://example.org", "Page", "t1")]
    manager = CitationManager()
    citations = manager.create(facts)
    assert citations[0].source_url == facts[0].source_url
    assert manager.validate(citations, facts)["fabricated_count"] == 0
    fabricated = [{**citations[0].to_dict(), "evidence": "Evidence not present on source"}]
    assert manager.validate(fabricated, facts)["fabricated_count"] == 1


def test_research_topic_runs_multi_source_workflow_and_preserves_citations(research_with_tools):
    research, search, reader = research_with_tools
    result = research.research_topic("encrypted transport", max_sources=2)
    assert result["success"] is True
    data = result["data"]
    assert len(data["sources"]) == 2
    assert len(data["citations"]) >= 1
    assert all(citation["source_url"] for citation in data["citations"])
    assert reader.calls == ["https://docs.example.org/standard", "https://research.example.net/article"]
    assert search.calls == [("encrypted transport", 2)]


def test_verify_claim_compares_sources(research_with_tools):
    research, _, _ = research_with_tools
    result = research.verify_claim("protocol supports encrypted transport", max_sources=2)
    assert result["success"] is True
    assert result["data"]["status"] in {"supported", "partially_supported", "mixed"}
    assert len(result["data"]["supporting_sources"]) >= 1


def test_research_learning_is_opt_in_and_uses_existing_pipeline_gate():
    research = ResearchCapability()
    calls = []

    class Pipeline:
        def run(self, candidate):
            calls.append(candidate)
            return SimpleNamespace(final_decision=SimpleNamespace(value="no"))

    research.set_learning_pipeline(Pipeline())
    not_requested = research.action_learn_finding({"research_result": {"citations": []}, "remember": False})
    assert not_requested["accepted"] is False
    assert calls == []

    requested = research.action_learn_finding(
        {"research_result": {"citations": [{"source_url": "https://example.org"}]}, "remember": True}
    )
    assert requested["success"] is True
    assert requested["accepted"] is False
    assert calls[0].source_component == "ResearchCapability"
    assert calls[0].metadata["provenance_preserved"] is True


def test_knowledge_base_remains_separate_from_research():
    names = {capability.name for capability in create_all_capabilities()}
    assert "knowledge_base" in names
    assert "research_capability" in names
    assert "web_search_capability" not in names
