"""Knowledge Extraction Capability for Freya AI.

This module provides an end-to-end pipeline for converting raw information
from various sources into structured knowledge objects that can be used
by Planning, Reasoning, Memory, Decision Making, Autonomous Learning,
and Software Engineering capabilities.

The pipeline supports:
- LLM response extraction
- Documentation extraction (Markdown, PDF)
- Extensible architecture for new source types

Core Components:
- KnowledgeExtractionPipeline: Main orchestrator
- KnowledgeObject: Structured output format
- Extractor: Base class for source-specific extractors
- LLMExtractor: Extract from LLM responses
- DocumentExtractor: Extract from documentation files
"""

from app.knowledge_extraction.models import (
    KnowledgeObject,
    SourceType,
    KnowledgeCategory,
    ExtractionError,
    KnowledgeExtractionResult,
)
from app.knowledge_extraction.pipeline import KnowledgeExtractionPipeline, pipeline
from app.knowledge_extraction.extractors import Extractor, ExtractorRegistry, registry
from app.knowledge_extraction.llm_extractor import LLMExtractor
from app.knowledge_extraction.doc_extractor import DocumentExtractor

# Initialize and register default extractors
def _register_default_extractors() -> None:
    """Register built-in extractors with the global registry."""
    registry.register(LLMExtractor())
    registry.register(DocumentExtractor())


# Register on import
_register_default_extractors()

__all__ = [
    "KnowledgeObject",
    "SourceType",
    "ExtractionError",
    "KnowledgeExtractionResult",
    "KnowledgeExtractionPipeline",
    "Extractor",
    "ExtractorRegistry",
    "LLMExtractor",
    "DocumentExtractor",
    # Global instances
    "pipeline",
    "registry",
]