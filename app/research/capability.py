"""Public-web research capability for Freya.

The module intentionally keeps the research domain model separate from the
canonical workflow capability registry.  ``ResearchCapability`` is the
registry-facing adapter; all network and research stages are exposed as named
ToolManager tools when the capability is wired into the runtime.
"""

from __future__ import annotations

import asyncio
import base64
from html import unescape
import concurrent.futures

import ipaddress
import json
import logging
import requests
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import quote_plus, urljoin, urlparse, parse_qs, parse_qsl, urlencode, urlunparse
from urllib.request import Request, urlopen
from bs4 import BeautifulSoup

from app.orchestrator.capability_registry import Capability, CapabilityCategory, CapabilityMetadata, CapabilityState
from app.software_engineering_knowledge.external_import import InternetResearchImporter
from app.research.osint import WebSearchCapability, OSINTCapability
from app.free_image_research_providers import FreeImageResearchChain

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Structured research records
# ---------------------------------------------------------------------------

@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    source: str = ""
    rank: int = 0
    relevance: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ShoppingQuery:
    raw_query: str
    intent: str = "product_research"
    product_category: str = ""
    use_case: str = ""
    ranking: str = ""
    requested_site: str = ""
    requested_domain: str = ""
    allowed_domains: List[str] = field(default_factory=list)
    preferred_marketplace: str = ""
    region: str = ""
    normalized_query: str = ""
    follow_up: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProductListing:
    product_name: str
    model: str = ""
    product_type: str = ""
    price: Optional[float] = None
    currency: str = ""
    seller: str = ""
    marketplace: str = ""
    source_url: str = ""
    product_url: str = ""
    image_url: str = ""
    availability: str = ""
    shipping: Optional[float] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    specifications: Dict[str, Any] = field(default_factory=dict)
    source: str = ""
    retrieved_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    confidence: float = 0.0
    evidence: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WebPage:

    url: str
    title: str
    content: str
    retrieved_at: str
    source_metadata: Dict[str, Any] = field(default_factory=dict)
    fetch_error: Optional[str] = None

    @property
    def domain(self) -> str:
        return (urlparse(self.url).hostname or "").lower()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SourceQuality:
    url: str
    title: str
    domain: str
    score: float
    authority: str
    source_type: str
    relevance_score: float
    recency_score: Optional[float]
    corroboration_score: float
    spam_flags: List[str] = field(default_factory=list)
    rationale: List[str] = field(default_factory=list)
    uncertainty: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Fact:
    claim: str
    evidence: str
    source_url: str
    source_title: str
    retrieved_at: str
    context: str = ""
    confidence: float = 0.0
    fact_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Citation:
    citation_id: str
    claim: str
    evidence: str
    source_url: str
    source_title: str
    retrieved_at: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CrossReferenceResult:
    corroborating_claims: List[Dict[str, Any]] = field(default_factory=list)
    conflicting_claims: List[Dict[str, Any]] = field(default_factory=list)
    unique_claims: List[Dict[str, Any]] = field(default_factory=list)
    unsupported_claims: List[str] = field(default_factory=list)
    missing_evidence: List[str] = field(default_factory=list)
    uncertainty: List[str] = field(default_factory=list)

    @property
    def confidence(self) -> float:
        corroborated = len(self.corroborating_claims)
        conflicts = len(self.conflicting_claims)
        if not corroborated and not conflicts:
            return 0.0
        return max(0.0, min(1.0, (corroborated - conflicts * 0.5) / max(1, corroborated)))

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["confidence"] = self.confidence
        return result


@dataclass
class ResearchResult:
    topic: str
    answer: str
    key_findings: List[Dict[str, Any]]
    supporting_evidence: List[Dict[str, Any]]
    sources: List[Dict[str, Any]]
    citations: List[Dict[str, Any]]
    conflicts: List[Dict[str, Any]]
    uncertainty: List[str]
    confidence: float
    errors: List[str] = field(default_factory=list)
    partial: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Safety and async helpers
# ---------------------------------------------------------------------------

_PUBLIC_SCHEMES = {"http", "https"}
_BLOCKED_HOSTS = {"localhost", "localhost.localdomain", "ip6-localhost"}


def validate_public_url(url: Any) -> tuple[bool, str]:
    """Allow only public HTTP(S) URLs and reject obvious local-network targets.

    Freya has no dedicated URL policy object today.  This small guard is kept
    at the shared page-reader boundary so every research fetch receives the
    same protection and the existing importer remains unchanged for its
    legacy callers.
    """
    if not isinstance(url, str) or not url.strip():
        return False, "URL must be a non-empty string"
    value = url.strip()
    try:
        parsed = urlparse(value)
    except ValueError as error:
        return False, f"Invalid URL: {error}"
    if parsed.scheme.lower() not in _PUBLIC_SCHEMES:
        return False, "Only http and https URLs are supported"
    if not parsed.hostname:
        return False, "URL must include a hostname"
    if parsed.username or parsed.password:
        return False, "URLs containing embedded credentials are blocked"
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in _BLOCKED_HOSTS or hostname.endswith(".localhost"):
        return False, "Localhost URLs are blocked"
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and (
        address.is_private or address.is_loopback or address.is_link_local
        or address.is_reserved or address.is_unspecified
    ):
        return False, "Private or local-network URLs are blocked"
    return True, ""


