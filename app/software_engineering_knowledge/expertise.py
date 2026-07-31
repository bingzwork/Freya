"""Engineering Expertise - Higher-level expertise built from accumulated knowledge.

EngineeringExpertise represents synthesized, high-level knowledge that combines
multiple knowledge items into actionable expertise areas.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.software_engineering_knowledge.models import (
    EngineeringDomain,
    EngineeringExpertise,
    EngineeringKnowledgeItem,
    EngineeringKnowledgeType,
    ValidationStatus,
)
from app.software_engineering_knowledge.storage import get_knowledge_storage
from app.software_engineering_knowledge.ranking import EngineeringRankingEngine
from app.software_engineering_knowledge.validation import KnowledgeValidator


class ExpertiseBuilder:
    """Build EngineeringExpertise from accumulated knowledge items."""

    def __init__(self, storage_path: Optional[str] = None):
        self.storage = get_knowledge_storage(storage_path) if storage_path else get_knowledge_storage()
        self.ranker = EngineeringRankingEngine(storage_path)
        self.validator = KnowledgeValidator(storage_path=storage_path)

    def build_expertise(
        self,
        domain: EngineeringDomain,
        title: str,
        description: str,
        min_confidence: float = 0.7,
        min_items: int = 3,
    ) -> Optional[EngineeringExpertise]:
        """Build an expertise area from knowledge items in a domain.

        Args:
            domain: Engineering domain to build expertise for
            title: Title of the expertise
            description: Description of what this expertise covers
            min_confidence: Minimum confidence for items to include
            min_items: Minimum items required to build expertise

        Returns:
            EngineeringExpertise if enough items found, None otherwise
        """
        # Get high-confidence items in domain
        items = self.storage.get_by_domain(domain, limit=100)
        items = [i for i in items if i.confidence >= min_confidence]

        if len(items) < min_items:
            return None

        # Rank items by relevance to expertise
        ranked_items = self._rank_items_for_expertise(items, title, description)

        # Select top items
        selected_items = ranked_items[:20]  # Max 20 items per expertise

        # Calculate expertise confidence
        expertise_confidence = self._calculate_expertise_confidence(selected_items)

        # Create expertise
        expertise = EngineeringExpertise(
            domain=domain,
            title=title,
            description=description,
            knowledge_item_ids=[item.id for item in selected_items],
            confidence=expertise_confidence,
            metadata={
                "built_from_items": len(selected_items),
                "min_item_confidence": min_confidence,
                "domains_covered": list(set(i.domain.value for i in selected_items)),
                "types_covered": list(set(i.knowledge_type.value for i in selected_items)),
            },
        )

        return expertise

    def _rank_items_for_expertise(
        self,
        items: List[EngineeringKnowledgeItem],
        expertise_title: str,
        expertise_description: str,
    ) -> List[EngineeringKnowledgeItem]:
        """Rank items by relevance to the expertise area."""
        # Simple relevance scoring
        scored = []
        title_terms = set(expertise_title.lower().split())
        desc_terms = set(expertise_description.lower().split())
        all_terms = title_terms | desc_terms

        for item in items:
            score = 0.0

            # Title relevance
            item_title_terms = set(item.title.lower().split())
            score += len(title_terms & item_title_terms) / max(len(title_terms), 1) * 0.4

            # Tag relevance
            item_tag_terms = set(t.lower() for t in item.tags)
            score += len(desc_terms & item_tag_terms) / max(len(desc_terms), 1) * 0.3

            # Content relevance (sample)
            content_sample = item.content[:500].lower()
            content_terms = set(content_sample.split())
            score += len(all_terms & content_terms) / max(len(all_terms), 1) * 0.2

            # Confidence bonus
            score += item.confidence * 0.1

            scored.append((score, item))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored]

    def _calculate_expertise_confidence(self, items: List[EngineeringKnowledgeItem]) -> float:
        """Calculate confidence for an expertise built from items."""
        if not items:
            return 0.0

        # Weighted average of item confidences
        total_weight = 0.0
        weighted_sum = 0.0

        for item in items:
            # Weight by validation status
            status_weights = {
                ValidationStatus.VALIDATED: 1.0,
                ValidationStatus.PENDING: 0.7,
                ValidationStatus.LOW_CONFIDENCE: 0.4,
                ValidationStatus.DUPLICATE: 0.3,
                ValidationStatus.CONFLICT: 0.2,
                ValidationStatus.REJECTED: 0.0,
            }
            weight = status_weights.get(item.validation_status, 0.5)
            weighted_sum += item.confidence * weight
            total_weight += weight

        if total_weight == 0:
            return 0.0

        base_confidence = weighted_sum / total_weight

        # Bonus for diversity of knowledge types
        types = set(i.knowledge_type for i in items)
        type_bonus = min(len(types) * 0.02, 0.1)

        # Bonus for number of items (up to a point)
        count_bonus = min(len(items) * 0.01, 0.1)

        return min(base_confidence + type_bonus + count_bonus, 1.0)

    def build_expertise_for_all_domains(
        self,
        min_confidence: float = 0.7,
        min_items: int = 3,
    ) -> Dict[EngineeringDomain, List[EngineeringExpertise]]:
        """Build expertise areas for all domains."""
        results = {}

        for domain in EngineeringDomain:
            if domain == EngineeringDomain.UNKNOWN:
                continue

            items = self.storage.get_by_domain(domain, limit=100)
            items = [i for i in items if i.confidence >= min_confidence]

            if len(items) < min_items:
                continue

            # Build multiple expertise areas per domain based on sub-categories
            sub_cats = set(i.sub_category for i in items if i.sub_category)

            domain_expertise = []
            for sub_cat in sub_cats:
                sub_items = [i for i in items if i.sub_category == sub_cat]
                if len(sub_items) >= min_items:
                    expertise = self.build_expertise(
                        domain=domain,
                        title=f"{domain.value.replace('_', ' ').title()}: {sub_cat.replace('_', ' ').title()}",
                        description=f"Expertise in {sub_cat} within {domain.value}",
                        min_confidence=min_confidence,
                        min_items=min_items,
                    )
                    if expertise:
                        domain_expertise.append(expertise)

            # Also build general domain expertise
            general = self.build_expertise(
                domain=domain,
                title=f"{domain.value.replace('_', ' ').title()} Expertise",
                description=f"General expertise in {domain.value}",
                min_confidence=min_confidence,
                min_items=min_items,
            )
            if general:
                domain_expertise.insert(0, general)

            if domain_expertise:
                results[domain] = domain_expertise

        return results

    def save_all_expertise(self, expertise_dict: Dict[EngineeringDomain, List[EngineeringExpertise]]) -> int:
        """Save all built expertise to storage."""
        saved = 0
        for domain, exp_list in expertise_dict.items():
            for exp in exp_list:
                self.storage.save_expertise(exp)
                saved += 1
        return saved


class ExpertiseQueryEngine:
    """Query and apply engineering expertise."""

    def __init__(self, storage_path: Optional[str] = None):
        self.storage = get_knowledge_storage(storage_path) if storage_path else get_knowledge_storage()
        self.ranker = EngineeringRankingEngine(storage_path)

    def get_expertise_for_domain(self, domain: EngineeringDomain) -> List[EngineeringExpertise]:
        """Get all expertise for a domain."""
        return self.storage.list_expertise(domain)

    def get_all_expertise(self) -> List[EngineeringExpertise]:
        """Get all expertise across domains."""
        return self.storage.list_expertise()

    def find_relevant_expertise(
        self,
        query: str,
        domain: Optional[EngineeringDomain] = None,
        min_confidence: float = 0.6,
    ) -> List[EngineeringExpertise]:
        """Find expertise relevant to a query."""
        all_exp = self.get_all_expertise() if domain is None else self.get_expertise_for_domain(domain)

        # Filter by confidence
        all_exp = [e for e in all_exp if e.confidence >= min_confidence]

        # Simple relevance scoring
        query_terms = set(query.lower().split())
        scored = []

        for exp in all_exp:
            score = 0.0
            exp_terms = set((exp.title + " " + exp.description).lower().split())
            overlap = query_terms & exp_terms
            score = len(overlap) / max(len(query_terms), 1)
            score *= exp.confidence
            scored.append((score, exp))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [exp for score, exp in scored if score > 0]

    def get_knowledge_for_expertise(self, expertise: EngineeringExpertise) -> List[EngineeringKnowledgeItem]:
        """Get all knowledge items that form an expertise."""
        items = []
        for item_id in expertise.knowledge_item_ids:
            item = self.storage.get(item_id)
            if item:
                items.append(item)
        return items

    def apply_expertise_to_query(
        self,
        query: str,
        expertise: EngineeringExpertise,
    ) -> List[EngineeringKnowledgeItem]:
        """Apply expertise to enhance query results."""
        # Get the knowledge items that form this expertise
        items = self.get_knowledge_for_expertise(expertise)

        # Convert to retrieval results and rank
        from app.software_engineering_knowledge.sources import EngineeringKnowledgeAdapter
        from app.knowledge_retrieval.models import RetrievalQuery

        adapter = EngineeringKnowledgeAdapter()
        retrieval_query = RetrievalQuery(query=query)

        results = []
        for item in items:
            result = adapter._item_to_result(item, retrieval_query)
            results.append(result)

        # Rank with expertise boost
        ranked = self.ranker.rank_results(results, retrieval_query)

        # Convert back to knowledge items (top N)
        top_items = []
        for result in ranked[:10]:
            item = self.storage.get(result.source_id)
            if item:
                top_items.append(item)

        return top_items


class ExpertiseBasedRecommendation:
    """Generate recommendations based on engineering expertise."""

    def __init__(self, storage_path: Optional[str] = None):
        self.query_engine = ExpertiseQueryEngine(storage_path)

    def recommend_for_task(
        self,
        task_description: str,
        domain: Optional[EngineeringDomain] = None,
    ) -> Dict[str, Any]:
        """Generate recommendations for a task based on expertise."""
        # Find relevant expertise
        expertise_list = self.query_engine.find_relevant_expertise(task_description, domain)

        if not expertise_list:
            return {
                "recommendations": [],
                "expertise_used": [],
                "message": "No relevant expertise found",
            }

        recommendations = []
        for exp in expertise_list[:3]:  # Top 3 expertise areas
            items = self.query_engine.apply_expertise_to_query(task_description, exp)

            for item in items[:3]:  # Top 3 items per expertise
                recommendations.append({
                    "expertise": exp.title,
                    "expertise_confidence": exp.confidence,
                    "knowledge_title": item.title,
                    "knowledge_summary": item.summary,
                    "knowledge_type": item.knowledge_type.value,
                    "confidence": item.confidence,
                    "domain": item.domain.value,
                })

        return {
            "recommendations": recommendations,
            "expertise_used": [e.title for e in expertise_list[:3]],
            "message": f"Found {len(expertise_list)} relevant expertise areas",
        }

    def recommend_best_practices(
        self,
        context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Recommend best practices for a context."""
        language = context.get("language")
        framework = context.get("framework")
        task_type = context.get("task_type", "implementation")

        # Build query from context
        query_parts = [task_type]
        if language:
            query_parts.append(language)
        if framework:
            query_parts.append(framework)
        query_parts.append("best practice")

        query = " ".join(query_parts)

        # Find expertise
        expertise_list = self.query_engine.find_relevant_expertise(query)

        recommendations = []
        for exp in expertise_list:
            items = self.query_engine.get_knowledge_for_expertise(exp)
            best_practices = [i for i in items if i.knowledge_type == "best_practice"]

            for bp in best_practices[:2]:
                recommendations.append({
                    "practice": bp.title,
                    "summary": bp.summary,
                    "context": bp.content[:300],
                    "confidence": bp.confidence,
                    "expertise": exp.title,
                })

        return recommendations

    def recommend_patterns(
        self,
        problem_description: str,
        domain: Optional[EngineeringDomain] = None,
    ) -> List[Dict[str, Any]]:
        """Recommend design/code patterns for a problem."""
        query = f"pattern {problem_description}"
        expertise_list = self.query_engine.find_relevant_expertise(query, domain)

        recommendations = []
        for exp in expertise_list:
            items = self.query_engine.get_knowledge_for_expertise(exp)
            patterns = [i for i in items if i.knowledge_type in ("code_pattern", "design_pattern", "architecture")]

            for p in patterns[:2]:
                recommendations.append({
                    "pattern": p.title,
                    "description": p.summary,
                    "details": p.content[:300],
                    "confidence": p.confidence,
                    "expertise": exp.title,
                    "domain": p.domain.value,
                })

        return recommendations

    def recommend_troubleshooting(
        self,
        error_description: str,
    ) -> List[Dict[str, Any]]:
        """Recommend troubleshooting approaches for an error."""
        query = f"troubleshoot {error_description}"
        expertise_list = self.query_engine.find_relevant_expertise(query, EngineeringDomain.DEBUGGING)

        recommendations = []
        for exp in expertise_list:
            items = self.query_engine.get_knowledge_for_expertise(exp)
            troubleshoot = [i for i in items if i.knowledge_type in ("troubleshooting", "debugging_strategy", "lesson_learned")]

            for t in troubleshoot[:2]:
                recommendations.append({
                    "approach": t.title,
                    "summary": t.summary,
                    "details": t.content[:300],
                    "confidence": t.confidence,
                    "expertise": exp.title,
                })

        return recommendations


