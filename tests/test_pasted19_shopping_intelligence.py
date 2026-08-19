from types import SimpleNamespace

import pytest

from app.core.tool_manager import ToolManager
from app.research.capability import (
    CrossReference,
    Fact,
    ResearchCapability,
    WebPage,
    canonicalize_url,
    normalize_shopping_query,
)


class EmptySearch:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.calls = []

    def search(self, query, max_results=5):
        self.calls.append((query, max_results))
        return {"success": bool(self.results), "query": query, "results": self.results[:max_results], "errors": []}


class PageReader:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def read(self, url):
        self.calls.append(url)
        page = self.pages.get(url)
        if page is None:
            return {"success": False, "url": url, "page": None, "error": "unavailable"}
        return {"success": True, "url": url, "page": page.to_dict(), "error": None}


class FakeBrowser:
    def __init__(self):
        self.calls = []

    def execute(self, action, inputs):
        self.calls.append((action, dict(inputs)))
        if action == "open_url":
            return {"success": True, "url": inputs.get("url"), "title": "Shopee search"}
        if action == "extract_links":
            return {"success": True, "data": {"links": [
                {"href": "https://www.amazon.com/dp/BAD#ref=top", "text": "Amazon printer"},
                {"href": "https://shopee.ph/photo-printer-i.123.456#details", "text": "Photo printer Canon"},
                {"href": "https://shopee.ph/photo-printer-i.123.456?utm_source=x", "text": "Photo printer Canon"},
            ]}}
        if action == "read_page":
            return {"success": True, "data": {"text": ""}, "text": ""}
        return {"success": False, "error": "unsupported"}


def _product_page(url, title, price):
    return WebPage(
        url=url,
        title=title,
        content=f"{title}\nPrice: {price}\nSold by: Verified Store\nIn stock\n4.8 out of 5 120 ratings",
        retrieved_at="2026-08-19T00:00:00+00:00",
        source_metadata={"image_results": [{"image_url": "https://cdn.example.test/product.jpg"}]},
    )


def _product_research(tmp_path, results, pages):
    research = ResearchCapability()
    research.search_tool = EmptySearch(results)
    research.page_reader = PageReader(pages)
    research.set_tool_manager(ToolManager(str(tmp_path)))
    return research


def test_query_normalization_extracts_intent_site_and_ranking():
    query = normalize_shopping_query("how about the cheapest printer in shopee for photo printing?")
    assert query.requested_domain == "shopee.ph"
    assert query.allowed_domains == ["shopee.ph"]
    assert query.ranking == "cheapest"
    assert query.normalized_query == "photo printer"
    assert "shopee" not in query.normalized_query.lower()


def test_hard_site_constraint_never_substitutes_amazon():
    research = ResearchCapability()
    research.search_tool = EmptySearch()
    research.set_tool_manager(ToolManager("."))
    browser = FakeBrowser()
    research.set_browser_capability(browser)
    result = research.action_search_web({
        "query": "cheapest printer in Shopee for photo printing",
        "normalized_query": "photo printer",
        "site_constraint": "shopee.ph",
        "allowed_domains": ["shopee.ph"],
        "max_results": 5,
    })
    assert result["success"] is True
    assert all("shopee.ph" in item["url"] for item in result["results"])
    assert all("amazon.com" not in item["url"] for item in result["results"])
    opened = [inputs["url"] for action, inputs in browser.calls if action == "open_url"]
    assert opened and all("shopee.ph" in url for url in opened)


def test_constrained_failure_is_explicit_and_does_not_fall_back(tmp_path):
    research = ResearchCapability()
    research.search_tool = EmptySearch()
    research.set_tool_manager(ToolManager(str(tmp_path)))
    browser = FakeBrowser()
    browser.execute = lambda action, inputs: {"success": True, "url": inputs.get("url"), "data": {"links": []}} if action == "extract_links" else ({"success": True, "url": inputs.get("url")} if action == "open_url" else {"success": True, "text": ""})
    research.set_browser_capability(browser)
    result = research.action_research_topic({"topic": "cheapest printer in shopee", "max_sources": 3})
    assert result["success"] is False
    assert "shopee.ph" in result["data"]["answer"].lower()
    assert "amazon" not in result["data"]["answer"].lower()


