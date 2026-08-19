"""Freya-owned adapters for maintained public-web retrieval components.

This module deliberately contains web machinery only.  Intent, routing,
safety, memory, shopping semantics, evidence evaluation, and final synthesis
remain owned by the canonical Freya components.
"""

from __future__ import annotations

import ipaddress
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)


class ResearchMode(str, Enum):
    FAST_SEARCH = "FAST_SEARCH"
    DEEP_RESEARCH = "DEEP_RESEARCH"
    IMAGE_SEARCH = "IMAGE_SEARCH"

    @classmethod
    def coerce(cls, value: Any, query: str = "") -> "ResearchMode":
        normalized = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
        aliases = {
            "FAST": cls.FAST_SEARCH,
            "SEARCH": cls.FAST_SEARCH,
            "FAST_WEB_SEARCH": cls.FAST_SEARCH,
            "DEEP": cls.DEEP_RESEARCH,
            "RESEARCH": cls.DEEP_RESEARCH,
            "DEEP_WEB_RESEARCH": cls.DEEP_RESEARCH,
            "IMAGE": cls.IMAGE_SEARCH,
            "IMAGES": cls.IMAGE_SEARCH,
            "PHOTO": cls.IMAGE_SEARCH,
            "IMAGE_SEARCH": cls.IMAGE_SEARCH,
        }
        if normalized in aliases:
            return aliases[normalized]
        if normalized in {item.value for item in cls}:
            return cls(normalized)
        query_lower = str(query or "").lower()
        if re.search(r"\b(?:deeply|in depth|deep research|investigate|thoroughly|multi[- ]source|comprehensively)\b", query_lower):
            return cls.DEEP_RESEARCH
        explicit_image = re.search(r"\b(?:show|give\s+me|fetch|send)\b.{0,50}\b(?:photo(?:s)?|picture(?:s)?|image(?:s)?)\b", query_lower) or re.search(r"\bfind\b.{0,60}\b(?:photo(?:s)?|picture(?:s)?|image(?:s)?)\s+of\b", query_lower) or re.search(r"\b(?:photo(?:s)?|picture(?:s)?|image(?:s)?)\s+of\b", query_lower) or re.search(r"\bwhat does .* look like\b", query_lower)
        if explicit_image and not re.search(r"\bphoto\s+printer\b", query_lower):
            return cls.IMAGE_SEARCH
        return cls.FAST_SEARCH


@dataclass(frozen=True)
class ResearchLimits:
    """Explicit foreground budgets for bounded web work."""

    max_queries: int = 4
    max_sources: int = 8
    max_pages: int = 8
    max_depth: int = 1
    max_browser_steps: int = 24
    max_duration_seconds: float = 75.0
    max_images: int = 4

    @classmethod
    def from_inputs(cls, inputs: Optional[Dict[str, Any]] = None, *, deep: bool = False) -> "ResearchLimits":
        values = dict(inputs or {})
        defaults = cls(
            max_queries=4 if deep else 1,
            max_sources=8 if deep else 5,
            max_pages=8 if deep else 5,
            max_depth=1 if deep else 0,
            max_browser_steps=24 if deep else 8,
            max_duration_seconds=75.0 if deep else 35.0,
            max_images=4,
        )

        def bounded(name: str, low: int, high: int, default: int) -> int:
            try:
                return max(low, min(high, int(values.get(name, default))))
            except (TypeError, ValueError):
                return default

        try:
            duration = max(5.0, min(180.0, float(values.get("max_duration", values.get("max_duration_seconds", defaults.max_duration_seconds)))))
        except (TypeError, ValueError):
            duration = defaults.max_duration_seconds
        return cls(
            max_queries=bounded("max_queries", 1, 8, defaults.max_queries),
            max_sources=bounded("max_sources", 1, 20, defaults.max_sources),
            max_pages=bounded("max_pages", 1, 20, defaults.max_pages),
            max_depth=bounded("max_depth", 0, 2, defaults.max_depth),
            max_browser_steps=bounded("max_browser_steps", 1, 60, defaults.max_browser_steps),
            max_duration_seconds=duration,
            max_images=bounded("max_images", 1, 4, defaults.max_images),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_queries": self.max_queries,
            "max_sources": self.max_sources,
            "max_pages": self.max_pages,
            "max_depth": self.max_depth,
            "max_browser_steps": self.max_browser_steps,
            "max_duration_seconds": self.max_duration_seconds,
            "max_images": self.max_images,
        }


