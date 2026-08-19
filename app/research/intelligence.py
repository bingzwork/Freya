"""Freya-owned research intelligence primitives.

This module is deliberately lightweight and synchronous.  It does not own
routing, browser lifecycle, memory, or autonomous execution.  It carries a
validated request goal through the canonical ResearchCapability pipeline,
classifies evidence before shopping/synthesis, and selects a task-aware answer
shape.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence
from urllib.parse import urlparse


class ResearchIntent(str, Enum):
    FACTUAL_LOOKUP = "FACTUAL_LOOKUP"
    CURRENT_LOOKUP = "CURRENT_LOOKUP"
    NEWS_RESEARCH = "NEWS_RESEARCH"
    DEEP_RESEARCH = "DEEP_RESEARCH"
    TECHNICAL_COMPARISON = "TECHNICAL_COMPARISON"
    PRODUCT_COMPARISON = "PRODUCT_COMPARISON"
    SHOPPING_DISCOVERY = "SHOPPING_DISCOVERY"
    SHOPPING_PRICE_SEARCH = "SHOPPING_PRICE_SEARCH"
    REVIEW_RESEARCH = "REVIEW_RESEARCH"
    SPECIFICATION_LOOKUP = "SPECIFICATION_LOOKUP"
    CLAIM_VERIFICATION = "CLAIM_VERIFICATION"
    IMAGE_SEARCH = "IMAGE_SEARCH"
    PAGE_SUMMARY = "PAGE_SUMMARY"
    GENERAL_WEB_RESEARCH = "GENERAL_WEB_RESEARCH"


class FreshnessRequirement(str, Enum):
    NONE = "NONE"
    CURRENT_PREFERRED = "CURRENT_PREFERRED"
    LATEST = "LATEST"


class EvidenceType(str, Enum):
    OFFICIAL_PRODUCT = "OFFICIAL_PRODUCT"
    OFFICIAL_ANNOUNCEMENT = "OFFICIAL_ANNOUNCEMENT"
    OFFICIAL_DOCUMENTATION = "OFFICIAL_DOCUMENTATION"
    NEWS_ARTICLE = "NEWS_ARTICLE"
    RETAIL_LISTING = "RETAIL_LISTING"
    MARKETPLACE_LISTING = "MARKETPLACE_LISTING"
    REVIEW = "REVIEW"
    BENCHMARK = "BENCHMARK"
    TECHNICAL_COMPARISON = "TECHNICAL_COMPARISON"
    RESEARCH_PAPER = "RESEARCH_PAPER"
    FORUM_DISCUSSION = "FORUM_DISCUSSION"
    SOCIAL_POST = "SOCIAL_POST"
    GENERAL_WEB = "GENERAL_WEB"
    IMAGE = "IMAGE"


class PriceType(str, Enum):
    CURRENT_LISTING_PRICE = "CURRENT_LISTING_PRICE"
    MSRP = "MSRP"
    LAUNCH_PRICE = "LAUNCH_PRICE"
    REFERENCE_PRICE = "REFERENCE_PRICE"
    HISTORICAL_PRICE = "HISTORICAL_PRICE"
    SALE_PRICE = "SALE_PRICE"
    ESTIMATED_PRICE = "ESTIMATED_PRICE"
    UNKNOWN_PRICE = "UNKNOWN_PRICE"


@dataclass
class RequestSemanticModel:
    intent: str
    execution_mode: str
    entities: List[str] = field(default_factory=list)
    operation: str = "answer"
    freshness: str = FreshnessRequirement.NONE.value
    comparison_dimensions: List[str] = field(default_factory=list)
    shopping: bool = False
    price_lookup: bool = False
    news: bool = False
    image: bool = False
    requested_domain: str = ""
    output_goal: str = "direct_answer"
    explicit_references: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    query: str = ""
    confidence: float = 0.0
    reasoning: List[str] = field(default_factory=list)

    @property
    def is_follow_up(self) -> bool:
        return bool(self.explicit_references)

    @property
    def self_contained(self) -> bool:
        return not self.is_follow_up or bool(self.entities and self.operation != "answer")

    @property
    def uses_shopping_context(self) -> bool:
        return self.is_follow_up and self.intent in {
            ResearchIntent.SHOPPING_DISCOVERY.value,
            ResearchIntent.SHOPPING_PRICE_SEARCH.value,
            ResearchIntent.PRODUCT_COMPARISON.value,
            ResearchIntent.IMAGE_SEARCH.value,
        }

    @property
    def should_research(self) -> bool:
        return self.intent not in {ResearchIntent.FACTUAL_LOOKUP.value, ResearchIntent.IMAGE_SEARCH.value}

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RequestSemanticAnalyzer:
    """Classify obvious requests deterministically and preserve the full goal."""

    _REFERENCE_RE = re.compile(
        r"\b(?:it|that|this|that one|this one|the first one|the second one|the cheapest one|the lowest one|the winner|the product|the printer|another photo|show me another|what about it|compare it)\b",
        re.I,
    )
    _SITE_RE = re.compile(r"\b(?:shopee(?:\.com(?:\.ph)?|\.ph)?|amazon(?:\.com)?|lazada(?:\.com(?:\.ph)?|\.ph)?|ebay(?:\.com)?|walmart(?:\.com)?|newegg(?:\.com)?)\b", re.I)
    _COMPARISON_RE = re.compile(r"\b(?:compare|comparison|versus|vs\.?|against)\b", re.I)
    _NEWS_RE = re.compile(r"\b(?:news|headline|headlines|update|updates|happening|announcement|announcements)\b", re.I)
    _LATEST_RE = re.compile(r"\b(?:latest|newest|current|currently|today|now|recent)\b", re.I)
    _SHOPPING_RE = re.compile(r"\b(?:cheapest|cheaper|cheap|affordable|lowest\s+price|price\s+comparison|shopping|buy|purchase|seller|listing|availability|in\s+stock|on\s+(?:shopee|amazon|lazada|ebay|walmart|newegg))\b", re.I)
    _REVIEW_RE = re.compile(r"\b(?:review|reviews|reviewers|what\s+do\s+people\s+say|user\s+experience|benchmark(?:s)?|performance\s+test)\b", re.I)
    _SPEC_RE = re.compile(r"\b(?:spec|specs|specification|specifications|technical\s+details|architecture|vram|memory\s+interface|power\s+draw)\b", re.I)
    _VERIFY_RE = re.compile(r"\b(?:verify|fact\s*[- ]?check|is\s+it\s+true|confirm\s+whether)\b", re.I)
    _DEEP_RE = re.compile(r"\b(?:deeply|in\s+depth|deep\s+research|investigate|thoroughly|multi[- ]source|comprehensively)\b", re.I)
    _IMAGE_RE = re.compile(r"\b(?:show|give\s+me|fetch|send)\b.{0,50}\b(?:photo(?:s)?|picture(?:s)?|image(?:s)?)\b|\bfind\b.{0,60}\b(?:photo(?:s)?|picture(?:s)?|image(?:s)?)\s+of\b|\b(?:photo(?:s)?|picture(?:s)?|image(?:s)?)\s+of\b|\bwhat\s+does\b.{0,60}\blook\s+like\b", re.I)

    @classmethod
    def analyze(cls, query: str, *, context: Optional[Dict[str, Any]] = None) -> RequestSemanticModel:
        text = " ".join(str(query or "").split()).strip()
        lower = text.lower()
        context = dict(context or {})
        references = list(dict.fromkeys(match.group(0).lower() for match in cls._REFERENCE_RE.finditer(text)))
        entities = cls._extract_entities(text)
        comparison = bool(cls._COMPARISON_RE.search(text))
        news = bool(cls._NEWS_RE.search(text) and (cls._LATEST_RE.search(text) or "news" in lower))
        shopping = bool(cls._SHOPPING_RE.search(text) or cls._SITE_RE.search(text))
        price_lookup = bool(re.search(r"\b(?:cheapest|cheaper|lowest\s+price|price|cost|availability|in\s+stock|seller|listing)\b", lower))
        image = bool(cls._IMAGE_RE.search(text)) and not bool(re.search(r"\bphoto\s+printer\b", lower))
        review = bool(cls._REVIEW_RE.search(text))
        verify = bool(cls._VERIFY_RE.search(text))
        deep = bool(cls._DEEP_RE.search(text))
        spec = bool(cls._SPEC_RE.search(text))
        explicit_operation = bool(re.search(r"\b(?:find|show|compare|summarize|research|explain|verify|review|what|which|how much|is)\b", lower))
        requested_domain = ""
        site_match = cls._SITE_RE.search(lower)
        if site_match:
            requested_domain = {
                "shopee": "shopee.ph",
                "shopee.ph": "shopee.ph",
                "amazon": "amazon.com",
                "amazon.com": "amazon.com",
                "lazada": "lazada.com.ph",
                "lazada.com.ph": "lazada.com.ph",
                "ebay": "ebay.com",
                "ebay.com": "ebay.com",
                "walmart": "walmart.com",
                "walmart.com": "walmart.com",
                "newegg": "newegg.com",
                "newegg.com": "newegg.com",
            }.get(site_match.group(0).lower(), site_match.group(0).lower())

        if image:
            intent, operation, output_goal = ResearchIntent.IMAGE_SEARCH.value, "show", "image_results"
        elif verify:
            intent, operation, output_goal = ResearchIntent.CLAIM_VERIFICATION.value, "verify", "verified_claim"
        elif comparison and price_lookup and bool(re.search(r"\b(?:cheapest|buy|purchase|seller|listing|on\s+\w+)\b", lower)):
            intent, operation, output_goal = ResearchIntent.SHOPPING_PRICE_SEARCH.value, "find", "price_comparison"
        elif comparison:
            intent, operation, output_goal = (ResearchIntent.PRODUCT_COMPARISON.value if shopping else ResearchIntent.TECHNICAL_COMPARISON.value), "compare", "comparison"
        elif news:
            intent, operation, output_goal = ResearchIntent.NEWS_RESEARCH.value, "summarize", "news_developments"
        elif shopping and price_lookup:
            intent, operation, output_goal = ResearchIntent.SHOPPING_PRICE_SEARCH.value, "find", "price_comparison"
        elif shopping:
            intent, operation, output_goal = ResearchIntent.SHOPPING_DISCOVERY.value, "find", "shopping_options"
        elif review:
            intent, operation, output_goal = ResearchIntent.REVIEW_RESEARCH.value, "review", "review_consensus"
        elif deep:
            intent, operation, output_goal = ResearchIntent.DEEP_RESEARCH.value, "research", "deep_synthesis"
        elif spec:
            intent, operation, output_goal = ResearchIntent.SPECIFICATION_LOOKUP.value, "answer", "specifications"
        elif cls._LATEST_RE.search(text):
            intent, operation, output_goal = ResearchIntent.CURRENT_LOOKUP.value, "answer", "current_answer"
        elif re.search(r"\b(?:research|search|look\s+up|find|web)\b", lower):
            intent, operation, output_goal = ResearchIntent.GENERAL_WEB_RESEARCH.value, "research", "direct_answer"
        else:
            intent, operation, output_goal = ResearchIntent.FACTUAL_LOOKUP.value, "answer", "direct_answer"

        if intent == ResearchIntent.IMAGE_SEARCH.value:
            execution_mode = "IMAGE_SEARCH"
        elif intent in {ResearchIntent.NEWS_RESEARCH.value, ResearchIntent.TECHNICAL_COMPARISON.value, ResearchIntent.PRODUCT_COMPARISON.value, ResearchIntent.DEEP_RESEARCH.value, ResearchIntent.REVIEW_RESEARCH.value} or deep:
            execution_mode = "DEEP_RESEARCH"
        else:
            execution_mode = "FAST_SEARCH"

        freshness = FreshnessRequirement.NONE.value
        if cls._LATEST_RE.search(text) or news:
            freshness = FreshnessRequirement.LATEST.value if cls._LATEST_RE.search(text) or news else FreshnessRequirement.CURRENT_PREFERRED.value
        elif price_lookup or spec:
            freshness = FreshnessRequirement.CURRENT_PREFERRED.value

        dimensions = cls._comparison_dimensions(text) if comparison else []
        constraints = []
        if requested_domain:
            constraints.append(f"domain:{requested_domain}")
        if re.search(r"\bonly\s+on\b", lower):
            constraints.append("hard_marketplace_constraint")
        if freshness == FreshnessRequirement.LATEST.value:
            constraints.append("prefer_recent_publication_or_event_date")
        reasoning = []
        if comparison:
            reasoning.append("comparison language detected; evidence goal is preserved separately from shopping")
        if news:
            reasoning.append("news/update language plus freshness cue detected")
        if shopping:
            reasoning.append("commerce or marketplace language detected")
        if references:
            reasoning.append("explicit anaphoric reference detected; only typed antecedents may be reused")
        if entities and explicit_operation:
            reasoning.append("named entity and complete operation make the request self-contained")

        confidence = 0.92 if comparison or news or image or verify else 0.82 if shopping or review or spec else 0.68
        return RequestSemanticModel(
            intent=intent,
            execution_mode=execution_mode,
            entities=entities,
            operation=operation,
            freshness=freshness,
            comparison_dimensions=dimensions,
            shopping=shopping and intent in {ResearchIntent.SHOPPING_DISCOVERY.value, ResearchIntent.SHOPPING_PRICE_SEARCH.value, ResearchIntent.PRODUCT_COMPARISON.value},
            price_lookup=price_lookup,
            news=news,
            image=image,
            requested_domain=requested_domain,
            output_goal=output_goal,
            explicit_references=references,
            constraints=constraints,
            query=text,
            confidence=confidence,
            reasoning=reasoning,
        )

    @staticmethod
    def _extract_entities(text: str) -> List[str]:
        cleaned = re.sub(r"\b(?:what\s+is|what's|what\s+are|latest\s+news\s+of|latest\s+update\s+of|find\s+latest\s+update\s+of|compare|comparison|show\s+me|find|research|review|reviews\s+of|the|a|an)\b", " ", text, flags=re.I)
        parts = [part.strip(" .?!,:;()[]{}") for part in re.split(r"\b(?:vs\.?|versus|against)\b", cleaned, flags=re.I)]
        entities: List[str] = []
        for part in parts:
            part = re.sub(r"\s+", " ", part).strip()
            if not part:
                continue
            if re.search(r"\b(?:rtx|rx|ryzen|core|geforce|radeon|galaxy|iphone|postgresql|mysql|ssd|openai|nvidia|amd|intel)\b", part, re.I):
                entities.append(part)
        if not entities:
            for match in re.finditer(r"\b(?:NVIDIA|AMD|Intel|OpenAI|PostgreSQL|MySQL|GeForce|Radeon|RTX|RX)\b(?:\s+[A-Za-z0-9.-]+){0,5}", text, re.I):
                value = re.sub(r"\s+", " ", match.group(0)).strip(" .?!,:;()[]{}")
                if value and value.lower() not in {item.lower() for item in entities}:
                    entities.append(value)
        normalized: List[str] = []
        for value in entities:
            value = re.sub(r"\b9060xt\b", "9060 XT", value, flags=re.I)
            value = re.sub(r"\brtx\s+(\d+)", lambda m: "RTX " + m.group(1), value, flags=re.I)
            value = re.sub(r"\brx\s+(\d+)\s*(?:xt)?", lambda m: "RX " + m.group(1) + (" XT" if re.search(r"xt", value, re.I) else ""), value, flags=re.I)
            if value and value.lower() not in {item.lower() for item in normalized}:
                normalized.append(value)
        return normalized[:6]

    @staticmethod
    def _comparison_dimensions(text: str) -> List[str]:
        lower = text.lower()
        dimensions = []
        for label, pattern in (
            ("architecture", r"architecture|generation|process node"),
            ("specifications", r"spec|vram|memory|cores|storage|features?"),
            ("performance", r"performance|benchmark|fps|speed"),
            ("ray_tracing", r"ray tracing|\b(?:rt|dlss|fsr)\b|upscaling|frame generation"),
            ("power", r"power|tdp|efficiency"),
            ("price", r"price|cost|msrp|value"),
            ("user_experience", r"review|experience|software|driver"),
        ):
            if re.search(pattern, lower):
                dimensions.append(label)
        if not dimensions or dimensions == ["ray_tracing"]:
            return ["specifications", "performance", "features", "value"]
        return dimensions


class ResearchStrategySelector:
    """Build small role-aware query sets without becoming a second planner."""

    @staticmethod
    def build_queries(semantic: RequestSemanticModel, *, max_queries: int = 4) -> List[str]:
        base = semantic.query.strip(" .?!")
        entities = " vs ".join(semantic.entities[:2]) if len(semantic.entities) >= 2 else (semantic.entities[0] if semantic.entities else base)
        if semantic.intent == ResearchIntent.NEWS_RESEARCH.value:
            queries = [f"{entities} latest news", f"{entities} latest announcement", f"{entities} recent development", f"{entities} official news"]
        elif semantic.intent in {ResearchIntent.TECHNICAL_COMPARISON.value, ResearchIntent.PRODUCT_COMPARISON.value}:
            dimension_text = " ".join(semantic.comparison_dimensions[:4])
            queries = [f"{entities} official specifications", f"{entities} independent benchmarks review", f"{entities} {dimension_text}", f"{entities} MSRP value comparison"]
        elif semantic.intent == ResearchIntent.REVIEW_RESEARCH.value:
            queries = [f"{base} independent reviews", f"{base} benchmark testing", f"{base} user experience review", f"{base} strengths weaknesses"]
        elif semantic.intent == ResearchIntent.SPECIFICATION_LOOKUP.value:
            queries = [f"{base} official specifications", f"{base} official documentation", f"{base} technical details"]
        else:
            queries = [base, f"{base} primary source", f"{base} independent analysis", f"{base} official documentation"]
        return list(dict.fromkeys(item for item in queries if item.strip()))[: max(1, min(8, int(max_queries)))]


class EvidenceClassifier:
    """Classify public evidence and restrict fields that synthesis may infer."""

    _COMMERCE_DOMAINS = {"amazon", "ebay", "walmart", "newegg", "bestbuy", "shopee", "lazada", "aliexpress", "adidas", "nike"}
    _BENCHMARK_TOKENS = {"benchmark", "userbenchmark", "pcbench", "nanoreview", "technical.city", "technicalcity", "passmark", "gpu-monkey", "gpumonkey", "3dmark"}
    _REVIEW_TOKENS = {"tomshardware", "techpowerup", "pcmag", "rtings", "gamersnexus", "anandtech", "notebookcheck", "techradar", "review", "reviews"}
    _NEWS_TOKENS = {"news", "nvidianews", "reuters", "apnews", "theverge", "techcrunch", "arstechnica", "businesswire"}
    _PAPER_TOKENS = {"arxiv", "doi.org", "acm.org", "ieeexplore", "nature.com", "science.org"}

    @classmethod
    def classify(cls, record: Dict[str, Any], semantic: Optional[RequestSemanticModel] = None) -> Dict[str, Any]:
        url = str(record.get("url") or record.get("source_url") or "").strip()
        title = str(record.get("title") or record.get("source_title") or "").strip()
        content = str(record.get("content") or record.get("snippet") or record.get("evidence") or "")
        host = (urlparse(url).hostname or "").lower()
        haystack = f"{host} {url} {title} {content}".lower()
        path = (urlparse(url).path or "").lower()
        commerce_domain = any(token in host for token in cls._COMMERCE_DOMAINS)
        commerce_signals = []
        for label, pattern in (("current_price", r"(?:current|our)\s+price|price\s*[:$€£₱]|\$\s*\d|₱\s*\d"), ("seller", r"sold\s+by|seller\s*[:\-]|store\s*[:\-]"), ("availability", r"in\s+stock|out\s+of\s+stock|available|pre[- ]?order"), ("commerce_action", r"add\s+to\s+(?:cart|basket)|buy\s+now|checkout"), ("product_schema", r"productid|offers|availability|pricecurrency")):
            if re.search(pattern, haystack, re.I):
                commerce_signals.append(label)
        official = bool(re.search(r"\b(?:official|manufacturer|products?|specifications?|documentation|press[- ]release)\b", haystack))
        if commerce_domain and (len(commerce_signals) >= 2 or re.search(r"/(?:dp|gp/product|product|item|p)/", path)):
            evidence_type = EvidenceType.MARKETPLACE_LISTING.value if any(token in host for token in {"shopee", "lazada", "aliexpress"}) else EvidenceType.RETAIL_LISTING.value
        elif any(token in host or token in haystack for token in cls._BENCHMARK_TOKENS):
            evidence_type = EvidenceType.BENCHMARK.value
        elif any(token in host or token in haystack for token in cls._PAPER_TOKENS):
            evidence_type = EvidenceType.RESEARCH_PAPER.value
        elif any(token in host or token in haystack for token in cls._REVIEW_TOKENS):
            evidence_type = EvidenceType.REVIEW.value
        elif any(token in host or token in haystack for token in cls._NEWS_TOKENS) or re.search(r"\b(?:news|headline|press release|announced)\b", title, re.I):
            evidence_type = EvidenceType.NEWS_ARTICLE.value
        elif official and re.search(r"/(?:products?|spec|documentation|docs|support|press|news)/", path):
            evidence_type = EvidenceType.OFFICIAL_ANNOUNCEMENT.value if re.search(r"press|news|announce|release", path + " " + title, re.I) else EvidenceType.OFFICIAL_PRODUCT.value
        elif re.search(r"\b(?:specification|documentation|api reference|manual)\b", haystack):
            evidence_type = EvidenceType.OFFICIAL_DOCUMENTATION.value
        elif re.search(r"\b(?:forum|reddit|discussion|community)\b", haystack):
            evidence_type = EvidenceType.FORUM_DISCUSSION.value
        else:
            evidence_type = EvidenceType.GENERAL_WEB.value
        price_type = cls.price_type(content, evidence_type, commerce_signals)
        allowed_fields = ["claim", "excerpt", "source_url", "source_title", "publication_date", "event_date", "performance", "specifications", "methodology"]
        if evidence_type in {EvidenceType.RETAIL_LISTING.value, EvidenceType.MARKETPLACE_LISTING.value}:
            allowed_fields += ["seller", "marketplace", "availability", "current_price", "sale_price", "product_url", "image_url"]
        if evidence_type in {EvidenceType.BENCHMARK.value, EvidenceType.REVIEW.value, EvidenceType.TECHNICAL_COMPARISON.value}:
            allowed_fields += ["benchmark", "fps", "power", "relative_performance", "test_methodology"]
        if evidence_type in {EvidenceType.NEWS_ARTICLE.value, EvidenceType.OFFICIAL_ANNOUNCEMENT.value}:
            allowed_fields += ["announcement", "quote", "publication_date", "event_date", "updated_date"]
        relevance = cls.topic_relevance(record, semantic)
        blocked = bool(re.search(r"(?:captcha|are you a robot|enable javascript|enable cookies|access denied|robot check|terms of service and cookie policy)", haystack, re.I))
        return {"evidence_type": evidence_type, "source_role": evidence_type, "source_quality": cls.quality(host, evidence_type), "allowed_fields": allowed_fields, "commerce_signals": commerce_signals, "commerce_verified": evidence_type in {EvidenceType.RETAIL_LISTING.value, EvidenceType.MARKETPLACE_LISTING.value}, "price_type": price_type, "topic_relevance": relevance, "blocked_or_garbage": blocked}

    @staticmethod
    def quality(host: str, evidence_type: str) -> float:
        if evidence_type in {EvidenceType.OFFICIAL_PRODUCT.value, EvidenceType.OFFICIAL_ANNOUNCEMENT.value, EvidenceType.OFFICIAL_DOCUMENTATION.value}:
            return 0.9
        if evidence_type in {EvidenceType.RETAIL_LISTING.value, EvidenceType.MARKETPLACE_LISTING.value}:
            return 0.72
        if evidence_type in {EvidenceType.REVIEW.value, EvidenceType.BENCHMARK.value, EvidenceType.RESEARCH_PAPER.value}:
            return 0.7
        if evidence_type == EvidenceType.NEWS_ARTICLE.value:
            return 0.68
        return 0.45

    @staticmethod
    def price_type(content: str, evidence_type: str, signals: Sequence[str]) -> str:
        text = str(content or "").lower()
        if evidence_type not in {EvidenceType.RETAIL_LISTING.value, EvidenceType.MARKETPLACE_LISTING.value}:
            if re.search(r"\bmsrp\b|manufacturer.?s suggested", text):
                return PriceType.MSRP.value
            if re.search(r"\blaunch\s+price\b|at\s+launch", text):
                return PriceType.LAUNCH_PRICE.value
            if re.search(r"\bhistorical|originally|was\s+\$", text):
                return PriceType.HISTORICAL_PRICE.value
            if re.search(r"\$|€|£|₱|\b(?:usd|eur|gbp|php)\b", text):
                return PriceType.REFERENCE_PRICE.value
            return PriceType.UNKNOWN_PRICE.value
        if "current_price" in signals or "commerce_action" in signals or "availability" in signals:
            if re.search(r"\bsale|discount|offer\b", text):
                return PriceType.SALE_PRICE.value
            return PriceType.CURRENT_LISTING_PRICE.value
        return PriceType.UNKNOWN_PRICE.value

    @classmethod
    def topic_relevance(cls, record: Dict[str, Any], semantic: Optional[RequestSemanticModel]) -> Dict[str, Any]:
        if semantic is None:
            return {"score": 0.5, "relevant": True, "reasons": []}
        title = str(record.get("title") or "")
        content = str(record.get("content") or record.get("snippet") or record.get("evidence") or "")
        text = f"{title} {content}".lower()
        tokens = [token.lower() for entity in semantic.entities for token in re.findall(r"[a-z0-9]+", entity) if len(token) >= 3]
        matched = [token for token in dict.fromkeys(tokens) if token in text]
        score = len(matched) / max(1, min(4, len(set(tokens))))
        reasons = [f"matched entity term: {token}" for token in matched[:4]]
        if semantic.news and re.search(r"\b(?:gpu|graphics|geforce|radeon|rtx|rx|driver|graphics card)\b", semantic.query, re.I):
            gpu_terms = [term for term in ("gpu", "graphics", "geforce", "radeon", "rtx", "rx", "driver") if term in text]
            if not gpu_terms:
                score *= 0.25
                reasons.append("requested GPU/news topic was not present in the evidence")
        relevant = score >= 0.25 if tokens else True
        return {"score": round(min(1.0, score), 3), "relevant": relevant, "reasons": reasons}


class SynthesisEngine:
    """Produce compact task-specific answers from typed facts and citations."""

    _URL_GARBAGE = re.compile(r"\]\((?:https?://)[^)]+\)")
    _NAV_GARBAGE = re.compile(r"\b(?:view source|open image|skip to main content|select address|sign in|register)\b", re.I)

    @classmethod
    def clean(cls, text: str) -> str:
        value = str(text or "")
        value = cls._URL_GARBAGE.sub("", value)
        value = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", value)
        value = cls._NAV_GARBAGE.sub(" ", value)
        value = value.replace("�", " ").replace("â", " ").replace("Â", " ").replace("¯", " ")
        value = re.sub(r"\[[^\]]{0,160}\]", " ", value)
        value = value.replace("|", " ")
        value = re.sub(r"\s+", " ", value).strip(" -:;,.\t\r\n")
        return value

    @classmethod
    def synthesize(cls, semantic: RequestSemanticModel, facts: Sequence[Dict[str, Any]], sources: Sequence[Dict[str, Any]], conflicts: Sequence[Dict[str, Any]] = (), citations: Sequence[Dict[str, Any]] = ()) -> Dict[str, Any]:
        clean_facts = []
        seen = set()
        for raw in facts:
            if not isinstance(raw, dict):
                continue
            claim = cls.clean(raw.get("claim") or raw.get("evidence") or raw.get("content") or "")
            if not claim or claim.lower() in seen:
                continue
            seen.add(claim.lower())
            clean = dict(raw); clean["claim"] = claim
            clean_facts.append(clean)
        uncertainty: List[str] = []
        if conflicts:
            for conflict in conflicts[:3]:
                if isinstance(conflict, dict):
                    description = str(conflict.get("description") or "").strip()
                    if description:
                        uncertainty.append(description)
        if semantic.intent == ResearchIntent.NEWS_RESEARCH.value:
            answer = cls._news(semantic, clean_facts)
        elif semantic.intent in {ResearchIntent.TECHNICAL_COMPARISON.value, ResearchIntent.PRODUCT_COMPARISON.value}:
            answer = cls._comparison(semantic, clean_facts)
        elif semantic.intent == ResearchIntent.REVIEW_RESEARCH.value:
            answer = cls._review(semantic, clean_facts)
        elif semantic.intent == ResearchIntent.SPECIFICATION_LOOKUP.value:
            answer = cls._specification(semantic, clean_facts)
        else:
            answer = cls._factual(semantic, clean_facts)
        if not clean_facts:
            uncertainty.append("The available public sources did not provide enough relevant readable evidence.")
        return {"answer": answer, "facts": clean_facts, "uncertainty": list(dict.fromkeys(uncertainty)), "selected_citations": list(citations)[:8], "source_count": len(sources), "answer_plan": semantic.output_goal}

    @classmethod
    def _news(cls, semantic: RequestSemanticModel, facts: Sequence[Dict[str, Any]]) -> str:
        if not facts:
            return f"I could not verify a current {(' '.join(semantic.entities) or semantic.query)} development from the available public sources."
        lines = [f"Here are the most relevant recent developments I found for {' '.join(semantic.entities) or semantic.query}:"]
        for index, fact in enumerate(facts[:3], 1):
            date = fact.get("published_date") or fact.get("event_date") or fact.get("updated_date") or "date not exposed"
            title = str(fact.get("source_title") or "Source")
            lines.append(f"{index}. {fact.get('claim', '')} ({date}; {title})")
        return "\n".join(lines)

    @classmethod
    def _comparison(cls, semantic: RequestSemanticModel, facts: Sequence[Dict[str, Any]]) -> str:
        entities = semantic.entities[:2] or ["Item A", "Item B"]
        left, right = (entities + ["Item B", "Item C"])[:2]
        buckets = {left.lower(): [], right.lower(): [], "shared": []}
        for fact in facts:
            claim = str(fact.get("claim") or "")
            lower = claim.lower()
            if left.lower() in lower:
                buckets[left.lower()].append(claim)
            elif right.lower() in lower:
                buckets[right.lower()].append(claim)
            else:
                buckets["shared"].append(claim)
        lines = [f"Technical comparison: **{left}** versus **{right}**", "", "| Evidence area | " + left + " | " + right + " |", "|---|---|---|"]
        for dimension in semantic.comparison_dimensions[:6]:
            l = buckets[left.lower()][0] if buckets[left.lower()] else "Not established by the retrieved evidence"
            r = buckets[right.lower()][0] if buckets[right.lower()] else "Not established by the retrieved evidence"
            lines.append(f"| {dimension.replace('_', ' ').title()} | {cls.clean(l)[:220]} | {cls.clean(r)[:220]} |")
            if buckets[left.lower()]: buckets[left.lower()] = buckets[left.lower()][1:]
            if buckets[right.lower()]: buckets[right.lower()] = buckets[right.lower()][1:]
        if buckets["shared"]:
            lines.extend(["", "Independent evidence:", *[f"- {claim}" for claim in buckets["shared"][:3]]])
        lines.extend(["", "Tradeoff: the retrieved evidence supports a comparison, but it does not establish a universal winner. The better choice depends on the dimensions above and on whether current market price was explicitly requested."])
        return "\n".join(lines)

    @classmethod
    def _review(cls, semantic: RequestSemanticModel, facts: Sequence[Dict[str, Any]]) -> str:
        if not facts:
            return f"I could not find enough independent review evidence for {(' '.join(semantic.entities) or semantic.query)}."
        return "Reviewer evidence for " + (" ".join(semantic.entities) or semantic.query) + ":\n" + "\n".join(f"- {fact.get('claim', '')}" for fact in facts[:5]) + "\n\nThe sources may use different test conditions, so their performance figures should not be treated as directly interchangeable unless the methodology matches."

    @classmethod
    def _specification(cls, semantic: RequestSemanticModel, facts: Sequence[Dict[str, Any]]) -> str:
        if not facts:
            return f"I could not verify the requested specifications for {(' '.join(semantic.entities) or semantic.query)}."
        return "Relevant specifications I could verify:\n" + "\n".join(f"- {fact.get('claim', '')}" for fact in facts[:6])

    @classmethod
    def _factual(cls, semantic: RequestSemanticModel, facts: Sequence[Dict[str, Any]]) -> str:
        if not facts:
            return "I could not verify enough relevant public evidence to answer that reliably."
        return "\n".join(["Here is the answer supported by the relevant sources:", *[f"- {fact.get('claim', '')}" for fact in facts[:5]]])


__all__ = [
    "EvidenceClassifier",
    "EvidenceType",
    "FreshnessRequirement",
    "PriceType",
    "RequestSemanticAnalyzer",
    "RequestSemanticModel",
    "ResearchIntent",
    "ResearchStrategySelector",
    "SynthesisEngine",
]