# === Integration with Knowledge Retrieval ===

class ExpertiseEnhancedRetrieval:
    """Enhance knowledge retrieval with expertise awareness."""

    def __init__(self, storage_path: Optional[str] = None):
        self.storage = get_knowledge_storage(storage_path) if storage_path else get_knowledge_storage()
        self.expertise_engine = ExpertiseQueryEngine(storage_path)
        self.ranker = EngineeringRankingEngine(storage_path)

    def retrieve_with_expertise(
        self,
        query: str,
        max_results: int = 10,
        domain: Optional[EngineeringDomain] = None,
    ) -> Dict[str, Any]:
        """Retrieve knowledge enhanced by relevant expertise."""
        from app.knowledge_retrieval.models import RetrievalQuery
        from app.software_engineering_knowledge.sources import EngineeringKnowledgeAdapter

        # Find relevant expertise
        expertise_list = self.expertise_engine.find_relevant_expertise(query, domain)

        # Get base knowledge results
        adapter = EngineeringKnowledgeAdapter()
        retrieval_query = RetrievalQuery(query=query, max_results=max_results * 2)

        candidates = adapter.retrieve_candidates(retrieval_query, max_results * 2)

        # Rank candidates
        ranked = self.ranker.rank_results(candidates, retrieval_query)

        # Boost results that match expertise
        if expertise_list:
            expertise_items = set()
            for exp in expertise_list:
                for item_id in exp.knowledge_item_ids:
                    expertise_items.add(item_id)

            for result in ranked:
                if result.source_id in expertise_items:
                    # Boost rank score
                    result.rank_score = min(result.rank_score * 1.2, 1.0)
                    result.metadata = result.metadata or {}
                    result.metadata["expertise_boosted"] = True

            # Re-sort
            ranked.sort(key=lambda r: r.rank_score, reverse=True)

        # Combine results
        return {
            "results": ranked[:max_results],
            "expertise_used": [e.title for e in expertise_list[:3]],
            "total_candidates": len(candidates),
        }


