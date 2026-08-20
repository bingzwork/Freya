"""Jan-style native ``web_search`` and ``web_fetch`` tools.

The module deliberately keeps the contract small: search discovers ranked
sources, fetch reads one selected page, and a caller-owned model loop decides
whether to call either tool again. Provider details never enter successful tool
results.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from html import unescape
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

EXA_HOSTED_URL = "https://mcp.exa.ai/mcp"
EXA_SEARCH_URL = "https://api.exa.ai/search"
SEARCH_DEFAULT_COUNT = 5
SEARCH_MAX_COUNT = 20
FETCH_DEFAULT_MAX_CHARS = 40_000
FETCH_MAX_BYTES = 5_000_000


class WebProviderError(RuntimeError):
    """A provider failure that should be distinguishable from no results."""

    def __init__(self, code: str, message: str, provider: str):
        self.code = code
        self.provider = provider
        super().__init__(message)


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    published_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "published_at": self.published_at,
        }


@dataclass(frozen=True)
class FetchResult:
    title: str
    url: str
    content: str
    truncated: bool = False
    published_at: Optional[str] = None
    author: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "title": self.title,
            "url": self.url,
            "content": self.content,
            "truncated": self.truncated,
        }
        if self.published_at:
            result["published_at"] = self.published_at
        if self.author:
            result["author"] = self.author
        return result


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, count: int) -> List[SearchResult]:
        ...


def _clip(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[: max(0, int(limit))]


def _public_http_url(value: Any, *, allow_private: bool = False) -> str:
    raw = str(value or "").strip()
    if not raw.startswith(("http://", "https://")):
        return ""
    try:
        parsed = urlparse(raw)
    except ValueError:
        return ""
    host = (parsed.hostname or "").rstrip(".").lower()
    if not host or parsed.username or parsed.password:
        return ""
    if not allow_private and (host == "localhost" or host.endswith(".localhost")):
        return ""
    if not allow_private:
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_unspecified
        ):
            return ""
    return raw


def canonical_url(value: Any) -> str:
    raw = _public_http_url(value)
    if not raw:
        return ""
    parsed = urlparse(raw)
    ignored = {"ref", "ref_", "tag", "linkcode", "camp", "psc", "spm"}
    query = [
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in ignored
    ]
    host = (parsed.hostname or "").lower()
    path = re.sub(r"/{2,}", "/", parsed.path or "/").rstrip("/") or "/"
    return urlunparse((parsed.scheme.lower(), host, path, "", urlencode(query), ""))


def _dedupe_results(results: Iterable[SearchResult], count: int) -> List[SearchResult]:
    output: List[SearchResult] = []
    seen: set[str] = set()
    for item in results:
        url = canonical_url(item.url)
        title = _clip(item.title, 240)
        if not url or not title or url in seen:
            continue
        seen.add(url)
        output.append(
            SearchResult(
                title=title,
                url=url,
                snippet=_clip(item.snippet, 800),
                published_at=_clip(item.published_at, 80) or None,
            )
        )
        if len(output) >= count:
            break
    return output


def _parse_exa_hosted_text(body: str) -> str:
    payload = body.strip()
    for line in body.splitlines():
        if line.strip().startswith("data:"):
            payload = line.split("data:", 1)[1].strip()
            break
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise WebProviderError("EXA_RESPONSE_INVALID", "Exa returned an invalid response.", "exa") from exc
    if parsed.get("error"):
        raise WebProviderError("EXA_PROVIDER_FAILURE", "Exa returned a provider error.", "exa")
    result = parsed.get("result") or {}
    if result.get("isError"):
        raise WebProviderError("EXA_PROVIDER_FAILURE", "Exa could not complete the request.", "exa")
    content = result.get("content") or []
    if not content or not isinstance(content[0], dict):
        raise WebProviderError("EXA_RESPONSE_INVALID", "Exa returned no usable content.", "exa")
    return str(content[0].get("text") or "")


def _parse_exa_hosted_search(text: str) -> List[SearchResult]:
    results: List[SearchResult] = []
    for block in text.split("\n---\n"):
        title = ""
        url = ""
        published: Optional[str] = None
        highlight_lines: List[str] = []
        in_highlights = False
        for line in block.splitlines():
            value = line.strip()
            if value.startswith("Title:"):
                title = value.split(":", 1)[1].strip()
            elif value.startswith("URL:"):
                url = value.split(":", 1)[1].strip()
            elif value.startswith("Published:"):
                candidate = value.split(":", 1)[1].strip()
                if candidate and candidate.upper() != "N/A":
                    published = candidate
            elif value.startswith("Highlights:"):
                in_highlights = True
            elif in_highlights and value and value != "..." and not value.startswith("Author:"):
                highlight_lines.append(value)
        if title or url:
            results.append(SearchResult(title, url, " ".join(highlight_lines), published))
    return results


class ExaProvider:
    """Exa provider matching Jan's keyless hosted and optional keyed REST modes."""

    name = "exa"

    def __init__(self, api_key: Optional[str] = None, timeout: Optional[float] = None):
        key = str(api_key or os.getenv("EXA_API_KEY", "")).strip()
        self.api_key = "" if key in {"", "YOUR_EXA_API_KEY_HERE"} else key
        self.timeout = max(3.0, float(timeout or os.getenv("FREYA_WEB_SEARCH_TIMEOUT", "30")))

    def _post(self, url: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
        except requests.Timeout as exc:
            raise WebProviderError("EXA_TIMEOUT", "Exa did not respond within the search time limit.", self.name) from exc
        except requests.RequestException as exc:
            raise WebProviderError("EXA_NETWORK_FAILURE", "Exa was unreachable.", self.name) from exc
        if not response.ok:
            raise WebProviderError(
                f"EXA_HTTP_{response.status_code}",
                f"Exa returned HTTP {response.status_code}.",
                self.name,
            )
        return response

    def search(self, query: str, count: int) -> List[SearchResult]:
        if self.api_key:
            response = self._post(
                EXA_SEARCH_URL,
                {
                    "query": query,
                    "type": "auto",
                    "numResults": count,
                    "contents": {"text": {"maxCharacters": 800}, "highlights": {"numSentences": 3, "highlightsPerUrl": 1}},
                },
                {"x-api-key": self.api_key, "content-type": "application/json"},
            )
            try:
                payload = response.json()
            except ValueError as exc:
                raise WebProviderError("EXA_RESPONSE_INVALID", "Exa returned invalid JSON.", self.name) from exc
            results = []
            for raw in payload.get("results") or []:
                if not isinstance(raw, dict):
                    continue
                highlights = raw.get("highlights") or []
                snippet = highlights[0] if highlights else raw.get("text") or ""
                results.append(SearchResult(raw.get("title", ""), raw.get("url", ""), snippet, raw.get("publishedDate")))
            return _dedupe_results(results, count)

        response = self._post(
            EXA_HOSTED_URL,
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "web_search_exa", "arguments": {"query": query, "numResults": count}}},
            {"content-type": "application/json", "accept": "application/json, text/event-stream"},
        )
        return _dedupe_results(_parse_exa_hosted_search(_parse_exa_hosted_text(response.text)), count)


