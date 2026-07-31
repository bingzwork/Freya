"""Knowledge Extraction Pipeline.

Main orchestrator that coordinates the end-to-end extraction process:
Input Source -> Source Detection -> Content Parsing -> Information Extraction
    -> Knowledge Structuring -> Metadata Generation -> Knowledge Object
"""

import time
from typing import Any, Dict, List, Optional

from app.core.logger import logger

from app.knowledge_extraction.models import (
    KnowledgeObject,
    KnowledgeExtractionResult,
    SourceType,
    ExtractionError,
)
from app.knowledge_extraction.extractors import ExtractorRegistry, registry


class KnowledgeExtractionPipeline:
    """End-to-end knowledge extraction pipeline.

    This pipeline orchestrates the complete extraction process:
    1. Source Detection - Identify source type
    2. Content Parsing - Parse raw content (handled by extractor)
    3. Information Extraction - Extract key concepts (handled by extractor)
    4. Knowledge Structuring - Structure into KnowledgeObjects (handled by extractor)
    5. Metadata Generation - Add timestamps, IDs, etc. (handled by pipeline)
    6. Return Knowledge Objects

    The pipeline is reusable by any capability that needs to extract
    structured knowledge from raw sources.
    """

    def __init__(self, extractor_registry: Optional[ExtractorRegistry] = None):
        """Initialize the pipeline.

        Args:
            extractor_registry: Custom extractor registry. Uses global registry if not provided.
        """
        self.registry = extractor_registry or registry
        self._stats = {
            "total_extractions": 0,
            "successful_extractions": 0,
            "failed_extractions": 0,
        }

    def extract(
        self,
        content: str,
        source: str,
        source_type: Optional[SourceType] = None,
        **context
    ) -> KnowledgeExtractionResult:
        """Extract knowledge from raw content.

        This is the main entry point for the pipeline. It automatically
        dispatches to the appropriate extractor based on source type
        or file extension detection.

        Args:
            content: Raw content to extract knowledge from.
            source: Source identifier (file path, URL, conversation ID, etc.).
            source_type: Optional explicit source type. Auto-detected if not provided.
            **context: Additional context passed to the extractor.

        Returns:
            KnowledgeExtractionResult containing extracted knowledge objects
            or error information.
        """
        start_time = time.time()
        self._stats["total_extractions"] += 1

        # Validate input
        if not content or not content.strip():
            error = ExtractionError(
                message="Empty content provided for extraction",
                source_type=source_type or SourceType.UNKNOWN,
                source=source,
            )
            result = KnowledgeExtractionResult.error_result(
                error=error,
                source=source,
                source_type=source_type or SourceType.UNKNOWN,
                extraction_time=time.time() - start_time,
            )
            self._stats["failed_extractions"] += 1
            logger.warning(f"[KnowledgeExtractionPipeline] {error}")
            return result

        # Auto-detect source type if not provided
        if source_type is None:
            source_type = self._detect_source_type(source)
            logger.debug(f"[KnowledgeExtractionPipeline] Auto-detected source type: {source_type.value}")

        # Get appropriate extractor
        extractor = self.registry.get_for_source(source, source_type)

        if not extractor:
            error = ExtractionError(
                message=f"No extractor available for source type: {source_type.value}",
                source_type=source_type,
                source=source,
            )
            result = KnowledgeExtractionResult.error_result(
                error=error,
                source=source,
                source_type=source_type,
                extraction_time=time.time() - start_time,
            )
            self._stats["failed_extractions"] += 1
            logger.warning(f"[KnowledgeExtractionPipeline] {error}")
            return result

        # Execute extraction
        try:
            logger.info(f"[KnowledgeExtractionPipeline] Extracting from {source} ({source_type.value})")
            result = extractor.extract(content, source, **context)

            if result.success:
                self._stats["successful_extractions"] += 1
                # Post-process: ensure all objects have metadata
                for obj in result.knowledge_objects:
                    self._enrich_knowledge_object(obj, source, source_type)
                logger.info(
                    f"[KnowledgeExtractionPipeline] Successfully extracted "
                    f"{len(result.knowledge_objects)} knowledge objects from {source}"
                )
            else:
                self._stats["failed_extractions"] += 1
                logger.warning(f"[KnowledgeExtractionPipeline] Extraction failed: {result.error}")

            return result

        except Exception as e:
            self._stats["failed_extractions"] += 1
            error = ExtractionError(
                message=f"Extraction failed with exception: {str(e)}",
                source_type=source_type,
                source=source,
                details={"exception_type": type(e).__name__},
            )
            logger.error(f"[KnowledgeExtractionPipeline] {error}")
            return KnowledgeExtractionResult.error_result(
                error=error,
                source=source,
                source_type=source_type,
                extraction_time=time.time() - start_time,
            )

    def extract_from_file(
        self,
        file_path: str,
        **context
    ) -> KnowledgeExtractionResult:
        """Extract knowledge from a file.

        Automatically reads the file and detects source type from extension.

        Args:
            file_path: Path to the file.
            **context: Additional context passed to the extractor.

        Returns:
            KnowledgeExtractionResult.
        """
        from pathlib import Path

        path = Path(file_path)
        if not path.exists():
            error = ExtractionError(
                message=f"File not found: {file_path}",
                source_type=SourceType.UNKNOWN,
                source=file_path,
            )
            return KnowledgeExtractionResult.error_result(
                error=error,
                source=file_path,
                source_type=SourceType.UNKNOWN,
                extraction_time=0.0,
            )

        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Try binary read for PDFs, etc.
            try:
                content = path.read_bytes()
                if hasattr(content, 'decode'):
                    content = content.decode('utf-8', errors='replace')
            except Exception as e:
                error = ExtractionError(
                    message=f"Unable to read file: {str(e)}",
                    source_type=SourceType.UNKNOWN,
                    source=file_path,
                )
                return KnowledgeExtractionResult.error_result(
                    error=error,
                    source=file_path,
                    source_type=SourceType.UNKNOWN,
                    extraction_time=0.0,
                )

        return self.extract(content, str(path), **context)

    def extract_batch(
        self,
        items: List[Dict[str, Any]],
        **context
    ) -> List[KnowledgeExtractionResult]:
        """Extract knowledge from multiple sources in batch.

        Args:
            items: List of dicts with keys: 'content', 'source', optional 'source_type'.
            **context: Additional context passed to each extraction.

        Returns:
            List of KnowledgeExtractionResult in same order as input.
        """
        results = []
        for item in items:
            content = item.get("content", "")
            source = item.get("source", "")
            source_type = item.get("source_type")
            result = self.extract(content, source, source_type, **context)
            results.append(result)
        return results

    def _detect_source_type(self, source: str) -> SourceType:
        """Auto-detect source type from source identifier.

        Args:
            source: Source identifier (file path, URL, etc.).

        Returns:
            Detected SourceType.
        """
        source_lower = source.lower()

        # Check file extensions
        if source_lower.endswith((".md", ".markdown", ".txt", ".rst")):
            return SourceType.DOCUMENTATION
        elif source_lower.endswith(".pdf"):
            return SourceType.PDF
        elif source_lower.endswith((".py", ".js", ".ts", ".java", ".cpp", ".cs", ".go", ".rs")):
            return SourceType.SOURCE_CODE
        elif source_lower.endswith((".log", ".txt")) and "log" in source_lower:
            return SourceType.LOG

        # Check for URLs
        if source_lower.startswith(("http://", "https://")):
            if "api" in source_lower:
                return SourceType.API_RESPONSE
            return SourceType.DOCUMENTATION

        # Check for conversation IDs
        if source_lower.startswith(("conv_", "chat_", "msg_")):
            return SourceType.LLM_RESPONSE

        return SourceType.UNKNOWN

    def _enrich_knowledge_object(
        self,
        obj: KnowledgeObject,
        source: str,
        source_type: SourceType,
    ) -> None:
        """Add pipeline-level metadata to knowledge object.

        Args:
            obj: Knowledge object to enrich.
            source: Original source.
            source_type: Source type.
        """
        if not obj.extracted_at:
            from datetime import datetime, timezone
            obj.extracted_at = datetime.now(timezone.utc).isoformat()

        # Add pipeline metadata
        obj.metadata.setdefault("pipeline", {})
        obj.metadata["pipeline"]["extracted_by"] = "KnowledgeExtractionPipeline"
        obj.metadata["pipeline"]["source"] = source
        obj.metadata["pipeline"]["source_type"] = source_type.value

    def get_stats(self) -> Dict[str, Any]:
        """Get pipeline statistics.

        Returns:
            Dictionary with extraction statistics.
        """
        return {
            **self._stats,
            "success_rate": (
                self._stats["successful_extractions"] / self._stats["total_extractions"]
                if self._stats["total_extractions"] > 0 else 0
            ),
            "registered_extractors": self.registry.list_extractors(),
        }

    def reset_stats(self) -> None:
        """Reset pipeline statistics."""
        self._stats = {
            "total_extractions": 0,
            "successful_extractions": 0,
            "failed_extractions": 0,
        }


# Global pipeline instance
pipeline = KnowledgeExtractionPipeline()