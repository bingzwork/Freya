from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field

from html import unescape
from pathlib import Path
from typing import Any, Iterable, Optional, TYPE_CHECKING
from urllib.parse import urljoin, urlparse, urlencode, quote
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup
import requests

if TYPE_CHECKING:
    from app.research.capability import WebSearchTool
from app.free_image_matching import compare_candidate, deduplicate_candidates

logger = logging.getLogger(__name__)


@dataclass
class ProviderOutcome:
    success: bool
    provider: str
    candidates: list[dict[str, Any]]
    error: str | None = None
    challenged: bool = False
    metrics: dict[str, Any] = field(default_factory=dict)


def _public_url(value: Any, base_url: str = "") -> str:
    raw = unescape(str(value or "").strip())
    if not raw:
        return ""
    absolute = urljoin(base_url, raw)
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    host = parsed.netloc.lower()
    if host in {"localhost", "127.0.0.1", "::1"} or host.startswith("192.168.") or host.startswith("10."):
        return ""
    if any(token in absolute.lower() for token in ("pixel", "spacer", "tracking", "favicon")):
        return ""
    return absolute


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower()


def _candidate(title: str, image_url: str, source_url: str, provider: str, *, match_type: str = "related", relevance: Any = None, snippet: str = "", entity: str = "", entity_match_score: Any = None, publication_date: str = "", freshness_score: Any = None, width: Any = None, height: Any = None, asset_type: str = "photo") -> dict[str, Any] | None:

    image_url = _public_url(image_url, source_url)
    source_url = _public_url(source_url)
    if not image_url:
        return None
    return {
        "title": re.sub(r"\s+", " ", str(title or "Image result")).strip()[:240],
        "thumbnail_url": image_url,
        "image_url": image_url,
        "source_page_url": source_url or image_url,
        "url": source_url or image_url,
        "source_domain": _domain(source_url or image_url),
        "match_type": match_type,
        "relevance": relevance,
        "provider": provider,
        "snippet": re.sub(r"\s+", " ", str(snippet or "")).strip()[:500],
        "entity": str(entity or "").strip(),
        "entity_match_score": entity_match_score,
        "publication_date": str(publication_date or "").strip(),
        "freshness_score": freshness_score,
        "width": int(width) if str(width or "").isdigit() else None,
        "height": int(height) if str(height or "").isdigit() else None,
        "asset_type": asset_type or "photo",
        "provenance": {"provider": provider, "source_page_url": source_url or image_url},
    }


def _overfetch_limit(requested_count: int, hard_limit: int = 50) -> int:
    target = max(1, min(int(requested_count or 10), hard_limit))
    return max(target, min(hard_limit, target * 3 if target > 1 else 8))