class SearXNGProvider:
    name = "searxng"

    def __init__(self, endpoint: str, timeout: Optional[float] = None):
        endpoint = str(endpoint or "").strip().rstrip("/")
        if not endpoint.startswith(("http://", "https://")):
            raise ValueError("SearXNG URL must be an http(s) URL")
        self.endpoint = endpoint
        self.timeout = max(3.0, float(timeout or os.getenv("FREYA_WEB_SEARCH_TIMEOUT", "30")))

    def search(self, query: str, count: int) -> List[SearchResult]:
        try:
            response = requests.get(
                f"{self.endpoint}/search",
                params={"q": query, "format": "json"},
                timeout=self.timeout,
                headers={"User-Agent": "Freya native web_search/1.0"},
            )
        except requests.Timeout as exc:
            raise WebProviderError("SEARXNG_TIMEOUT", "SearXNG did not respond within the search time limit.", self.name) from exc
        except requests.RequestException as exc:
            raise WebProviderError("SEARXNG_NETWORK_FAILURE", "SearXNG was unreachable.", self.name) from exc
        if not response.ok:
            raise WebProviderError(f"SEARXNG_HTTP_{response.status_code}", f"SearXNG returned HTTP {response.status_code}.", self.name)
        try:
            payload = response.json()
        except ValueError as exc:
            raise WebProviderError("SEARXNG_RESPONSE_INVALID", "SearXNG did not return JSON.", self.name) from exc
        return _dedupe_results(
            [SearchResult(raw.get("title", ""), raw.get("url", ""), raw.get("content", ""), raw.get("publishedDate")) for raw in payload.get("results", []) if isinstance(raw, dict)],
            count,
        )


