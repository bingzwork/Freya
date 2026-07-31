"""Software Engineering Knowledge - Unified capability for Freya.

This package provides a complete system for managing software engineering knowledge
across all projects, including extraction, validation, ranking, and expertise building.

Main Components:
- models: Core data models (EngineeringKnowledgeItem, domains, types, etc.)
- categories: Category registry with 35+ engineering domains
- storage: Persistent storage with CRUD and versioning
- sources: Adapters for Knowledge Retrieval Pipeline integration
- extraction: Extract knowledge from code, docs, external sources
- import_experience: Import from ExperienceMemory, EngineeringLessons, etc.
- validation: Validate knowledge (confidence, duplicates, conflicts)
- ranking: Engineering-specific ranking using unified engine
- external_import: Import from official docs, internet, packages
- autonomous_expansion: Auto-extract knowledge after tasks/events
- expertise: Build higher-level expertise from accumulated knowledge
"""

from typing import Any, Dict, List, Optional

from app.software_engineering_knowledge.models import (
    # Enums
    EngineeringDomain,
    EngineeringKnowledgeType,
    KnowledgeSource,
    ValidationStatus,
    # Core models
    EngineeringKnowledgeItem,
    EngineeringCategory,
    ExtractionResult,
    ValidationResult,
    EngineeringExpertise,
)

from app.software_engineering_knowledge.categories import (
    CategoryRegistry,
    DEFAULT_CATEGORIES,
    get_category_registry,
)

from app.software_engineering_knowledge.storage import (
    EngineeringKnowledgeStorage,
    get_knowledge_storage,
)

from app.software_engineering_knowledge.sources import (
    EngineeringKnowledgeAdapter,
    ExtractedKnowledgeAdapter,
    EngineeringLessonsAdapter,
    create_engineering_adapters,
    register_engineering_sources,
)

from app.software_engineering_knowledge.extraction import (
    KnowledgeExtractor,
    CodeExtractor,
    DocumentationExtractor,
    ExternalDocumentationExtractor,
)

from app.software_engineering_knowledge.import_experience import (
    KnowledgeImporter,
    ExperienceImporter,
    EngineeringLessonsImporter,
    ReflectionImporter,
    UserKnowledgeImporter,
)

from app.software_engineering_knowledge.validation import (
    KnowledgeValidator,
    ValidationConfig,
    ConfidenceScorer,
)

from app.software_engineering_knowledge.ranking import (
    EngineeringRankingEngine,
    EngineeringQueryBuilder,
    create_engineering_ranker,
    create_engineering_query,
    rank_knowledge_items,
)

from app.software_engineering_knowledge.external_import import (
    ExternalKnowledgeImporter,
    InternetResearchImporter,
    PackageDocumentationImporter,
    UnifiedExternalImporter,
    EXTERNAL_SOURCES,
)

from app.software_engineering_knowledge.autonomous_expansion import (
    AutonomousExpander,
    ExpansionTrigger,
    ExpansionResult,
    TaskCompletionExpander,
    ExpansionEventHandler,
)

from app.software_engineering_knowledge.expertise import (
    ExpertiseBuilder,
    ExpertiseQueryEngine,
    ExpertiseBasedRecommendation,
    ExpertiseEnhancedRetrieval,
    build_domain_expertise,
    get_task_recommendations,
    create_expertise_from_items,
)


__version__ = "1.0.0"

__all__ = [
    # Models
    "EngineeringDomain",
    "EngineeringKnowledgeType",
    "KnowledgeSource",
    "ValidationStatus",
    "EngineeringKnowledgeItem",
    "EngineeringCategory",
    "ExtractionResult",
    "ValidationResult",
    "EngineeringExpertise",
    # Categories
    "CategoryRegistry",
    "DEFAULT_CATEGORIES",
    "get_category_registry",
    # Storage
    "EngineeringKnowledgeStorage",
    "get_knowledge_storage",
    # Sources
    "EngineeringKnowledgeAdapter",
    "ExtractedKnowledgeAdapter",
    "EngineeringLessonsAdapter",
    "create_engineering_adapters",
    "register_engineering_sources",
    # Extraction
    "KnowledgeExtractor",
    "CodeExtractor",
    "DocumentationExtractor",
    "ExternalDocumentationExtractor",
    # Experience Import
    "KnowledgeImporter",
    "ExperienceImporter",
    "EngineeringLessonsImporter",
    "ReflectionImporter",
    "UserKnowledgeImporter",
    # Validation
    "KnowledgeValidator",
    "ValidationConfig",
    "ConfidenceScorer",
    # Ranking
    "EngineeringRankingEngine",
    "EngineeringQueryBuilder",
    "create_engineering_ranker",
    "create_engineering_query",
    "rank_knowledge_items",
    # External Import
    "ExternalKnowledgeImporter",
    "InternetResearchImporter",
    "PackageDocumentationImporter",
    "UnifiedExternalImporter",
    "EXTERNAL_SOURCES",
    # Autonomous Expansion
    "AutonomousExpander",
    "ExpansionTrigger",
    "ExpansionResult",
    "TaskCompletionExpander",
    "ExpansionEventHandler",
    # Expertise
    "ExpertiseBuilder",
    "ExpertiseQueryEngine",
    "ExpertiseBasedRecommendation",
    "ExpertiseEnhancedRetrieval",
    "build_domain_expertise",
    "get_task_recommendations",
    "create_expertise_from_items",
]