@dataclass
class AdapterOutcome:
    success: bool
    provider: str
    results: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    attempts: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "provider": self.provider,
            "results": list(self.results),
            "errors": list(self.errors),
            "attempts": list(self.attempts),
            **dict(self.metadata),
        }


def _public_url(value: Any) -> str:
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
    if host in {"localhost", "localhost.localdomain", "127.0.0.1", "::1"} or host.endswith(".localhost"):
        return ""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and (address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_unspecified):
        return ""
    return raw


def _domain(url: str) -> str:
    return (urlparse(str(url or "")).hostname or "").lower()


def _normalize_text_result(raw: Any, rank: int) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    url = _public_url(raw.get("href") or raw.get("url") or raw.get("link"))
    title = re.sub(r"\s+", " ", str(raw.get("title") or "")).strip()
    if not url or not title:
        return None
    snippet = re.sub(r"\s+", " ", str(raw.get("body") or raw.get("snippet") or raw.get("description") or "")).strip()
    return {
        "title": title[:240],
        "url": url,
        "snippet": snippet[:800],
        "source": "ddgs",
        "source_domain": _domain(url),
        "rank": rank,
        "relevance": round(1.0 / max(1, rank), 4),
        "provider": "ddgs",
    }


def _normalize_image_result(raw: Any, rank: int, query: str) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    image_url = _public_url(raw.get("image") or raw.get("image_url") or raw.get("thumbnail"))
    source_url = _public_url(raw.get("url") or raw.get("source") or image_url)
    if not image_url:
        return None
    title = re.sub(r"\s+", " ", str(raw.get("title") or query or "Image result")).strip()
    try:
        width = int(raw.get("width")) if raw.get("width") is not None else None
    except (TypeError, ValueError):
        width = None
    try:
        height = int(raw.get("height")) if raw.get("height") is not None else None
    except (TypeError, ValueError):
        height = None
    return {
        "title": title[:240],
        "image_url": image_url,
        "thumbnail_url": _public_url(raw.get("thumbnail")) or image_url,
        "source_page_url": source_url or image_url,
        "url": source_url or image_url,
        "source_domain": _domain(source_url or image_url),
        "entity": query[:240],
        "width": width,
        "height": height,
        "relevance": round(1.0 / max(1, rank), 4),
        "match_confidence": 0.0,
        "match_type": "public_image_result",
        "provider": "ddgs_images",
        "snippet": "",
    }


class DDGSProvider:
    """Thin adapter around the maintained DDGS metasearch API."""

    name = "ddgs"

    def __init__(self, timeout_seconds: float = 12.0):
        self.timeout_seconds = max(3.0, float(timeout_seconds))

    def search(self, query: str, *, max_results: int = 5) -> AdapterOutcome:
        try:
            from ddgs import DDGS
        except Exception as error:
            return AdapterOutcome(False, self.name, errors=[f"DDGS is unavailable: {type(error).__name__}"])
        try:
            with DDGS(timeout=self.timeout_seconds) as client:
                raw_results = client.text(str(query), max_results=max(1, min(int(max_results), 20)))
            results = [item for index, raw in enumerate(raw_results or [], start=1) if (item := _normalize_text_result(raw, index))]
            return AdapterOutcome(bool(results), self.name, results=results, errors=[] if results else ["DDGS returned no usable public results"], attempts=[{"provider": self.name, "success": bool(results)}])
        except Exception as error:
            logger.info("DDGS text search failed: %s", error)
            return AdapterOutcome(False, self.name, errors=[f"DDGS search failed: {type(error).__name__}"], attempts=[{"provider": self.name, "success": False}])

    def search_images(self, query: str, *, limit: int = 4) -> AdapterOutcome:
        try:
            from ddgs import DDGS
        except Exception as error:
            return AdapterOutcome(False, self.name, errors=[f"DDGS is unavailable: {type(error).__name__}"])
        try:
            with DDGS(timeout=self.timeout_seconds) as client:
                raw_results = client.images(str(query), max_results=max(1, min(int(limit) * 2, 12)))
            results = [item for index, raw in enumerate(raw_results or [], start=1) if (item := _normalize_image_result(raw, index, str(query)))]
            return AdapterOutcome(bool(results), "ddgs_images", results=results[:limit], errors=[] if results else ["DDGS returned no usable public image results"], attempts=[{"provider": "ddgs_images", "success": bool(results)}])
        except Exception as error:
            logger.info("DDGS image search failed: %s", error)
            return AdapterOutcome(False, "ddgs_images", errors=[f"DDGS image search failed: {type(error).__name__}"], attempts=[{"provider": "ddgs_images", "success": False}])


