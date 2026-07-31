"""Source adapters for Software Engineering Knowledge integration with Knowledge Retrieval Pipeline.

Provides EngineeringKnowledgeAdapter to expose the engineering knowledge base
as a knowledge source for the unified retrieval pipeline.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from app.knowledge_retrieval.models import (
    KnowledgeRetrievalResult,
    KnowledgeSourceType,
    RetrievalQuery,
)
from app.knowledge_retrieval.sources import KnowledgeSourceAdapter
from app.software_engineering_knowledge.models import (
    EngineeringDomain,
    EngineeringKnowledgeItem,
    EngineeringKnowledgeType,
    KnowledgeSource,
    ValidationStatus,
)
from app.software_engineering_knowledge.storage import get_knowledge_storage


class EngineeringKnowledgeAdapter(KnowledgeSourceAdapter):
    """Adapter to expose Software Engineering Knowledge as a retrieval source.

    This allows the KnowledgeRetrievalPipeline to query the engineering
    knowledge base alongside other sources like semantic memory, episodic memory, etc.
    """

    def __init__(self, storage_path: Optional[str] = None):
        """Initialize adapter with storage path.

        Args:
            storage_path: Path to engineering knowledge storage directory
        """
        self.storage = get_knowledge_storage(storage_path)
        self._source_type = KnowledgeSourceType.KNOWLEDGE_BASE

    @property
    def source_type(self) -> KnowledgeSourceType:
        return self._source_type

    def is_available(self) -> bool:
        """Check if the knowledge base is available."""
        return self.storage.count() > 0

    def retrieve_candidates(
        self, query: RetrievalQuery, max_results: int = 50
    ) -> List[KnowledgeRetrievalResult]:
        """Retrieve candidate knowledge items matching the query.

        Uses the storage's search capabilities with query filtering.

        Args:
            query: The retrieval query with parameters
            max_results: Maximum number of results to return

        Returns:
            List of KnowledgeRetrievalResult objects
        """
        # Use storage search
        items = self.storage.search(query.query, limit=max_results * 2)

        # Apply filters
        items = self._apply_filters(items, query)

        # Convert to retrieval results
        results = []
        for item in items[:max_results]:
            result = self._item_to_result(item, query)
            results.append(result)

        return results

    def _apply_filters(self, items: List[EngineeringKnowledgeItem], query: RetrievalQuery) -> List[EngineeringKnowledgeItem]:
        """Apply query filters to candidate items."""
        filtered = items

        # Filter by minimum score/confidence
        min_conf = getattr(query, "min_confidence", 0.0)
        if min_conf > 0:
            filtered = [i for i in filtered if i.confidence >= min_conf]

        # Filter by domain/category
        if hasattr(query, "domain") and query.domain:
            if isinstance(query.domain, str):
                try:
                    domain_enum = EngineeringDomain(query.domain)
                    filtered = [i for i in filtered if i.domain == domain_enum]
                except ValueError:
                    pass
            elif isinstance(query.domain, EngineeringDomain):
                filtered = [i for i in filtered if i.domain == query.domain]

        # Filter by knowledge type
        if hasattr(query, "knowledge_type") and query.knowledge_type:
            if isinstance(query.knowledge_type, str):
                try:
                    type_enum = EngineeringKnowledgeType(query.knowledge_type)
                    filtered = [i for i in filtered if i.knowledge_type == type_enum]
                except ValueError:
                    pass
            elif isinstance(query.knowledge_type, EngineeringKnowledgeType):
                filtered = [i for i in filtered if i.knowledge_type == query.knowledge_type]

        # Filter by validation status
        if hasattr(query, "validation_status") and query.validation_status:
            if isinstance(query.validation_status, str):
                try:
                    status_enum = ValidationStatus(query.validation_status)
                    filtered = [i for i in filtered if i.validation_status == status_enum]
                except ValueError:
                    pass
            elif isinstance(query.validation_status, ValidationStatus):
                filtered = [i for i in filtered if i.validation_status == query.validation_status]

        # Filter by tags (if query has boost_tags or required_tags)
        if hasattr(query, "required_tags") and query.required_tags:
            required = set(t.lower() for t in query.required_tags)
            filtered = [i for i in filtered if required.issubset(set(t.lower() for t in i.tags))]

        # Filter by language
        if hasattr(query, "language") and query.language:
            filtered = [i for i in filtered if i.language and i.language.lower() == query.language.lower()]

        # Filter by frameworks
        if hasattr(query, "frameworks") and query.frameworks:
            required = set(f.lower() for f in query.frameworks)
            filtered = [i for i in filtered if required.issubset(set(f.lower() for f in i.frameworks))]

        return filtered

    def _item_to_result(
        self, item: EngineeringKnowledgeItem, query: RetrievalQuery
    ) -> KnowledgeRetrievalResult:
        """Convert an EngineeringKnowledgeItem to a KnowledgeRetrievalResult."""
        # Determine category for ranking
        category = item.sub_category or item.domain.value

        # Build metadata for ranking signals
        metadata = {
            "engineering_domain": item.domain.value,
            "knowledge_type": item.knowledge_type.value,
            "source": item.source.value,
            "validation_status": item.validation_status.value,
            "tags": item.tags,
            "language": item.language,
            "frameworks": item.frameworks,
            "version": item.version,
            "access_count": item.access_count,
            "success_count": item.success_count,
            "related_items": item.related_items,
            "prerequisites": item.prerequisites,
        }

        # Include custom metadata
        metadata.update(item.metadata)

        return KnowledgeRetrievalResult(
            content=item.content,
            title=item.title,
            summary=item.summary or item.content[:200],
            source_type=self._source_type,
            source_id=item.id,
            raw_confidence=item.confidence,
            category=category,
            tags=item.tags,
            language=item.language,
            last_updated=item.updated_at,
            access_count=item.access_count,
            source_metadata=metadata,
        )

    def get_source_quality(self) -> float:
        """Return the trustworthiness score for this source.

        Engineering knowledge base is high quality (curated, validated).
        """
        return 0.95

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about this knowledge source."""
        return {
            "total_items": self.storage.count(),
            "by_domain": {k.value: v for k, v in self.storage.count_by_domain().items()},
            "by_type": {k.value: v for k, v in self.storage.count_by_type().items()},
            "by_source": {k.value: v for k, v in self.storage.count_by_source().items()},
            "by_validation": {k.value: v for k, v in self.storage.count_by_validation().items()},
        }


