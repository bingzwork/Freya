"""Knowledge Acquisition Capability for Freya AI.

This module provides a unified knowledge acquisition pipeline that:
1. Extracts knowledge from various sources (files, URLs, LLM responses, internet research)
2. Validates extracted knowledge using confidence calibration and conflict detection
3. Stores validated knowledge in the appropriate knowledge bases
4. Indexes knowledge for retrieval

The pipeline orchestrates:
- KnowledgeExtractionPipeline: Extract structured knowledge from raw content
- KnowledgeValidator: Validate confidence, detect duplicates/conflicts
- EngineeringKnowledgeStorage (Software Eng Knowledge): Persistent storage
- KnowledgeRetrievalPipeline: Index and make knowledge searchable
- External Knowledge Importers: Web docs, package docs, internet research

Phase 4: Unified Knowledge Acquisition Pipeline
Phase 5: External Knowledge Acquisition (web docs, package docs, internet research)
"""

from app.knowledge_acquisition.models import (
    AcquisitionSource,
    AcquisitionSourceType,
    AcquisitionJob,
    AcquisitionResult,
    AcquisitionStatus,
    KnowledgeAcquisitionConfig,
)

from app.knowledge_acquisition.pipeline import (
    KnowledgeAcquisitionPipeline,
    create_acquisition_pipeline,
)

from app.knowledge_acquisition.external import (
    ExternalKnowledgeAcquisition,
    acquire_external_knowledge,
)

__all__ = [
    # Models
    "AcquisitionSource",
    "AcquisitionSourceType",
    "AcquisitionJob",
    "AcquisitionResult",
    "AcquisitionStatus",
    "KnowledgeAcquisitionConfig",
    # Pipeline
    "KnowledgeAcquisitionPipeline",
    "create_acquisition_pipeline",
    # External
    "ExternalKnowledgeAcquisition",
    "acquire_external_knowledge",
]