class BingHtmlProvider:
    name = "bing_html"

    def __init__(self, timeout: Optional[float] = None):
        self.timeout = max(3.0, float(timeout or os.getenv("FREYA_WEB_SEARCH_TIMEOUT", "30")))

    def search(self, query: str, count: int) -> List[SearchResult]:
        try:
            response = requests.get(
                "https://www.bing.com/search",
                params={"q": query, "count": min(count, 10)},
                timeout=self.timeout,
                headers={"User-Agent": "Freya native web_search/1.0"},
            )
        except requests.Timeout as exc:
            raise WebProviderError("BING_TIMEOUT", "The fallback search provider timed out.", self.name) from exc
        except requests.RequestException as exc:
            raise WebProviderError("BING_NETWORK_FAILURE", "The fallback search provider was unreachable.", self.name) from exc
        if not response.ok:
            raise WebProviderError(f"BING_HTTP_{response.status_code}", f"The fallback search provider returned HTTP {response.status_code}.", self.name)
        soup = BeautifulSoup(response.text, "html.parser")
        results: List[SearchResult] = []
        for node in soup.select("li.b_algo"):
            link = node.select_one("h2 a")
            if link is None:
                continue
            snippet = node.select_one(".b_caption p") or node.select_one("p")
            results.append(SearchResult(link.get_text(" ", strip=True), link.get("href", ""), snippet.get_text(" ", strip=True) if snippet else "", None))
        return _dedupe_results(results, count)


