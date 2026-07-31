"""Knowledge Ranking for Software Engineering Knowledge.

Integrates with the unified Knowledge Retrieval ranking engine to provide
domain-specific ranking for engineering knowledge items.
"""

from typing import Any, Dict, List, Optional, Tuple

from app.knowledge_retrieval.models import (
    KnowledgeRetrievalResult,
    RankingConfig,
    RankingSignal,
    RetrievalQuery,
)
from app.knowledge_retrieval.ranking import RankingEngine, AdaptiveRankingEngine
from app.software_engineering_knowledge.models import (
    EngineeringDomain,
    EngineeringKnowledgeItem,
    EngineeringKnowledgeType,
    KnowledgeSource,
    ValidationStatus,
)
from app.software_engineering_knowledge.storage import get_knowledge_storage


class EngineeringRankingEngine:
    """Ranking engine specialized for software engineering knowledge.

    Extends the unified ranking engine with engineering-specific signals.
    """

    def __init__(self, storage_path: Optional[str] = None, adaptive: bool = True):
        self.storage = get_knowledge_storage(storage_path) if storage_path else get_knowledge_storage()
        self.adaptive = adaptive

        # Create ranking config with engineering-specific weights
        config = RankingConfig(
            weights={
                RankingSignal.RELEVANCE: 0.28,
                RankingSignal.CONFIDENCE: 0.22,
                RankingSignal.SOURCE_QUALITY: 0.12,
                RankingSignal.USAGE_FREQUENCY: 0.10,
                RankingSignal.RECENCY: 0.08,
                RankingSignal.COMPLETENESS: 0.08,
                RankingSignal.RELIABILITY: 0.06,
                RankingSignal.FRESHNESS: 0.04,
                RankingSignal.HISTORICAL_USEFULNESS: 0.02,
            },
            source_quality_scores={
                # Engineering-specific source quality
                "project_code": 0.85,
                "documentation": 0.90,
                "experience_memory": 0.75,
                "engineering_lessons": 0.85,
                "reflection": 0.70,
                "external_docs": 0.80,
                "internet_research": 0.60,
                "user_input": 0.95,
                "llm_training": 0.65,
                "synthesized": 0.75,
                "unknown": 0.50,
            },
            calibration_enabled=True,
            calibration_method="isotonic",
            adaptation_enabled=adaptive,
            adaptation_rate=0.01,
        )

        if adaptive:
            self.engine = AdaptiveRankingEngine(config=config)
        else:
            self.engine = RankingEngine(config=config)

        # Register engineering-specific calculators
        self._register_engineering_calculators()

    def _register_engineering_calculators(self) -> None:
        """Register engineering-specific signal calculators."""
        # Domain relevance - boost items matching query domain
        self.engine.register_calculator(
            RankingSignal.RELEVANCE,
            self._calculate_domain_relevance
        )

        # Knowledge type appropriateness - certain types better for certain queries
        self.engine.register_calculator(
            RankingSignal.COMPLETENESS,
            self._calculate_eng_completeness
        )

    def _calculate_domain_relevance(self, result: KnowledgeRetrievalResult, query: RetrievalQuery,
                                     analytics) -> Tuple[float, Dict[str, Any]]:
        """Calculate relevance with domain/type awareness."""
        from app.knowledge_retrieval.ranking import RankingEngine

        # Get base relevance
        base_engine = RankingEngine()
        base_value, base_meta = base_engine._calculate_relevance(result, query)

        # Boost if domain matches query context
        boost = 0.0
        metadata = result.metadata or {}

        eng_domain = metadata.get("engineering_domain")
        if eng_domain and hasattr(query, "context") and query.context:
            task_type = query.context.get("task_type", "")
            if task_type:
                # Simple heuristic: match task type to domain
                domain_task_map = {
                    "implementation": [EngineeringDomain.PROGRAMMING_LANGUAGES, EngineeringDomain.FRAMEWORKS,
                                       EngineeringDomain.LIBRARIES, EngineeringDomain.APIS],
                    "debugging": [EngineeringDomain.DEBUGGING, EngineeringDomain.TESTING,
                                  EngineeringDomain.BUG_PATTERNS, EngineeringDomain.ROOT_CAUSES],
                    "architecture": [EngineeringDomain.SOFTWARE_ARCHITECTURE, EngineeringDomain.DESIGN_PATTERNS,
                                     EngineeringDomain.SYSTEM_DESIGN],
                    "performance": [EngineeringDomain.PERFORMANCE_OPTIMIZATION],
                    "security": [EngineeringDomain.SECURITY, EngineeringDomain.AUTHENTICATION],
                    "deployment": [EngineeringDomain.CI_CD, EngineeringDomain.DEVOPS, EngineeringDomain.CLOUD],
                    "refactoring": [EngineeringDomain.REFACTORING, EngineeringDomain.CODE_QUALITY],
                    "testing": [EngineeringDomain.TESTING],
                }

                for task, domains in domain_task_map.items():
                    if task in task_type.lower():
                        try:
                            if EngineeringDomain(eng_domain) in domains:
                                boost = 0.15
                                break
                        except ValueError:
                            pass

        # Boost for knowledge type matching query intent
        eng_type = metadata.get("knowledge_type")
        if eng_type and hasattr(query, "context") and query.context:
            intent = query.context.get("intent", "")
            if intent:
                type_intent_map = {
                    "how_to": [EngineeringKnowledgeType.PROCEDURE, EngineeringKnowledgeType.EXAMPLE],
                    "what_is": [EngineeringKnowledgeType.CONCEPT, EngineeringKnowledgeType.DEFINITION],
                    "best_practice": [EngineeringKnowledgeType.BEST_PRACTICE, EngineeringKnowledgeType.RECOMMENDATION],
                    "troubleshoot": [EngineeringKnowledgeType.TROUBLESHOOTING, EngineeringKnowledgeType.DEBUGGING_STRATEGY],
                    "decision": [EngineeringKnowledgeType.DECISION_RATIONALE, EngineeringKnowledgeType.ARCHITECTURE],
                    "pattern": [EngineeringKnowledgeType.CODE_PATTERN, EngineeringKnowledgeType.ANTI_PATTERN],
                }
                for intent_key, types in type_intent_map.items():
                    if intent_key in intent.lower():
                        if eng_type in [t.value for t in types]:
                            boost = max(boost, 0.1)
                            break

        final_value = min(base_value + boost, 1.0)
        metadata["domain_boost"] = boost
        return final_value, metadata

    def _calculate_eng_completeness(self, result: KnowledgeRetrievalResult, query: RetrievalQuery,
                                     analytics) -> Tuple[float, Dict[str, Any]]:
        """Calculate completeness with engineering-specific factors."""
        metadata = result.metadata or {}

        score = 0.0
        factors = {}

        # Base completeness from content
        if result.content:
            content_len = len(result.content)
            score += min(content_len / 2000.0, 0.3)
            factors["content_length"] = min(content_len / 2000.0, 0.3)

        if result.summary:
            score += 0.15
            factors["has_summary"] = 0.15

        if result.tags:
            score += min(len(result.tags) * 0.03, 0.15)
            factors["tag_count"] = min(len(result.tags) * 0.03, 0.15)

        # Engineering-specific
        if metadata.get("engineering_domain"):
            score += 0.1
            factors["has_domain"] = 0.1

        if metadata.get("knowledge_type"):
            score += 0.1
            factors["has_type"] = 0.1

        if metadata.get("language"):
            score += 0.05
            factors["has_language"] = 0.05

        if metadata.get("frameworks"):
            score += min(len(metadata.get("frameworks", [])) * 0.02, 0.05)
            factors["framework_count"] = min(len(metadata.get("frameworks", [])) * 0.02, 0.05)

        if result.code_snippet:
            score += 0.1
            factors["has_code"] = 0.1

        if metadata.get("related_items"):
            score += min(len(metadata.get("related_items", [])) * 0.02, 0.05)
            factors["related_items"] = min(len(metadata.get("related_items", [])) * 0.02, 0.05)

        return min(score, 1.0), factors

    def rank_results(self, results: List[KnowledgeRetrievalResult], query: RetrievalQuery) -> List[KnowledgeRetrievalResult]:
        """Rank a list of results for a query."""
        return self.engine.rank(results, query)

    def record_feedback(self, result_id: str, positive: bool) -> None:
        """Record user feedback for adaptive ranking."""
        if self.adaptive:
            self.engine.record_feedback(result_id, positive)