class SearchProviderPool:
    """Provider pool that prefers DDGS and reports fallback attempts explicitly."""

    def __init__(self, primary: Optional[DDGSProvider] = None):
        self.primary = primary or DDGSProvider()

    def search(self, query: str, *, max_results: int = 5) -> AdapterOutcome:
        outcome = self.primary.search(query, max_results=max_results)
        if outcome.success:
            return outcome
        return outcome


class TrafilaturaPageReader:
    """Maintained main-content extractor with a small public HTTP boundary."""

    name = "trafilatura"

    def __init__(self, timeout_seconds: float = 15.0, max_chars: int = 50000):
        self.timeout_seconds = max(3.0, float(timeout_seconds))
        self.max_chars = max(1000, int(max_chars))

    def read(self, url: str) -> AdapterOutcome:
        safe_url = _public_url(url)
        if not safe_url:
            return AdapterOutcome(False, self.name, errors=["Only public http(s) URLs are accepted"])
        try:
            import trafilatura
        except Exception as error:
            return AdapterOutcome(False, self.name, errors=[f"Trafilatura is unavailable: {type(error).__name__}"])
        try:
            response = requests.get(
                safe_url,
                timeout=self.timeout_seconds,
                allow_redirects=True,
                headers={"User-Agent": "Freya/1.0 public research reader"},
            )
            response.raise_for_status()
            final_url = _public_url(str(response.url)) or safe_url
            document = trafilatura.bare_extraction(
                response.text[:2_500_000],
                url=final_url,
                include_comments=False,
                include_tables=True,
                include_images=True,
                include_links=True,
                output_format="python",
            )
            text = str(getattr(document, "text", "") or "").strip() if document is not None else ""
            title = str(getattr(document, "title", "") or "").strip() if document is not None else ""
            links = getattr(document, "links", None) if document is not None else None
            images = getattr(document, "images", None) if document is not None else None
            metadata = {
                "provider": self.name,
                "extraction_backend": self.name,
                "author": str(getattr(document, "author", "") or "") if document is not None else "",
                "published_at": str(getattr(document, "date", "") or "") if document is not None else "",
                "sitename": str(getattr(document, "sitename", "") or "") if document is not None else "",
                "links": list(links) if isinstance(links, (list, tuple)) else [],
                "images": list(images) if isinstance(images, (list, tuple)) else [],
            }
            if len(text) < 80:
                return AdapterOutcome(False, self.name, errors=["Maintained extractor returned insufficient readable content"], metadata={"url": final_url, "title": title, "source_metadata": metadata})
            return AdapterOutcome(True, self.name, results=[{"url": final_url, "title": title, "content": text[: self.max_chars], "source_metadata": metadata}], attempts=[{"provider": self.name, "success": True}])
        except Exception as error:
            logger.info("Trafilatura page extraction failed for %s: %s", safe_url, error)
            return AdapterOutcome(False, self.name, errors=[f"Trafilatura page read failed: {type(error).__name__}"], attempts=[{"provider": self.name, "success": False}])


