"""General comparison intelligence between request semantics and web evidence.

This module deliberately does not search, browse, route, remember, or synthesize raw
pages.  It converts a typed comparison request and classified facts into a compact,
validated comparison state that the canonical ResearchCapability can execute.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, replace
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.research.intelligence import EvidenceType, RequestSemanticModel, ResearchIntent


class SufficiencyStatus(str, Enum):
    SUFFICIENT = "SUFFICIENT"
    PARTIAL_BUT_USEFUL = "PARTIAL_BUT_USEFUL"
    INSUFFICIENT = "INSUFFICIENT"


@dataclass
class ResolvedEntity:
    raw_text: str
    canonical_name: str
    manufacturer: str = ""
    family: str = ""
    model: str = ""
    category: str = ""
    aliases: List[str] = field(default_factory=list)
    confidence: float = 0.0
    resolution_source: str = "deterministic_context"
    verification_evidence: List[str] = field(default_factory=list)
    ambiguous_candidates: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ComparisonPlan:
    entities: List[ResolvedEntity]
    category: str
    dimensions: List[str]
    required_evidence_roles: List[str]
    queries: List[Dict[str, Any]]
    max_queries: int = 8

    def to_dict(self) -> Dict[str, Any]:
        value = asdict(self)
        value["entities"] = [entity.to_dict() for entity in self.entities]
        return value


@dataclass
class TypedClaim:
    entity: str
    property: str
    value: str
    unit: str = ""
    evidence_role: str = EvidenceType.GENERAL_WEB.value
    source_url: str = ""
    source_title: str = ""
    conditions: Dict[str, str] = field(default_factory=dict)
    confidence: float = 0.0
    direct_quote: str = ""
    comparable: Optional[bool] = None
    source_quality: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceCell:
    entity: str
    dimension: str
    claims: List[TypedClaim] = field(default_factory=list)
    status: str = "missing"
    support_count: int = 0
    comparable: Optional[bool] = None
    conflicting: bool = False

    def to_dict(self) -> Dict[str, Any]:
        value = asdict(self)
        value["claims"] = [claim.to_dict() for claim in self.claims]
        return value


@dataclass
class ComparisonEvidenceMatrix:
    entities: List[str]
    dimensions: List[str]
    cells: Dict[str, Dict[str, EvidenceCell]] = field(default_factory=dict)
    shared_claims: List[TypedClaim] = field(default_factory=list)
    sufficiency: SufficiencyStatus = SufficiencyStatus.INSUFFICIENT
    missing_evidence: List[str] = field(default_factory=list)
    gap_queries: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entities": list(self.entities),
            "dimensions": list(self.dimensions),
            "cells": {entity: {dimension: cell.to_dict() for dimension, cell in values.items()} for entity, values in self.cells.items()},
            "shared_claims": [claim.to_dict() for claim in self.shared_claims],
            "sufficiency": self.sufficiency.value,
            "missing_evidence": list(self.missing_evidence),
            "gap_queries": list(self.gap_queries),
        }


@dataclass
class ComparisonState:
    resolved_entities: List[ResolvedEntity]
    category: str
    plan: ComparisonPlan
    claims: List[TypedClaim] = field(default_factory=list)
    matrix: Optional[ComparisonEvidenceMatrix] = None
    conflicts: List[Dict[str, Any]] = field(default_factory=list)
    validation_errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resolved_entities": [item.to_dict() for item in self.resolved_entities],
            "category": self.category,
            "plan": self.plan.to_dict(),
            "claims": [item.to_dict() for item in self.claims],
            "matrix": self.matrix.to_dict() if self.matrix else None,
            "conflicts": list(self.conflicts),
            "validation_errors": list(self.validation_errors),
        }


class ComparisonIntelligenceEngine:
    """Resolve, plan, classify, and validate comparisons without owning retrieval."""

    _CATEGORY_RULES: Sequence[Tuple[str, str, str, str]] = (
        ("gpu", r"\b(?:rtx|rx|geforce|radeon)\b", "", ""),
        ("smartphone", r"\b(?:iphone|galaxy\s+s?\d{1,2}|pixel\s+\d{1,2})\b", "", ""),
        ("cpu", r"\b(?:ryzen|core\s+i\d|threadripper|epyc)\b", "", ""),
        ("console", r"\b(?:playstation|ps\s*\d|xbox|switch)\b", "", ""),
        ("laptop", r"\b(?:macbook|thinkpad|surface\s+laptop|zenbook)\b", "", ""),
        ("database", r"\b(?:postgres(?:ql)?|mysql|mariadb|sqlite|oracle)\b", "", ""),
        ("browser automation framework", r"\b(?:playwright|selenium|puppeteer|cypress)\b", "", ""),
        ("frontend framework", r"\b(?:react|vue|angular|svelte)\b", "", ""),
    )
    _DIMENSIONS: Dict[str, List[str]] = {
        "gpu": ["architecture", "specifications", "vram", "memory", "raster performance", "ray tracing", "power", "software features", "media", "price/value"],
        "cpu": ["architecture", "cores/threads", "clock", "cache", "gaming performance", "productivity performance", "efficiency", "platform", "price/value"],
        "smartphone": ["display", "camera", "battery", "chipset", "software", "storage", "durability", "price"],
        "console": ["hardware", "performance", "games/ecosystem", "storage", "features", "power", "price"],
        "laptop": ["processor", "display", "memory/storage", "battery", "graphics", "build", "price"],
        "database": ["capabilities", "architecture", "performance", "transactions", "ecosystem", "operations", "compatibility", "best use cases"],
        "browser automation framework": ["capabilities", "architecture", "performance", "ecosystem", "learning curve", "maintainability", "deployment", "compatibility"],
        "frontend framework": ["capabilities", "architecture", "performance", "ecosystem", "learning curve", "maintainability", "deployment", "compatibility"],
        "general": ["capabilities", "architecture", "performance", "compatibility", "ecosystem", "price/value", "best use cases"],
    }
    _PREFIXES = ("rtx", "rx", "geforce", "radeon", "ryzen", "core", "galaxy", "iphone", "playstation", "ps", "macbook", "postgresql", "postgres", "mysql", "playwright", "selenium", "react", "vue")

    def resolve(self, semantic: RequestSemanticModel, context: Optional[Dict[str, Any]] = None) -> List[ResolvedEntity]:
        if semantic.intent not in {ResearchIntent.TECHNICAL_COMPARISON.value, ResearchIntent.PRODUCT_COMPARISON.value}:
            return []
        raw_sides = self._raw_sides(semantic.query)
        if len(raw_sides) < 2:
            raw_sides = list(semantic.entities[:2])
        if len(raw_sides) < 2:
            return []
        category = self.category(" ".join(raw_sides), context=context)
        first = self._normalize(raw_sides[0], category, context=context)
        second = self._normalize(raw_sides[1], category, context=context, inherited=first)
        return [first, second]

    def resolve_semantic(self, semantic: RequestSemanticModel, context: Optional[Dict[str, Any]] = None) -> RequestSemanticModel:
        resolved = self.resolve(semantic, context=context)
        if not resolved:
            return semantic
        dimensions = list(semantic.comparison_dimensions) or self.dimensions(self.category(" ".join(item.canonical_name for item in resolved)))
        return replace(semantic, entities=[item.canonical_name for item in resolved], comparison_dimensions=dimensions, confidence=min(0.99, max(semantic.confidence, min(item.confidence for item in resolved))))

    def category(self, text: str, context: Optional[Dict[str, Any]] = None) -> str:
        lowered = str(text or "").lower()
        for category, pattern, _, _ in self._CATEGORY_RULES:
            if re.search(pattern, lowered, re.I):
                return category
        context_category = str((context or {}).get("comparison_category") or "").strip().lower()
        return context_category or "general"

    def dimensions(self, category: str, requested: Optional[Sequence[str]] = None) -> List[str]:
        defaults = list(self._DIMENSIONS.get(category, self._DIMENSIONS["general"]))
        if requested:
            requested_lower = {str(item).lower() for item in requested}
            selected = [item for item in defaults if item.lower() in requested_lower or any(token in item.lower() for token in requested_lower)]
            if selected:
                return selected
        return defaults

    def build_plan(self, semantic: RequestSemanticModel, entities: Sequence[ResolvedEntity]) -> ComparisonPlan:
        category = self.category(" ".join(item.canonical_name for item in entities))
        dimensions = self.dimensions(category, semantic.comparison_dimensions)
        labels = [item.canonical_name for item in entities]
        queries: List[Dict[str, Any]] = []
        search_labels = [self._search_label(entity) for entity in entities]
        for entity, search_label in zip(entities, search_labels):
            queries.extend([
                {"query": f"{search_label} official specifications", "entity": entity.canonical_name, "role": EvidenceType.OFFICIAL_PRODUCT.value},
                {"query": f"{search_label} independent benchmarks review", "entity": entity.canonical_name, "role": EvidenceType.BENCHMARK.value},
            ])
        queries.extend([
            {"query": f"{search_labels[0]} vs {search_labels[1]} benchmark comparison", "entity": "shared", "role": EvidenceType.TECHNICAL_COMPARISON.value},
            {"query": f"{search_labels[0]} vs {search_labels[1]} review value", "entity": "shared", "role": EvidenceType.REVIEW.value},
        ])
        roles = [EvidenceType.OFFICIAL_PRODUCT.value, EvidenceType.OFFICIAL_DOCUMENTATION.value, EvidenceType.BENCHMARK.value, EvidenceType.REVIEW.value, EvidenceType.TECHNICAL_COMPARISON.value]
        return ComparisonPlan(list(entities), category, dimensions, roles, queries, max_queries=min(10, len(queries)))

    @staticmethod
    def entity_matches_text(entity: ResolvedEntity, text: str) -> bool:
        haystack = " ".join(re.findall(r"[a-z0-9]+", str(text or "").lower()))
        model_tokens = [token for token in re.findall(r"[a-z0-9]+", entity.model.lower()) if len(token) >= 2]
        if entity.family and entity.family.lower() in haystack and model_tokens and any(token in haystack for token in model_tokens):
            return True
        return any(" ".join(re.findall(r"[a-z0-9]+", alias.lower())) in haystack for alias in entity.aliases if len(alias) >= 4)

    def extract_claims(self, facts: Sequence[Dict[str, Any]], entities: Sequence[ResolvedEntity], category: str) -> List[TypedClaim]:
        claims: List[TypedClaim] = []
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            claim_text = str(fact.get("claim") or fact.get("evidence") or "").strip()
            if not self._valid_source_text(claim_text):
                continue
            if re.search(r"(?:automated bot check|captcha|cookie policy|sign in|register|skip to main)", claim_text, re.I):
                continue
            role = str(fact.get("source_role") or fact.get("evidence_type") or EvidenceType.GENERAL_WEB.value)
            source_url = str(fact.get("source_url") or "")
            source_title = str(fact.get("source_title") or "")
            haystack = f"{claim_text} {source_title}".lower()
            matched = self._match_entities(haystack, entities)
            if not matched:
                continue
            property_name, unit = self._property(claim_text, category)
            if not property_name:
                continue
            if not self._role_allowed(property_name, role):
                continue
            value = self._value(claim_text, property_name)
            if not value:
                continue
            conditions = self._conditions(claim_text)
            confidence = float(fact.get("confidence") or 0.0)
            quality = float(fact.get("source_quality") or fact.get("quality", 0.0) or 0.0)
            for entity in matched:
                claims.append(TypedClaim(entity=entity.canonical_name if entity != "shared" else "shared", property=property_name, value=value, unit=unit, evidence_role=role, source_url=source_url, source_title=source_title, conditions=conditions, confidence=max(0.4, min(1.0, confidence or 0.55)), direct_quote=claim_text[:500], comparable=self._comparable(conditions), source_quality=quality))
        return self._dedupe_claims(claims)

    def build_matrix(self, entities: Sequence[ResolvedEntity], dimensions: Sequence[str], claims: Sequence[TypedClaim]) -> ComparisonEvidenceMatrix:
        labels = [item.canonical_name for item in entities]
        matrix = ComparisonEvidenceMatrix(labels, list(dimensions))
        matrix.cells = {entity: {dimension: EvidenceCell(entity, dimension) for dimension in dimensions} for entity in labels}
        for claim in claims:
            if claim.entity == "shared":
                matrix.shared_claims.append(claim)
                continue
            if claim.entity not in matrix.cells:
                continue
            dimension = self._dimension_alias(claim.property, dimensions)
            if dimension is None:
                continue
            cell = matrix.cells[claim.entity][dimension]
            cell.claims.append(claim)
            cell.support_count = len(cell.claims)
            cell.status = "supported"
            cell.comparable = claim.comparable
        important = dimensions[: min(4, len(dimensions))]
        for entity in labels:
            for dimension in important:
                cell = matrix.cells[entity][dimension]
                if not cell.claims:
                    cell.status = "missing"
                    matrix.missing_evidence.append(f"{entity}: {dimension}")
        has_both = all(any(matrix.cells[entity][dimension].claims for dimension in dimensions[: min(3, len(dimensions))]) for entity in labels)
        has_any = any(any(cell.claims for cell in matrix.cells[entity].values()) for entity in labels)
        if has_both and not matrix.missing_evidence:
            matrix.sufficiency = SufficiencyStatus.SUFFICIENT
        elif has_any:
            matrix.sufficiency = SufficiencyStatus.PARTIAL_BUT_USEFUL
        else:
            matrix.sufficiency = SufficiencyStatus.INSUFFICIENT
        matrix.gap_queries = self.gap_queries(matrix, entities)
        return matrix

    @staticmethod
    def _search_label(entity: ResolvedEntity) -> str:
        value = entity.canonical_name
        value = re.sub(r"\b(?:NVIDIA GeForce|AMD Radeon|Apple|Samsung|Sony)\b", "", value, flags=re.I)
        value = re.sub(r"\s+", " ", value).strip()
        return value or entity.canonical_name

    def gap_queries(self, matrix: ComparisonEvidenceMatrix, entities: Sequence[ResolvedEntity]) -> List[str]:
        gaps = []
        for missing in matrix.missing_evidence[:4]:
            entity, dimension = missing.split(": ", 1)
            gaps.append(f"{entity} {dimension} independent evidence")
        return gaps

    def detect_conflicts(self, claims: Sequence[TypedClaim]) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        groups: Dict[Tuple[str, str, Tuple[Tuple[str, str], ...]], List[TypedClaim]] = {}
        for claim in claims:
            if claim.entity == "shared" or claim.comparable is False:
                continue
            key = (claim.entity, claim.property, tuple(sorted(claim.conditions.items())))
            groups.setdefault(key, []).append(claim)
        for (entity, prop, conditions), group in groups.items():
            values = {claim.value.lower() for claim in group}
            sources = {claim.source_url for claim in group if claim.source_url}
            if len(values) > 1 and len(sources) >= 2 and all(claim.confidence >= 0.5 for claim in group):
                result.append({"entity": entity, "property": prop, "conditions": dict(conditions), "claims": [claim.to_dict() for claim in group], "source_count": len(sources), "material": True, "description": f"Comparable sources report different values for {prop} on {entity}."})
        return result

    def validate(self, state: ComparisonState) -> List[str]:
        errors: List[str] = []
        if len(state.resolved_entities) < 2:
            errors.append("comparison requires at least two resolved entities")
        if any(self._placeholder(item.canonical_name) for item in state.resolved_entities):
            errors.append("placeholder entity leaked into resolved entities")
        if state.matrix is None:
            errors.append("comparison evidence matrix is missing")
        elif state.matrix.sufficiency == SufficiencyStatus.INSUFFICIENT:
            errors.append("evidence is insufficient for a complete comparison")
        for item in state.resolved_entities:
            raw = item.raw_text.lower()
            if state.category == "cpu" and re.search(r"\b(?:intel\s+)?(?:core\s+)?i[3579]\s*[- ]?\s*\d{3,5}\b", raw, re.I) and item.manufacturer != "Intel":
                errors.append(f"Intel CPU was normalized with the wrong manufacturer: {item.canonical_name}")
            if state.category == "cpu" and re.search(r"\bryzen\b", raw, re.I) and item.manufacturer != "AMD":
                errors.append(f"AMD Ryzen CPU was normalized with the wrong manufacturer: {item.canonical_name}")
        for claim in state.claims:
            if self._placeholder(claim.entity) or not claim.property or not claim.value or not claim.source_url:
                errors.append("untyped or unsupported claim entered comparison state")
        return list(dict.fromkeys(errors))

    @staticmethod
    def _raw_sides(query: str) -> List[str]:
        return [part.strip(" .?!,:;()[]{}") for part in re.split(r"\b(?:vs\.?|versus|against)\b", str(query or ""), flags=re.I) if part.strip()][:2]

    def _normalize(self, raw: str, category: str, context: Optional[Dict[str, Any]] = None, inherited: Optional[ResolvedEntity] = None) -> ResolvedEntity:
        value = re.sub(r"\s+", " ", str(raw or "").strip())
        lowered = value.lower()
        manufacturer, family, canonical = "", "", value
        if category == "gpu":
            if re.search(r"\b(?:rtx|geforce)\b", lowered) or (inherited and inherited.family.lower() in {"rtx", "geforce"} and re.search(r"\b\d{3,4}\b", lowered)):
                manufacturer, family = "NVIDIA", "RTX"
                model = re.search(r"\b\d{3,4}(?:\s*(?:ti|super|xt))?\b", lowered, re.I)
                canonical = f"NVIDIA GeForce RTX {model.group(0).upper() if model else value.upper().replace('RTX ', '')}" if model else "NVIDIA GeForce " + value
            elif re.search(r"\b(?:rx|radeon)\b", lowered) or (inherited and inherited.family.lower() in {"rx", "radeon"}):
                manufacturer, family = "AMD", "RX"
                model = re.search(r"\b\d{3,4}(?:\s*xt)?\b", lowered, re.I)
                canonical = f"AMD Radeon RX {model.group(0).upper() if model else value.upper().replace('RX ', '')}" if model else "AMD Radeon " + value
            else:
                manufacturer, family = (inherited.manufacturer, inherited.family) if inherited else ("", "")
        elif category == "smartphone":
            if "iphone" in lowered or (inherited and inherited.family == "iPhone"):
                manufacturer, family = "Apple", "iPhone"
                model = re.search(r"\b\d{1,2}(?:\s*(?:pro|max|plus|mini|promax))?\b", lowered, re.I)
                canonical = f"Apple iPhone {model.group(0) if model else value.replace('iPhone', '').strip()}".strip()
            elif "galaxy" in lowered or (inherited and inherited.family == "Galaxy S"):
                manufacturer, family = "Samsung", "Galaxy S"
                model = re.search(r"\bS?\d{1,2}(?:\s*(?:ultra|plus|fe))?\b", value, re.I)
                canonical = f"Samsung Galaxy S{model.group(0).lstrip('Ss') if model else value}".strip()
        elif category == "cpu":
            intel_match = re.search(r"\b(?:intel\s+)?(?:core\s+)?(i[3579])\s*[- ]?\s*(\d{3,5})([a-z]{0,3})?\b", lowered, re.I)
            ryzen_match = re.search(r"\bryzen\s+(?:(\d)\s+)?(\d{3,5})([a-z]{0,3})\b", lowered, re.I)
            if intel_match:
                manufacturer, family = "Intel", "Core"
                model = f"{intel_match.group(1).lower()}-{intel_match.group(2)}{(intel_match.group(3) or '').upper()}"
                canonical = f"Intel Core {model}"
            elif ryzen_match:
                manufacturer, family = "AMD", "Ryzen"
                series = f"{ryzen_match.group(1)} " if ryzen_match.group(1) else ""
                canonical = f"AMD Ryzen {series}{ryzen_match.group(2)}{(ryzen_match.group(3) or '').upper()}"
            elif inherited and inherited.family in {"Ryzen", "Core"} and re.fullmatch(r"\d{3,5}[a-z]{0,3}", lowered):
                manufacturer, family = inherited.manufacturer, inherited.family
                prefix = "AMD Ryzen" if family == "Ryzen" else "Intel Core"
                canonical = f"{prefix} {value.upper()}"
        elif category == "console" and ("playstation" in lowered or lowered.startswith("ps") or (inherited and inherited.family == "PlayStation")):
            manufacturer, family = "Sony", "PlayStation"
            suffix = value.lower().replace("playstation", "").replace("ps", "").strip()
            canonical = f"Sony PlayStation {suffix.title()}".strip()
        elif category == "laptop" and "macbook" in lowered:
            manufacturer, family = "Apple", "MacBook"
            canonical = "Apple " + value
        elif category == "database":
            canonical = value
        elif category == "browser automation framework":
            canonical = value.title()
        elif category == "frontend framework":
            canonical = value.title()
        model = canonical
        if family and family.lower() in model.lower():
            model = model.split(family, 1)[-1].strip()
        return ResolvedEntity(raw_text=value, canonical_name=canonical, manufacturer=manufacturer, family=family, model=model, category=category, aliases=list(dict.fromkeys([value, canonical])), confidence=0.96 if inherited and re.search(r"\d", value) else 0.91, resolution_source="contextual_inheritance" if inherited else "deterministic_entity_pattern")

    @staticmethod
    def _valid_source_text(text: str) -> bool:
        return 20 <= len(text) <= 1800 and not re.search(r"(?:skip to main|select address|sign in|register|cookie policy|compare .* with other)", text, re.I)

    @staticmethod
    def _match_entities(text: str, entities: Sequence[ResolvedEntity]) -> List[Any]:
        raw_text = str(text or "").lower()
        normalized_text = " ".join(re.findall(r"[a-z0-9]+", raw_text))
        matched = []
        for entity in entities:
            aliases = [" ".join(re.findall(r"[a-z0-9]+", alias.lower())) for alias in entity.aliases if len(alias) >= 3]
            model_tokens = [token for token in re.findall(r"[a-z0-9]+", entity.model.lower()) if len(token) >= 2]
            family = str(entity.family or "").lower()
            alias_hit = any(alias and alias in normalized_text for alias in aliases)
            token_hit = bool(family and family in normalized_text and model_tokens and any(token in normalized_text for token in model_tokens))
            if alias_hit or token_hit:
                matched.append(entity)
        if len(matched) >= 2:
            return ["shared"]
        return matched

    @staticmethod
    def _property(text: str, category: str) -> Tuple[str, str]:
        lower = text.lower()
        patterns = [("vram", r"\bvram\b|video memory", "GB"), ("memory", r"memory interface|memory bandwidth|\bmemory\b", ""), ("architecture", r"architecture|generation|process node", ""), ("performance", r"benchmark|performance|\bfps\b|faster|slower", ""), ("ray tracing", r"ray tracing|ray-tracing", ""), ("power", r"\b(?:tdp|power draw|watt|watts)\b", "W"), ("cores/threads", r"cores?|threads?", ""), ("clock", r"clock|ghz|mhz", ""), ("cache", r"cache", ""), ("display", r"display|screen|oled|lcd", ""), ("camera", r"camera|megapixel|mp", ""), ("battery", r"battery|mah", ""), ("storage", r"storage|ssd|gb", ""), ("price/value", r"msrp|price|cost|value", ""), ("capabilities", r"capabilit|features?|supports?", ""), ("compatibility", r"compatib|works with|support", "")]
        for prop, pattern, unit in patterns:
            if re.search(pattern, lower):
                return prop, unit
        return "", ""

    @staticmethod
    def _value(text: str, prop: str) -> str:
        patterns = {
            "vram": r"\b\d+(?:\.\d+)?\s*(?:gb|tb|mb)\b",
            "memory": r"\b\d+(?:\.\d+)?\s*(?:gb|tb|mb|bit|bits|gb/s)\b",
            "power": r"\b\d+(?:\.\d+)?\s*(?:w|watts?)\b",
            "performance": r"\b\d+(?:\.\d+)?\s*(?:fps|%)\b|\b(?:factor|by)\s+\d+(?:\.\d+)?\s*x\b|\b\d+\.\d+\s*x\b|\b(?:faster|slower|倍)\b",
            "clock": r"\b\d+(?:\.\d+)?\s*(?:ghz|mhz)\b",
            "cores/threads": r"\b\d+\s*(?:cores?|threads?)\b",
            "price/value": r"(?:[$€£₱]\s*\d[\d,]*(?:\.\d+)?|\b\d[\d,]*(?:\.\d+)?\s*(?:usd|eur|gbp|php)\b)",
            "display": r"\b\d+(?:\.\d+)?\s*(?:inch|in|hz|nit|nits)\b",
            "camera": r"\b\d+(?:\.\d+)?\s*(?:mp|megapixels?)\b",
            "battery": r"\b\d+(?:\.\d+)?\s*(?:mah|hours?|hrs?)\b",
            "storage": r"\b\d+(?:\.\d+)?\s*(?:gb|tb|mb)\b",
        }
        pattern = patterns.get(prop)
        if pattern:
            matches = re.findall(pattern, text, re.I)
            if matches:
                return ", ".join(dict.fromkeys(match if isinstance(match, str) else match[0] for match in matches))[:120]
        cleaned = re.sub(r"\s+", " ", text).strip()
        if prop in {"architecture", "ray tracing", "capabilities", "compatibility"}:
            return cleaned[:240]
        if prop == "performance" and re.search(r"\b(?:faster|slower)\b", cleaned, re.I):
            return re.search(r"\b(?:faster|slower)\b", cleaned, re.I).group(0)
        return ""

    @staticmethod
    def _conditions(text: str) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for key, pattern in (("resolution", r"\b(\d{3,4}p)\b"), ("preset", r"\b(low|medium|high|ultra)\b"), ("application", r"\b(?:in|on)\s+([A-Z][A-Za-z0-9 ._-]{2,30})")):
            match = re.search(pattern, text, re.I)
            if match:
                result[key] = match.group(1)
        return result

    @staticmethod
    def _comparable(conditions: Dict[str, str]) -> bool:
        return True

    @staticmethod
    def _role_allowed(prop: str, role: str) -> bool:
        if prop in {"performance", "ray tracing"}:
            return role in {EvidenceType.BENCHMARK.value, EvidenceType.REVIEW.value, EvidenceType.TECHNICAL_COMPARISON.value, EvidenceType.OFFICIAL_PRODUCT.value, EvidenceType.OFFICIAL_ANNOUNCEMENT.value}
        if prop in {"price/value"}:
            return role in {EvidenceType.RETAIL_LISTING.value, EvidenceType.MARKETPLACE_LISTING.value, EvidenceType.OFFICIAL_PRODUCT.value, EvidenceType.OFFICIAL_ANNOUNCEMENT.value, EvidenceType.REVIEW.value}
        return role not in {EvidenceType.GENERAL_WEB.value, EvidenceType.FORUM_DISCUSSION.value, EvidenceType.SOCIAL_POST.value} or prop in {"capabilities", "compatibility"}

    @staticmethod
    def _dimension_alias(prop: str, dimensions: Sequence[str]) -> Optional[str]:
        normalized = prop.lower()
        for dimension in dimensions:
            if normalized == dimension.lower() or normalized in dimension.lower() or dimension.lower() in normalized:
                return dimension
        return None

    @staticmethod
    def _dedupe_claims(claims: Sequence[TypedClaim]) -> List[TypedClaim]:
        seen = set()
        result = []
        for claim in claims:
            key = (claim.entity.lower(), claim.property.lower(), claim.value.lower(), claim.source_url)
            if key in seen:
                continue
            seen.add(key)
            result.append(claim)
        return result

    @staticmethod
    def _placeholder(value: str) -> bool:
        return bool(re.search(r"\b(?:item\s*[ab]|entity\s*\d+|unknown_product)\b", str(value or ""), re.I))