class ExtractedKnowledgeAdapter(KnowledgeSourceAdapter):
    """Adapter for extracted knowledge (from code, docs, etc.) before validation."""

    def __init__(self, storage_path: Optional[str] = None):
        self.storage = get_knowledge_storage(storage_path)
        self._source_type = KnowledgeSourceType.EXTRACTED_KNOWLEDGE

    @property
    def source_type(self) -> KnowledgeSourceType:
        return self._source_type

    def is_available(self) -> bool:
        # Check for pending validation items
        pending = self.storage.get_by_validation(ValidationStatus.PENDING)
        return len(pending) > 0

    def retrieve_candidates(
        self, query: RetrievalQuery, max_results: int = 50
    ) -> List[KnowledgeRetrievalResult]:
        # Get pending/low confidence items
        candidates = self.storage.get_by_validation(ValidationStatus.PENDING, limit=max_results)
        candidates += self.storage.get_by_validation(ValidationStatus.LOW_CONFIDENCE, limit=max_results)

        # Simple text matching
        query_lower = query.query.lower()
        filtered = []
        for item in candidates:
            searchable = f"{item.title} {item.summary} {item.content}".lower()
            if query_lower in searchable:
                filtered.append(item)

        results = []
        for item in filtered[:max_results]:
            result = KnowledgeRetrievalResult(
                content=item.content,
                title=item.title,
                summary=item.summary or item.content[:200],
                source_type=self._source_type,
                source_id=item.id,
                raw_confidence=item.confidence,
                category=item.sub_category or item.domain.value,
                tags=item.tags,
                language=item.language,
                last_updated=item.updated_at,
                access_count=item.access_count,
                source_metadata={
                    "engineering_domain": item.domain.value,
                    "knowledge_type": item.knowledge_type.value,
                    "source": item.source.value,
                    "validation_status": item.validation_status.value,
                    "extraction_metadata": item.source_metadata,
                },
            )
            results.append(result)

        return results

    def get_source_quality(self) -> float:
        return 0.80  # Lower quality - not yet validated


class EngineeringLessonsAdapter(KnowledgeSourceAdapter):
    """Adapter specifically for engineering lessons and best practices."""

    def __init__(self, storage_path: Optional[str] = None):
        self.storage = get_knowledge_storage(storage_path)
        self._source_type = KnowledgeSourceType.ENGINEERING_LESSONS

    @property
    def source_type(self) -> KnowledgeSourceType:
        return self._source_type

    def is_available(self) -> bool:
        lessons = self.storage.get_by_type(
            EngineeringKnowledgeType.LESSON_LEARNED, limit=1
        )
        lessons += self.storage.get_by_type(
            EngineeringKnowledgeType.BEST_PRACTICE, limit=1
        )
        return len(lessons) > 0

    def retrieve_candidates(
        self, query: RetrievalQuery, max_results: int = 50
    ) -> List[KnowledgeRetrievalResult]:
        # Get lessons and best practices
        candidates = self.storage.get_by_type(EngineeringKnowledgeType.LESSON_LEARNED, limit=max_results)
        candidates += self.storage.get_by_type(EngineeringKnowledgeType.BEST_PRACTICE, limit=max_results)
        candidates += self.storage.get_by_type(EngineeringKnowledgeType.RECOMMENDATION, limit=max_results)

        # Simple text matching
        query_lower = query.query.lower()
        filtered = []
        for item in candidates:
            searchable = f"{item.title} {item.summary} {item.content} {' '.join(item.tags)}".lower()
            if query_lower in searchable:
                filtered.append(item)

        results = []
        for item in filtered[:max_results]:
            result = KnowledgeRetrievalResult(
                content=item.content,
                title=item.title,
                summary=item.summary or item.content[:200],
                source_type=self._source_type,
                source_id=item.id,
                raw_confidence=item.confidence,
                category=item.sub_category or "lessons",
                tags=item.tags,
                language=item.language,
                last_updated=item.updated_at,
                access_count=item.access_count,
                source_metadata={
                    "engineering_domain": item.domain.value,
                    "knowledge_type": item.knowledge_type.value,
                    "source": item.source.value,
                },
            )
            results.append(result)

        return results

    def get_source_quality(self) -> float:
        return 0.85  # High quality - distilled experience


# === Registration helper ===

def create_engineering_adapters(storage_path: Optional[str] = None) -> List[KnowledgeSourceAdapter]:
    """Create all engineering knowledge adapters for the retrieval pipeline."""
    return [
        EngineeringKnowledgeAdapter(storage_path),
        ExtractedKnowledgeAdapter(storage_path),
        EngineeringLessonsAdapter(storage_path),
    ]


def register_engineering_sources(pipeline, storage_path: Optional[str] = None) -> None:
    """Register all engineering knowledge sources with a pipeline."""
    for adapter in create_engineering_adapters(storage_path):
        pipeline.register_adapter(adapter)