class ReadablePageFetcher:
    """Bounded, SSRF-aware HTML reader used by web_fetch."""

    def __init__(self, max_chars: Optional[int] = None, timeout: Optional[float] = None):
        self.max_chars = max(1_000, int(max_chars or os.getenv("FREYA_WEB_FETCH_MAX_CHARS", FETCH_DEFAULT_MAX_CHARS)))
        self.timeout = max(3.0, float(timeout or os.getenv("FREYA_WEB_FETCH_TIMEOUT", "30")))

    @staticmethod
    def _metadata(soup: BeautifulSoup) -> tuple[str, Optional[str], Optional[str]]:
        title = _clip(soup.title.get_text(" ", strip=True) if soup.title else "", 240)
        published = None
        author = None
        for key in ("article:published_time", "datePublished", "pubdate"):
            node = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
            if node and node.get("content"):
                published = _clip(node.get("content"), 80)
                break
        node = soup.find("meta", attrs={"name": re.compile("author", re.I)})
        if node and node.get("content"):
            author = _clip(node.get("content"), 120)
        return title, published, author

    def fetch(self, url: str) -> FetchResult:
        safe_url = _public_http_url(url)
        if not safe_url:
            raise WebProviderError("INVALID_URL", "Only public http(s) URLs are accepted.", "web_fetch")
        try:
            response = requests.get(
                safe_url,
                timeout=self.timeout,
                allow_redirects=True,
                stream=True,
                headers={"User-Agent": "Freya native web_fetch/1.0"},
            )
        except requests.Timeout as exc:
            raise WebProviderError("FETCH_TIMEOUT", "The page did not respond within the fetch time limit.", "web_fetch") from exc
        except requests.SSLError as exc:
            raise WebProviderError("SSL_FAILURE", "The page could not be fetched because its TLS connection failed.", "web_fetch") from exc
        except requests.RequestException as exc:
            raise WebProviderError("FETCH_NETWORK_FAILURE", "The page was unreachable.", "web_fetch") from exc
        final_url = _public_http_url(response.url)
        if not final_url:
            raise WebProviderError("REDIRECT_BLOCKED", "The page redirected to a private or invalid URL.", "web_fetch")
        if response.status_code >= 400:
            raise WebProviderError(f"HTTP_{response.status_code}", f"The page returned HTTP {response.status_code}.", "web_fetch")
        content_type = (response.headers.get("content-type") or "").lower()
        if content_type and not any(kind in content_type for kind in ("text/html", "application/xhtml", "text/plain", "application/json")):
            raise WebProviderError("UNSUPPORTED_CONTENT_TYPE", "The selected URL is not a readable HTML or text page.", "web_fetch")
        try:
            body = response.raw.read(FETCH_MAX_BYTES + 1)
        except requests.RequestException as exc:
            raise WebProviderError("FETCH_READ_FAILURE", "The page body could not be read.", "web_fetch") from exc
        if len(body) > FETCH_MAX_BYTES:
            body = body[:FETCH_MAX_BYTES]
        html = body.decode(response.encoding or "utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")
        title, published, author = self._metadata(soup)
        for node in soup(["script", "style", "noscript", "template", "svg", "nav", "footer", "header", "aside", "form"]):
            node.decompose()
        main = soup.find("main") or soup.find("article") or soup.body or soup
        text = unescape(main.get_text(" ", strip=True))
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) < 80:
            raise WebProviderError("EMPTY_CONTENT", "The page did not expose enough readable text.", "web_fetch")
        truncated = len(text) > self.max_chars
        if truncated:
            # Stop at a sentence boundary when possible rather than cutting a word.
            bounded = text[: self.max_chars]
            boundary = max(bounded.rfind(". "), bounded.rfind("! "), bounded.rfind("? "))
            text = bounded[: boundary + 1] if boundary >= self.max_chars // 2 else bounded
        return FetchResult(title=title, url=final_url, content=text, truncated=truncated, published_at=published, author=author)


