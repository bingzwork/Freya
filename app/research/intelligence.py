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
    input_modalities: List[str] = field(default_factory=list)
    requested_operation: str = "answer"
    attachment_role: str = "UNKNOWN"
    entity_source: str = ""
    resolved_entities: List[Dict[str, Any]] = field(default_factory=list)
    requires_vision: bool = False
    requires_web_search: bool = False
    requires_image_search: bool = False
    requires_reverse_image_search: bool = False
    requires_image_edit: bool = False
    requires_shopping: bool = False
    knowledge_improvement_state: str = "LOCAL_UNKNOWN"
    local_knowledge_confidence: float = 0.0
    freshness_class: str = "MEDIUM_CHANGE"
    research_reason: str = ""

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
        model = RequestSemanticModel(
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
        return cls._apply_multimodal(model, text, context)

    @classmethod
    def _apply_multimodal(cls, model: RequestSemanticModel, text: str, context: Dict[str, Any]) -> RequestSemanticModel:
        modalities = list(context.get("input_modalities") or [])
        if not modalities:
            paths = context.get("attachment_paths") or context.get("attachments") or []
            for raw in paths if isinstance(paths, list) else []:
                suffix = str(raw).lower().rsplit(".", 1)[-1] if "." in str(raw) else ""
                if suffix in {"jpg", "jpeg", "png", "webp", "gif", "bmp"}:
                    modalities.append("image")
                elif suffix in {"mp3", "wav", "m4a", "flac"}:
                    modalities.append("audio")
                elif suffix in {"mp4", "mov", "webm"}:
                    modalities.append("video")
                elif suffix:
                    modalities.append("document")
        modalities = list(dict.fromkeys(str(item).lower() for item in modalities if item))
        has_image = "image" in modalities
        lower = text.lower()
        reverse = bool(re.search(r"\b(?:reverse\s+image|find\s+(?:where|the\s+original\s+source)|where\s+(?:did|is)\s+this\s+(?:image|picture|photo)|find\s+this\s+image)\b", lower))
        similar = bool(re.search(r"\bfind\s+(?:similar|similars?)\b|\bsimilar\s+(?:images?|pictures?|photos?)\b", lower))
        edit = bool(re.search(r"\b(?:remove|change|replace|blur|crop|resize|rotate|edit|enhance)\b.{0,40}\b(?:background|image|photo|picture|it|this)\b", lower))
        ocr = bool(re.search(r"\b(?:read|extract|ocr|transcribe)\b.{0,50}\b(?:text|words|writing|sign|screenshot|image|photo|document)\b", lower))
        describe = bool(re.search(r"\b(?:describe|what does this (?:image|photo|picture) show|what is in this)\b", lower))
        visual_question = bool(re.search(r"\b(?:what color|what is (?:she|he|it) wearing|how many|is this|does this|where is the|what does the)\b", lower))
        show_more = bool(re.search(r"\b(?:show|find|give|send|fetch)\b.{0,60}\b(?:more|another|other|photos?|pictures?|images?)\b", lower) or re.search(r"\b(?:photos?|pictures?|images?)\s+of\b", lower))
        if re.search(r"\bphoto\s+printer\b", lower):
            show_more = False
        comparison = bool(cls._COMPARISON_RE.search(text))
        shopping = bool(cls._SHOPPING_RE.search(text) or cls._SITE_RE.search(text))
        current = bool(cls._LATEST_RE.search(text) or cls._NEWS_RE.search(text))
        deep = bool(cls._DEEP_RE.search(text))
        explicit_user_entities = cls._extract_user_provided_entities(text)
        user_entities = list(explicit_user_entities)
        recent_candidate = str(context.get("recent_image_entity") or "").strip()
        recent_entity = recent_candidate if re.search(r"\b(?:another|more|again|her|him|it|this one|same)\b", lower) else ""
        if not user_entities and recent_entity and re.search(r"\b(?:another|more|again|her|him|it|this one|same)\b", lower):
            user_entities = [recent_entity]
        entities = list(dict.fromkeys(list(model.entities) + user_entities))
        if reverse:
            model.intent = "REVERSE_IMAGE_SEARCH" if has_image else "REVERSE_IMAGE_SEARCH"
            model.operation = "find_source"
            model.output_goal = "image_results"
        elif similar:
            model.intent = "SIMILAR_IMAGE_SEARCH"
            model.operation = "find_similar"
            model.output_goal = "image_results"
        elif edit:
            model.intent = "IMAGE_EDIT"
            model.operation = "edit"
            model.output_goal = "edited_image"
        elif ocr:
            model.intent = "OCR"
            model.operation = "extract_text"
            model.output_goal = "extracted_text"
        elif describe:
            model.intent = "IMAGE_DESCRIPTION"
            model.operation = "describe"
            model.output_goal = "image_description"
        elif visual_question:
            model.intent = "VISION_QA"
            model.operation = "answer_about"
            model.output_goal = "visual_answer"
        elif comparison:
            model.intent = ResearchIntent.PRODUCT_COMPARISON.value if shopping else ResearchIntent.TECHNICAL_COMPARISON.value
            model.operation = "compare"
            model.output_goal = "comparison"
        elif show_more:
            model.intent = ResearchIntent.IMAGE_SEARCH.value
            model.operation = "find_more_photos" if re.search(r"\bmore|another|other\b", lower) else "search_images"
            model.output_goal = "image_results"
        elif current:
            model.intent = ResearchIntent.NEWS_RESEARCH.value
            model.operation = "summarize"
        elif deep:
            model.intent = ResearchIntent.DEEP_RESEARCH.value
            model.operation = "research"
        model.requested_operation = model.operation
        model.entities = entities[:6]
        model.entity_source = "USER_PROVIDED" if explicit_user_entities else ("CONVERSATION_CONTEXT" if recent_entity else "")
        model.resolved_entities = [{"raw": item, "canonical": item, "source": model.entity_source or "CONTEXT"} for item in entities]
        model.requires_image_search = bool(show_more and not reverse and not similar)
        model.requires_reverse_image_search = reverse
        model.requires_image_edit = edit
        model.requires_shopping = bool(shopping and model.intent in {ResearchIntent.SHOPPING_DISCOVERY.value, ResearchIntent.SHOPPING_PRICE_SEARCH.value, ResearchIntent.PRODUCT_COMPARISON.value})
        model.requires_web_search = bool(current or deep or comparison or shopping or model.requires_image_search)
        if modalities:
            model.input_modalities = modalities
            model.image = has_image or model.image
            model.attachment_role = "SEARCH_SEED" if reverse or similar else "EDIT_TARGET" if edit else "DOCUMENT_SOURCE" if "document" in modalities and not has_image else "REFERENCE_CONTEXT" if (show_more or comparison or shopping or current or deep) else "PRIMARY_SUBJECT"
            model.requires_vision = bool(has_image and (describe or visual_question or ocr or (reverse or similar) and not entities))
            model.reasoning.append("multimodal operation resolved from explicit text before attachment tool selection")
        return model

    @staticmethod
    def _extract_user_provided_entities(text: str) -> List[str]:
        patterns = [
            r"\bthis is\s+([A-Z][A-Za-z0-9.-]*(?:\s+[A-Z][A-Za-z0-9.-]*){0,5})",
            r"\b(?:named|called|name is)\s+([A-Z][A-Za-z0-9.-]*(?:\s+[A-Z][A-Za-z0-9.-]*){0,5})",
        ]
        found: List[str] = []
        for pattern in patterns:
            for match in re.finditer(pattern, text, flags=re.I):
                value = re.split(r"\b(?:show|find|compare|and|who|what|with)\b", match.group(1), maxsplit=1, flags=re.I)[0].strip(" .?!,;:")
                if value and len(value) >= 2:
                    found.append(value)
        return list(dict.fromkeys(found))[:4]

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

    @staticmethod
    def select_vertical(semantic: RequestSemanticModel) -> str:
        if semantic.intent == ResearchIntent.NEWS_RESEARCH.value:
            return "NEWS"
        if semantic.intent == ResearchIntent.SPECIFICATION_LOOKUP.value:
            return "OFFICIAL_DOCUMENTATION"
        if semantic.intent == ResearchIntent.REVIEW_RESEARCH.value:
            return "REVIEWS"
        if semantic.intent in {ResearchIntent.SHOPPING_DISCOVERY.value, ResearchIntent.SHOPPING_PRICE_SEARCH.value}:
            return "MARKETPLACES" if semantic.requested_domain else "PRODUCTS"
        if semantic.intent in {ResearchIntent.TECHNICAL_COMPARISON.value, ResearchIntent.PRODUCT_COMPARISON.value}:
            return "PRODUCTS"
        if semantic.intent == ResearchIntent.IMAGE_SEARCH.value:
            return "IMAGE_SEARCH"
        query = semantic.query.lower()
        if re.search(r"\b(?:paper|journal|study|research|doi|arxiv|scientific)\b", query):
            return "ACADEMIC_RESEARCH"
        if re.search(r"\b(?:github|repository|source code|library|package|api|sdk)\b", query):
            return "SOFTWARE_REPOSITORIES"
        if re.search(r"\b(?:docs|documentation|manual|reference|how to use)\b", query):
            return "OFFICIAL_DOCUMENTATION"
        return "GENERAL_WEB"

    @classmethod
    def vertical_plan(cls, semantic: RequestSemanticModel) -> Dict[str, Any]:
        vertical = cls.select_vertical(semantic)
        configs = {
            "NEWS": (['primary_reporting', 'official_announcement', 'independent_reputable_news'], "REALTIME", ['latest', 'official announcement', 'independent reporting'], ['publication date', 'event date', 'source independence'], ['prefer recent publication/event date', 'retain date uncertainty']),
            "OFFICIAL_DOCUMENTATION": (['first_party_docs', 'source_repository', 'standards'], "HIGH_CHANGE", ['official documentation', 'release notes', 'source repository'], ['version', 'supported behavior', 'deprecation'], ['prefer first-party sources', 'check version/date']),
            "ACADEMIC_RESEARCH": (['paper', 'journal', 'recognized_research'], "MEDIUM_CHANGE", ['primary paper', 'systematic review', 'independent replication'], ['methodology', 'sample/context', 'publication metadata'], ['separate findings from hypotheses']),
            "PRODUCTS": (['manufacturer', 'official_specs', 'independent_review', 'retailer'], "HIGH_CHANGE", ['official specifications', 'independent review', 'current price/value'], ['model/variant', 'specification', 'price type'], ['do not use reviews as manufacturer facts']),
            "MARKETPLACES": (['actual_listing', 'retailer', 'seller'], "HIGH_CHANGE", ['current listing', 'price stock variant', 'seller reputation'], ['listing URL', 'currency/region', 'availability', 'variant'], ['verify actual product page']),
            "REVIEWS": (['independent_review', 'benchmark', 'user_experience'], "MEDIUM_CHANGE", ['independent review', 'benchmark testing', 'strengths weaknesses'], ['test methodology', 'date', 'tradeoffs'], ['separate measured facts from opinion']),
            "SOFTWARE_REPOSITORIES": (['official_docs', 'source_repository', 'release_notes'], "HIGH_CHANGE", ['official documentation', 'release notes', 'source repository'], ['version', 'platform', 'license/compatibility'], ['prefer repository and first-party docs']),
            "IMAGE_SEARCH": (['image_source', 'entity_relevance', 'provenance'], "MEDIUM_CHANGE", ['entity images', 'source provenance'], ['image URL', 'source page', 'entity relevance'], ['do not claim identity beyond user context']),
            "GENERAL_WEB": (['authoritative_explanation', 'primary_source', 'independent_analysis'], "MEDIUM_CHANGE", ['primary source', 'independent analysis', 'official documentation'], ['claim', 'source', 'date'], ['qualify insufficient evidence']),
        }
        priorities, freshness, suffixes, extraction, verification = configs[vertical]
        return VerticalResearchPlan(vertical, priorities, freshness, suffixes, extraction, verification).to_dict()


class ResearchVertical(str, Enum):
    GENERAL_WEB = "GENERAL_WEB"
    NEWS = "NEWS"
    OFFICIAL_DOCUMENTATION = "OFFICIAL_DOCUMENTATION"
    ACADEMIC_RESEARCH = "ACADEMIC_RESEARCH"
    PRODUCTS = "PRODUCTS"
    MARKETPLACES = "MARKETPLACES"
    REVIEWS = "REVIEWS"
    SOFTWARE_REPOSITORIES = "SOFTWARE_REPOSITORIES"
    IMAGE_SEARCH = "IMAGE_SEARCH"


@dataclass
class VerticalResearchPlan:
    vertical: str
    source_priorities: List[str] = field(default_factory=list)
    freshness_requirement: str = "MEDIUM_CHANGE"
    query_suffixes: List[str] = field(default_factory=list)
    extraction_requirements: List[str] = field(default_factory=list)
    verification_rules: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SourceQualityProfile:
    domain: str
    source_type: str = "GENERAL_WEB"
    authority_score: float = 0.45
    extraction_successes: int = 0
    extraction_failures: int = 0
    freshness_successes: int = 0
    relevance_hits: int = 0
    duplicate_observations: int = 0
    conflict_observations: int = 0
    verification_successes: int = 0
    rate_limit_failures: int = 0
    last_evaluated_at: str = ""

    @property
    def extraction_success_rate(self) -> float:
        total = self.extraction_successes + self.extraction_failures
        return round(self.extraction_successes / total, 3) if total else 0.5

    @property
    def verification_rate(self) -> float:
        return round(self.verification_successes / max(1, self.relevance_hits), 3)

    def ranking_bonus(self) -> float:
        return round(max(-0.25, min(0.25, (self.authority_score - 0.5) * 0.25 + (self.extraction_success_rate - 0.5) * 0.15 + (self.verification_rate - 0.5) * 0.10 - self.rate_limit_failures * 0.01)), 3)

    def to_dict(self) -> Dict[str, Any]:
        return {**asdict(self), "extraction_success_rate": self.extraction_success_rate, "verification_rate": self.verification_rate, "ranking_bonus": self.ranking_bonus()}


class SourceQualityProfileStore:
    """Operational source profiles; evidence remains stronger than reputation."""

    def __init__(self):
        self._profiles: Dict[str, SourceQualityProfile] = {}

    @staticmethod
    def _domain(value: str) -> str:
        host = (urlparse(str(value or "")).hostname or str(value or "")).lower().strip()
        return host.removeprefix("www.")

    def get(self, url_or_domain: str, source_type: str = "GENERAL_WEB") -> SourceQualityProfile:
        domain = self._domain(url_or_domain)
        if domain not in self._profiles:
            self._profiles[domain] = SourceQualityProfile(domain=domain, source_type=source_type)
        profile = self._profiles[domain]
        if source_type and profile.source_type == "GENERAL_WEB":
            profile.source_type = source_type
        return profile

    def observe(self, url: str, *, source_type: str = "GENERAL_WEB", authority_score: Optional[float] = None, extracted: Optional[bool] = None, relevant: Optional[bool] = None, duplicate: bool = False, conflict: bool = False, verified: bool = False, rate_limited: bool = False) -> SourceQualityProfile:
        profile = self.get(url, source_type)
        if authority_score is not None:
            profile.authority_score = round(max(0.0, min(1.0, (profile.authority_score + float(authority_score)) / 2)), 3)
        if extracted is True:
            profile.extraction_successes += 1
        elif extracted is False:
            profile.extraction_failures += 1
        if relevant:
            profile.relevance_hits += 1
        if duplicate:
            profile.duplicate_observations += 1
        if conflict:
            profile.conflict_observations += 1
        if verified:
            profile.verification_successes += 1
        if rate_limited:
            profile.rate_limit_failures += 1
        profile.last_evaluated_at = datetime.now(timezone.utc).isoformat()
        return profile

    def ranking_bonus(self, url: str) -> float:
        return self.get(url).ranking_bonus()

    def snapshot(self) -> List[Dict[str, Any]]:
        return [profile.to_dict() for profile in self._profiles.values()]


class FeedbackType(str, Enum):
    USER_PREFERENCE = "USER_PREFERENCE"
    FACTUAL_CORRECTION = "FACTUAL_CORRECTION"
    SOURCE_FEEDBACK = "SOURCE_FEEDBACK"
    ANSWER_STYLE = "ANSWER_STYLE"
    EXECUTION_FEEDBACK = "EXECUTION_FEEDBACK"
    ANSWER_CONFIRMATION = "ANSWER_CONFIRMATION"
    UNKNOWN = "UNKNOWN"


class FeedbackClassifier:
    @classmethod
    def classify(cls, text: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        value = " ".join(str(text or "").split()).strip()
        lower = value.lower()
        if re.search(r"\b(?:wrong|incorrect|not correct|that's not right|that is not right|false|you made a mistake|fix that)", lower):
            feedback_type = FeedbackType.FACTUAL_CORRECTION.value
        elif re.search(r"\b(?:source|citation|reference|don't use|do not use|better source|more reliable)", lower):
            feedback_type = FeedbackType.SOURCE_FEEDBACK.value
        elif re.search(r"\b(?:prefer|i like|i want|keep answers|be more|be less|concise|verbose|shorter|longer)", lower):
            feedback_type = FeedbackType.USER_PREFERENCE.value if "prefer" in lower or "i like" in lower or "i want" in lower else FeedbackType.ANSWER_STYLE.value
        elif re.search(r"\b(?:didn't work|did not work|failed|failure|broken|error|couldn't|could not)", lower):
            feedback_type = FeedbackType.EXECUTION_FEEDBACK.value
        elif re.search(r"\b(?:correct|right|accurate|thanks|thank you|works|helpful)", lower):
            feedback_type = FeedbackType.ANSWER_CONFIRMATION.value
        else:
            feedback_type = FeedbackType.UNKNOWN.value
        return {"type": feedback_type, "text": value, "has_prior_research": bool((context or {}).get("research_result") or (context or {}).get("last_research_result")), "requires_fact_verification": feedback_type == FeedbackType.FACTUAL_CORRECTION.value}


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
    def attach_inline_citations(cls, answer: str, facts: Sequence[Dict[str, Any]], citations: Sequence[Dict[str, Any]]) -> str:
        text = str(answer or "").strip()
        if not text or not facts or not citations:
            return text
        citation_by_url: Dict[str, int] = {}
        visible_sources: List[Dict[str, Any]] = []
        for item in citations:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or item.get("source_url") or "").strip()
            if not url:
                continue
            if url not in citation_by_url:
                citation_by_url[url] = len(citation_by_url) + 1
                visible_sources.append({"number": citation_by_url[url], "title": str(item.get("title") or item.get("source_title") or url), "url": url})
        if not citation_by_url:
            return text
        fact_records = [item for item in facts if isinstance(item, dict)]
        paragraphs = re.split(r"(?<=[.!?])\s+", text)
        rendered: List[str] = []
        for paragraph in paragraphs:
            sentence = paragraph.strip()
            if not sentence:
                continue
            best = None
            best_score = 0.0
            for fact in fact_records:
                score = KnowledgeReconciler._similarity(sentence, str(fact.get("claim") or fact.get("evidence") or ""))
                if score > best_score:
                    best_score = score
                    best = fact
            url = str((best or {}).get("source_url") or (best or {}).get("url") or "")
            number = citation_by_url.get(url)
            rendered.append(sentence + (f" [{number}]" if number and best_score >= 0.16 else ""))
        if not rendered:
            return text
        source_lines = [f"[{item['number']}] [{item['title']}]({item['url']})" for item in visible_sources]
        return " ".join(rendered) + "\n\nSources:\n" + "\n".join(source_lines)

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


class KnowledgeFreshness(str, Enum):
    STATIC = "STATIC"
    LOW_CHANGE = "LOW_CHANGE"
    MEDIUM_CHANGE = "MEDIUM_CHANGE"
    HIGH_CHANGE = "HIGH_CHANGE"
    REALTIME = "REALTIME"


class KnowledgeImprovementState(str, Enum):
    LOCAL_SUFFICIENT_AND_CURRENT = "LOCAL_SUFFICIENT_AND_CURRENT"
    LOCAL_VALID_BUT_ENRICHABLE = "LOCAL_VALID_BUT_ENRICHABLE"
    LOCAL_STALE = "LOCAL_STALE"
    LOCAL_CONFLICTED = "LOCAL_CONFLICTED"
    LOCAL_INCOMPLETE = "LOCAL_INCOMPLETE"
    LOCAL_UNKNOWN = "LOCAL_UNKNOWN"
    OFFLINE_LOCAL_ONLY = "OFFLINE_LOCAL_ONLY"


@dataclass
class LocalKnowledgeSnapshot:
    query: str
    claims: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    provenance: List[Dict[str, Any]] = field(default_factory=list)
    learned_at: str = ""
    verified_at: str = ""
    freshness: str = KnowledgeFreshness.MEDIUM_CHANGE.value
    domain: str = ""
    source_types: List[str] = field(default_factory=list)
    retrieval_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ReconciledClaim:
    claim: str
    status: str
    local_value: str = ""
    external_value: str = ""
    local_provenance: Dict[str, Any] = field(default_factory=dict)
    external_provenance: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    chosen_interpretation: str = ""
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class KnowledgeImprovementAssessor:
    """Decide whether a local baseline can materially benefit from research."""

    _FRESHNESS_INTENTS = {
        ResearchIntent.CURRENT_LOOKUP.value,
        ResearchIntent.NEWS_RESEARCH.value,
        ResearchIntent.SHOPPING_DISCOVERY.value,
        ResearchIntent.SHOPPING_PRICE_SEARCH.value,
        ResearchIntent.REVIEW_RESEARCH.value,
        ResearchIntent.SPECIFICATION_LOOKUP.value,
        ResearchIntent.TECHNICAL_COMPARISON.value,
        ResearchIntent.PRODUCT_COMPARISON.value,
    }
    _ENRICHMENT_TERMS = re.compile(r"\b(?:best|recommend|recommended|options|examples|alternatives|technical|software|model|architecture|scientific|medical|legal|financial|political|market|available|version|release|benchmark|review|compare|explain)\b", re.I)

    @classmethod
    def freshness_for(cls, semantic: Optional[RequestSemanticModel]) -> str:
        if semantic is None:
            return KnowledgeFreshness.MEDIUM_CHANGE.value
        if semantic.intent in {ResearchIntent.NEWS_RESEARCH.value} or semantic.freshness == FreshnessRequirement.LATEST.value:
            return KnowledgeFreshness.REALTIME.value
        if semantic.intent in cls._FRESHNESS_INTENTS or semantic.freshness == FreshnessRequirement.CURRENT_PREFERRED.value:
            return KnowledgeFreshness.HIGH_CHANGE.value
        if semantic.intent in {ResearchIntent.FACTUAL_LOOKUP.value, ResearchIntent.PAGE_SUMMARY.value}:
            return KnowledgeFreshness.LOW_CHANGE.value
        return KnowledgeFreshness.MEDIUM_CHANGE.value

    @classmethod
    def build_snapshot(cls, query: str, retrieved: Sequence[Any], semantic: Optional[RequestSemanticModel] = None) -> LocalKnowledgeSnapshot:
        claims: List[Dict[str, Any]] = []
        provenance: List[Dict[str, Any]] = []
        source_types: List[str] = []
        scores: List[float] = []
        for item in list(retrieved or [])[:20]:
            if isinstance(item, dict):
                content = str(item.get("content") or item.get("text") or item.get("claim") or "").strip()
                source = str(item.get("source_id") or item.get("source") or "local_memory")
                score = item.get("score", 0.0)
                metadata = dict(item.get("metadata") or {})
            else:
                content = str(getattr(item, "content", "") or getattr(item, "claim", "") or "").strip()
                source = str(getattr(item, "source_id", None) or getattr(item, "source", None) or "local_memory")
                score = getattr(item, "score", 0.0)
                metadata = dict(getattr(item, "metadata", {}) or {})
            if not content:
                continue
            try:
                numeric_score = max(0.0, min(1.0, float(score)))
            except (TypeError, ValueError):
                numeric_score = 0.0
            scores.append(numeric_score)
            source_type = str(metadata.get("source_type") or metadata.get("category") or "LOCAL_MEMORY")
            source_types.append(source_type)
            claim = {"claim": content[:1200], "source": source, "score": numeric_score, "metadata": metadata}
            claims.append(claim)
            provenance.append({"source": source, "source_type": source_type, "score": numeric_score, "metadata": metadata})
        return cls._snapshot_from_claims(query, claims, provenance, source_types, scores, semantic)

    @classmethod
    def _snapshot_from_claims(cls, query, claims, provenance, source_types, scores, semantic):
        freshness = cls.freshness_for(semantic)
        learned_dates = [str(item.get("metadata", {}).get(key) or "") for item in claims for key in ("learned_at", "created_at", "updated_at", "verified_at") if item.get("metadata", {}).get(key)]
        verified_dates = [str(item.get("metadata", {}).get("verified_at") or "") for item in claims if item.get("metadata", {}).get("verified_at")]
        return LocalKnowledgeSnapshot(
            query=str(query or ""),
            claims=claims,
            confidence=round(sum(scores) / len(scores), 3) if scores else 0.0,
            provenance=provenance,
            learned_at=max(learned_dates) if learned_dates else "",
            verified_at=max(verified_dates) if verified_dates else "",
            freshness=freshness,
            domain=(semantic.requested_domain if semantic else ""),
            source_types=list(dict.fromkeys(source_types)),
            retrieval_count=len(claims),
        )

    @classmethod
    def assess(cls, query: str, semantic: RequestSemanticModel, snapshot: LocalKnowledgeSnapshot, *, external_available: bool = True) -> Dict[str, Any]:
        if not external_available:
            state = KnowledgeImprovementState.OFFLINE_LOCAL_ONLY.value if snapshot.claims else KnowledgeImprovementState.LOCAL_UNKNOWN.value
            return {"state": state, "should_research": False, "reason": "external research is unavailable", "freshness": snapshot.freshness}
        if not snapshot.claims:
            return {"state": KnowledgeImprovementState.LOCAL_UNKNOWN.value, "should_research": True, "reason": "no relevant local baseline was retrieved", "freshness": snapshot.freshness}
        if semantic.intent in cls._FRESHNESS_INTENTS or semantic.freshness in {FreshnessRequirement.CURRENT_PREFERRED.value, FreshnessRequirement.LATEST.value}:
            state = KnowledgeImprovementState.LOCAL_STALE.value if snapshot.freshness in {KnowledgeFreshness.HIGH_CHANGE.value, KnowledgeFreshness.REALTIME.value} else KnowledgeImprovementState.LOCAL_VALID_BUT_ENRICHABLE.value
            return {"state": state, "should_research": True, "reason": "request is freshness-sensitive or externally changing", "freshness": snapshot.freshness}
        if cls._ENRICHMENT_TERMS.search(query) or len(snapshot.claims) < 2:
            return {"state": KnowledgeImprovementState.LOCAL_VALID_BUT_ENRICHABLE.value, "should_research": True, "reason": "external evidence can materially improve depth, alternatives, context, or confidence", "freshness": snapshot.freshness}
        return {"state": KnowledgeImprovementState.LOCAL_SUFFICIENT_AND_CURRENT.value, "should_research": False, "reason": "local evidence is sufficient for this stable request", "freshness": snapshot.freshness}


class KnowledgeReconciler:
    """Reconcile local claims with external facts without treating recency as truth."""

    @staticmethod
    def _text(value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()

    @staticmethod
    def _tokens(value: str) -> set[str]:
        return {token for token in re.findall(r"[a-z0-9]+", value.lower()) if len(token) >= 3}

    @classmethod
    def _similarity(cls, left: str, right: str) -> float:
        a, b = cls._tokens(left), cls._tokens(right)
        return len(a & b) / max(1, len(a | b))

    @classmethod
    def _external_record(cls, item: Any) -> Dict[str, Any]:
        raw = item.to_dict() if hasattr(item, "to_dict") else dict(item or {}) if isinstance(item, dict) else {}
        return {"claim": cls._text(raw.get("claim") or raw.get("evidence") or raw.get("content")), "source_url": cls._text(raw.get("source_url") or raw.get("url")), "source_title": cls._text(raw.get("source_title") or raw.get("title")), "evidence_type": cls._text(raw.get("evidence_type") or raw.get("source_role") or "GENERAL_WEB"), "confidence": float(raw.get("confidence") or raw.get("source_quality") or 0.0), "published_date": cls._text(raw.get("published_date") or raw.get("event_date") or raw.get("updated_date")), "metadata": dict(raw.get("metadata") or {})}

    @classmethod
    def reconcile(cls, snapshot: LocalKnowledgeSnapshot, external: Sequence[Any], semantic: Optional[RequestSemanticModel] = None) -> Dict[str, Any]:
        local_claims = list(snapshot.claims or [])
        external_claims = [cls._external_record(item) for item in list(external or []) if cls._external_record(item).get("claim")]
        used_external: set[int] = set()
        reconciled: List[ReconciledClaim] = []
        for local in local_claims:
            local_text = cls._text(local.get("claim"))
            best_index, best_score = None, 0.0
            for index, item in enumerate(external_claims):
                score = cls._similarity(local_text, item["claim"])
                if score > best_score:
                    best_index, best_score = index, score
            provenance = {"source": local.get("source", "local_memory"), "metadata": local.get("metadata", {})}
            if best_index is None or best_score < 0.20:
                reconciled.append(ReconciledClaim(local_text, "LOCAL_ONLY", local_text, "", provenance, {}, float(local.get("score", 0.0)), local_text, "No sufficiently similar external claim was found."))
                continue
            used_external.add(best_index)
            external_item = external_claims[best_index]
            external_text = external_item["claim"]
            local_numbers = re.findall(r"\b\d+(?:\.\d+)?%?\b", local_text)
            external_numbers = re.findall(r"\b\d+(?:\.\d+)?%?\b", external_text)
            if local_numbers and external_numbers and local_numbers != external_numbers:
                status = "CONFLICT"
                chosen = external_text if external_item["confidence"] > float(local.get("score", 0.0)) else local_text
                reason = "Material numeric values differ; the higher-quality or higher-confidence evidence was preferred without erasing the disagreement."
            elif best_score >= 0.55:
                status, chosen, reason = "AGREE", external_text, "Local and external claims materially agree."
            else:
                status, chosen, reason = "PARTIAL_AGREEMENT", external_text, "The claims overlap but do not establish identical detail."
            reconciled.append(ReconciledClaim(local_text, status, local_text, external_text, provenance, {"source_url": external_item["source_url"], "source_title": external_item["source_title"], "evidence_type": external_item["evidence_type"]}, round(max(float(local.get("score", 0.0)), external_item["confidence"], best_score), 3), chosen, reason))
        for index, item in enumerate(external_claims):
            if index not in used_external:
                reconciled.append(ReconciledClaim(item["claim"], "WEB_ONLY", "", item["claim"], {}, {"source_url": item["source_url"], "source_title": item["source_title"], "evidence_type": item["evidence_type"]}, round(max(item["confidence"], 0.45), 3), item["claim"], "External evidence adds a claim absent from the local baseline."))
        statuses = [item.status for item in reconciled]
        if any(item == "CONFLICT" for item in statuses):
            overall = "CONFLICTED"
        elif external_claims and any(item in {"WEB_ONLY", "PARTIAL_AGREEMENT"} for item in statuses):
            overall = "PARTIAL_AGREEMENT"
        elif external_claims and statuses:
            overall = "AGREE"
        elif local_claims:
            overall = "LOCAL_ONLY"
        else:
            overall = "INSUFFICIENT_EVIDENCE"
        return {"status": overall, "claims": [item.to_dict() for item in reconciled], "local_claim_count": len(local_claims), "external_claim_count": len(external_claims), "source_count": len({item["source_url"] for item in external_claims if item["source_url"]})}


class ResearchAnswerQualityVerifier:
    """Check answer coverage against selected evidence before presentation."""

    @classmethod
    def verify(cls, answer: str, facts: Sequence[Any], sources: Sequence[Any], conflicts: Sequence[Any] = ()) -> Dict[str, Any]:
        text = str(answer or "").strip()
        evidence = [KnowledgeReconciler._external_record(item) for item in list(facts or [])]
        material_claims = [part.strip(" -*\n") for part in re.split(r"(?:\n+|(?<=[.!?])\s+)", text) if len(part.strip()) >= 24 and not part.strip().startswith(("Technical comparison:", "Here are the most relevant", "Relevant specifications"))]
        unsupported: List[str] = []
        supported: List[str] = []
        for claim in material_claims[:12]:
            best = max((KnowledgeReconciler._similarity(claim, item["claim"]) for item in evidence), default=0.0)
            if best < 0.16:
                unsupported.append(claim[:240])
            else:
                supported.append(claim[:240])
        if not evidence:
            status = "INSUFFICIENT_EVIDENCE"
        elif conflicts:
            status = "CONFLICTED" if not unsupported else "PARTIALLY_VERIFIED"
        elif unsupported:
            status = "PARTIALLY_VERIFIED"
        else:
            status = "VERIFIED"
        return {"status": status, "supported_claims": supported, "unsupported_claims": unsupported, "source_count": len({item["source_url"] for item in evidence if item["source_url"]}), "repair_recommended": bool(unsupported) or (bool(evidence) and len(sources or []) == 0), "checked_claim_count": len(material_claims[:12])}


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