class ImageSearchProviderPool:
    """Provider-neutral image search with an injectable fallback chain."""

    def __init__(self, primary: Optional[DDGSProvider] = None, fallback: Optional[Callable[..., Any]] = None):
        self.primary = primary or DDGSProvider()
        self.fallback = fallback

    def search(self, query: str, *, limit: int = 4) -> AdapterOutcome:
        primary = self.primary.search_images(query, limit=limit)
        if primary.success:
            return primary
        if self.fallback is None:
            return primary
        try:
            raw = self.fallback(query, limit=limit)
            if isinstance(raw, AdapterOutcome):
                records = raw.results
            elif hasattr(raw, "candidates"):
                records = list(getattr(raw, "candidates", []) or [])
            else:
                records = raw.get("image_results") or raw.get("matches") or raw.get("results") or [] if isinstance(raw, dict) else []
            normalized = [dict(item) for item in records if isinstance(item, dict) and _public_url(item.get("image_url") or item.get("thumbnail_url"))]
            return AdapterOutcome(bool(normalized), "freya_image_chain", results=normalized[:limit], errors=list(primary.errors), attempts=list(primary.attempts) + [{"provider": "freya_image_chain", "success": bool(normalized)}])
        except Exception as error:
            return AdapterOutcome(False, "freya_image_chain", errors=list(primary.errors) + [f"Image fallback failed: {type(error).__name__}"], attempts=list(primary.attempts) + [{"provider": "freya_image_chain", "success": False}])


class WebResearchAdapter:
    """Container for replaceable low-level web machinery."""

    def __init__(self, *, timeout_seconds: float = 15.0):
        self.search_providers = SearchProviderPool(DDGSProvider(timeout_seconds=min(timeout_seconds, 15.0)))
        self.page_reader = TrafilaturaPageReader(timeout_seconds=timeout_seconds)
        self.image_providers = ImageSearchProviderPool(DDGSProvider(timeout_seconds=min(timeout_seconds, 15.0)))

    def search(self, query: str, *, max_results: int = 5) -> AdapterOutcome:
        return self.search_providers.search(query, max_results=max_results)

    def read_page(self, url: str) -> AdapterOutcome:
        return self.page_reader.read(url)

    def search_images(self, query: str, *, limit: int = 4) -> AdapterOutcome:
        return self.image_providers.search(query, limit=limit)


class DeepResearchCoordinator:
    """Deterministic bounded research-loop helpers inspired by mature projects."""

    @staticmethod
    def build_queries(topic: str, *, context: Optional[Dict[str, Any]] = None, max_queries: int = 4) -> List[str]:
        base = re.sub(r"\s+", " ", str(topic or "")).strip(" .?!")
        if not base:
            return []
        context = dict(context or {})
        queries: List[str] = [base]
        if re.search(r"\b(?:architecture|specification|cpu|gpu|model|technical|documentation|release|version)\b", base, re.I):
            queries.extend([f"{base} official specifications", f"{base} official announcement documentation"])
        elif re.search(r"\b(?:price|cheapest|cost|shopping|ram|printer|laptop|product)\b", base, re.I):
            queries.extend([f"{base} price warranty review", f"{base} official product specifications"])
        else:
            queries.extend([f"{base} primary source", f"{base} independent analysis"])
        if context.get("site_constraint"):
            domain = str(context["site_constraint"]).strip()
            queries = [f"site:{domain} {item}" for item in queries]
        return list(dict.fromkeys(queries))[: max(1, min(8, int(max_queries)))]

    @staticmethod
    def choose_follow_up_queries(topic: str, *, covered_text: str, max_queries: int = 2) -> List[str]:
        text = f"{topic} {covered_text}".lower()
        follow_ups: List[str] = []
        if re.search(r"\b(?:price|cheapest|cost|own|ownership|printer|ram|product)\b", text) and not re.search(r"\b(?:warranty|yield|ink|latency|seller|availability)\b", text):
            follow_ups.append(f"{topic} warranty availability seller reputation")
        if re.search(r"\b(?:architecture|cpu|gpu|model|technical|specification)\b", text) and not re.search(r"\b(?:official|documentation|announcement|specifications)\b", text):
            follow_ups.append(f"{topic} official documentation announcement")
        if not follow_ups and not re.search(r"\b(?:independent|comparison|review|analysis)\b", text):
            follow_ups.append(f"{topic} independent comparison analysis")
        return list(dict.fromkeys(follow_ups))[: max(0, min(3, int(max_queries)))]


__all__ = [
    "AdapterOutcome",
    "DDGSProvider",
    "DeepResearchCoordinator",
    "ImageSearchProviderPool",
    "ResearchLimits",
    "ResearchMode",
    "SearchProviderPool",
    "TrafilaturaPageReader",
    "WebResearchAdapter",
]