# === Convenience functions ===

def build_domain_expertise(domain: EngineeringDomain, storage_path: Optional[str] = None) -> List[EngineeringExpertise]:
    """Quick function to build expertise for a domain."""
    builder = ExpertiseBuilder(storage_path)
    return list(builder.build_expertise_for_all_domains().get(domain, []))


def get_task_recommendations(task: str, context: Dict[str, Any], storage_path: Optional[str] = None) -> Dict[str, Any]:
    """Quick function to get recommendations for a task."""
    recommender = ExpertiseBasedRecommendation(storage_path)
    return recommender.recommend_for_task(task, context.get("domain"))


def create_expertise_from_items(
    title: str,
    description: str,
    item_ids: List[str],
    domain: EngineeringDomain,
    storage_path: Optional[str] = None,
) -> EngineeringExpertise:
    """Create expertise manually from a list of item IDs."""
    storage = get_knowledge_storage(storage_path)

    items = []
    for item_id in item_ids:
        item = storage.get(item_id)
        if item:
            items.append(item)

    if not items:
        raise ValueError("No valid items found")

    builder = ExpertiseBuilder(storage_path)
    expertise = builder.build_expertise(domain, title, description)
    if expertise:
        expertise.knowledge_item_ids = item_ids
        expertise.confidence = builder._calculate_expertise_confidence(items)
        storage.save_expertise(expertise)

    return expertise