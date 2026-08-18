"""Search and public-information investigation adapters for ResearchCapability."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote, urlparse
import hashlib
import re
import requests



def validate_public_url(url: str):
    from app.research.capability import validate_public_url as _validator
    return _validator(url)


@dataclass
class SearchEvidence:
    title: str
    url: str
    snippet: str = ""
    domain: str = ""
    date: str | None = None
    result_type: str = "web"
    provenance: dict[str, Any] | None = None

    def to_dict(self):
        return {"title": self.title, "url": self.url, "snippet": self.snippet, "domain": self.domain, "date": self.date, "result_type": self.result_type, "provenance": self.provenance or {}}


class WebSearchCapability:
    """Search adapter; the existing WebSearchTool remains the search engine."""
    def __init__(self, search_tool, timeout_seconds: float = 10.0):
        self.search_tool = search_tool
        self.timeout_seconds = max(1.0, float(timeout_seconds))

    @staticmethod
    def build_advanced_queries(query: str, options: dict[str, Any] | None = None) -> list[str]:
        options = options or {}
        base = str(query).strip()
        if not base:
            return []
        queries = [base]
        if options.get("exact_phrase", True):
            queries.append(f'"{base}"')
        for domain in options.get("sites", []) or []:
            queries.append(f"{base} site:{domain}")
        for file_type in options.get("file_types", []) or []:
            queries.append(f"{base} filetype:{file_type}")
        for year in options.get("years", []) or []:
            queries.append(f"{base} {year}")
        for alias in options.get("aliases", []) or []:
            queries.append(f"{base} {alias}")
        return list(dict.fromkeys(queries))[:10]

    def search(self, query: str, *, max_results: int = 5, advanced: dict[str, Any] | None = None) -> dict[str, Any]:
        queries = self.build_advanced_queries(query, advanced) if advanced else [query]
        results, errors = [], []
        for generated in queries:
            response = self.search_tool.search(generated, max_results=max_results)
            errors.extend(response.get("errors", []))
            for raw in response.get("results", []):
                url = str(raw.get("url") or "")
                if not url or not validate_public_url(url)[0]:
                    continue
                parsed = urlparse(url)
                evidence = SearchEvidence(
                    title=str(raw.get("title") or ""), url=url,
                    snippet=str(raw.get("snippet") or raw.get("content") or ""),
                    domain=parsed.hostname or "", date=raw.get("date") or raw.get("published"),
                    result_type=str(raw.get("result_type") or "web"),
                    provenance={"query": generated, "source": "WebSearchTool", "url": url},
                ).to_dict()
                if url not in {item["url"] for item in results}:
                    results.append(evidence)
                if len(results) >= max_results:
                    break
            if len(results) >= max_results:
                break
        return {"success": bool(results) or not errors, "query": query, "results": results[:max_results], "errors": errors}

    def archive_search(self, url_or_query: str, *, max_results: int = 10) -> dict[str, Any]:
        target = url_or_query.strip()
        if not target:
            return {"success": False, "results": [], "errors": ["url or query is required"]}
        if not target.startswith(("http://", "https://")):
            return {"success": False, "results": [], "errors": ["archive search requires a public URL"]}
        allowed, reason = validate_public_url(target)
        if not allowed:
            return {"success": False, "results": [], "errors": [reason]}
        endpoint = "https://web.archive.org/cdx/search/cdx?url=" + quote(target, safe="") + "&output=json&fl=timestamp,original,statuscode,digest&filter=statuscode:200&collapse=digest&limit=" + str(max_results)
        try:
            response = requests.get(endpoint, timeout=self.timeout_seconds)
            response.raise_for_status()
            rows = response.json()
            headers, records = (rows[0], rows[1:]) if rows else ([], [])
            results = []
            for row in records:
                record = dict(zip(headers, row))
                archived = f"https://web.archive.org/web/{record.get('timestamp')}/{record.get('original')}"
                results.append(SearchEvidence(record.get("original", target), archived, "Archived public snapshot", urlparse(target).hostname or "", record.get("timestamp"), "archive", {"source": "Internet Archive CDX", "timestamp": record.get("timestamp"), "original_url": record.get("original")}).to_dict())
            return {"success": True, "results": results, "errors": []}
        except Exception as error:
            return {"success": False, "results": [], "errors": [str(error)]}


class ReverseImageProvider(Protocol):
    def search(self, image_path: str, *, limit: int = 10) -> list[dict[str, Any]]: ...


class ReverseImageSearchProvider:
    """Provider boundary with no identity inference; concrete providers can be injected."""
    def search(self, image_path: str, *, limit: int = 10) -> list[dict[str, Any]]:
        raise RuntimeError("Free reverse-image providers are unavailable")


class OSINTCapability:
    def __init__(self, web_search: WebSearchCapability, vision=None, reverse_image_provider: ReverseImageProvider | None = None):
        self.web_search = web_search
        self.vision = vision
        self.reverse_image_provider = reverse_image_provider or ReverseImageSearchProvider()

    def cross_site_research(self, topic: str, *, max_results: int = 10, depth: int = 1) -> dict[str, Any]:
        depth = max(0, min(int(depth), 2))
        paths = [topic, f"{topic} official", f"{topic} news", f"{topic} conference", f"{topic} filetype:pdf"]
        if depth > 0:
            paths += [f"{topic} profile", f"{topic} university", f"{topic} archive"]
        findings, seen = [], set()
        for path in paths:
            result = self.web_search.search(path, max_results=max(1, max_results // max(1, len(paths))))
            for item in result.get("results", []):
                if item["url"] not in seen:
                    seen.add(item["url"]); findings.append(item)
                if len(findings) >= max_results: break
            if len(findings) >= max_results: break
        return {"success": bool(findings), "topic": topic, "search_paths": paths, "results": findings, "provenance": [item.get("provenance", {}) for item in findings], "depth": depth}

    def reverse_image_search(self, image_path: str, *, limit: int = 10) -> dict[str, Any]:
        try:
            path = Path(image_path).resolve(strict=True)
            matches = self.reverse_image_provider.search(str(path), limit=max(1, min(int(limit), 20)))
            if isinstance(matches, dict):
                result = dict(matches)
                result.setdefault("matches", result.get("image_results", []))
                result.setdefault("success", bool(result.get("matches")))
            else:
                result = {"success": bool(matches), "matches": matches}
            result.setdefault("warning", "Visual similarity is not identity confirmation.")
            result.setdefault("provenance", [{"provider": type(self.reverse_image_provider).__name__, "image_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}])
            return result
        except Exception as error:
            return {"success": False, "matches": [], "errors": [str(error)]}

    def image_intelligence(self, image_path: str, *, question: str = "Extract useful public-investigation clues") -> dict[str, Any]:
        path = Path(image_path).resolve(strict=True)
        clues = {"filename": path.name, "size_bytes": path.stat().st_size}
        try:
            from PIL import Image
            with Image.open(path) as image:
                clues.update({"width": image.width, "height": image.height, "format": image.format, "mode": image.mode, "metadata": dict(image.getexif())})
        except Exception as error:
            clues["image_error"] = str(error)
        if self.vision:
            try:
                clues["vision"] = self.vision.action_analyze({"image_path": str(path), "question": question})
                clues["ocr"] = self.vision.action_ocr({"image_path": str(path)})
            except Exception as error:
                clues["vision_error"] = str(error)
        return {"success": True, "clues": clues, "follow_up_queries": [str(value) for value in clues.get("ocr", {}).get("text", "").splitlines()[:5] if value.strip()]}