# Convenience factory functions

def create_knowledge_system(
    project_root: str = ".",
    storage_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a complete software engineering knowledge system.

    Returns a dictionary with all major components initialized.
    """
    from pathlib import Path

    project_path = Path(project_root)
    storage = get_knowledge_storage(storage_path)

    return {
        "storage": storage,
        "categories": get_category_registry(storage_path),
        "extractor": KnowledgeExtractor(project_path),
        "importer": KnowledgeImporter(project_root=project_path),
        "validator": KnowledgeValidator(storage_path=storage_path),
        "ranker": EngineeringRankingEngine(storage_path),
        "external_importer": UnifiedExternalImporter(),
        "expander": AutonomousExpander(project_path, storage_path),
        "event_handler": ExpansionEventHandler(AutonomousExpander(project_path, storage_path)),
        "expertise_builder": ExpertiseBuilder(storage_path),
        "expertise_query": ExpertiseQueryEngine(storage_path),
        "recommender": ExpertiseBasedRecommendation(storage_path),
    }


def quick_extract_and_store(
    project_root: str = ".",
    storage_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Quickly extract knowledge from project and store it.

    Runs code and documentation extraction, validates, and stores.
    """
    system = create_knowledge_system(project_root, storage_path)

    # Extract
    extraction_results = system["extractor"].extract_all()

    # Import experience
    experience_results = system["importer"].import_all()

    # Validate and store all items
    all_items = []
    for result in extraction_results.values():
        all_items.extend(result.items)
    for result in experience_results.values():
        all_items.extend(result.items)

    stored = 0
    errors = []
    for item in all_items:
        validation = system["validator"].validate(item)
        if validation.is_valid:
            item.validation_status = validation.validation_status
            item.confidence = validation.confidence
            system["storage"].create(item)
            stored += 1
        else:
            errors.append(f"{item.title}: {validation.notes}")

    return {
        "extracted": len(all_items),
        "stored": stored,
        "errors": errors,
        "extraction_results": {k: v.metadata for k, v in extraction_results.items()},
        "experience_results": {k: v.metadata for k, v in experience_results.items()},
    }


# Simple one-off functions

def store_knowledge(
    title: str,
    content: str,
    domain: EngineeringDomain,
    knowledge_type: EngineeringKnowledgeType = EngineeringKnowledgeType.CUSTOM,
    source: KnowledgeSource = KnowledgeSource.USER_INPUT,
    tags: Optional[List[str]] = None,
    confidence: float = 0.8,
    storage_path: Optional[str] = None,
) -> EngineeringKnowledgeItem:
    """Quickly store a knowledge item."""
    from app.software_engineering_knowledge.storage import get_knowledge_storage
    from app.software_engineering_knowledge.validation import KnowledgeValidator

    storage = get_knowledge_storage(storage_path)
    validator = KnowledgeValidator(storage_path=storage_path)

    item = EngineeringKnowledgeItem(
        title=title,
        summary=content[:200],
        content=content,
        domain=domain,
        knowledge_type=knowledge_type,
        source=source,
        tags=tags or [],
        confidence=confidence,
        validation_status=ValidationStatus.PENDING,
    )

    validation = validator.validate(item)
    if validation.is_valid:
        item.validation_status = validation.validation_status
        item.confidence = validation.confidence
        return storage.create(item)
    else:
        raise ValueError(f"Validation failed: {validation.notes}")


def retrieve_knowledge(
    query: str,
    max_results: int = 10,
    domain: Optional[EngineeringDomain] = None,
    knowledge_type: Optional[EngineeringKnowledgeType] = None,
    storage_path: Optional[str] = None,
) -> List[EngineeringKnowledgeItem]:
    """Quickly retrieve knowledge items matching a query."""
    from app.software_engineering_knowledge.ranking import create_engineering_query, rank_knowledge_items
    from app.software_engineering_knowledge.storage import get_knowledge_storage
    from app.knowledge_retrieval.models import RetrievalQuery

    storage = get_knowledge_storage(storage_path)

    # Build query
    builder = create_engineering_query(query)
    if domain:
        builder.with_domain(domain)
    if knowledge_type:
        builder.with_knowledge_type(knowledge_type)

    query_obj = builder.build()

    # Get candidate items
    if domain:
        candidates = storage.get_by_domain(domain, limit=100)
    elif knowledge_type:
        candidates = storage.get_by_type(knowledge_type, limit=100)
    else:
        candidates = storage.search(query, limit=100)

    # Rank
    ranked_results = rank_knowledge_items(candidates, query_obj, storage_path)

    # Convert back
    items = []
    for result in ranked_results[:max_results]:
        item = storage.get(result.source_id)
        if item:
            items.append(item)

    return items