def test_product_research_parses_prices_sorts_winner_and_returns_images(tmp_path):
    cheap_url = "https://shopee.ph/canon-mini-i.1.2#overview"
    expensive_url = "https://shopee.ph/canon-pro-i.3.4?utm_source=ad"
    results = [{"title": "Canon mini", "url": cheap_url}, {"title": "Canon pro", "url": expensive_url}]
    pages = {
        canonicalize_url(cheap_url): _product_page(canonicalize_url(cheap_url), "Canon Mini Photo Printer", "₱3,499"),
        canonicalize_url(expensive_url): _product_page(canonicalize_url(expensive_url), "Canon Pro Photo Printer", "₱5,999"),
    }
    research = _product_research(tmp_path, results, pages)
    result = research.action_research_topic({"topic": "Find the cheapest photo printer on Shopee", "max_sources": 5})
    assert result["success"] is True
    data = result["data"]
    assert data["winner"]["price"] == 3499.0
    assert [item["price"] for item in data["product_candidates"]] == [3499.0, 5999.0]
    assert data["comparison"]["lowest_price"] == 3499.0
    assert data["image_results"][0]["match_type"] == "exact_product_page"
    assert "cheapest" in data["answer"].lower()
    assert "Based on the retrieved sources" not in data["answer"]


def test_url_canonicalization_deduplicates_fragments_and_tracking():
    assert canonicalize_url("https://www.amazon.com/s?k=printer&utm_source=x#skippedLink") == "https://www.amazon.com/s?k=printer"


def test_cross_reference_does_not_call_distinct_listing_prices_a_conflict():
    facts = [
        Fact("Printer listing price is $99 from seller A", "", "https://shop.example/a#x", "A", "2026-08-19"),
        Fact("Printer listing price is $129 from seller B", "", "https://shop.example/b?utm_source=x", "B", "2026-08-19"),
    ]
    result = CrossReference().compare(facts, claims_to_check=["printer price"])
    assert result.conflicting_claims == []


def test_three_turn_shopping_state_resolves_cheapest_product_image(monkeypatch):
    import ui_server

    session = "p19-test-session"
    first = {
        "shopping_query": {"normalized_query": "photo printer", "requested_domain": "amazon.com"},
        "product_candidates": [{"product_name": "Printer A", "price": 120.0, "currency": "USD", "source_url": "https://amazon.com/dp/A", "product_url": "https://amazon.com/dp/A", "image_url": "https://cdn.test/a.jpg", "marketplace": "amazon.com"}],
        "winner": {"product_name": "Printer A", "price": 120.0, "currency": "USD", "source_url": "https://amazon.com/dp/A", "product_url": "https://amazon.com/dp/A", "image_url": "https://cdn.test/a.jpg", "marketplace": "amazon.com"},
        "comparison": {"basis": "cheapest"},
    }
    state = ui_server._shopping_state_from_research(first)
    ui_server._set_shopping_state(session, state)
    answer, images = ui_server._known_product_image_followup("can you show me a photo of the cheapest printer?", session)
    assert "Printer A" in answer
    assert images and images[0]["image_url"] == "https://cdn.test/a.jpg"
    assert ui_server._get_shopping_state(session)["winner"]["product_name"] == "Printer A"


def test_unscripted_laptop_ssd_followup_keeps_active_topic_and_winner():
    import ui_server

    state = ui_server._shopping_state_from_research({
        "shopping_query": {"normalized_query": "laptop ssd", "requested_domain": ""},
        "product_candidates": [{"product_name": "SSD Laptop", "price": 800.0}],
        "winner": {"product_name": "SSD Laptop", "price": 800.0},
        "comparison": {"basis": "price"},
    })
    next_state = ui_server._shopping_state_from_research({"shopping_query": {"normalized_query": "laptop ssd reviews", "requested_domain": ""}, "product_candidates": [], "winner": None}, state)
    assert next_state["active_topic"] == "laptop ssd reviews"
    assert next_state["winner"]["product_name"] == "SSD Laptop"