def _run_coroutine(coroutine):
    """Run importer coroutines from both sync code and an active event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)

    # ``asyncio.run`` cannot be nested.  Use a short-lived worker only for the
    # synchronous capability boundary; it does not create a background service.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coroutine).result()


def _jsonable(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value
_SEARCH_STOPWORDS = {"the", "and", "for", "with", "from", "search", "latest", "newest", "today", "current", "currently", "what", "is", "of", "to", "me", "please", "find", "information", "about", "can", "you", "this", "that", "one", "some", "found", "kit", "kits", "web", "internet"}
_PRODUCT_QUERY_WORDS = {"cheapest", "cheap", "affordable", "price", "prices", "lowest", "shopping", "product", "products", "listing", "listings", "availability", "available", "buy", "purchase", "review", "reviews"}
_BLOCKED_BROWSER_RESULT_TERMS = ("skip to main", "select address", "sign in", "sign-in", "register", "login", "captcha", "access denied", "0 items that match")


def _is_product_query(query: str) -> bool:
    return bool(_PRODUCT_QUERY_WORDS.intersection({token.lower() for token in re.findall(r"[a-z0-9]{3,}", str(query or ""))}))


_SITE_ALIASES = {
    "shopee": "shopee.ph",
    "shopee.ph": "shopee.ph",
    "shopee.com": "shopee.com",
    "amazon": "amazon.com",
    "amazon.com": "amazon.com",
    "lazada": "lazada.com.ph",
    "lazada.com": "lazada.com",
    "lazada.com.ph": "lazada.com.ph",
    "ebay": "ebay.com",
    "ebay.com": "ebay.com",
    "walmart": "walmart.com",
    "walmart.com": "walmart.com",
    "newegg": "newegg.com",
    "newegg.com": "newegg.com",
}
_SITE_PATTERNS = re.compile(r"\b(shopee(?:\.com(?:\.ph)?|\.ph)?|amazon(?:\.com)?|lazada(?:\.com(?:\.ph)?|\.ph)?|ebay(?:\.com)?|walmart(?:\.com)?|newegg(?:\.com)?)\b", re.I)
_RANKING_PATTERNS = re.compile(r"\b(?:cheapest|cheaper|lowest(?:\s+price)?|best\s+price|most\s+affordable|affordable|price|prices|compare|comparison)\b", re.I)
_QUERY_FILLER = re.compile(r"\b(?:how\s+about|what\s+about|can\s+you|could\s+you|please|find|show\s+me|look\s+for|search\s+for|in|on|from|the|a|an|me|one|it|that|now|today)\b", re.I)


def canonicalize_url(value: Any) -> str:
    """Canonicalize public evidence URLs for source and listing deduplication."""
    raw = str(value or "").strip()
    if not raw.startswith(("http://", "https://")):
        return ""
    parsed = urlparse(raw)
    query = [(key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True)
             if not (key.lower().startswith("utm_") or key.lower() in {"ref", "ref_", "tag", "linkcode", "camp", "psc", "spm"})]
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    host = (parsed.hostname or "").lower()
    if host.endswith("amazon.com") and re.match(r"^/(?:dp|gp/product)/", path, re.I):
        query = []
    return urlunparse((parsed.scheme.lower(), host, path.rstrip("/") or "/", "", urlencode(query), ""))


def normalize_shopping_query(query: str, *, region: str = "") -> ShoppingQuery:
    raw = re.sub(r"\s+", " ", str(query or "")).strip(" .?!")
    lowered = raw.lower()
    site_match = _SITE_PATTERNS.search(lowered)
    requested_site = site_match.group(1).lower() if site_match else ""
    requested_domain = _SITE_ALIASES.get(requested_site, requested_site)
    region_value = str(region or "").strip().lower()
    if re.search(r"\b(?:philippines|philippine|pinoy|manila|peso|php|₱)\b", lowered):
        region_value = "ph"
    if requested_site == "shopee" and region_value in {"", "ph", "philippines"}:
        requested_domain = "shopee.ph"
    ranking_match = _RANKING_PATTERNS.search(lowered)
    ranking = "cheapest" if ranking_match and re.search(r"\b(?:cheapest|cheaper|lowest|affordable)\b", lowered) else (ranking_match.group(0).lower() if ranking_match else "")
    use_case = ""
    use_match = re.search(r"\bfor\s+(.+?)(?:\s+on\s+|\s+in\s+|\s+from\s+|\s*$)", lowered)
    if use_match:
        use_case = re.sub(r"\s+", " ", use_match.group(1)).strip(" .?!")
    topical = _SITE_PATTERNS.sub(" ", lowered)
    topical = _RANKING_PATTERNS.sub(" ", topical)
    topical = _QUERY_FILLER.sub(" ", topical)
    topical = re.sub(r"\b(?:photo\s+printing|photo\s+print(?:ing)?)\b", "photo printer", topical)
    topical = re.sub(r"\bprinter\s+(?:for\s+)?photo\s+printer\b", "photo printer", topical)
    topical = re.sub(r"\bprinter\s+photo\b", "photo printer", topical)
    topical = re.sub(r"\s+", " ", topical).strip(" .?!")
    if not topical:
        topical = re.sub(r"\s+", " ", raw).strip(" .?!")
    normalized = topical
    if requested_domain and not normalized:
        normalized = "product"
    return ShoppingQuery(
        raw_query=raw,
        product_category=topical,
        use_case=use_case,
        ranking=ranking,
        requested_site=requested_site,
        requested_domain=requested_domain,
        allowed_domains=[requested_domain] if requested_domain else [],
        preferred_marketplace=requested_domain,
        region=region_value,
        normalized_query=normalized,
        follow_up=bool(re.search(r"\b(?:it|that|the\s+cheapest|the\s+best|one|printer|laptop|product)\b", lowered)),
    )


def _parse_price(text: str) -> tuple[Optional[float], str]:
    value = re.sub(r"\s+", " ", str(text or ""))
    patterns = [
        (r"(?:₱|PHP)\s*([0-9][0-9,]*(?:\.\d{1,2})?)", "PHP"),
        (r"(?:\$|USD)\s*([0-9][0-9,]*(?:\.\d{1,2})?)", "USD"),
        (r"(?:€|EUR)\s*([0-9][0-9,.]*(?:\d{1,2})?)", "EUR"),
        (r"(?:£|GBP)\s*([0-9][0-9,.]*(?:\d{1,2})?)", "GBP"),
        (r"\b([0-9][0-9,]*(?:\.\d{1,2})?)\s*(PHP|USD|EUR|GBP)\b", None),
    ]
    for pattern, currency in patterns:
        match = re.search(pattern, value, re.I)
        if not match:
            continue
        try:
            amount = float(match.group(1).replace(",", ""))
        except ValueError:
            continue
        return amount, (currency or match.group(2).upper())
    return None, ""


def _is_search_landing_page(page: WebPage) -> bool:
    sample = f"{page.title} {page.content[:5000]}".lower()
    path = (urlparse(page.url).path or "").lower()
    markers = ("sort by: featured", "results for", "search results", "refine your", "skip to main", "select address", "1-16 of")
    marketplace_search_path = path in {"/s", "/search", "/search/", "/sch/i.html", "/catalog/"} or path.startswith("/search/")
    return marketplace_search_path or any(marker in sample for marker in markers) or any(marker in sample for marker in ("sign in or create account", "create account", "login to continue"))


def _extract_product_listing(raw_result: Dict[str, Any], page: WebPage, shopping: ShoppingQuery) -> Optional[ProductListing]:
    if _is_search_landing_page(page):
        return None
    source_url = canonicalize_url(page.url or raw_result.get("url"))
    if not source_url:
        return None
    title = re.sub(r"\s+", " ", str(page.title or raw_result.get("title") or "")).strip()
    title = re.sub(r"\s*[|–-]\s*(?:Amazon|Shopee|Lazada|eBay|Walmart).*?$", "", title, flags=re.I).strip()
    content = re.sub(r"\s+", " ", str(page.content or ""))
    price, currency = _parse_price(content[:30000])
    if price is None:
        price, currency = _parse_price(str(raw_result.get("snippet") or ""))
    host = (urlparse(source_url).hostname or "").lower()
    marketplace = next((domain for domain in shopping.allowed_domains if host == domain or host.endswith("." + domain)), host.replace("www.", ""))
    seller_match = re.search(r"\b(?:sold by|seller|store)\s*[:\-]?\s*([A-Z0-9][^|.;]{2,80})", content, re.I)
    seller = re.sub(r"\s+", " ", seller_match.group(1)).strip() if seller_match else marketplace
    seller = re.split(r"\s+(?:this price|price:|available|ships? from|delivery)\b", seller, maxsplit=1, flags=re.I)[0].strip(" .:-") or marketplace
    availability_match = re.search(r"\b(in stock|out of stock|available|unavailable|pre[- ]?order)\b", content, re.I)
    rating_match = re.search(r"\b([1-5](?:\.\d)?)\s*(?:out of 5|/5|stars?)\b", content, re.I)
    review_match = re.search(r"\b([0-9][0-9,]*)\s+(?:ratings?|reviews?)\b", content, re.I)
    metadata = page.source_metadata if isinstance(page.source_metadata, dict) else {}
    image_results = metadata.get("image_results") if isinstance(metadata.get("image_results"), list) else []
    image_url = ""
    for item in image_results:
        if isinstance(item, dict) and item.get("image_url"):
            image_url = str(item["image_url"])
            break
    if not image_url:
        try:
            from app.free_image_research_providers import extract_public_page_images
            exact_images = extract_public_page_images(source_url, limit=3)
            if exact_images:
                image_url = str(exact_images[0].get("image_url") or "")
        except Exception:
            image_url = ""
    confidence = 0.75 if price is not None else 0.45

    return ProductListing(
        product_name=title[:240] or str(raw_result.get("title") or shopping.normalized_query)[:240],
        product_type=shopping.product_category,
        price=price,
        currency=currency,
        seller=seller[:120],
        marketplace=marketplace,
        source_url=source_url,
        product_url=source_url,
        image_url=image_url,
        availability=availability_match.group(1).lower() if availability_match else "",
        rating=float(rating_match.group(1)) if rating_match else None,
        review_count=int(review_match.group(1).replace(",", "")) if review_match else None,
        source=str(raw_result.get("source") or "public_web"),
        confidence=confidence,
        evidence=content[:1200],
    )


def _query_relevant_public_search_results(records: Any, query: str) -> list[dict[str, Any]]:
    usable = _usable_public_search_results(records)
    terms = {token.lower() for token in re.findall(r"[a-z0-9]{3,}", str(query or "").lower()) if token.lower() not in _SEARCH_STOPWORDS}
    if not terms:
        return usable
    relevant = []
    for item in usable:
        haystack = " ".join(str(item.get(field) or "") for field in ("title", "snippet", "url", "source_domain")).lower()
        overlap = sum(1 for term in terms if term in haystack)
        minimum_overlap = 2 if len(terms) >= 2 else 1
        if overlap >= minimum_overlap:
            relevant.append(item)
    return relevant


def _usable_public_search_results(records: Any) -> list[dict[str, Any]]:

    """Keep actual public pages and reject search-homepage garbage."""
    results: list[dict[str, Any]] = []
    search_hosts = {"google.com", "www.google.com", "google.com.ph", "www.google.com.ph", "search.google", "bing.com", "www.bing.com", "search.yahoo.com", "yahoo.com", "www.yahoo.com", "duckduckgo.com", "html.duckduckgo.com", "startpage.com", "www.startpage.com"}
    for raw in records if isinstance(records, list) else []:
        if not isinstance(raw, dict):
            continue
        item = dict(_jsonable(raw))
        url = str(item.get("url") or item.get("source_url") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        path = (parsed.path or "/").rstrip("/").lower() or "/"
        is_search_home = host in search_hosts and (path in {"/", "/search", "/xhtml", "/html", "/images"} or path.startswith("/search/") or path.startswith("/xhtml/"))
        title = str(item.get("title") or "").strip().lower()
        if is_search_home or (host in search_hosts and title in {"google search", "bing", "yahoo search", "duckduckgo"}):
            continue
        if not str(item.get("title") or item.get("snippet") or "").strip():
            continue
        item["url"] = url
        results.append(item)
    return results



# ---------------------------------------------------------------------------
# Research tools
# ---------------------------------------------------------------------------

class WebSearchTool:
    """Structured public-web search with a primary importer and bounded fallback."""

    def __init__(self, importer: Optional[InternetResearchImporter] = None):
        self.importer = importer or InternetResearchImporter()

    @staticmethod
    def _duckduckgo_fallback(query: str, max_results: int) -> Dict[str, Any]:
        url = "https://html.duckduckgo.com/html/?q=" + quote_plus(query)
        request = Request(url, headers={"User-Agent": "Freya/1.0 public-research-fallback"})
        with urlopen(request, timeout=15) as response:
            html = response.read().decode("utf-8", errors="replace")
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        results = []
        for item in soup.select(".result")[: max(1, min(int(max_results), 10))]:
            link = item.select_one("a.result__a")
            if link is None:
                continue
            href = str(link.get("href") or "").strip()
            title = link.get_text(" ", strip=True)
            snippet_node = item.select_one(".result__snippet")
            snippet = snippet_node.get_text(" ", strip=True) if snippet_node else ""
            if not href or not title:
                continue
            results.append({"title": title, "url": href, "snippet": snippet, "source": "duckduckgo_html"})
        return {"success": bool(results), "query": query, "results": results, "errors": [] if results else ["DuckDuckGo returned no parseable results"], "provider": "duckduckgo_html"}

    @staticmethod
    def _google_html_fallback(query: str, max_results: int) -> Dict[str, Any]:
        url = "https://www.google.com/search?" + urlencode({"q": query, "num": min(10, max_results)})
        try:
            response = requests.get(url, headers={"User-Agent": "Mozilla/5.0 Freya public research"}, timeout=max(3.0, float(os.getenv("FREYA_SEARCH_PROVIDER_TIMEOUT", "12"))))
            response.raise_for_status()
            soup = BeautifulSoup(response.text[:2_000_000], "html.parser")
            results: list[dict[str, Any]] = []
            seen: set[str] = set()
            query_terms={token.lower() for token in re.findall(r"[a-z0-9]{3,}", query.lower()) if token.lower() not in {"the","and","for","with","from","search","web","latest","today"}}
            for link in soup.find_all("a", href=True):
                href = str(link.get("href") or "")
                target = ""
                if href.startswith("/url?"):
                    target = parse_qs(urlparse(href).query).get("q", [""])[0]
                elif href.startswith(("http://", "https://")):
                    target = href
                if not target or target in seen:
                    continue
                parsed = urlparse(target)
                host = (parsed.hostname or "").lower()
                if host.endswith("google.com") or host in {"google.com", "google.com.ph"} or host in {"search.google", "accounts.google.com"}:
                    continue
                if not parsed.scheme or not parsed.netloc:
                    continue
                title = link.get_text(" ", strip=True)
                if len(title) < 8:
                    continue
                haystack=(title+" "+target).lower()
                if query_terms and not any(term in haystack for term in query_terms):
                    continue
                seen.add(target)
                results.append({"title": title[:240], "url": target, "snippet": title[:500], "source": "google_html"})
                if len(results) >= max_results:
                    break
            return {"success": bool(results), "query": query, "results": results, "errors": [] if results else ["Google HTML returned no parseable results"], "provider": "google_html"}
        except Exception as error:
            return {"success": False, "query": query, "results": [], "errors": [f"Google HTML fallback failed: {error}"], "provider": "google_html"}

    async def search_async(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        if not isinstance(query, str) or not query.strip():
            return {"success": False, "query": query, "results": [], "errors": ["query is required"]}
        normalized = query.strip()
        primary_error = ""
        try:
            results = await asyncio.wait_for(
                self.importer.search(normalized, max_results=max_results),
                timeout=max(3.0, float(os.getenv("FREYA_SEARCH_PROVIDER_TIMEOUT", "12"))),
            )
            usable = _usable_public_search_results(results)
            if usable:
                return {"success": True, "query": normalized, "results": usable[:max_results], "errors": [], "provider": "internet_research_importer"}

            primary_error = "Primary web-search provider returned no usable public page results"
        except Exception as error:
            primary_error = str(error)
        logger.debug("Primary web search unavailable; trying DuckDuckGo fallback: %s", primary_error)
        try:
            fallback = await asyncio.to_thread(self._duckduckgo_fallback, normalized, max_results)
            fallback.setdefault("errors", [])
            declared_fallback_success = bool(fallback.get("success"))
            fallback["results"] = _usable_public_search_results(fallback.get("results", []))[:max_results]
            fallback["success"] = bool(fallback["results"]) or declared_fallback_success
            fallback["errors"] = [primary_error] + list(fallback["errors"])
            if fallback["success"] or (declared_fallback_success and not fallback["results"]):
                return fallback
            google = await asyncio.to_thread(self._google_html_fallback, normalized, max_results)
            google["errors"] = list(fallback["errors"]) + list(google.get("errors", []))
            google["results"] = _usable_public_search_results(google.get("results", []))[:max_results]
            google["success"] = bool(google["results"])
            if not google["success"]:
                google["errors"].append("No usable public page results remained after bounded free-provider fallbacks")
            return google
        except Exception as fallback_error:
            logger.warning("DuckDuckGo web-search fallback failed: %s", fallback_error)
            return {"success": False, "query": normalized, "results": [], "errors": [primary_error, str(fallback_error)], "provider": "none"}

    def search(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        return _run_coroutine(self.search_async(query, max_results=max_results))


class WebPageReader:
    """Fetch and parse readable page content via the existing importer stack."""

    def __init__(self, importer: Optional[InternetResearchImporter] = None):
        self.importer = importer or InternetResearchImporter()

    async def read_async(self, url: str) -> Dict[str, Any]:
        allowed, reason = validate_public_url(url)
        if not allowed:
            return {"success": False, "url": url, "page": None, "error": reason}
        try:
            result = await asyncio.wait_for(
                self.importer.import_from_url(url.strip()),
                timeout=max(3.0, float(os.getenv("FREYA_PAGE_RETRIEVAL_TIMEOUT", "15"))),
            )
            if not result.success or not result.items:
                errors = getattr(result, "errors", None) or [f"No readable content extracted from {url}"]
                return {"success": False, "url": url, "page": None, "error": "; ".join(map(str, errors))}
            item = result.items[0]
            metadata = dict(getattr(item, "source_metadata", {}) or {})
            page = WebPage(
                url=str(getattr(item, "source_uri", None) or url),
                title=str(getattr(item, "title", None) or ""),
                content=str(getattr(item, "content", None) or ""),
                retrieved_at=str(metadata.get("fetch_timestamp") or datetime.now(timezone.utc).isoformat()),
                source_metadata=metadata,
            )
            if not page.content.strip():
                return {"success": False, "url": url, "page": None, "error": "Page contained no readable content"}
            return {"success": True, "url": page.url, "page": page, "error": None}
        except Exception as error:
            logger.warning("Page read failed for %s: %s", url, error)
            return {"success": False, "url": url, "page": None, "error": str(error)}

    def read(self, url: str) -> Dict[str, Any]:
        return _run_coroutine(self.read_async(url))


class SourceEvaluator:
    """Rank source quality without silently discarding uncertain evidence."""

    _AUTHORITATIVE_DOMAINS = {
        "rfc-editor.org", "w3.org", "developer.mozilla.org", "docs.python.org",
        "python.org", "docs.aws.amazon.com", "kubernetes.io", "go.dev",
        "rust-lang.org", "developer.hashicorp.com", "nist.gov", "who.int",
    }
    _SPAM_TERMS = {"casino", "betting", "viagra", "pills", "make money fast", "click here"}

    def evaluate(self, page: WebPage | Dict[str, Any], query: str = "", corroboration_count: int = 0) -> SourceQuality:
        page_obj = page if isinstance(page, WebPage) else WebPage(**page)
        parsed = urlparse(page_obj.url)
        domain = (parsed.hostname or "").lower()
        title_and_content = f"{page_obj.title} {page_obj.content}".lower()
        query_terms = {term for term in re.findall(r"[a-z0-9]{3,}", query.lower())}
        matched_terms = sum(1 for term in query_terms if term in title_and_content)
        relevance = matched_terms / max(1, len(query_terms)) if query_terms else 0.5
        rationale: List[str] = []
        uncertainty: List[str] = []
        spam_flags = [term for term in self._SPAM_TERMS if term in title_and_content]

        known_authority = any(domain == d or domain.endswith("." + d) for d in self._AUTHORITATIVE_DOMAINS)
        if known_authority:
            authority, authority_score = "authoritative", 0.92
            rationale.append("recognized official, standards, or public-interest domain")
        elif domain.endswith(".gov") or domain.endswith(".edu") or domain.endswith(".int"):
            authority, authority_score = "high", 0.85
            rationale.append("government, education, or international-organization domain")
        elif any(token in domain for token in ("docs", "documentation", "official", "research", "university")):
            authority, authority_score = "moderate-high", 0.72
            rationale.append("domain appears documentation- or research-oriented")
        else:
            authority, authority_score = "unclear", 0.50
            uncertainty.append("domain authority could not be established from URL metadata")

        path = (parsed.path or "").lower()
        primary = any(token in path for token in ("/spec", "/standard", "/rfc", "/reference", "/api/", "/release", "/dataset"))
        source_type = "primary" if primary else "secondary/unclear"
        if primary:
            rationale.append("URL path suggests a primary reference, standard, release, or dataset")
        else:
            uncertainty.append("primary-source status is not explicit")

        recency: Optional[float] = None
        fetched_at = page_obj.source_metadata.get("published_at") or page_obj.source_metadata.get("date")
        if fetched_at:
            recency = 0.5  # A conservative neutral score when no date parser is configured.
            uncertainty.append("publication date was supplied but not normalized")
        corroboration = min(1.0, corroboration_count / 2.0)
        score = (
            0.35 * authority_score
            + 0.25 * relevance
            + 0.15 * (recency if recency is not None else 0.5)
            + 0.15 * corroboration
            + 0.10 * (1.0 if parsed.scheme == "https" else 0.5)
        )
        if spam_flags:
            score = max(0.0, score - 0.25)
            rationale.append("obvious low-quality or spam-like terms detected")
        if len(page_obj.content) < 200:
            score = max(0.0, score - 0.10)
            uncertainty.append("page contains limited readable content")
        return SourceQuality(
            url=page_obj.url,
            title=page_obj.title,
            domain=domain,
            score=round(max(0.0, min(1.0, score)), 3),
            authority=authority,
            source_type=source_type,
            relevance_score=round(relevance, 3),
            recency_score=None if recency is None else round(recency, 3),
            corroboration_score=round(corroboration, 3),
            spam_flags=spam_flags,
            rationale=rationale,
            uncertainty=uncertainty,
        )


class FactExtractor:
    """Extract evidence-bearing claims without detaching them from sources."""

    def extract(
        self,
        page: WebPage | Dict[str, Any],
        query: str = "",
        source_quality: Optional[SourceQuality | Dict[str, Any]] = None,
        max_facts: int = 8,
    ) -> List[Fact]:
        page_obj = page if isinstance(page, WebPage) else WebPage(**page)
        quality = source_quality if isinstance(source_quality, SourceQuality) else None
        quality_score = quality.score if quality else 0.5
        paragraphs = [part.strip() for part in re.split(r"\n+", page_obj.content) if part.strip()]
        candidates: List[str] = []
        for paragraph in paragraphs:
            sentences = re.split(r"(?<=[.!?])\s+", paragraph)
            for sentence in sentences:
                cleaned = re.sub(r"\s+", " ", sentence).strip(" -•\t")
                if 35 <= len(cleaned) <= 1200 and not cleaned.startswith(("#", "http://", "https://")):
                    candidates.append(cleaned)
        if not candidates and page_obj.content.strip():
            candidates = [re.sub(r"\s+", " ", page_obj.content).strip()[:1200]]
        query_terms = {term for term in re.findall(r"[a-z0-9]{3,}", query.lower())}
        candidates = sorted(
            enumerate(candidates),
            key=lambda pair: (-sum(term in pair[1].lower() for term in query_terms), pair[0]),
        )
        facts: List[Fact] = []
        for index, sentence in candidates[:max_facts]:
            fact_id = f"fact_{abs(hash((page_obj.url, sentence))) % 10**12:012d}"
            facts.append(Fact(
                fact_id=fact_id,
                claim=sentence,
                evidence=sentence,
                source_url=page_obj.url,
                source_title=page_obj.title,
                retrieved_at=page_obj.retrieved_at,
                context=page_obj.content[max(0, page_obj.content.find(sentence) - 160): page_obj.content.find(sentence) + len(sentence) + 160],
                confidence=round(max(0.0, min(1.0, quality_score * (0.65 if query_terms else 0.55) + 0.25)), 3),
            ))
        return facts


class CrossReference:
    """Compare evidence and surface corroboration, conflict, and uncertainty."""

    _STOPWORDS = {"the", "and", "for", "with", "that", "this", "from", "are", "was", "were", "is", "to", "of", "in", "on", "a", "an", "as", "by", "it", "be", "or"}
    _NEGATIONS = {"not", "no", "never", "without", "cannot", "can't", "false", "否"}

    @classmethod
    def _tokens(cls, text: str) -> set[str]:
        return {
            token for token in re.findall(r"[a-z0-9%.-]+", text.lower())
            if token not in cls._STOPWORDS
        }

    @classmethod
    def _similarity(cls, left: str, right: str) -> float:
        a, b = cls._tokens(left), cls._tokens(right)
        if not a or not b:
            return 0.0
        return len(a & b) / max(1, min(len(a), len(b)))

    @classmethod
    def _has_conflicting_value(cls, left: str, right: str, *, distinct_sources: bool = False) -> bool:
        numbers_left = re.findall(r"\b\d+(?:\.\d+)?%?\b", left)
        numbers_right = re.findall(r"\b\d+(?:\.\d+)?%?\b", right)
        listing_markers = r"(?:price|cost|listing|seller|store|shop|amazon|shopee|lazada|ebay|walmart|newegg|usd|php|eur|gbp|₱|\$|€|£)"
        if distinct_sources and re.search(listing_markers, left, re.I) and re.search(listing_markers, right, re.I):
            return False
        if numbers_left and numbers_right and numbers_left != numbers_right:
            return True
        left_negated = bool(cls._tokens(left) & cls._NEGATIONS)
        right_negated = bool(cls._tokens(right) & cls._NEGATIONS)
        return left_negated != right_negated

    def compare(
        self,
        facts: Sequence[Fact | Dict[str, Any]],
        claims_to_check: Optional[Sequence[str]] = None,
    ) -> CrossReferenceResult:
        normalized = [fact if isinstance(fact, Fact) else Fact(**fact) for fact in facts]
        groups: List[List[Fact]] = []
        for fact in normalized:
            for group in groups:
                if self._similarity(fact.claim, group[0].claim) >= 0.55:
                    group.append(fact)
                    break
            else:
                groups.append([fact])

        corroborating: List[Dict[str, Any]] = []
        conflicting: List[Dict[str, Any]] = []
        unique: List[Dict[str, Any]] = []
        for group in groups:
            source_urls = list(dict.fromkeys(canonicalize_url(item.source_url) or item.source_url for item in group))
            values_conflict = any(
                self._has_conflicting_value(group[index].claim, group[other].claim, distinct_sources=len(source_urls) > 1)
                for index in range(len(group)) for other in range(index + 1, len(group))
            )
            payload = {
                "claims": [item.to_dict() for item in group],
                "source_urls": source_urls,
                "source_count": len(source_urls),
            }
            if values_conflict:
                # Keep the conflict visible, but do not erase agreement among
                # multiple sources that make the same claim.
                claim_groups: Dict[str, List[Fact]] = {}
                for item in group:
                    normalized_claim = re.sub(r"\s+", " ", item.claim.lower()).strip()
                    claim_groups.setdefault(normalized_claim, []).append(item)
                agreeing = max(claim_groups.values(), key=len)
                if len({item.source_url for item in agreeing}) >= 2:
                    corroborating.append({
                        "claims": [item.to_dict() for item in agreeing],
                        "source_urls": list(dict.fromkeys(item.source_url for item in agreeing)),
                        "source_count": len({item.source_url for item in agreeing}),
                    })
                conflicting.append(payload)
            elif len(source_urls) >= 2:
                corroborating.append(payload)
            else:
                unique.append(payload)

        unsupported: List[str] = []
        if claims_to_check:
            for claim in claims_to_check:
                if not any(self._similarity(claim, fact.claim) >= 0.45 for fact in normalized):
                    unsupported.append(claim)
        missing = ["No independent source corroboration was available."] if normalized and not corroborating else []
        uncertainty: List[str] = []
        if conflicting:
            uncertainty.append("Credible-looking sources contain conflicting claims; the conflict is unresolved.")
        if unsupported:
            uncertainty.append("One or more requested claims were not supported by retrieved evidence.")
        if not normalized:
            uncertainty.append("No extractable facts were available for comparison.")
        return CrossReferenceResult(
            corroborating_claims=corroborating,
            conflicting_claims=conflicting,
            unique_claims=unique,
            unsupported_claims=unsupported,
            missing_evidence=missing,
            uncertainty=uncertainty,
        )


class CitationManager:
    """Create and validate citations only from retrieved evidence."""

    def create(self, facts: Sequence[Fact | Dict[str, Any]]) -> List[Citation]:
        citations: List[Citation] = []
        seen: set[tuple[str, str]] = set()
        for fact_value in facts:
            fact = fact_value if isinstance(fact_value, Fact) else Fact(**fact_value)
            if not fact.source_url or not fact.evidence:
                continue
            key = (fact.claim, fact.source_url)
            if key in seen:
                continue
            seen.add(key)
            citations.append(Citation(
                citation_id=f"C{len(citations) + 1}",
                claim=fact.claim,
                evidence=fact.evidence,
                source_url=fact.source_url,
                source_title=fact.source_title,
                retrieved_at=fact.retrieved_at,
            ))
        return citations

    def validate(self, citations: Sequence[Citation | Dict[str, Any]], facts: Sequence[Fact | Dict[str, Any]]) -> Dict[str, Any]:
        fact_records = [fact if isinstance(fact, Fact) else Fact(**fact) for fact in facts]
        valid: List[Dict[str, Any]] = []
        invalid: List[Dict[str, Any]] = []
        for citation_value in citations:
            citation = citation_value if isinstance(citation_value, Citation) else Citation(**citation_value)
            matching = [fact for fact in fact_records if fact.source_url == citation.source_url]
            supported = any(
                citation.evidence.strip() == fact.evidence.strip()
                and citation.claim.strip() == fact.claim.strip()
                for fact in matching
            )
            target = citation.to_dict()
            (valid if supported else invalid).append(target)
        return {"valid": valid, "invalid": invalid, "fabricated_count": len(invalid)}


# ---------------------------------------------------------------------------
# Canonical workflow capability
# ---------------------------------------------------------------------------


class ResearchCapability(Capability):
    """Canonical workflow capability for lightweight search and full research."""

    TOOL_NAMES = {
        "search": "research::web_search",
        "read": "research::web_page_reader",
        "evaluate": "research::source_evaluator",
        "facts": "research::fact_extractor",
        "cross_reference": "research::cross_reference",
        "citations": "research::citation_manager",
        "archive": "research::archive_search",
    }

    def __init__(self):
        metadata = CapabilityMetadata(
            name="research_capability",
            version="1.0.0",
            description="Public web search, source evaluation, evidence extraction, verification, and cited research",
            category=CapabilityCategory.KNOWLEDGE,
            is_singleton=True,
            auto_discoverable=True,
            safe_query=True,
            default_action="search_web",
            supported_actions=["search_web", "read_page", "research_topic", "compare_sources", "verify_claim", "learn_finding", "archive_search", "advanced_search", "cross_site_research", "image_search", "reverse_image_search", "image_intelligence"],
            tags=["research", "web", "search", "sources", "citations", "verify", "evidence"],
            aliases=["websearch", "web search", "search the web", "internet research", "deep research", "research"],
            required_collaborators=["tool_manager"],
        )
        super().__init__(metadata)
        self._event_bus = None
        self._tool_manager = None
        self._learning_pipeline = None
        self.search_tool = WebSearchTool()
        self.page_reader = WebPageReader()
        self.image_research = FreeImageResearchChain(self.search_tool)
        # Optional test/integration seam; production uses the free chain above.
        self.image_search_provider = None
        self.browser_capability = None

        self.source_evaluator = SourceEvaluator()

        self.fact_extractor = FactExtractor()
        self.cross_reference = CrossReference()
        self.citation_manager = CitationManager()
        self.web_search = WebSearchCapability(self.search_tool)
        self.osint = OSINTCapability(self.web_search, reverse_image_provider=self.image_research)

    # The registry expects an instance of its Capability class.  Rather than
    # duplicate BaseCapability’s implementation, expose the same small public
    # contract directly and let the registry invoke action_* methods.
    @property
    def name(self) -> str:
        return self.metadata.name

    @property
    def description(self) -> str:
        return self.metadata.description

    @property
    def category(self):
        return self.metadata.category

    def supports_action(self, action: str) -> bool:
        return action in self.metadata.supported_actions and callable(getattr(self, f"action_{action}", None))

    def is_executable(self) -> bool:
        return bool(self.metadata.default_action and all(self.supports_action(action) for action in self.metadata.supported_actions))

    def execute(self, action: str, inputs: Dict[str, Any]) -> Any:
        if not self.supports_action(action):
            raise NotImplementedError(f"Capability '{self.name}' does not support executable action '{action}'")
        return getattr(self, f"action_{action}")(inputs)

    def _initialize(self) -> bool:
        return True

    def _activate(self) -> bool:
        self.state = CapabilityState.ACTIVE
        return True

    def _deactivate(self) -> bool:
        self.state = CapabilityState.INACTIVE
        return True

    def _publish_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Emit bounded research lifecycle metadata through Freya's EventBus."""
        try:
            from app.core.events import Event, get_event_bus
            get_event_bus().publish(Event(
                name=event_type,
                data=payload,
                source=f"capability:{self.name}",
            ))
        except Exception as error:
            logger.debug("Unable to publish research event %s: %s", event_type, error)

    def set_tool_manager(self, tool_manager) -> None:
        """Register every research stage as a named ToolManager tool."""
        self._tool_manager = tool_manager
        tool_manager.register(self.TOOL_NAMES["search"], lambda **kwargs: self.search_tool.search(**kwargs))
        tool_manager.register(self.TOOL_NAMES["archive"], lambda **kwargs: self.web_search.archive_search(**kwargs))
        tool_manager.register(self.TOOL_NAMES["read"], lambda **kwargs: self.page_reader.read(**kwargs))
        tool_manager.register(self.TOOL_NAMES["evaluate"], lambda **kwargs: _jsonable(self.source_evaluator.evaluate(**kwargs)))
        tool_manager.register(self.TOOL_NAMES["facts"], lambda **kwargs: _jsonable(self.fact_extractor.extract(**kwargs)))
        tool_manager.register(self.TOOL_NAMES["cross_reference"], lambda **kwargs: _jsonable(self.cross_reference.compare(**kwargs)) )
        tool_manager.register(self.TOOL_NAMES["citations"], lambda **kwargs: _jsonable(self.citation_manager.create(**kwargs)))

    def set_browser_capability(self, browser_capability) -> None:
        self.browser_capability = browser_capability
        self.image_research.set_browser(browser_capability)

    @staticmethod
    def _browser_result_url(value: Any) -> str:
        url = str(value or "").strip()
        if not url.startswith(("http://", "https://")):
            return ""
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if host.endswith("bing.com") and parsed.path.startswith("/ck/a"):
            encoded = parse_qs(parsed.query).get("u", [""])[0]
            if encoded.startswith("a1"):
                try:
                    payload = encoded[2:]
                    payload += "=" * (-len(payload) % 4)
                    decoded = base64.urlsafe_b64decode(payload).decode("utf-8", errors="replace")
                    if decoded.startswith(("http://", "https://")):
                        return decoded
                except Exception:
                    return ""
        return url

    @staticmethod
    def _browser_rss_records(text: str, query: str, max_results: int) -> List[Dict[str, Any]]:
        try:
            soup = BeautifulSoup(str(text or ""), "xml")
        except Exception:
            return []
        query_terms = {
            token.lower() for token in re.findall(r"[a-z0-9]{3,}", query.lower())
            if token.lower() not in {"the", "and", "for", "with", "from", "search", "latest", "newest", "today", "current", "currently", "what", "is", "of", "to", "me", "please", "find", "information", "about", "can", "you"}
        }
        records: List[Dict[str, Any]] = []
        seen: set[str] = set()
        item_blocks = re.findall(r"<item\b.*?</item>", str(text or ""), flags=re.IGNORECASE | re.DOTALL)
        item_nodes = soup.find_all("item")
        if not item_nodes:
            item_nodes = [BeautifulSoup(block, "html.parser") for block in item_blocks]
        for item_index, item in enumerate(item_nodes):
            title = item.find("title")
            link = item.find("link")
            if title is None:
                continue
            title_text = title.get_text(" ", strip=True)
            raw_block = item_blocks[item_index] if item_index < len(item_blocks) else ""
            link_match = re.search(r"<link[^>]*>(.*?)</link>", raw_block, flags=re.IGNORECASE | re.DOTALL)
            url = unescape(re.sub(r"<[^>]+>", "", link_match.group(1)).strip()) if link_match else ""
            if not url and link is not None:
                url = str(link.get_text(" ", strip=True) or link.get("href") or "").strip()
            source = item.find("source")
            source_url = str(source.get("url") or "").strip() if source is not None else ""
            if not url.startswith(("http://", "https://")) or url in seen or len(title_text) < 8:
                continue
            title_lower = title_text.lower()
            overlap = sum(1 for term in query_terms if term in title_lower)
            if query_terms and overlap < 1:
                continue
            seen.add(url)
            records.append({
                "title": title_text[:240],
                "url": url,
                "snippet": str(item.find("description").get_text(" ", strip=True) if item.find("description") is not None else "")[:500],
                "source": "playwright_chromium_google_news_rss",
                "source_domain": (urlparse(source_url).hostname or "").lower() if source_url else "",
                "source_url": source_url,
                "published_at": str(item.find("pubDate").get_text(" ", strip=True) if item.find("pubDate") is not None else ""),
            })
            if len(records) >= max_results:
                break
        return records

    def _browser_search(self, query: str, max_results: int, *, site_constraint: str = "", allowed_domains: Optional[Sequence[str]] = None, normalized_query: str = "") -> Dict[str, Any]:
        """Search public pages through the existing Playwright fallback.

        Explicit marketplace constraints are hard constraints: the browser opens
        only the requested marketplace and accepted result URLs are filtered to
        that domain. It never substitutes Amazon or another marketplace.
        """
        if self.browser_capability is None:
            return {"success": False, "results": [], "errors": ["Browser fallback is unavailable"]}
        query = str(query or "").strip()
        if not query:
            return {"success": False, "results": [], "errors": ["query is required"]}
        shopping = normalize_shopping_query(query)
        domains = [str(domain).lower().removeprefix("www.") for domain in (allowed_domains or ([site_constraint] if site_constraint else shopping.allowed_domains)) if str(domain).strip()]
        search_query = re.sub(r"\s+", " ", str(normalized_query or shopping.normalized_query or query)).strip(" .?!")
        search_query = search_query or query
        topical_terms = [token for token in re.findall(r"[a-z0-9]{3,}", search_query.lower()) if token not in _SEARCH_STOPWORDS]
        if len(topical_terms) >= 2:
            search_query = " ".join(topical_terms)
        search_hosts = {"google.com", "www.google.com", "bing.com", "www.bing.com", "duckduckgo.com", "html.duckduckgo.com", "search.yahoo.com"}
        query_terms = {token.lower() for token in re.findall(r"[a-z0-9]{3,}", search_query.lower()) if token.lower() not in _SEARCH_STOPWORDS}
        marketplace_urls = {
            "shopee.ph": "https://shopee.ph/search?" + urlencode({"keyword": search_query}),
            "shopee.com": "https://shopee.com/search?" + urlencode({"keyword": search_query}),
            "amazon.com": "https://www.amazon.com/s?" + urlencode({"k": search_query}),
            "lazada.com.ph": "https://www.lazada.com.ph/catalog/?" + urlencode({"q": search_query}),
            "lazada.com": "https://www.lazada.com/catalog/?" + urlencode({"q": search_query}),
            "ebay.com": "https://www.ebay.com/sch/i.html?" + urlencode({"_nkw": search_query}),
            "walmart.com": "https://www.walmart.com/search?" + urlencode({"q": search_query}),
            "newegg.com": "https://www.newegg.com/p/pl?" + urlencode({"d": search_query}),
        }
        if domains:
            engines = (marketplace_urls.get(domains[0], f"https://{domains[0]}/search?" + urlencode({"q": search_query})),)
        else:
            engines = ("https://html.duckduckgo.com/html/?q=" + quote_plus(search_query), "https://www.bing.com/search?" + urlencode({"q": search_query, "count": min(10, max_results * 2), "setlang": "en-US", "setmkt": "en-US", "cc": "us"}), "https://news.google.com/rss/search?" + urlencode({"q": search_query, "hl": "en-US", "gl": "US", "ceid": "US:en"}), "https://www.google.com/search?" + urlencode({"q": search_query, "num": min(10, max_results * 2)}))
            if _is_product_query(query):
                engines = (("https://www.google.com/search?" + urlencode({"tbm": "shop", "q": search_query, "num": min(10, max_results * 2)}), "https://www.bing.com/shop?" + urlencode({"q": search_query, "setlang": "en-US", "setmkt": "en-US"})) + engines)
        errors: List[str] = []
        for engine_url in engines:
            try:
                opened = self.browser_capability.execute("open_url", {"url": engine_url, "wait_until": "domcontentloaded", "timeout_ms": int(os.getenv("FREYA_BROWSER_NAVIGATION_TIMEOUT", "25000")), "safe_read_only": True})
                if not opened.get("success"):
                    errors.append(str(opened.get("error") or "Browser search page could not be opened")); continue
                extracted = self.browser_capability.execute("extract_links", {"selector": "a[href]", "limit": 120, "safe_read_only": True})
                if not extracted.get("success"):
                    errors.append(str(extracted.get("error") or "Browser search results could not be inspected")); continue
                records: List[Dict[str, Any]] = []; seen: set[str] = set()
                links = extracted.get("data", {}).get("links", []) if isinstance(extracted.get("data"), dict) else []
                for link in links if isinstance(links, list) else []:
                    if not isinstance(link, dict): continue
                    url = canonicalize_url(self._browser_result_url(link.get("href")))
                    if not url or url in seen: continue
                    parsed = urlparse(url); host = (parsed.hostname or "").lower(); path_lower = (parsed.path or "").lower()
                    if domains:
                        if not any(host == domain or host.endswith("." + domain) for domain in domains): continue
                        if path_lower in {"", "/", "/search", "/search/", "/mall/search"} or path_lower.startswith("/search/"): continue
                    elif host in search_hosts or host.endswith(".google.com") or any(marker in path_lower for marker in ("/search", "/searchpage", "/p/pl", "/sch/", "/site/search")): continue
                    title = str(link.get("text") or link.get("title") or "").strip(); title_lower = title.lower()
                    if len(title) < 4 or any(term in title_lower for term in _BLOCKED_BROWSER_RESULT_TERMS): continue
                    haystack = (title + " " + url).lower(); overlap = sum(1 for term in query_terms if term in haystack)
                    if query_terms and overlap < (1 if domains else (2 if len(query_terms) >= 2 else 1)): continue
                    seen.add(url); records.append({"title": title[:240], "url": url, "source_url": url, "snippet": "", "source": "playwright_chromium", "source_domain": host, "allowed_domain": bool(domains)})
                    if len(records) >= max_results: break
                if not records and not domains:
                    body_result = self.browser_capability.execute("read_page", {"selector": "body", "max_chars": 50000, "safe_read_only": True}); body_data = body_result.get("data") if isinstance(body_result.get("data"), dict) else {}; body_text = str(body_result.get("text") or body_data.get("text") or ""); records = self._browser_rss_records(body_text, search_query, max_results)
                if records:
                    return {"success": True, "query": query, "normalized_query": search_query, "results": records, "errors": errors, "provider": "playwright_chromium", "site_constraint": domains[0] if domains else ""}
                errors.append("Constrained marketplace page contained no usable product links" if domains else "Browser search page contained no usable public result links")
            except Exception as error:
                errors.append(str(error))
        if domains: errors.insert(0, f"No usable results were found on the required site {domains[0]}; no other marketplace was searched.")
        return {"success": False, "query": query, "normalized_query": search_query, "results": [], "errors": errors, "provider": "playwright_chromium", "site_constraint": domains[0] if domains else ""}

    def _browser_read_page(self, url: str) -> Dict[str, Any]:
        """Read visible text from a public page through the browser fallback."""
        if self.browser_capability is None:
            return {"success": False, "url": url, "page": None, "error": "Browser fallback is unavailable"}
        try:
            result = self.browser_capability.execute("open_url", {
                "url": url,
                "wait_until": "domcontentloaded",
                "timeout_ms": int(os.getenv("FREYA_BROWSER_NAVIGATION_TIMEOUT", "25000")),
                "safe_read_only": True,
            })
            if not result.get("success"):
                return {"success": False, "url": url, "page": None, "error": str(result.get("error") or "Browser could not open the public page")}
            resolved_from = str(result.get("url") or url)
            parsed_result = urlparse(resolved_from)
            if (parsed_result.hostname or "").lower().endswith("news.google.com") and "/rss/articles/" in parsed_result.path:
                links_result = self.browser_capability.execute("extract_links", {"selector": "a[href]", "limit": 120, "safe_read_only": True})
                links_data = links_result.get("data") if isinstance(links_result.get("data"), dict) else {}
                candidates = links_data.get("links", []) if isinstance(links_data.get("links"), list) else []
                for candidate in candidates:
                    if not isinstance(candidate, dict):
                        continue
                    candidate_url = self._browser_result_url(candidate.get("href"))
                    candidate_host = (urlparse(candidate_url).hostname or "").lower()
                    if not candidate_url or candidate_host.endswith("news.google.com") or candidate_host.endswith("google.com"):
                        continue
                    if len(str(candidate.get("text") or candidate.get("title") or "").strip()) < 5:
                        continue
                    redirected = self.browser_capability.execute("open_url", {"url": candidate_url, "wait_until": "domcontentloaded", "timeout_ms": int(os.getenv("FREYA_BROWSER_NAVIGATION_TIMEOUT", "25000")), "safe_read_only": True})
                    if redirected.get("success"):
                        result = redirected
                        resolved_from = str(redirected.get("url") or candidate_url)
                        break
            visible = self.browser_capability.execute("read_page", {
                "selector": "body",
                "max_chars": int(os.getenv("FREYA_BROWSER_PAGE_MAX_CHARS", "30000")),
                "safe_read_only": True,
            })
            text = str(visible.get("text") or "").strip()
            title = str(visible.get("title") or result.get("title") or "").strip()
            text_lower = text[:5000].lower()
            title_lower = title.lower()
            if any(term in title_lower for term in _BLOCKED_BROWSER_RESULT_TERMS) or "we found 0 items that match" in text_lower or "verify you are human" in text_lower:
                return {"success": False, "url": url, "page": None, "error": "Browser page was a login wall, challenge, or empty result page"}
            if not visible.get("success") or len(text) < 80:
                return {"success": False, "url": url, "page": None, "error": "Browser page contained insufficient readable public content"}
            page_url = str(visible.get("url") or result.get("url") or url)
            image_results = []
            try:
                from app.free_image_research_providers import extract_public_page_images
                image_results = extract_public_page_images(page_url, limit=5)
            except Exception:
                image_results = []
            page = WebPage(
                url=page_url,
                title=title,
                content=text,
                retrieved_at=datetime.now(timezone.utc).isoformat(),
                source_metadata={"provider": "playwright_chromium", "browser_fallback": True, "image_results": image_results},
            )
            return {"success": True, "url": page.url, "page": page, "error": None}
        except Exception as error:
            return {"success": False, "url": url, "page": None, "error": str(error)}

    def set_vision_capability(self, vision_capability) -> None:

        self.image_research.set_vision(vision_capability)
        self.osint.vision = vision_capability

    def set_learning_pipeline(self, learning_pipeline) -> None:
        self._learning_pipeline = learning_pipeline

    def _invoke(self, stage: str, **kwargs) -> Any:
        if self._tool_manager is None:
            return {"success": False, "error": "ToolManager not initialized"}
        result = self._tool_manager.execute(self.TOOL_NAMES[stage], **kwargs)
        if not result.success:
            return {"success": False, "error": result.error}
        return result.output

    @staticmethod
    def _dict_page(value: Any) -> Optional[WebPage]:
        if isinstance(value, WebPage):
            return value
        if isinstance(value, dict):
            return WebPage(**value)
        return None

    @staticmethod
    def _dict_fact(value: Any) -> Fact:
        return value if isinstance(value, Fact) else Fact(**value)

    def action_image_search(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        query = str(inputs.get("query") or inputs.get("topic") or "").strip()
        limit = max(1, min(int(inputs.get("max_results", inputs.get("limit", 8))), 20))
        if not query:
            return {"success": False, "error": "query is required", "image_results": [], "provider": "free_image_research"}
        # Preserve the injectable provider seam for deterministic tests and local integrations;
        # no paid or Bing implementation is retained here.
        if self.image_search_provider is not None:
            try:
                records = self.image_search_provider.search(query, limit=limit)
                candidates = []
                for record in records or []:
                    if not isinstance(record, dict):
                        continue
                    image_url = str(record.get("image_url") or record.get("thumbnail_url") or "")
                    if not image_url.lower().startswith(("http://", "https://")):
                        continue
                    candidates.append(record)
                return {"success": bool(candidates), "query": query, "image_results": candidates[:limit], "results": candidates[:limit], "provider": "injected_free_provider", "error": None if candidates else "Injected image provider returned no usable public candidates"}
            except Exception as error:
                return {"success": False, "query": query, "image_results": [], "results": [], "provider": "injected_free_provider", "error": str(error)}
        outcome = self.image_research.search_text(query, limit=limit)
        return {"success": outcome.success, "query": query, "image_results": outcome.candidates, "results": outcome.candidates, "provider": outcome.provider, "error": outcome.error}

    def action_search_web(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        query = str(inputs.get("query", "")).strip()
        max_results = max(1, min(int(inputs.get("max_results", 5)), 20))
        if not query:
            return {"success": False, "error": "query is required", "results": []}
        shopping = normalize_shopping_query(query)
        shopping_request = _is_product_query(query) or bool(shopping.requested_domain) or bool(shopping.ranking)
        requested_domain = str(inputs.get("site_constraint") or shopping.requested_domain or "").lower().removeprefix("www.")
        allowed_domains = [str(item).lower().removeprefix("www.") for item in (inputs.get("allowed_domains") or ([requested_domain] if requested_domain else [])) if str(item).strip()]
        normalized_query = str(inputs.get("normalized_query") or (shopping.normalized_query if shopping_request else query)).strip()
        result = self._invoke("search", query=normalized_query, max_results=max_results)
        if not isinstance(result, dict):
            result = {"success": False, "error": "Invalid search tool response", "results": []}
        result.setdefault("results", [])
        if allowed_domains:
            filtered = []
            for item in result.get("results", []) if isinstance(result.get("results"), list) else []:
                if not isinstance(item, dict):
                    continue
                host = (urlparse(str(item.get("url") or item.get("source_url") or "")).hostname or "").lower()
                if any(host == domain or host.endswith("." + domain) for domain in allowed_domains):
                    item = dict(item); item["url"] = canonicalize_url(item.get("url") or item.get("source_url")); filtered.append(item)
            result["results"] = filtered[:max_results]
        elif result.get("provider") or result.get("source"):
            result["results"] = _query_relevant_public_search_results(result["results"], normalized_query)[:max_results]
        else:
            result["results"] = _usable_public_search_results(result["results"])[:max_results]
        result["success"] = bool(result["results"])
        if not result["success"]:
            result.setdefault("errors", []).append("No usable public page results remained after filtering search homepages")
            browser_result = self._browser_search(query, max_results, site_constraint=requested_domain, allowed_domains=allowed_domains, normalized_query=normalized_query)
            if browser_result.get("success"):
                browser_result["errors"] = list(result.get("errors", [])) + list(browser_result.get("errors", []))
                result = browser_result
            elif allowed_domains:
                result = {**result, "success": False, "results": [], "site_constraint": allowed_domains[0], "errors": list(result.get("errors", [])) + list(browser_result.get("errors", []))}

        self._publish_event(
            "research.search.completed" if result["success"] else "research.search.failed",
            {"query": query[:200], "result_count": len(result["results"]), "error_count": len(result.get("errors", []))},
        )
        return result

    def action_advanced_search(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        return self.web_search.search(str(inputs.get("query") or ""), max_results=int(inputs.get("max_results", 5)), advanced=inputs.get("options") or inputs.get("advanced"))

    def action_archive_search(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        return self._invoke("archive", url_or_query=str(inputs.get("url") or inputs.get("query") or ""), max_results=int(inputs.get("max_results", 10)))

    def action_cross_site_research(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        return self.osint.cross_site_research(str(inputs.get("topic") or inputs.get("query") or ""), max_results=int(inputs.get("max_results", 10)), depth=int(inputs.get("depth", 1)))

    def action_reverse_image_search(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        return self.osint.reverse_image_search(str(inputs.get("image_path") or inputs.get("path") or ""), limit=int(inputs.get("limit", 10)))

    def action_image_intelligence(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        return self.osint.image_intelligence(str(inputs.get("image_path") or inputs.get("path") or ""), question=str(inputs.get("question") or "Extract useful public-investigation clues"))

    def action_read_page(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        url = inputs.get("url")
        if not url:
            return {"success": False, "error": "url is required", "page": None}
        result = self._invoke("read", url=url)
        if isinstance(result, dict) and isinstance(result.get("page"), WebPage):
            result["page"] = result["page"].to_dict()
        normalized = result if isinstance(result, dict) else {"success": False, "error": "Invalid page reader response", "page": None}
        page_value = normalized.get("page") if isinstance(normalized, dict) else None
        page_content = page_value.get("content") if isinstance(page_value, dict) else getattr(page_value, "content", "")
        if normalized.get("success") and len(str(page_content or "").strip()) < 80:
            normalized["success"] = False
            normalized["error"] = "Fast page reader returned insufficient readable content"
        if not normalized.get("success"):
            browser_result = self._browser_read_page(str(url))
            if browser_result.get("success"):
                browser_page = browser_result.get("page")
                normalized = dict(browser_result)
                if isinstance(browser_page, WebPage):
                    normalized["page"] = browser_page.to_dict()
            else:
                normalized["error"] = "; ".join(filter(None, [str(normalized.get("error") or ""), str(browser_result.get("error") or "")]))

        self._publish_event(
            "research.page.retrieved" if normalized.get("success") else "research.page.failed",
            {"url": str(url)[:500], "error": normalized.get("error")},
        )
        return normalized

    def action_research_topic(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        topic = str(inputs.get("topic") or inputs.get("query") or "").strip()
        if not topic:
            return {"success": False, "error": "topic is required"}
        max_sources = max(1, min(int(inputs.get("max_sources", 5)), 10))
        shopping = normalize_shopping_query(topic, region=str(inputs.get("region") or ""))
        product_query = _is_product_query(topic) or bool(shopping.requested_domain) or bool(shopping.ranking)
        search_query = shopping.normalized_query if product_query else topic
        search = self.action_search_web({
            "query": topic,
            "normalized_query": search_query,
            "site_constraint": shopping.requested_domain,
            "allowed_domains": shopping.allowed_domains,
            "max_results": max_sources,
        })
        errors = list(search.get("errors", [])) if isinstance(search, dict) else ["Search failed"]
        if not search.get("success") and not search.get("results"):
            message = (f"I could not find usable public listings on {shopping.requested_domain}; I did not substitute another marketplace."
                       if shopping.requested_domain else "Insufficient evidence was retrieved to answer this question.")
            result = ResearchResult(topic, message, [], [], [], [], [], list(dict.fromkeys(map(str, errors))), 0.0, errors=errors, partial=False)
            data = result.to_dict()
            data.update({"shopping_query": shopping.to_dict(), "product_candidates": [], "candidates": [], "winner": None, "image_results": [], "comparison": {"basis": shopping.ranking or "price", "currency": "", "lowest_price": None}})
            return {"success": False, "data": data, "error": "; ".join(map(str, errors))}

        pages: List[WebPage] = []
        sources: List[Dict[str, Any]] = []
        facts: List[Fact] = []
        candidates: List[ProductListing] = []
        seen_urls: set[str] = set()
        topic_terms = {token.lower() for token in re.findall(r"[a-z0-9]{3,}", shopping.normalized_query.lower()) if token.lower() not in _SEARCH_STOPWORDS and token.lower() not in _PRODUCT_QUERY_WORDS}

        for raw_result in search.get("results", []):
            if not isinstance(raw_result, dict):
                continue
            url = canonicalize_url(raw_result.get("url") or raw_result.get("source_url"))
            if not url or url in seen_urls:
                continue
            if shopping.allowed_domains:
                host = (urlparse(url).hostname or "").lower()
                if not any(host == domain or host.endswith("." + domain) for domain in shopping.allowed_domains):
                    continue
            seen_urls.add(url)
            page_response = self.action_read_page({"url": url})
            if not page_response.get("success"):
                errors.append(str(page_response.get("error") or f"Failed to read {url}"))
                continue
            page = self._dict_page(page_response.get("page"))
            if page is None:
                errors.append(f"Invalid page result for {url}")
                continue
            pages.append(page)
            if product_query:
                listing = _extract_product_listing(raw_result, page, shopping)
                if listing is None:
                    sources.append({"search_result": raw_result, "page": page.to_dict(), "role": "discovery_only", "quality": {"rationale": ["Search or category page was not used as final product evidence"]}})
                    continue
                candidates.append(listing)
                sources.append({"search_result": raw_result, "page": page.to_dict(), "product_listing": listing.to_dict(), "role": "product_listing", "quality": {"relevance_score": listing.confidence, "rationale": ["Readable product page with parsed listing fields"]}})
                continue
            quality_raw = self._invoke("evaluate", page=page.to_dict(), query=topic)
            quality = quality_raw if isinstance(quality_raw, dict) else _jsonable(quality_raw)
            sources.append({"search_result": raw_result, "page": page.to_dict(), "quality": quality})
            facts_raw = self._invoke("facts", page=page.to_dict(), query=topic, source_quality=quality)
            if isinstance(facts_raw, list):
                extracted_facts = [self._dict_fact(item) for item in facts_raw]
                facts.extend(extracted_facts)

        if product_query:
            deduped: List[ProductListing] = []
            seen_listing_keys: set[tuple[str, Optional[float], str]] = set()
            for listing in candidates:
                key = (canonicalize_url(listing.source_url), listing.price, re.sub(r"\W+", " ", listing.product_name.lower()).strip())
                if key in seen_listing_keys:
                    continue
                seen_listing_keys.add(key); deduped.append(listing)
            candidates = deduped
            priced = [item for item in candidates if item.price is not None]
            priced.sort(key=lambda item: (item.price, item.currency or "", item.product_name.lower()))
            unpriced = [item for item in candidates if item.price is None]
            candidates = priced + unpriced
            winner = priced[0] if priced else (candidates[0] if candidates else None)
            candidate_dicts = [item.to_dict() for item in candidates]
            image_results = []
            for item in candidates:
                if item.image_url:
                    image_results.append({"title": item.product_name, "image_url": item.image_url, "thumbnail_url": item.image_url, "source_domain": item.marketplace, "url": item.product_url, "snippet": item.evidence[:500], "match_type": "exact_product_page"})
            image_results = image_results[:8]
            if winner and winner.price is not None:
                price_text = f"{winner.currency + ' ' if winner.currency else ''}{winner.price:,.2f}".strip()
                answer = f"Among the {shopping.requested_domain + ' ' if shopping.requested_domain else ''}product listings I could verify, the cheapest was **{winner.product_name}** at **{price_text}** from **{winner.seller}**."
                if len(priced) > 1:
                    answer += f" I compared {len(priced)} priced listing(s); the results are ordered from lowest to highest price."
            elif candidates:
                answer = f"I found {len(candidates)} {shopping.requested_domain + ' ' if shopping.requested_domain else ''}product listing(s), but the available pages did not expose a verifiable numeric price, so I cannot honestly identify the cheapest one."
            else:
                answer = (f"I could not verify a readable product listing on {shopping.requested_domain}; I did not return results from another marketplace." if shopping.requested_domain else "I could not verify a readable product listing from the available public pages.")
            normal_fallback_markers = ("primary web-search provider", "duckduckgo returned", "google html returned", "bounded free-provider fallbacks", "filtering search homepages")
            uncertainty = list(dict.fromkeys(str(item) for item in errors if item and not any(marker in str(item).lower() for marker in normal_fallback_markers)))
            if candidates and not priced:
                uncertainty.append("The available product pages did not expose numeric prices.")
            comparison = {"basis": shopping.ranking or "price", "currency": winner.currency if winner else "", "lowest_price": winner.price if winner else None, "priced_count": len(priced), "candidate_count": len(candidates), "ordered_candidates": candidate_dicts}
            confidence = round(sum(item.confidence for item in candidates) / len(candidates), 3) if candidates else 0.0
            result = ResearchResult(topic=topic, answer=answer, key_findings=candidate_dicts, supporting_evidence=candidate_dicts, sources=sources, citations=[{"title": item.product_name, "url": item.source_url, "snippet": item.evidence[:500]} for item in candidates], conflicts=[], uncertainty=uncertainty, confidence=confidence, errors=errors, partial=bool(errors or not pages))
            data = result.to_dict()
            data.update({"shopping_query": shopping.to_dict(), "product_candidates": candidate_dicts, "candidates": candidate_dicts, "winner": winner.to_dict() if winner else None, "image_results": image_results, "comparison": comparison})
            data["uncertainty"] = uncertainty
            result.uncertainty = uncertainty
            result.key_findings = candidate_dicts
            result.supporting_evidence = candidate_dicts
            data["answer"] = answer
            payload = {"success": bool(candidates), "data": data, "errors": errors}
            self._publish_event("research.completed" if payload["success"] else "research.partial_or_failed", {"topic": topic[:200], "source_count": len(sources), "fact_count": len(candidates), "error_count": len(errors), "partial": result.partial, "shopping": True})
            return payload

        cross_raw = self._invoke("cross_reference", facts=[fact.to_dict() for fact in facts], claims_to_check=[topic])
        cross = cross_raw if isinstance(cross_raw, dict) else _jsonable(cross_raw)
        citations_raw = self._invoke("citations", facts=[fact.to_dict() for fact in facts])
        citations = citations_raw if isinstance(citations_raw, list) else []
        key_findings = [fact.to_dict() for fact in facts]
        conflicts = list(cross.get("conflicting_claims", [])) if isinstance(cross, dict) else []
        uncertainty = list(cross.get("uncertainty", [])) if isinstance(cross, dict) else []
        if not pages: uncertainty.append("No selected search result could be read successfully.")
        if errors: uncertainty.append("Some sources failed and the result is partial.")
        confidence = float(cross.get("confidence", 0.0)) if isinstance(cross, dict) else 0.0
        if not confidence and facts: confidence = min(0.75, max(fact.confidence for fact in facts))
        if conflicts: confidence = min(confidence, 0.5)
        answer = "Based on the retrieved sources: " + " ".join(fact.claim for fact in facts[:3]) if facts else "Insufficient readable evidence was retrieved to answer this question."
        result = ResearchResult(topic=topic, answer=answer, key_findings=key_findings, supporting_evidence=[fact.to_dict() for fact in facts], sources=sources, citations=citations, conflicts=conflicts, uncertainty=list(dict.fromkeys(uncertainty)), confidence=round(max(0.0, min(1.0, confidence)), 3), errors=errors, partial=bool(errors or not pages))
        payload = {"success": bool(facts), "data": result.to_dict(), "errors": errors}
        self._publish_event("research.completed" if payload["success"] else "research.partial_or_failed", {"topic": topic[:200], "source_count": len(sources), "fact_count": len(facts), "error_count": len(errors), "partial": result.partial})
        if inputs.get("remember"):
            payload["learning"] = self.action_learn_finding({"research_result": result.to_dict()})
        return payload

    def action_compare_sources(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        topic = str(inputs.get("topic") or inputs.get("question") or inputs.get("query") or "").strip()
        if not topic:
            return {"success": False, "error": "topic_or_question is required"}
        research = self.action_research_topic({**inputs, "topic": topic})
        if not research.get("data"):
            return research
        data = research["data"]
        return {"success": research.get("success", False), "data": {"topic": topic, "sources": data.get("sources", []), "comparison": {"corroborating_claims": data.get("key_findings", []), "conflicting_claims": data.get("conflicts", []), "uncertainty": data.get("uncertainty", [])}}, "errors": research.get("errors", [])}

    def action_verify_claim(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        claim = str(inputs.get("claim") or "").strip()
        if not claim:
            return {"success": False, "error": "claim is required"}
        research = self.action_research_topic({**inputs, "topic": claim})
        data = research.get("data", {})
        conflicts = data.get("conflicts", [])
        findings = data.get("key_findings", [])
        cross = CrossReference().compare([Fact(**item) for item in findings], claims_to_check=[claim])
        support_sources = list(dict.fromkeys(fact["source_url"] for fact in findings if claim.lower() in fact["claim"].lower()))
        if conflicts:
            status = "mixed" if support_sources else "contradicted"
        elif support_sources and len(support_sources) >= 2:
            status = "supported"
        elif support_sources:
            status = "partially_supported"
        else:
            status = "insufficient_evidence"
        return {"success": bool(findings), "data": {"claim": claim, "status": status, "supporting_sources": support_sources, "evidence": findings, "conflicts": conflicts, "uncertainty": data.get("uncertainty", []), "confidence": data.get("confidence", 0.0)}, "errors": research.get("errors", [])}

    def action_learn_finding(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Submit a finding to the existing gated learning pipeline only on request."""
        if not inputs.get("remember", True):
            return {"success": True, "accepted": False, "reason": "Research findings are not automatically remembered"}
        if self._learning_pipeline is None:
            return {"success": False, "accepted": False, "reason": "LearningPipeline is not initialized"}
        from app.learning.models import LearningCandidate, LearningCandidateType
        research_result = inputs.get("research_result") or inputs.get("finding") or {}
        candidate = LearningCandidate(
            candidate_type=LearningCandidateType.MANUAL_INPUT,
            source_component="ResearchCapability",
            raw_observation={"research_result": research_result, "verified": bool(inputs.get("verified", True))},
            context={"provenance": research_result.get("citations", []) if isinstance(research_result, dict) else []},
            tags=["research", "external", "provenance-preserved"],
            metadata={"source": "public_web", "provenance_preserved": True},
        )
        try:
            if callable(getattr(self._learning_pipeline, "run", None)):
                result = self._learning_pipeline.run(candidate)
                decision = getattr(getattr(result, "final_decision", None), "value", getattr(result, "final_decision", None))
                return {"success": True, "accepted": decision == "yes", "decision": decision, "pipeline_result": _jsonable(result)}
            if callable(getattr(self._learning_pipeline, "submit", None)):
                self._learning_pipeline.submit(candidate)
                return {"success": True, "accepted": False, "queued": True, "candidate_id": candidate.id}
            return {"success": False, "accepted": False, "reason": "LearningPipeline has no supported ingress"}
        except Exception as error:
            logger.warning("Research learning handoff failed: %s", error)
            return {"success": False, "accepted": False, "reason": str(error)}

    # Public method aliases keep the requested lightweight interface available
    # to direct callers while the workflow system uses action_*.
    def search_web(self, query: str, **kwargs) -> Dict[str, Any]:
        return self.action_search_web({"query": query, **kwargs})

    def read_page(self, url: str) -> Dict[str, Any]:
        return self.action_read_page({"url": url})

    def research_topic(self, topic: str, **kwargs) -> Dict[str, Any]:
        return self.action_research_topic({"topic": topic, **kwargs})

    def compare_sources(self, topic_or_question: str, **kwargs) -> Dict[str, Any]:
        return self.action_compare_sources({"topic": topic_or_question, **kwargs})

    def verify_claim(self, claim: str, **kwargs) -> Dict[str, Any]:
        return self.action_verify_claim({"claim": claim, **kwargs})


__all__ = [
    "Citation", "CitationManager", "CrossReference", "CrossReferenceResult", "Fact", "FactExtractor",
    "ResearchCapability", "ResearchResult", "SearchResult", "SourceEvaluator", "SourceQuality", "WebPage",
    "WebPageReader", "WebSearchTool", "validate_public_url",
]