class EngineeringQueryBuilder:
    """Build engineering-specific retrieval queries."""

    def __init__(self):
        self.query = RetrievalQuery(query="")
        self._domain_filter: Optional[EngineeringDomain] = None
        self._type_filter: Optional[EngineeringKnowledgeType] = None
        self._validation_filter: Optional[ValidationStatus] = None
        self._required_tags: List[str] = []
        self._boost_tags: List[str] = []
        self._language: Optional[str] = None
        self._frameworks: List[str] = []
        self._context: Dict[str, Any] = {}
        # Ensure context dict exists
        if self.query.context is None:
            self.query.context = {}

    def with_query(self, query: str) -> "EngineeringQueryBuilder":
        self.query.query = query
        return self

    def with_domain(self, domain: EngineeringDomain) -> "EngineeringQueryBuilder":
        self._domain_filter = domain
        self.query.context["engineering_domain"] = domain.value
        return self

    def with_knowledge_type(self, ktype: EngineeringKnowledgeType) -> "EngineeringQueryBuilder":
        self._type_filter = ktype
        self.query.context["knowledge_type"] = ktype.value
        return self

    def with_validation_status(self, status: ValidationStatus) -> "EngineeringQueryBuilder":
        self._validation_filter = status
        self.query.context["validation_status"] = status.value
        return self

    def require_tags(self, tags: List[str]) -> "EngineeringQueryBuilder":
        self._required_tags = tags
        self.query.context["required_tags"] = tags
        return self

    def boost_tags(self, tags: List[str]) -> "EngineeringQueryBuilder":
        self._boost_tags = tags
        self.query.context["boost_tags"] = tags
        return self

    def with_language(self, language: str) -> "EngineeringQueryBuilder":
        self._language = language
        self.query.context["language"] = language
        return self

    def with_frameworks(self, frameworks: List[str]) -> "EngineeringQueryBuilder":
        self._frameworks = frameworks
        self.query.context["frameworks"] = frameworks
        return self

    def with_task_context(self, task_type: str, intent: str = "") -> "EngineeringQueryBuilder":
        self._context["task_type"] = task_type
        if intent:
            self._context["intent"] = intent
        # Merge with existing context instead of overwriting
        self.query.context.update(self._context)
        return self

    def build(self) -> RetrievalQuery:
        """Build the final RetrievalQuery."""
        # Preserve existing context and add engineered filters
        self.query.context = self.query.context or {}
        self.query.context["engineering_filters"] = {
            "domain": self._domain_filter.value if self._domain_filter else None,
            "knowledge_type": self._type_filter.value if self._type_filter else None,
            "validation_status": self._validation_filter.value if self._validation_filter else None,
            "required_tags": self._required_tags,
            "boost_tags": self._boost_tags,
            "language": self._language,
            "frameworks": self._frameworks,
        }
        return self.query


# === Convenience functions ===

def create_engineering_ranker(storage_path: Optional[str] = None, adaptive: bool = True) -> EngineeringRankingEngine:
    """Create an engineering ranking engine."""
    return EngineeringRankingEngine(storage_path, adaptive)


def create_engineering_query(query: str) -> EngineeringQueryBuilder:
    """Create a query builder with initial query."""
    return EngineeringQueryBuilder().with_query(query)


def rank_knowledge_items(
    items: List[EngineeringKnowledgeItem],
    query: RetrievalQuery,
    storage_path: Optional[str] = None,
    adaptive: bool = True,
) -> List[KnowledgeRetrievalResult]:
    """Convenience function to rank engineering knowledge items directly."""
    from app.software_engineering_knowledge.sources import EngineeringKnowledgeAdapter

    adapter = EngineeringKnowledgeAdapter(storage_path)
    engine = create_engineering_ranker(storage_path, adaptive)

    # Convert items to retrieval results
    results = []
    for item in items:
        result = adapter._item_to_result(item, query)
        results.append(result)

    # Rank
    return engine.rank_results(results, query)