class NativeWebTools:
    """Canonical native tools with provider fallback and clean results."""

    def __init__(self, *, enabled: Optional[bool] = None, provider: Optional[str] = None, exa_api_key: Optional[str] = None, searxng_url: Optional[str] = None, max_fetch_chars: Optional[int] = None):
        self.enabled = (str(os.getenv("FREYA_WEB_SEARCH_ENABLED", "true")).lower() not in {"0", "false", "off", "no"}) if enabled is None else bool(enabled)
        self.provider_name = str(provider or os.getenv("FREYA_WEB_SEARCH_PROVIDER", "exa")).strip().lower() or "exa"
        self.exa_api_key = exa_api_key if exa_api_key is not None else os.getenv("EXA_API_KEY", "")
        self.searxng_url = searxng_url if searxng_url is not None else os.getenv("FREYA_SEARXNG_URL", "")
        self.fetcher = ReadablePageFetcher(max_chars=max_fetch_chars)

    @staticmethod
    def schemas() -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "Search the web and return ranked results with title, URL, snippet, and optional publication date. Use web_fetch to read a selected page.",
                    "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "The search query."}, "count": {"type": "integer", "description": "Maximum results (default 5, maximum 20)."}}, "required": ["query"]},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "web_fetch",
                    "description": "Fetch a public http(s) URL and return bounded readable page text with its source URL and title.",
                    "parameters": {"type": "object", "properties": {"url": {"type": "string", "description": "The public http(s) URL to fetch."}}, "required": ["url"]},
                },
            },
        ]

    def _provider_chain(self) -> List[SearchProvider]:
        exa = ExaProvider(self.exa_api_key)
        searxng = SearXNGProvider(self.searxng_url) if self.searxng_url else None
        if self.provider_name == "searxng" and searxng is not None:
            chain: List[SearchProvider] = [searxng, exa, BingHtmlProvider()]
        elif self.provider_name == "bing_html":
            chain = [BingHtmlProvider(), exa]
        else:
            chain = [exa]
            if searxng is not None:
                chain.append(searxng)
            chain.append(BingHtmlProvider())
        return chain

    def search(self, query: Any, count: Any = SEARCH_DEFAULT_COUNT) -> Dict[str, Any]:
        if not self.enabled:
            return {"error": "search_disabled", "message": "Web search is disabled in Freya settings."}
        query_text = str(query or "").strip()
        if not query_text:
            return {"error": "invalid_query", "message": "query is required."}
        try:
            requested = int(count)
        except (TypeError, ValueError):
            requested = SEARCH_DEFAULT_COUNT
        count_value = max(1, min(SEARCH_MAX_COUNT, requested))
        started = time.monotonic()
        failures: List[Dict[str, str]] = []
        attempted: List[str] = []
        had_success = False
        for provider in self._provider_chain():
            attempted.append(provider.name)
            try:
                results = _dedupe_results(provider.search(query_text, count_value), count_value)
                had_success = True
                if results:
                    logger.info("web_search called query=%s count=%d provider=%s result_count=%d latency_ms=%d", query_text[:200], count_value, provider.name, len(results), int((time.monotonic() - started) * 1000))
                    return [result.to_dict() for result in results]
            except WebProviderError as error:
                failures.append({"provider": error.provider, "code": error.code})
                logger.warning("web_search provider failure provider=%s code=%s", error.provider, error.code)
            except Exception as error:
                failures.append({"provider": provider.name, "code": "PROVIDER_FAILURE"})
                logger.warning("web_search provider failure provider=%s type=%s", provider.name, type(error).__name__)
        if had_success:
            logger.info("web_search completed with no results query=%s latency_ms=%d", query_text[:200], int((time.monotonic() - started) * 1000))
            return []
        logger.warning("web_search failed providers=%s latency_ms=%d", attempted, int((time.monotonic() - started) * 1000))
        return {"error": "search_failed", "code": failures[-1]["code"] if failures else "PROVIDER_FAILURE", "message": "No configured web-search provider could be reached.", "providers_attempted": attempted}

    def fetch(self, url: Any) -> Dict[str, Any]:
        started = time.monotonic()
        url_text = str(url or "").strip()
        try:
            page = self.fetcher.fetch(url_text)
            logger.info("web_fetch called url=%s status=success extraction=success content_length=%d latency_ms=%d", url_text[:500], len(page.content), int((time.monotonic() - started) * 1000))
            return page.to_dict()
        except WebProviderError as error:
            logger.warning("web_fetch failed url=%s code=%s latency_ms=%d", url_text[:500], error.code, int((time.monotonic() - started) * 1000))
            return {"error": "fetch_failed", "code": error.code, "url": url_text, "message": str(error)}
        except Exception:
            logger.exception("web_fetch failed unexpectedly")
            return {"error": "fetch_failed", "code": "FETCH_FAILURE", "url": url_text, "message": "The page could not be fetched or read."}

    def register(self, tool_manager: Any) -> None:
        tool_manager.register("web_search", self.search)
        tool_manager.register("web_fetch", self.fetch)


__all__ = ["FetchResult", "NativeWebTools", "ReadablePageFetcher", "SearchResult", "WebProviderError"]
