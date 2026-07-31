"""Base Extractor class and Registry for Knowledge Extraction.

This module provides the extensible architecture for adding new extractors.
"""

import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type

from app.knowledge_extraction.models import (
    KnowledgeObject,
    KnowledgeExtractionResult,
    SourceType,
    ExtractionError,
)


class Extractor(ABC):
    """Abstract base class for all knowledge extractors.

    Each extractor handles a specific source type and converts raw input
    into structured KnowledgeObjects.

    To add a new source:
    1. Subclass Extractor
    2. Implement extract() method
    3. Register with ExtractorRegistry
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize extractor with optional configuration.

        Args:
            config: Extractor-specific configuration options.
        """
        self.config = config or {}

    @property
    @abstractmethod
    def source_type(self) -> SourceType:
        """The source type this extractor handles."""
        pass

    @property
    @abstractmethod
    def supported_extensions(self) -> List[str]:
        """File extensions this extractor can handle (for file-based sources)."""
        pass

    @abstractmethod
    def extract(self, content: str, source: str, **context) -> KnowledgeExtractionResult:
        """Extract knowledge from raw content.

        Args:
            content: Raw content to extract from.
            source: Source identifier (file path, URL, conversation ID, etc.).
            **context: Additional context (metadata, language hints, etc.).

        Returns:
            KnowledgeExtractionResult with extracted knowledge or error.
        """
        pass

    def can_handle(self, source: str, source_type: Optional[SourceType] = None) -> bool:
        """Check if this extractor can handle the given source.

        Args:
            source: Source identifier.
            source_type: Optional explicit source type.

        Returns:
            True if extractor can handle this source.
        """
        if source_type and source_type != self.source_type:
            return False

        # Check file extension if applicable
        if self.supported_extensions:
            source_lower = source.lower()
            return any(source_lower.endswith(ext) for ext in self.supported_extensions)

        return True

    def _create_error_result(
        self,
        message: str,
        source: str,
        start_time: float,
        details: Optional[Dict[str, Any]] = None,
    ) -> KnowledgeExtractionResult:
        """Helper to create an error result."""
        return KnowledgeExtractionResult.error_result(
            error=ExtractionError(
                message=message,
                source_type=self.source_type,
                source=source,
                details=details or {},
            ),
            source=source,
            source_type=self.source_type,
            extraction_time=time.time() - start_time,
        )

    def _create_success_result(
        self,
        knowledge_objects: List[KnowledgeObject],
        source: str,
        start_time: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> KnowledgeExtractionResult:
        """Helper to create a success result."""
        return KnowledgeExtractionResult.success_result(
            knowledge_objects=knowledge_objects,
            source=source,
            source_type=self.source_type,
            extraction_time=time.time() - start_time,
            metadata=metadata,
        )


class ExtractorRegistry:
    """Registry for managing and dispatching extractors.

    Automatically dispatches the correct extractor based on source type
    or file extension. New extractors can be registered at runtime.
    """

    def __init__(self):
        self._extractors: Dict[SourceType, Extractor] = {}
        self._extension_map: Dict[str, SourceType] = {}

    def register(self, extractor: Extractor) -> None:
        """Register an extractor.

        Args:
            extractor: The extractor instance to register.
        """
        self._extractors[extractor.source_type] = extractor

        # Map extensions to source type for auto-detection
        for ext in extractor.supported_extensions:
            self._extension_map[ext.lower()] = extractor.source_type

    def unregister(self, source_type: SourceType) -> None:
        """Unregister an extractor.

        Args:
            source_type: The source type to unregister.
        """
        if source_type in self._extractors:
            extractor = self._extractors[source_type]
            for ext in extractor.supported_extensions:
                if ext.lower() in self._extension_map:
                    del self._extension_map[ext.lower()]
            del self._extractors[source_type]

    def get(self, source_type: SourceType) -> Optional[Extractor]:
        """Get extractor by source type.

        Args:
            source_type: The source type to look up.

        Returns:
            The extractor instance, or None if not found.
        """
        return self._extractors.get(source_type)

    def get_for_source(self, source: str, source_type: Optional[SourceType] = None) -> Optional[Extractor]:
        """Get the appropriate extractor for a source.

        Args:
            source: Source identifier (file path, URL, etc.).
            source_type: Optional explicit source type.

        Returns:
            Matching extractor, or None if no extractor can handle this source.
        """
        # If source type is explicitly provided, use it
        if source_type:
            return self._extractors.get(source_type)

        # Auto-detect from file extension
        source_lower = source.lower()
        for ext, s_type in self._extension_map.items():
            if source_lower.endswith(ext):
                return self._extractors.get(s_type)

        # Fallback: try to find an extractor that claims it can handle
        for extractor in self._extractors.values():
            if extractor.can_handle(source):
                return extractor

        return None

    def list_extractors(self) -> List[SourceType]:
        """List all registered source types.

        Returns:
            List of registered SourceType values.
        """
        return list(self._extractors.keys())

    def extract(
        self,
        content: str,
        source: str,
        source_type: Optional[SourceType] = None,
        **context
    ) -> KnowledgeExtractionResult:
        """Extract knowledge using the appropriate extractor.

        Args:
            content: Raw content to extract from.
            source: Source identifier.
            source_type: Optional explicit source type.
            **context: Additional context passed to extractor.

        Returns:
            KnowledgeExtractionResult from the matched extractor.
        """
        extractor = self.get_for_source(source, source_type)

        if not extractor:
            return KnowledgeExtractionResult.error_result(
                error=ExtractionError(
                    message=f"No extractor found for source: {source}",
                    source_type=source_type or SourceType.UNKNOWN,
                    source=source,
                ),
                source=source,
                source_type=source_type or SourceType.UNKNOWN,
                extraction_time=0.0,
            )

        return extractor.extract(content, source, **context)


# Global registry instance
registry = ExtractorRegistry()