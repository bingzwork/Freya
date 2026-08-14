"""Public-web research capability for Freya.

The module intentionally keeps the research domain model separate from the
canonical workflow capability registry.  ``ResearchCapability`` is the
registry-facing adapter; all network and research stages are exposed as named
ToolManager tools when the capability is wired into the runtime.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import ipaddress
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urlparse

from app.orchestrator.capability_registry import Capability, CapabilityCategory, CapabilityMetadata, CapabilityState
from app.software_engineering_knowledge.external_import import InternetResearchImporter

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


# ---------------------------------------------------------------------------
# Research tools
# ---------------------------------------------------------------------------

class WebSearchTool:
    """Structured public-web search backed by InternetResearchImporter."""

    def __init__(self, importer: Optional[InternetResearchImporter] = None):
        self.importer = importer or InternetResearchImporter()

    async def search_async(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        if not isinstance(query, str) or not query.strip():
            return {"success": False, "query": query, "results": [], "errors": ["query is required"]}
        try:
            results = await self.importer.search(query.strip(), max_results=max_results)
            return {
                "success": True,
                "query": query.strip(),
                "results": results,
                "errors": [],
            }
        except Exception as error:
            logger.warning("Web search failed: %s", error)
            return {"success": False, "query": query, "results": [], "errors": [str(error)]}

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
            result = await self.importer.import_from_url(url.strip())
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
    def _has_conflicting_value(cls, left: str, right: str) -> bool:
        numbers_left = re.findall(r"\b\d+(?:\.\d+)?%?\b", left)
        numbers_right = re.findall(r"\b\d+(?:\.\d+)?%?\b", right)
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
            source_urls = list(dict.fromkeys(item.source_url for item in group))
            values_conflict = any(
                self._has_conflicting_value(group[index].claim, group[other].claim)
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
            supported_actions=["search_web", "read_page", "research_topic", "compare_sources", "verify_claim", "learn_finding"],
            tags=["research", "web", "search", "sources", "citations", "verify", "evidence"],
            required_collaborators=["tool_manager"],
        )
        super().__init__(metadata)
        self._event_bus = None
        self._tool_manager = None
        self._learning_pipeline = None
        self.search_tool = WebSearchTool()
        self.page_reader = WebPageReader()
        self.source_evaluator = SourceEvaluator()
        self.fact_extractor = FactExtractor()
        self.cross_reference = CrossReference()
        self.citation_manager = CitationManager()

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
        tool_manager.register(self.TOOL_NAMES["read"], lambda **kwargs: self.page_reader.read(**kwargs))
        tool_manager.register(self.TOOL_NAMES["evaluate"], lambda **kwargs: _jsonable(self.source_evaluator.evaluate(**kwargs)))
        tool_manager.register(self.TOOL_NAMES["facts"], lambda **kwargs: _jsonable(self.fact_extractor.extract(**kwargs)))
        tool_manager.register(self.TOOL_NAMES["cross_reference"], lambda **kwargs: _jsonable(self.cross_reference.compare(**kwargs)) )
        tool_manager.register(self.TOOL_NAMES["citations"], lambda **kwargs: _jsonable(self.citation_manager.create(**kwargs)))

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

    def action_search_web(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        query = str(inputs.get("query", "")).strip()
        max_results = max(1, min(int(inputs.get("max_results", 5)), 20))
        if not query:
            return {"success": False, "error": "query is required", "results": []}
        result = self._invoke("search", query=query, max_results=max_results)
        if not isinstance(result, dict):
            return {"success": False, "error": "Invalid search tool response", "results": []}
        result.setdefault("results", [])
        result["results"] = [_jsonable(item) for item in result["results"]]
        result["success"] = bool(result.get("success", False))
        self._publish_event(
            "research.search.completed" if result["success"] else "research.search.failed",
            {"query": query[:200], "result_count": len(result["results"]), "error_count": len(result.get("errors", []))},
        )
        return result

    def action_read_page(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        url = inputs.get("url")
        if not url:
            return {"success": False, "error": "url is required", "page": None}
        result = self._invoke("read", url=url)
        if isinstance(result, dict) and isinstance(result.get("page"), WebPage):
            result["page"] = result["page"].to_dict()
        normalized = result if isinstance(result, dict) else {"success": False, "error": "Invalid page reader response", "page": None}
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
        search = self.action_search_web({"query": topic, "max_results": max_sources})
        errors = list(search.get("errors", [])) if isinstance(search, dict) else ["Search failed"]
        if not search.get("success") and not search.get("results"):
            result = ResearchResult(topic, "Insufficient evidence was retrieved to answer this question.", [], [], [], [], [], [str(error) for error in errors], 0.0, errors=errors, partial=False)
            return {"success": False, "data": result.to_dict(), "error": "; ".join(map(str, errors))}

        pages: List[WebPage] = []
        sources: List[Dict[str, Any]] = []
        facts: List[Fact] = []
        seen_urls: set[str] = set()
        for raw_result in search.get("results", []):
            url = raw_result.get("url") if isinstance(raw_result, dict) else None
            if not url or url in seen_urls:
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
            quality_raw = self._invoke("evaluate", page=page.to_dict(), query=topic)
            quality = quality_raw if isinstance(quality_raw, dict) else _jsonable(quality_raw)
            sources.append({"search_result": raw_result, "page": page.to_dict(), "quality": quality})
            facts_raw = self._invoke("facts", page=page.to_dict(), query=topic, source_quality=quality)
            if isinstance(facts_raw, list):
                facts.extend(self._dict_fact(item) for item in facts_raw)

        cross_raw = self._invoke("cross_reference", facts=[fact.to_dict() for fact in facts], claims_to_check=[topic])
        cross = cross_raw if isinstance(cross_raw, dict) else _jsonable(cross_raw)
        citations_raw = self._invoke("citations", facts=[fact.to_dict() for fact in facts])
        citations = citations_raw if isinstance(citations_raw, list) else []
        key_findings = [fact.to_dict() for fact in facts]
        conflicts = list(cross.get("conflicting_claims", [])) if isinstance(cross, dict) else []
        uncertainty = list(cross.get("uncertainty", [])) if isinstance(cross, dict) else []
        if not pages:
            uncertainty.append("No selected search result could be read successfully.")
        if errors:
            uncertainty.append("Some sources failed and the result is partial.")
        corroborated = len(cross.get("corroborating_claims", [])) if isinstance(cross, dict) else 0
        confidence = float(cross.get("confidence", 0.0)) if isinstance(cross, dict) else 0.0
        if not confidence and facts:
            confidence = min(0.75, max(fact.confidence for fact in facts))
        if conflicts:
            confidence = min(confidence, 0.5)
        if facts:
            answer = "Based on the retrieved sources: " + " ".join(fact.claim for fact in facts[:3])
        else:
            answer = "Insufficient readable evidence was retrieved to answer this question."
        result = ResearchResult(
            topic=topic,
            answer=answer,
            key_findings=key_findings,
            supporting_evidence=[fact.to_dict() for fact in facts],
            sources=sources,
            citations=citations,
            conflicts=conflicts,
            uncertainty=list(dict.fromkeys(uncertainty)),
            confidence=round(max(0.0, min(1.0, confidence)), 3),
            errors=errors,
            partial=bool(errors or not pages),
        )
        payload = {"success": bool(facts), "data": result.to_dict(), "errors": errors}
        self._publish_event(
            "research.completed" if payload["success"] else "research.partial_or_failed",
            {"topic": topic[:200], "source_count": len(sources), "fact_count": len(facts), "error_count": len(errors), "partial": result.partial},
        )
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
