import json

from app.core.priority_llm import LLMOutcome, LLMOutcomeKind
from app.core.tool_loop import NativeWebToolAgent
from app.research.native_web_tools import (
    FetchResult,
    NativeWebTools,
    ReadablePageFetcher,
    SearchResult,
    WebProviderError,
)


class FakeProvider:
    name = "fake"

    def __init__(self, results=None, error=None):
        self.results = results or []
        self.error = error

    def search(self, query, count):
        if self.error:
            raise self.error
        return self.results[:count]


def test_native_search_normalizes_and_deduplicates_results(monkeypatch):
    native = NativeWebTools(enabled=True)
    monkeypatch.setattr(native, "_provider_chain", lambda: [FakeProvider([
        SearchResult("One", "https://example.com/article?utm_source=x", "first"),
        SearchResult("Duplicate", "https://example.com/article", "duplicate"),
        SearchResult("Two", "https://example.org", "second", "2026-08-20"),
    ])])
    result = native.search("freya", 5)
    assert result == [
        {"title": "One", "url": "https://example.com/article", "snippet": "first", "published_at": None},
        {"title": "Two", "url": "https://example.org/", "snippet": "second", "published_at": "2026-08-20"},
    ]


def test_provider_failure_is_distinguished_from_no_results(monkeypatch):
    native = NativeWebTools(enabled=True)
    failure = WebProviderError("EXA_NETWORK_FAILURE", "unreachable", "exa")
    monkeypatch.setattr(native, "_provider_chain", lambda: [FakeProvider(error=failure)])
    result = native.search("freya", 5)
    assert result["error"] == "search_failed"
    assert result["code"] == "EXA_NETWORK_FAILURE"


def test_fetcher_bounds_content_and_preserves_title(monkeypatch):
    class Raw:
        def read(self, limit):
            return (b"<html><head><title>Example</title></head><body><main>" + b"A useful sentence. " * 200 + b"</main></body></html>")

    class Response:
        ok = True
        status_code = 200
        url = "https://example.com/article"
        encoding = "utf-8"
        headers = {"content-type": "text/html; charset=utf-8"}
        raw = Raw()

    monkeypatch.setattr("app.research.native_web_tools.requests.get", lambda *args, **kwargs: Response())
    result = ReadablePageFetcher(max_chars=1_000).fetch("https://example.com/article")
    assert result.title == "Example"
    assert result.url == "https://example.com/article"
    assert len(result.content) <= 1_000
    assert result.truncated is True


def test_tool_schemas_advertise_only_native_web_tools():
    names = [schema["function"]["name"] for schema in NativeWebTools.schemas()]
    assert names == ["web_search", "web_fetch"]
    assert NativeWebTools.schemas()[0]["function"]["parameters"]["required"] == ["query"]


class FakeNativeTools:
    def __init__(self):
        self.calls = []

    @staticmethod
    def schemas():
        return NativeWebTools.schemas()

    def search(self, query, count=5):
        self.calls.append(("web_search", query, count))
        return [{"title": "Example", "url": "https://example.com", "snippet": "Useful result", "published_at": None}]

    def fetch(self, url):
        self.calls.append(("web_fetch", url))
        return FetchResult("Example", url, "Readable article content.").to_dict()


class FakeToolModel:
    def __init__(self):
        self.turns = 0

    def supports_tool_calling(self):
        return True

    def ask_outcome_with_tools(self, *, messages, tools, priority, timeout):
        self.turns += 1
        if self.turns == 1:
            raw = {"message": {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "web_search", "arguments": {"query": "freya", "count": 2}}}]}}
            return LLMOutcome(LLMOutcomeKind.SUCCESS, content="", raw_response=raw)
        if self.turns == 2:
            raw = {"message": {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "web_fetch", "arguments": {"url": "https://example.com"}}}]}}
            return LLMOutcome(LLMOutcomeKind.SUCCESS, content="", raw_response=raw)
        return LLMOutcome(LLMOutcomeKind.SUCCESS, content="Based on the article, Freya is a local-first assistant.")


def test_model_controls_search_then_fetch_then_final_answer():
    web = FakeNativeTools()
    result = NativeWebToolAgent(FakeToolModel(), native_tools=web).run("What is Freya?")
    assert result.success is True
    assert result.content.startswith("Based on the article")
    assert result.search_calls == 1
    assert result.fetch_calls == 1
    assert [call[0] for call in web.calls] == ["web_search", "web_fetch"]


def test_non_tool_model_is_not_given_web_tools():
    class NoTools:
        def supports_tool_calling(self):
            return False

    result = NativeWebToolAgent(NoTools()).run("What is current?")
    assert result.success is False
    assert result.error["error"] == "tools_unsupported"
