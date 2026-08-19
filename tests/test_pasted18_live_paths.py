from __future__ import annotations

import base64
from pathlib import Path

import pytest

from app.core.protocols import SystemConfig
from app.intent.classifier import classify_intent
from app.research.capability import ResearchCapability
from main import FreyaApp


@pytest.fixture
def production_app(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    app = FreyaApp(workspace, SystemConfig(workspace=workspace, enable_autonomy=False))
    app.start()
    try:
        yield app
    finally:
        app.shutdown()


@pytest.mark.parametrize(
    "prompt",
    [
        "What is the latest CPU of Intel today?",
        "What's Intel's newest desktop processor?",
        "Find current Intel processor news.",
        "Find me the cheapest RAM.",
        "Find a cheap 32GB DDR5 kit.",
        "Compare RTX 5070 prices.",
        "Find reviews of this laptop.",
    ],
)
def test_current_product_and_review_requests_route_to_research_before_planning(production_app, prompt):
    route = production_app.system.facade._router.route(prompt)
    assert route.capability_name == "research_capability"
    assert route.is_direct_answer is True
    assert route.capability_name != "list_files"


@pytest.mark.parametrize(
    "prompt",
    [
        "Open https://example.com and tell me the page title.",
        "Open another tab.",
        "Go back to the first tab.",
    ],
)
def test_browser_requests_have_browser_precedence(production_app, prompt):
    route = production_app.system.facade._router.route(prompt)
    assert route.capability_name == "browser_capability"
    assert route.capability_name not in {"list_files", "show_memory", "automation", "system_status"}


class FakeBrowser:
    def __init__(self):
        self.calls = []

    def execute(self, action, inputs):
        self.calls.append((action, dict(inputs)))
        if action == "open_url":
            return {"success": True, "action": action, "url": inputs.get("url"), "title": "Search"}
        if action == "extract_links":
            return {
                "success": True,
                "action": action,
                "data": {
                    "links": [
                        {"href": "https://www.intel.com/content/www/us/en/newsroom/news.html", "text": "Intel latest processor news"},
                        {"href": "https://www.google.com/search?q=irrelevant", "text": "Google"},
                    ]
                },
            }
        if action == "read_page":
            return {
                "success": True,
                "action": action,
                "url": inputs.get("url", "https://www.intel.com/news"),
                "title": "Intel News",
                "text": "Intel published the latest processor information with product specifications and release details.",
            }
        return {"success": False, "action": action, "error": "unsupported fake action"}


def test_research_uses_browser_fallback_when_fast_search_is_unusable():
    capability = ResearchCapability()
    browser = FakeBrowser()
    capability.set_browser_capability(browser)

    result = capability.action_search_web({"query": "latest Intel processor", "max_results": 3})

    assert result["success"] is True
    assert result["provider"] == "playwright_chromium"
    assert result["results"][0]["url"].startswith("https://www.intel.com/")
    assert [action for action, _ in browser.calls][:2] == ["open_url", "extract_links"]


def test_browser_page_reader_is_used_when_fast_page_reader_fails():
    capability = ResearchCapability()
    browser = FakeBrowser()
    capability.set_browser_capability(browser)

    result = capability.action_read_page({"url": "https://www.intel.com/news"})

    assert result["success"] is True
    assert result["page"]["source_metadata"]["provider"] == "playwright_chromium"
    assert "processor information" in result["page"]["content"]
    assert [action for action, _ in browser.calls] == ["open_url", "read_page"]


def test_bing_redirect_urls_are_unwrapped_without_accepting_search_homepages():
    target = "https://www.intel.com/content/www/us/en/newsroom/news.html"
    encoded = base64.urlsafe_b64encode(target.encode()).decode().rstrip("=")
    wrapped = f"https://www.bing.com/ck/a?u=a1{encoded}"
    assert ResearchCapability._browser_result_url(wrapped) == target
    assert ResearchCapability._browser_result_url("https://www.bing.com/") == "https://www.bing.com/"


def test_google_news_rss_results_are_real_and_query_relevant():
    rss = """<rss><channel><item><title>Intel launches a new desktop processor</title><link>https://www.intel.com/news/processor</link><description>Official processor announcement.</description></item><item><title>Unrelated travel article</title><link>https://example.com/travel</link></item></channel></rss>"""
    records = ResearchCapability._browser_rss_records(rss, "latest Intel processor", 5)
    assert len(records) == 1
    assert records[0]["url"] == "https://www.intel.com/news/processor"


def test_freshness_classification_requires_external_evidence():
    classification = classify_intent("What is the latest CPU of Intel today?")
    assert classification.external_information_required is True
    assert "fresh_external_evidence" in classification.context_requirements