def validate_image_candidates(query: str, candidates: Iterable[dict[str, Any]], *, limit: int, exclude_urls: Optional[Iterable[str]] = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    excluded = {str(url or "").split("#", 1)[0].rstrip("/").lower() for url in (exclude_urls or []) if url}
    tokens = [token for token in re.findall(r"[a-z0-9]+", str(query or "").lower()) if len(token) >= 3]
    metrics = {"requested_count": int(limit), "candidates": 0, "validated": 0, "duplicates": 0, "rejected_mismatch": 0, "rejected_broken_asset": 0, "rejected_weak_asset": 0, "rejected_unsafe_asset": 0, "excluded_previous": 0}
    usable: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in candidates:
        metrics["candidates"] += 1
        if not isinstance(raw, dict):
            metrics["rejected_broken_asset"] += 1
            continue
        image_url = _public_url(raw.get("image_url") or raw.get("thumbnail_url"), str(raw.get("source_page_url") or raw.get("url") or ""))
        if not image_url:
            metrics["rejected_broken_asset"] += 1
            continue
        key = image_url.split("#", 1)[0].rstrip("/").lower()
        if key in excluded:
            metrics["excluded_previous"] += 1
            continue
        if key in seen:
            metrics["duplicates"] += 1
            continue
        seen.add(key)
        text = " ".join(str(raw.get(name) or "") for name in ("title", "snippet", "entity", "source_page_url", "source_domain")).lower()
        matched = {token for token in tokens if token in text}
        score = len(matched) / max(1, len(set(tokens))) if tokens else 1.0
        if len(set(tokens)) >= 2 and score < 0.25:
            metrics["rejected_mismatch"] += 1
            continue
        if len(set(tokens)) == 2:
            ordered_pattern = r"\b" + r"\W+".join(re.escape(token) for token in tokens) + r"\b"
            if not re.search(ordered_pattern, text, re.I):
                metrics["rejected_mismatch"] += 1
                continue
        visible_text = " ".join(str(raw.get(name) or "") for name in ("title", "snippet", "entity")).lower()
        visible_tokens = {token for token in re.findall(r"[a-z0-9]+", visible_text) if len(token) >= 3}
        visible_score = len(set(tokens) & visible_tokens) / max(1, len(set(tokens))) if tokens else 1.0
        if len(set(tokens)) >= 2 and len(visible_tokens) >= 2 and visible_score < 0.5:
            metrics["rejected_mismatch"] += 1
            continue
        if re.fullmatch(r"(?:explore|image|photo|picture|gallery|untitled|thumbnail)", str(raw.get("title") or "").strip(), re.I):
            metrics["rejected_weak_asset"] += 1
            continue
        combined_text = f"{image_url} {text} {visible_text}"
        if re.search(r"\b(?:porn|xxx|nsfw|nude|naked|sexual|sex|fuck|blowjob|hentai)\b", combined_text, re.I):
            metrics["rejected_unsafe_asset"] += 1
            continue
        width = int(raw.get("width") or 0) if str(raw.get("width") or "").isdigit() else 0
        height = int(raw.get("height") or 0) if str(raw.get("height") or "").isdigit() else 0
        if (width and width < 160) or (height and height < 120) or re.search(r"(?:pixel|spacer|tracking|favicon|logo|icon|sprite|advertisement|\.svg(?:$|[?#])|1px)", combined_text, re.I):
            metrics["rejected_weak_asset"] += 1
            continue
        item = dict(raw)
        item["image_url"] = image_url
        item["thumbnail_url"] = _public_url(item.get("thumbnail_url") or image_url, str(item.get("source_page_url") or item.get("url") or "")) or image_url
        item["source_page_url"] = _public_url(item.get("source_page_url") or item.get("url") or "", "") or image_url
        item["source_domain"] = _domain(item["source_page_url"])
        item["entity"] = str(query or "").strip()
        item["entity_match_score"] = round(score, 3)
        item["relevance"] = float(item.get("relevance") or score)
        item.setdefault("asset_type", "photo")
        item.setdefault("provenance", {"source_page_url": item["source_page_url"], "provider": item.get("provider", "unknown")})
        usable.append(item)
    usable.sort(key=lambda item: (float(item.get("entity_match_score") or 0.0), float(item.get("freshness_score") or 0.0), float(item.get("relevance") or 0.0)), reverse=True)
    selected = usable[:max(0, int(limit))]
    metrics["validated"] = len(selected)
    metrics["returned_count"] = len(selected)
    metrics["coverage_gap"] = "COUNT_GAP" if len(selected) < int(limit) else ""
    return selected, metrics


def _elements_from_observation(observation: Any) -> list[dict[str, Any]]:
    data = getattr(observation, "data", None) if observation is not None else None
    if isinstance(observation, dict):
        data = observation.get("data")
    elements = data.get("elements", []) if isinstance(data, dict) else []
    return [item for item in elements if isinstance(item, dict)]


class BrowserImageProvider:
    name = "browser"
    start_url = ""
    file_selector = 'input[type="file"]'
    media_selector = "a[href], img, meta[property='og:image'], meta[name='twitter:image']"
    default_match_type = "visually_similar"

    def __init__(self, browser=None, *, timeout_seconds: float = 20.0):
        self.browser = browser
        self.timeout_seconds = max(5.0, float(timeout_seconds))

    def search(self, image_path: str, *, limit: int = 10) -> ProviderOutcome:
        if self.browser is None:
            return ProviderOutcome(False, self.name, [], "Browser capability is unavailable")
        path = Path(str(image_path)).expanduser().resolve()
        if not path.is_file():
            return ProviderOutcome(False, self.name, [], "The supplied image file is unavailable")
        try:
            opened = self.browser.execute("open_url", {"url": self.start_url, "timeout_ms": int(self.timeout_seconds * 1000)})
            if not opened.get("success", False):
                return ProviderOutcome(False, self.name, [], str(opened.get("error") or "Browser navigation failed"))
            uploaded = self.browser.execute("upload_file", {"selector": self.file_selector, "path": str(path), "timeout_ms": int(self.timeout_seconds * 1000)})
            if not uploaded.get("success", False):
                return ProviderOutcome(False, self.name, [], str(uploaded.get("error") or "Image upload control was unavailable"))
            self.browser.execute("wait_for_element", {"selector": "body", "state": "visible", "timeout_ms": int(self.timeout_seconds * 1000)})
            observation = self.browser.execute("extract_media", {"selector": self.media_selector, "limit": 120, "timeout_ms": int(self.timeout_seconds * 1000)})
            text_observation = self.browser.execute("read_page", {"selector": "body", "max_chars": 12000, "timeout_ms": int(self.timeout_seconds * 1000)})
            title = str(observation.get("title") or text_observation.get("title") or "")
            page_url = str(observation.get("url") or text_observation.get("url") or self.start_url)
            body_text = str(text_observation.get("text") or "")
            if re.search(r"captcha|unusual traffic|verify you are human|robot check|access denied|blocked", f"{title} {body_text}", re.I):
                return ProviderOutcome(False, self.name, [], "Public provider presented a challenge or block", challenged=True)
            candidates: list[dict[str, Any]] = []
            for element in _elements_from_observation(observation):
                image_url = element.get("src") or element.get("data_src") or element.get("content")
                if not image_url and element.get("srcset"):
                    image_url = str(element["srcset"]).split(",")[-1].strip().split(" ")[0]
                source_url = element.get("href") or page_url
                item = _candidate(element.get("alt") or element.get("title") or element.get("text") or title, image_url, source_url, self.name, match_type=self.default_match_type)
                if item:
                    candidates.append(item)
                if len(candidates) >= limit:
                    break
            if not candidates:
                return ProviderOutcome(False, self.name, [], "Provider rendered no usable public image candidates")
            return ProviderOutcome(True, self.name, deduplicate_candidates(candidates, limit=limit))
        except Exception as error:
            logger.info("free image browser provider %s failed: %s", self.name, error)
            return ProviderOutcome(False, self.name, [], f"Provider operation failed: {type(error).__name__}")


class GoogleLensBrowserProvider(BrowserImageProvider):
    name = "google_lens_browser"
    start_url = "https://lens.google.com/"
    default_match_type = "visually_similar"


class YandexImagesBrowserProvider(BrowserImageProvider):
    name = "yandex_images_browser"
    start_url = "https://yandex.com/images/"
    default_match_type = "related"


def extract_public_page_images(url: str, *, timeout_seconds: float = 8.0, limit: int = 8) -> list[dict[str, Any]]:
    page_url = _public_url(url)
    if not page_url:
        return []
    request = Request(page_url, headers={"User-Agent": "Freya/1.0 public-page-image-extractor"})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            html = response.read(1_500_000).decode("utf-8", errors="replace")
    except Exception:
        return []
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[dict[str, Any]] = []
    for tag in soup.select("meta[property='og:image'], meta[name='twitter:image']"):
        image_url = _public_url(tag.get("content"), page_url)
        item = _candidate(soup.title.get_text(" ", strip=True) if soup.title else "Public page image", image_url, page_url, "public_page", match_type="possible_source")
        if item:
            candidates.append(item)
    for script in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(script.string or "")
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        for obj in stack:
            if not isinstance(obj, dict):
                continue
            images = obj.get("image") or obj.get("thumbnailUrl") or []
            if isinstance(images, str):
                images = [images]
            for image_url in images if isinstance(images, list) else []:
                item = _candidate(obj.get("name") or "Structured public image", image_url, page_url, "public_page", match_type="possible_source")
                if item:
                    candidates.append(item)
    for tag in soup.select("img[src], source[srcset]"):
        image_url = tag.get("src") or str(tag.get("srcset") or "").split(",")[-1].strip().split(" ")[0]
        item = _candidate(tag.get("alt") or (soup.title.get_text(" ", strip=True) if soup.title else "Public page image"), image_url, page_url, "public_page", match_type="possible_source")
        if item:
            candidates.append(item)
        if len(candidates) >= limit * 2:
            break
    return deduplicate_candidates(candidates, limit=limit)


def _public_image_search(query: str, *, limit: int = 10, timeout: float = 8.0) -> list[dict[str, Any]]:
    """Retrieve real public image candidates without an API key.

    Google Images is attempted as public HTML; Wikimedia Commons is a stable
    open-media fallback when Google renders no direct image elements.
    """
    candidates: list[dict[str, Any]] = []
    google_url = "https://www.google.com/search?" + urlencode({"tbm": "isch", "q": query})
    try:
        response = requests.get(google_url, headers={"User-Agent": "Mozilla/5.0 Freya public image research"}, timeout=timeout)
        response.raise_for_status()
        soup = BeautifulSoup(response.text[:2_000_000], "html.parser")
        for image in soup.find_all("img"):
            image_url = _public_url(image.get("src") or image.get("data-src") or image.get("data-iurl"))
            if not image_url or image_url.startswith("https://www.google."):
                continue
            parent = image.find_parent("a")
            source_url = _public_url(parent.get("href") if parent else "") or google_url
            candidates.append(_candidate(image.get("alt") or query, image_url, source_url, "public_search", match_type="possible", snippet="Google Images public result"))
            if len(candidates) >= limit:
                return deduplicate_candidates(candidates, limit=limit)
    except Exception as error:
        logger.info("Public Google Images fallback unavailable: %s", error)
    if len(candidates) < limit:
        commons_url = "https://commons.wikimedia.org/w/api.php?" + urlencode({
            "action": "query", "generator": "search", "gsrsearch": query,
            "gsrnamespace": 6, "gsrlimit": min(20, limit), "prop": "imageinfo",
            "iiprop": "url|mime", "format": "json",
        })
        try:
            response = requests.get(commons_url, headers={"User-Agent": "Freya/1.0 open-media research"}, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
            for page in (payload.get("query", {}).get("pages", {}) or {}).values():
                if not isinstance(page, dict):
                    continue
                info = (page.get("imageinfo") or [{}])[0]
                image_url = _public_url(info.get("url"))
                title = str(page.get("title") or query)
                page_url = _public_url(page.get("canonicalurl") or page.get("fullurl")) or "https://commons.wikimedia.org/wiki/" + quote(title.replace(" ", "_"), safe="")
                if not image_url or not page_url:
                    continue
                candidates.append(_candidate(title, image_url, page_url, "public_search", match_type="possible", snippet="Wikimedia Commons public result"))
                if len(candidates) >= limit:
                    break
        except Exception as error:
            logger.info("Wikimedia Commons public image fallback unavailable: %s", error)
    return deduplicate_candidates(candidates, limit=limit)


class VisionSearchFallbackProvider:
    name = "vision_web_fallback"

    def __init__(self, search_tool: WebSearchTool, vision=None, *, page_timeout: float = 8.0):
        self.search_tool = search_tool
        self.vision = vision
        self.page_timeout = page_timeout

    def search_text(self, query: str, *, limit: int = 10) -> ProviderOutcome:
        try:
            result = self.search_tool.search(f"{query} images", max_results=min(20, limit))

        except Exception:
            result = {"success": False, "results": [], "errors": ["public search failed"]}
        candidates: list[dict[str, Any]] = []
        for item in result.get("results", []) if isinstance(result, dict) else []:
            if not isinstance(item, dict):
                continue
            source_url = item.get("url") or item.get("source_url")
            direct = _candidate(item.get("title"), item.get("image_url") or item.get("thumbnail_url"), source_url or "", "public_search", match_type="related", snippet=item.get("snippet"))
            if direct:
                candidates.append(direct)
            candidates.extend(extract_public_page_images(str(source_url or ""), timeout_seconds=self.page_timeout, limit=5))

        candidates = deduplicate_candidates(candidates, limit=limit)
        if not candidates:
            candidates = _public_image_search(query, limit=limit, timeout=self.page_timeout)
            if candidates:
                logger.info("Public image fallback returned %d candidates for %s", len(candidates), query)
                return ProviderOutcome(True, "public_image_search", candidates, None)
        return ProviderOutcome(bool(candidates), self.name, candidates, None if candidates else "Public search returned no usable image candidates")

    def search(self, image_path: str, *, limit: int = 10) -> ProviderOutcome:
        if self.vision is None:
            return ProviderOutcome(False, self.name, [], "Local vision capability is unavailable")
        try:
            result = self.vision.execute("structured_analyze", {"paths": [str(image_path)], "question": "Extract subject, visible text, logos, landmarks, objects, and high-value public search clues."})
            data = result.get("data", {}) if isinstance(result, dict) else {}
            terms = data.get("search_terms", []) if isinstance(data, dict) else []
            if not terms:
                terms = [data.get("description", "uploaded image")]
            merged: list[dict[str, Any]] = []
            for term in [str(term).strip() for term in terms if str(term).strip()][:5]:
                outcome = self.search_text(term, limit=max(2, limit // 2))
                merged.extend(outcome.candidates)
            merged = deduplicate_candidates(merged, limit=limit)
            for candidate in merged:
                candidate.setdefault("match_type", "possible_source")
            return ProviderOutcome(bool(merged), self.name, merged, None if merged else "Vision-assisted public search returned no candidates")
        except Exception as error:
            return ProviderOutcome(False, self.name, [], f"Vision-assisted fallback failed: {type(error).__name__}")


class FreeImageResearchChain:
    """Provider-neutral free hierarchy: Google, Yandex, then local vision/public web."""

    def __init__(self, search_tool: WebSearchTool, *, browser=None, vision=None):
        self.search_tool = search_tool
        self.browser = browser
        self.vision = vision
        self.google = GoogleLensBrowserProvider(browser)
        self.yandex = YandexImagesBrowserProvider(browser)
        self.fallback = VisionSearchFallbackProvider(search_tool, vision)

    def set_browser(self, browser) -> None:
        self.browser = browser
        self.google.browser = browser
        self.yandex.browser = browser

    def set_vision(self, vision) -> None:
        self.vision = vision
        self.fallback.vision = vision

    def search_text(self, query: str, *, limit: int = 10, exclude_urls: Optional[Iterable[str]] = None) -> ProviderOutcome:
        discovery_limit = _overfetch_limit(limit)
        outcome = self.fallback.search_text(query, limit=discovery_limit)
        validated, metrics = validate_image_candidates(query, outcome.candidates, limit=limit, exclude_urls=exclude_urls)
        outcome.candidates = validated
        outcome.metrics = metrics
        outcome.success = bool(validated)
        return outcome

    def search(self, image_path: str, *, limit: int = 10, exclude_urls: Optional[Iterable[str]] = None) -> dict[str, Any]:
        attempts: list[dict[str, Any]] = []
        merged: list[dict[str, Any]] = []
        discovery_limit = _overfetch_limit(limit)
        for provider in (self.google, self.yandex):
            outcome = provider.search(image_path, limit=discovery_limit)

            attempts.append({"provider": outcome.provider, "success": outcome.success, "error": outcome.error, "challenged": outcome.challenged})
            merged.extend(outcome.candidates)
            if len(merged) >= discovery_limit:

                break
        if len(merged) < discovery_limit:
            fallback = self.fallback.search(image_path, limit=discovery_limit)
            attempts.append({"provider": fallback.provider, "success": fallback.success, "error": fallback.error, "challenged": fallback.challenged, "metrics": fallback.metrics})
            merged.extend(fallback.candidates)
        validated, metrics = validate_image_candidates("uploaded image", merged, limit=limit, exclude_urls=exclude_urls)
        provider = next((item.get("provider") for item in reversed(attempts) if item.get("success")), "free_image_research")
        return {"success": bool(validated), "provider": provider, "matches": validated, "image_results": validated, "attempts": attempts, "metrics": metrics, "warning": "Visual similarity is not identity confirmation.", "error": None if validated else "Free browser providers and vision-assisted public search returned no usable candidates."}


__all__ = ["FreeImageResearchChain", "GoogleLensBrowserProvider", "YandexImagesBrowserProvider", "VisionSearchFallbackProvider", "extract_public_page_images", "ProviderOutcome"]
