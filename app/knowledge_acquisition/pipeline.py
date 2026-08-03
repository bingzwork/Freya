"""Unified Knowledge Acquisition Pipeline.

This module provides the main orchestration pipeline for knowledge acquisition:
Acquire → Extract → Validate → Store → Index

The pipeline integrates:
- KnowledgeExtractionPipeline: Extract structured knowledge from raw content
- KnowledgeValidator: Validate confidence, detect duplicates/conflicts
- EngineeringKnowledgeStorage: Persistent storage with indexing
- KnowledgeRetrievalPipeline: Make knowledge searchable
- ExternalKnowledgeImporters: Web docs, package docs, internet research

All subsystems communicate via EventBus for reactive updates.
"""

import time
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from app.core.events import get_event_bus, Event, EventPriority
from app.core.background_jobs import get_job_service, JobTriggerConfig, JobTriggerType, JobPriority
from app.core.observability import get_observability_hub, HealthCheck, HealthResult, HealthStatus, ComponentInfo, ComponentType
from app.core.logger import logger

# Knowledge extraction
from app.knowledge_extraction import (
    KnowledgeExtractionPipeline,
    KnowledgeObject,
    SourceType,
    KnowledgeExtractionResult,
    pipeline as extraction_pipeline,
)

# Knowledge validation
from app.knowledge_retrieval.calibration import get_calibration_manager
from app.software_engineering_knowledge.validation import KnowledgeValidator, ValidationConfig, ValidationStatus

# Knowledge storage
from app.software_engineering_knowledge.storage import EngineeringKnowledgeStorage, get_knowledge_storage
from app.software_engineering_knowledge.models import (
    EngineeringKnowledgeItem,
    EngineeringDomain,
    EngineeringKnowledgeType,
    KnowledgeSource,
    ValidationStatus as EngValidationStatus,
)

# Knowledge retrieval (for indexing)
from app.knowledge_retrieval import (
    KnowledgeRetrievalPipeline,
    create_adapters_from_agent,
    KnowledgeSourceType,
    KnowledgeRetrievalResult,
)

# External knowledge importers
from app.software_engineering_knowledge.external_import import (
    UnifiedExternalImporter,
    ExternalKnowledgeImporter,
    InternetResearchImporter,
    PackageDocumentationImporter,
)

# Models
from app.knowledge_acquisition.models import (
    AcquisitionSource,
    AcquisitionSourceType,
    AcquisitionJob,
    AcquisitionResult,
    AcquisitionStatus,
    KnowledgeAcquisitionConfig,
)


@dataclass
class PipelineStats:
    """Statistics for the acquisition pipeline."""
    total_jobs: int = 0
    completed_jobs: int = 0
    failed_jobs: int = 0
    partial_jobs: int = 0
    total_items_acquired: int = 0
    total_items_extracted: int = 0
    total_items_validated: int = 0
    total_items_stored: int = 0
    total_items_indexed: int = 0
    total_items_skipped: int = 0
    avg_job_time: float = 0.0
    source_type_distribution: Dict[str, int] = field(default_factory=dict)
    error_distribution: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_jobs": self.total_jobs,
            "completed_jobs": self.completed_jobs,
            "failed_jobs": self.failed_jobs,
            "partial_jobs": self.partial_jobs,
            "total_items_acquired": self.total_items_acquired,
            "total_items_extracted": self.total_items_extracted,
            "total_items_validated": self.total_items_validated,
            "total_items_stored": self.total_items_stored,
            "total_items_indexed": self.total_items_indexed,
            "total_items_skipped": self.total_items_skipped,
            "avg_job_time": self.avg_job_time,
            "source_type_distribution": self.source_type_distribution,
            "error_distribution": self.error_distribution,
        }


class KnowledgeAcquisitionPipeline:
    """Unified knowledge acquisition pipeline.

    Orchestrates the complete acquisition flow:
    1. ACQUIRE - Fetch content from source (file, URL, package, research query)
    2. EXTRACT - Use KnowledgeExtractionPipeline to extract KnowledgeObjects
    3. VALIDATE - Validate confidence, check duplicates/conflicts using KnowledgeValidator
    4. STORE - Persist validated items to EngineeringKnowledgeStorage
    5. INDEX - Register with KnowledgeRetrievalPipeline for searchability

    Integrates with:
    - EventBus: Emits events at each stage for reactive updates
    - BackgroundJobService: Schedules periodic/recurring acquisition
    - ObservabilityHub: Health checks, metrics, alerting
    - FileWatcher: Auto-triggers on file changes (when configured)
    """

    def __init__(
        self,
        config: Optional[KnowledgeAcquisitionConfig] = None,
        storage_path: Optional[Path] = None,
        # Shared infrastructure (injected or auto-resolved)
        event_bus: Optional[object] = None,
        job_service: Optional[object] = None,
        observability: Optional[object] = None,
        extraction_pipeline: Optional[KnowledgeExtractionPipeline] = None,
        retrieval_pipeline: Optional[KnowledgeRetrievalPipeline] = None,
        validator: Optional[KnowledgeValidator] = None,
        storage: Optional[EngineeringKnowledgeStorage] = None,
        external_importer: Optional[UnifiedExternalImporter] = None,
    ):
        """Initialize the acquisition pipeline."""
        self.config = config or KnowledgeAcquisitionConfig()
        if storage_path:
            self.config.storage_path = storage_path

        # Shared infrastructure
        self.event_bus = event_bus or get_event_bus()
        self.job_service = job_service or get_job_service()
        self.observability = observability or get_observability_hub()

        # Core components
        self.extraction_pipeline = extraction_pipeline or KnowledgeExtractionPipeline()

        # Knowledge validator
        validation_config = ValidationConfig(
            min_confidence_for_validated=self.config.min_confidence_threshold,
            high_confidence_threshold=self.config.high_confidence_threshold,
            duplicate_similarity_threshold=self.config.duplicate_similarity_threshold,
            check_conflicts=self.config.check_conflicts,
            conflict_similarity_threshold=self.config.conflict_similarity_threshold,
        )
        self.validator = validator or KnowledgeValidator(
            config=validation_config,
            storage_path=str(self.config.storage_path) if self.config.storage_path else None,
        )

        # Storage
        self.storage = storage or get_knowledge_storage(
            str(self.config.storage_path) if self.config.storage_path else None
        )

        # Retrieval pipeline for indexing
        self.retrieval_pipeline = retrieval_pipeline

        # External importer
        self.external_importer = external_importer or UnifiedExternalImporter(
            cache_dir=self.config.storage_path / "external" if self.config.storage_path else None
        )

        # Statistics
        self._stats = PipelineStats()
        self._active_jobs: Dict[str, AcquisitionJob] = {}

        # Register with observability
        self._register_with_observability()

        logger.info("[KnowledgeAcquisitionPipeline] Initialized")

    def _register_with_observability(self) -> None:
        """Register this subsystem with the shared ObservabilityHub."""
        if self.observability:
            self.observability.add_health_check(HealthCheck(
                name="knowledge_acquisition_pipeline_health",
                component="knowledge_acquisition",
                check_func=self._health_check,
                interval_seconds=60.0,
            ))

            self.observability.register_component(ComponentInfo(
                name="KnowledgeAcquisitionPipeline",
                component_type=ComponentType.SERVICE,
                version="1.0.0",
                description="Unified knowledge acquisition: acquire→extract→validate→store→index",
                metadata={
                    "config": self.config.to_dict(),
                    "external_sources_enabled": self.config.enable_external,
                }
            ))

    def _health_check(self) -> HealthResult:
        """Health check for KnowledgeAcquisitionPipeline."""
        try:
            success_rate = self._stats.completed_jobs / max(1, self._stats.total_jobs)
            return HealthResult(
                name="knowledge_acquisition_pipeline_health",
                component="knowledge_acquisition",
                status=HealthStatus.HEALTHY if success_rate > 0.8 else HealthStatus.DEGRADED,
                message=f"KnowledgeAcquisitionPipeline operational (success rate: {success_rate:.1%})",
                metadata={
                    "total_jobs": self._stats.total_jobs,
                    "success_rate": success_rate,
                    "avg_job_time": self._stats.avg_job_time,
                    "items_acquired": self._stats.total_items_acquired,
                    "external_enabled": self.config.enable_external,
                }
            )
        except Exception as e:
            return HealthResult(
                name="knowledge_acquisition_pipeline_health",
                component="knowledge_acquisition",
                status=HealthStatus.UNHEALTHY,
                message=f"Health check failed: {e}",
                metadata={"error": str(e)}
            )

    def _publish_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Publish an event to the shared EventBus."""
        try:
            self.event_bus.emit(event_type, data)
        except Exception as e:
            logger.warning(f"Failed to publish event {event_type}: {e}")

    def acquire(
        self,
        source: Union[AcquisitionSource, str],
        **kwargs
    ) -> AcquisitionResult:
        """Main acquisition entry point.

        Args:
            source: AcquisitionSource object or string identifier (file path, URL, query)
            **kwargs: Additional configuration overrides

        Returns:
            AcquisitionResult with acquired knowledge items
        """
        # Normalize source
        if isinstance(source, str):
            source = self._create_source_from_string(source)

        # Create job
        job = AcquisitionJob(source=source)
        self._active_jobs[job.id] = job
        self._stats.total_jobs += 1

        start_time = time.time()
        logger.info(f"[KnowledgeAcquisitionPipeline] Starting job {job.id} for {source.identifier}")

        # Publish start event
        self._publish_event("knowledge.acquisition.started", {
            "job_id": job.id,
            "source_type": source.source_type.value,
            "source_identifier": source.identifier,
        })

        try:
            # Step 1: ACQUIRE - Fetch content from source
            acquired_content = self._acquire_content(source)
            if not acquired_content:
                return self._complete_job(job, AcquisitionStatus.FAILED,
                                          errors=["No content acquired from source"],
                                          start_time=start_time)

            # Step 2: EXTRACT - Extract knowledge objects
            extraction_result = self._extract_knowledge(acquired_content, source, job)
            if not extraction_result or not extraction_result.knowledge_objects:
                return self._complete_job(job, AcquisitionStatus.FAILED,
                                          errors=["No knowledge extracted"],
                                          start_time=start_time)
            job.extraction_result = extraction_result.to_dict()
            job.items_extracted = len(extraction_result.knowledge_objects)
            self._stats.total_items_extracted += job.items_extracted

            # Step 3: VALIDATE - Validate extracted knowledge
            validation_results = self._validate_knowledge(extraction_result.knowledge_objects, job)
            job.validation_result = {
                "items_validated": len([r for r in validation_results if r.is_valid]),
                "items_rejected": len([r for r in validation_results if not r.is_valid]),
                "conflicts": sum(len(r.conflicts) for r in validation_results),
                "duplicates": sum(len(r.duplicates) for r in validation_results),
            }
            job.items_validated = sum(1 for r in validation_results if r.is_valid)
            self._stats.total_items_validated += job.items_validated

            # Step 4: STORE - Store validated items
            storage_result = self._store_knowledge(extraction_result.knowledge_objects, validation_results, job)
            job.storage_result = storage_result
            job.items_stored = storage_result.get("stored", 0)
            job.items_skipped = storage_result.get("skipped", 0)
            self._stats.total_items_stored += job.items_stored
            self._stats.total_items_skipped += job.items_skipped

            # Step 5: INDEX - Index for retrieval
            if self.config.auto_index and self.retrieval_pipeline:
                indexing_result = self._index_knowledge(storage_result.get("stored_ids", []), job)
                job.indexing_result = indexing_result
                job.items_indexed = indexing_result.get("indexed", 0)
                self._stats.total_items_indexed += job.items_indexed

            # Determine final status
            if job.items_stored == 0 and job.items_skipped == 0:
                status = AcquisitionStatus.FAILED
            elif job.items_stored == job.items_extracted:
                status = AcquisitionStatus.COMPLETED
            else:
                status = AcquisitionStatus.PARTIAL

            return self._complete_job(job, status, start_time=start_time)

        except Exception as e:
            logger.error(f"[KnowledgeAcquisitionPipeline] Job {job.id} failed: {e}")
            return self._complete_job(job, AcquisitionStatus.FAILED,
                                      errors=[f"Pipeline error: {str(e)}"],
                                      start_time=start_time)

    def _create_source_from_string(self, identifier: str) -> AcquisitionSource:
        """Create AcquisitionSource from string identifier."""
        identifier_lower = identifier.lower()

        # URL detection
        if identifier_lower.startswith(("http://", "https://")):
            if "stackoverflow.com" in identifier_lower:
                source_type = AcquisitionSourceType.STACKOVERFLOW
            elif "github.com" in identifier_lower:
                source_type = AcquisitionSourceType.GITHUB_REPOSITORY
            elif any(d in identifier_lower for d in ["docs.", "documentation", "readthedocs", "pkg.go.dev", "docs.rs", "pypi.org"]):
                source_type = AcquisitionSourceType.WEB_DOCUMENTATION
            elif "rfc-editor.org" in identifier_lower or "w3.org" in identifier_lower or "ecma-international.org" in identifier_lower:
                source_type = AcquisitionSourceType.STANDARDS_BODY
            else:
                source_type = AcquisitionSourceType.WEB_DOCUMENTATION
        # Package references (python:requests, npm:lodash, etc.)
        elif ":" in identifier and identifier.split(":")[0] in ("python", "npm", "pypi", "rust", "crates", "go"):
            source_type = AcquisitionSourceType.PACKAGE_DOCUMENTATION
        # File paths
        elif "/" in identifier or "\\" in identifier or identifier.endswith((".md", ".txt", ".rst", ".py", ".json", ".yaml", ".toml")):
            from pathlib import Path
            path = Path(identifier)
            if path.is_dir():
                source_type = AcquisitionSourceType.DIRECTORY
            else:
                source_type = AcquisitionSourceType.FILE
        # Internal sources
        elif identifier_lower.startswith(("conv_", "chat_", "msg_")):
            source_type = AcquisitionSourceType.CONVERSATION_HISTORY
        else:
            # Default to internet research query
            source_type = AcquisitionSourceType.INTERNET_RESEARCH

        return AcquisitionSource(
            source_type=source_type,
            identifier=identifier,
            name=identifier,
        )

    def _acquire_content(self, source: AcquisitionSource) -> List[Dict[str, Any]]:
        """Fetch raw content from the source."""
        content_items = []

        if source.source_type == AcquisitionSourceType.FILE:
            content_items = self._acquire_from_file(source)
        elif source.source_type == AcquisitionSourceType.DIRECTORY:
            content_items = self._acquire_from_directory(source)
        elif source.source_type == AcquisitionSourceType.WEB_DOCUMENTATION:
            content_items = asyncio.run(self._acquire_from_web_doc(source))
        elif source.source_type == AcquisitionSourceType.PACKAGE_DOCUMENTATION:
            content_items = asyncio.run(self._acquire_from_package_docs(source))
        elif source.source_type == AcquisitionSourceType.INTERNET_RESEARCH:
            content_items = asyncio.run(self._acquire_from_internet_research(source))
        elif source.source_type == AcquisitionSourceType.STACKOVERFLOW:
            content_items = asyncio.run(self._acquire_from_stackoverflow(source))
        elif source.source_type == AcquisitionSourceType.GITHUB_REPOSITORY:
            content_items = asyncio.run(self._acquire_from_github_repo(source))
        elif source.source_type == AcquisitionSourceType.STANDARDS_BODY:
            content_items = asyncio.run(self._acquire_from_standards_body(source))
        elif source.source_type == AcquisitionSourceType.CONVERSATION_HISTORY:
            content_items = self._acquire_from_conversation(source)
        else:
            logger.warning(f"[KnowledgeAcquisitionPipeline] Unsupported source type: {source.source_type}")

        logger.info(f"[KnowledgeAcquisitionPipeline] Acquired {len(content_items)} content items from {source.identifier}")
        return content_items

    def _acquire_from_file(self, source: AcquisitionSource) -> List[Dict[str, Any]]:
        """Acquire content from a single file."""
        from pathlib import Path

        path = Path(source.identifier)
        if not path.exists():
            logger.warning(f"[KnowledgeAcquisitionPipeline] File not found: {path}")
            return []

        # Check file size
        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb > self.config.max_file_size_mb:
            logger.warning(f"[KnowledgeAcquisitionPipeline] File too large ({size_mb:.1f}MB): {path}")
            return []

        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                content = path.read_bytes().decode('utf-8', errors='replace')
            except Exception as e:
                logger.warning(f"[KnowledgeAcquisitionPipeline] Cannot read file {path}: {e}")
                return []

        return [{
            "content": content,
            "source": str(path),
            "source_type": SourceType.DOCUMENTATION if path.suffix in (".md", ".rst", ".txt") else SourceType.SOURCE_CODE,
            "metadata": {"file_path": str(path), "file_size": path.stat().st_size}
        }]

    def _acquire_from_directory(self, source: AcquisitionSource) -> List[Dict[str, Any]]:
        """Acquire content from all files in a directory."""
        from pathlib import Path

        path = Path(source.identifier)
        if not path.exists() or not path.is_dir():
            logger.warning(f"[KnowledgeAcquisitionPipeline] Directory not found: {path}")
            return []

        content_items = []
        extensions = {".md", ".markdown", ".txt", ".rst", ".py", ".js", ".ts", ".java", ".cpp", ".cs", ".go", ".rs", ".json", ".yaml", ".yml", ".toml"}

        for file_path in path.rglob("*"):
            if file_path.is_file() and file_path.suffix in extensions:
                if file_path.stat().st_size > self.config.max_file_size_mb * 1024 * 1024:
                    continue
                try:
                    content = file_path.read_text(encoding="utf-8")
                    source_type = SourceType.DOCUMENTATION if file_path.suffix in (".md", ".rst", ".txt") else SourceType.SOURCE_CODE
                    content_items.append({
                        "content": content,
                        "source": str(file_path),
                        "source_type": source_type,
                        "metadata": {"file_path": str(file_path), "directory": source.identifier}
                    })
                except Exception as e:
                    logger.debug(f"[KnowledgeAcquisitionPipeline] Failed to read {file_path}: {e}")

        return content_items

    async def _acquire_from_web_doc(self, source: AcquisitionSource) -> List[Dict[str, Any]]:
        """Acquire content from web documentation."""
        result = await self.external_importer.docs_importer.import_from_url(source.identifier)
        if not result.success:
            return []

        return [{
            "content": item.content,
            "source": item.source_uri or source.identifier,
            "source_type": SourceType.DOCUMENTATION,
            "metadata": {
                "title": item.title,
                "tags": item.tags,
                "domain": item.domain.value,
                "knowledge_type": item.knowledge_type.value,
                "url": source.identifier,
            }
        } for item in result.items]

    async def _acquire_from_package_docs(self, source: AcquisitionSource) -> List[Dict[str, Any]]:
        """Acquire documentation for a package (python:package, npm:package, etc.)."""
        parts = source.identifier.split(":", 1)
        if len(parts) != 2:
            return []

        lang, pkg = parts
        result = await self.external_importer.docs_importer.import_package_docs(pkg, lang)
        if not result.success:
            return []

        return [{
            "content": item.content,
            "source": item.source_uri or source.identifier,
            "source_type": SourceType.DOCUMENTATION,
            "metadata": {
                "title": item.title,
                "tags": item.tags,
                "domain": item.domain.value,
                "knowledge_type": item.knowledge_type.value,
                "package": pkg,
                "language": lang,
            }
        } for item in result.items]

    async def _acquire_from_internet_research(self, source: AcquisitionSource) -> List[Dict[str, Any]]:
        """Acquire knowledge from internet research (search query)."""
        result = await self.external_importer.research_importer.search_and_import(
            source.identifier,
            max_results=self.config.external_max_results
        )
        if not result.success:
            return []

        return [{
            "content": item.content,
            "source": item.source_uri or source.identifier,
            "source_type": SourceType.DOCUMENTATION,
            "metadata": {
                "title": item.title,
                "tags": item.tags,
                "domain": item.domain.value,
                "knowledge_type": item.knowledge_type.value,
                "query": source.identifier,
            }
        } for item in result.items]

    async def _acquire_from_stackoverflow(self, source: AcquisitionSource) -> List[Dict[str, Any]]:
        """Acquire knowledge from StackOverflow question."""
        # Extract question ID from URL
        import re
        match = re.search(r"stackoverflow\.com/questions/(\d+)", source.identifier)
        if not match:
            return []

        question_id = match.group(1)
        result = await self.external_importer.research_importer.import_from_stackoverflow(question_id)
        if not result.success:
            return []

        return [{
            "content": item.content,
            "source": item.source_uri or source.identifier,
            "source_type": SourceType.DOCUMENTATION,
            "metadata": {
                "title": item.title,
                "tags": item.tags,
                "domain": item.domain.value,
                "knowledge_type": item.knowledge_type.value,
                "question_id": question_id,
            }
        } for item in result.items]

    async def _acquire_from_github_repo(self, source: AcquisitionSource) -> List[Dict[str, Any]]:
        """Acquire knowledge from GitHub repository (README, docs)."""
        result = await self.external_importer.research_importer.import_from_github_repo(source.identifier)
        if not result.success:
            return []

        return [{
            "content": item.content,
            "source": item.source_uri or source.identifier,
            "source_type": SourceType.DOCUMENTATION,
            "metadata": {
                "title": item.title,
                "tags": item.tags,
                "domain": item.domain.value,
                "knowledge_type": item.knowledge_type.value,
                "repo_url": source.identifier,
            }
        } for item in result.items]

    async def _acquire_from_standards_body(self, source: AcquisitionSource) -> List[Dict[str, Any]]:
        """Acquire knowledge from standards bodies (RFC, ISO, W3C, ECMA)."""
        # Parse identifier like "rfc:1234" or "w3c:html5"
        parts = source.identifier.split(":", 1)
        if len(parts) != 2:
            return []

        body, identifier = parts
        result = await self.external_importer.docs_importer.import_from_standards_body(body, identifier)
        if not result.success:
            return []

        return [{
            "content": item.content,
            "source": item.source_uri or source.identifier,
            "source_type": SourceType.DOCUMENTATION,
            "metadata": {
                "title": item.title,
                "tags": item.tags,
                "domain": item.domain.value,
                "knowledge_type": item.knowledge_type.value,
                "standards_body": body,
                "identifier": identifier,
            }
        } for item in result.items]

    def _acquire_from_conversation(self, source: AcquisitionSource) -> List[Dict[str, Any]]:
        """Acquire knowledge from conversation history (placeholder for integration)."""
        # This would integrate with conversation_memory to extract knowledge
        # For now, return empty - would be implemented with actual memory integration
        logger.debug(f"[KnowledgeAcquisitionPipeline] Conversation acquisition not yet implemented: {source.identifier}")
        return []

    def _extract_knowledge(
        self,
        content_items: List[Dict[str, Any]],
        source: AcquisitionSource,
        job: AcquisitionJob
    ) -> KnowledgeExtractionResult:
        """Extract knowledge objects from acquired content."""
        job.status = AcquisitionStatus.EXTRACTING
        self._publish_event("knowledge.acquisition.extracting", {
            "job_id": job.id,
            "content_items": len(content_items),
        })

        # Batch extract
        results = self.extraction_pipeline.extract_batch(content_items)
        # Combine results
        all_objects = []
        for result in results:
            if result.success:
                all_objects.extend(result.knowledge_objects)

        # Create combined result
        combined_result = KnowledgeExtractionResult(
            success=len(all_objects) > 0,
            knowledge_objects=all_objects,
            source=source.identifier,
            source_type=content_items[0].get("source_type", SourceType.UNKNOWN) if content_items else SourceType.UNKNOWN,
            metadata={"job_id": job.id, "source_type": source.source_type.value},
        )

        self._publish_event("knowledge.acquisition.extracted", {
            "job_id": job.id,
            "objects_extracted": len(all_objects),
        })

        return combined_result

    def _validate_knowledge(
        self,
        knowledge_objects: List[KnowledgeObject],
        job: AcquisitionJob
    ) -> List[ValidationStatus]:
        """Validate extracted knowledge objects."""
        job.status = AcquisitionStatus.VALIDATING
        self._publish_event("knowledge.acquisition.validating", {
            "job_id": job.id,
            "objects_to_validate": len(knowledge_objects),
        })

        # Convert KnowledgeObjects to EngineeringKnowledgeItems for validation
        eng_items = []
        for obj in knowledge_objects:
            # Map source type
            source_map = {
                SourceType.DOCUMENTATION: KnowledgeSource.EXTERNAL_DOCS,
                SourceType.SOURCE_CODE: KnowledgeSource.PROJECT_CODE,
                SourceType.LLM_RESPONSE: KnowledgeSource.LLM_TRAINING,
                SourceType.UNKNOWN: KnowledgeSource.UNKNOWN,
            }
            eng_item = EngineeringKnowledgeItem(
                title=obj.title,
                summary=obj.summary,
                content=obj.content,
                domain=self._infer_domain(obj),
                sub_category="acquired",
                knowledge_type=self._map_category(obj.category),
                source=source_map.get(obj.source_type, KnowledgeSource.EXTERNAL_DOCS),
                source_uri=obj.source,
                source_metadata=obj.metadata,
                tags=obj.tags,
                language=obj.language,
                confidence=obj.confidence,
                validation_status=EngValidationStatus.PENDING,
            )
            eng_items.append(eng_item)

        # Validate batch
        validation_results = self.validator.validate_batch(eng_items)

        self._publish_event("knowledge.acquisition.validated", {
            "job_id": job.id,
            "validated": sum(1 for r in validation_results if r.is_valid),
            "rejected": sum(1 for r in validation_results if not r.is_valid),
        })

        return validation_results

    def _store_knowledge(
        self,
        knowledge_objects: List[KnowledgeObject],
        validation_results: List[ValidationStatus],
        job: AcquisitionJob
    ) -> Dict[str, Any]:
        """Store validated knowledge items."""
        job.status = AcquisitionStatus.STORING
        self._publish_event("knowledge.acquisition.storing", {
            "job_id": job.id,
        })

        stored_ids = []
        skipped = 0

        for obj, val_result in zip(knowledge_objects, validation_results):
            if not val_result.is_valid:
                # Check if we should still store (pending review)
                if val_result.validation_status == EngValidationStatus.PENDING and obj.confidence >= self.config.store_pending_threshold:
                    pass  # Will store with PENDING status
                else:
                    skipped += 1
                    self._stats.error_distribution[f"validation_{val_result.validation_status.value}"] = \
                        self._stats.error_distribution.get(f"validation_{val_result.validation_status.value}", 0) + 1
                    continue

            # Convert to EngineeringKnowledgeItem
            source_map = {
                SourceType.DOCUMENTATION: KnowledgeSource.EXTERNAL_DOCS,
                SourceType.SOURCE_CODE: KnowledgeSource.PROJECT_CODE,
                SourceType.LLM_RESPONSE: KnowledgeSource.LLM_TRAINING,
                SourceType.UNKNOWN: KnowledgeSource.UNKNOWN,
            }
            eng_item = EngineeringKnowledgeItem(
                title=obj.title,
                summary=obj.summary,
                content=obj.content,
                domain=self._infer_domain(obj),
                sub_category="acquired",
                knowledge_type=self._map_category(obj.category),
                source=source_map.get(obj.source_type, KnowledgeSource.EXTERNAL_DOCS),
                source_uri=obj.source,
                source_metadata={
                    **obj.metadata,
                    "acquisition_job_id": job.id,
                    "acquisition_source_type": job.source.source_type.value,
                    "validation_status": val_result.validation_status.value,
                    "validation_confidence": val_result.confidence,
                    "validation_conflicts": val_result.conflicts,
                    "validation_duplicates": val_result.duplicates,
                },
                tags=obj.tags + ["acquired"],
                language=obj.language,
                confidence=val_result.confidence,
                validation_status=val_result.validation_status,
            )

            try:
                item_id = self.storage.create(eng_item)
                stored_ids.append(item_id.id)
            except Exception as e:
                logger.warning(f"[KnowledgeAcquisitionPipeline] Failed to store item: {e}")
                skipped += 1

        self._publish_event("knowledge.acquisition.stored", {
            "job_id": job.id,
            "stored": len(stored_ids),
            "skipped": skipped,
        })

        return {"stored": len(stored_ids), "skipped": skipped, "stored_ids": stored_ids}

    def _index_knowledge(self, stored_ids: List[str], job: AcquisitionJob) -> Dict[str, Any]:
        """Index stored knowledge for retrieval."""
        if not self.retrieval_pipeline or not stored_ids:
            return {"indexed": 0}

        job.status = AcquisitionStatus.INDEXING
        self._publish_event("knowledge.acquisition.indexing", {
            "job_id": job.id,
            "items_to_index": len(stored_ids),
        })

        # The retrieval pipeline uses adapters that automatically pick up new items
        # from the storage. We just need to ensure the adapters are refreshed.
        # For now, we'll trigger a refresh if the adapter supports it.
        indexed = 0
        for adapter in self.retrieval_pipeline._adapters:
            if hasattr(adapter, 'refresh') and callable(adapter.refresh):
                try:
                    adapter.refresh()
                    indexed += 1
                except Exception as e:
                    logger.debug(f"[KnowledgeAcquisitionPipeline] Adapter refresh failed: {e}")

        self._publish_event("knowledge.acquisition.indexed", {
            "job_id": job.id,
            "indexed": indexed,
        })

        return {"indexed": indexed}

    def _complete_job(
        self,
        job: AcquisitionJob,
        status: AcquisitionStatus,
        errors: Optional[List[str]] = None,
        warnings: Optional[List[str]] = None,
        start_time: Optional[float] = None
    ) -> AcquisitionResult:
        """Complete a job and return result."""
        job.status = status
        job.completed_at = datetime.now(timezone.utc).isoformat()

        if start_time:
            job.total_time = time.time() - start_time
            # Update average
            n = self._stats.total_jobs
            self._stats.avg_job_time = (
                (self._stats.avg_job_time * (n - 1) + job.total_time) / n
            )

        if errors:
            job.errors.extend(errors)
            for err in errors:
                self._stats.error_distribution[err] = self._stats.error_distribution.get(err, 0) + 1

        if warnings:
            job.warnings = warnings or []

        # Update stats
        if status == AcquisitionStatus.COMPLETED:
            self._stats.completed_jobs += 1
            self._stats.total_items_acquired += job.items_stored
        elif status == AcquisitionStatus.PARTIAL:
            self._stats.partial_jobs += 1
            self._stats.total_items_acquired += job.items_stored
        else:
            self._stats.failed_jobs += 1

        # Source type distribution
        src_type = job.source.source_type.value
        self._stats.source_type_distribution[src_type] = self._stats.source_type_distribution.get(src_type, 0) + 1

        # Publish completion event
        self._publish_event("knowledge.acquisition.completed", {
            "job_id": job.id,
            "status": status.value,
            "items_stored": job.items_stored,
            "items_skipped": job.items_skipped,
            "total_time": job.total_time,
        })

        # Build result
        result = AcquisitionResult(
            job_id=job.id,
            success=status in (AcquisitionStatus.COMPLETED, AcquisitionStatus.PARTIAL),
            items_acquired=[
                {"id": item_id, "status": "stored"}
                for item_id in job.storage_result.get("stored_ids", []) if job.storage_result
            ],
            items_failed=[
                {"error": err}
                for err in job.errors
            ],
            errors=job.errors,
            warnings=job.warnings or [],
            extraction_time=0.0,  # Would track separately if needed
            validation_time=0.0,
            storage_time=0.0,
            indexing_time=0.0,
            total_time=job.total_time,
            metadata={
                "source_type": job.source.source_type.value,
                "source_identifier": job.source.identifier,
                "items_extracted": job.items_extracted,
                "items_validated": job.items_validated,
            }
        )

        # Clean up
        del self._active_jobs[job.id]

        logger.info(f"[KnowledgeAcquisitionPipeline] Job {job.id} completed: {status.value} ({job.items_stored} stored, {job.items_skipped} skipped)")

        return result

    def _infer_domain(self, obj: KnowledgeObject) -> EngineeringDomain:
        """Infer engineering domain from knowledge object."""
        # Check tags for hints
        tags_lower = [t.lower() for t in obj.tags]

        domain_keywords = {
            EngineeringDomain.PROGRAMMING_LANGUAGES: ["python", "javascript", "typescript", "rust", "go", "java", "c++", "c#"],
            EngineeringDomain.WEB_DEVELOPMENT: ["react", "vue", "angular", "html", "css", "dom", "browser"],
            EngineeringDomain.CLOUD: ["aws", "azure", "gcp", "cloud", "lambda", "kubernetes", "docker"],
            EngineeringDomain.DEVOPS: ["ci/cd", "jenkins", "gitlab", "github actions", "terraform", "ansible"],
            EngineeringDomain.DATABASES: ["sql", "postgresql", "mysql", "mongodb", "redis", "database"],
            EngineeringDomain.SECURITY: ["security", "auth", "oauth", "encryption", "vulnerability"],
            EngineeringDomain.TESTING: ["test", "pytest", "jest", "testing", "tdd"],
            EngineeringDomain.AI_ENGINEERING: ["ml", "ai", "machine learning", "neural", "llm", "transformer"],
            EngineeringDomain.SOFTWARE_ARCHITECTURE: ["architecture", "microservices", "monolith", "pattern"],
            EngineeringDomain.DESIGN_PATTERNS: ["singleton", "factory", "observer", "strategy", "decorator", "pattern"],
        }

        for domain, keywords in domain_keywords.items():
            if any(kw in tags_lower for kw in keywords):
                return domain

        # Check content for keywords
        content_lower = (obj.content + " " + obj.title + " " + obj.summary).lower()
        for domain, keywords in domain_keywords.items():
            if any(kw in content_lower for kw in keywords):
                return domain

        return EngineeringDomain.LIBRARIES

    def _map_category(self, category) -> EngineeringKnowledgeType:
        """Map KnowledgeCategory to EngineeringKnowledgeType."""
        # Simple mapping based on category name
        category_map = {
            "fact": EngineeringKnowledgeType.FACT,
            "explanation": EngineeringKnowledgeType.EXPLANATION,
            "procedure": EngineeringKnowledgeType.PROCEDURE,
            "algorithm": EngineeringKnowledgeType.ALGORITHM,
            "best_practice": EngineeringKnowledgeType.BEST_PRACTICE,
            "recommendation": EngineeringKnowledgeType.RECOMMENDATION,
            "workflow": EngineeringKnowledgeType.WORKFLOW,
            "troubleshooting": EngineeringKnowledgeType.TROUBLESHOOTING,
            "concept": EngineeringKnowledgeType.CONCEPT,
            "definition": EngineeringKnowledgeType.DEFINITION,
            "example": EngineeringKnowledgeType.EXAMPLE,
            "warning": EngineeringKnowledgeType.WARNING,
            "reference": EngineeringKnowledgeType.REFERENCE,
            "architecture": EngineeringKnowledgeType.ARCHITECTURE,
        }

        cat_value = category.value if hasattr(category, 'value') else str(category)
        return category_map.get(cat_value, EngineeringKnowledgeType.REFERENCE)

    def acquire_batch(
        self,
        sources: List[Union[AcquisitionSource, str]],
        **kwargs
    ) -> List[AcquisitionResult]:
        """Acquire knowledge from multiple sources in batch."""
        results = []
        for source in sources:
            result = self.acquire(source, **kwargs)
            results.append(result)
        return results

    def schedule_recurring_acquisition(
        self,
        source: Union[AcquisitionSource, str],
        interval_hours: int = 24,
        job_id: Optional[str] = None
    ) -> str:
        """Schedule recurring knowledge acquisition from a source."""
        if isinstance(source, str):
            source = self._create_source_from_string(source)

        job_id = job_id or f"acquire_{source.source_type.value}_{source.identifier.replace('/', '_').replace('.', '_')}"
        job_id = job_id[:64]  # Limit length

        def acquisition_job():
            self.acquire(source)

        self.job_service.schedule(
            job_id=job_id,
            func=acquisition_job,
            trigger=JobTriggerConfig(
                type=JobTriggerType.RECURRING,
                interval_seconds=interval_hours * 3600
            ),
            priority=JobPriority.LOW,
            max_retries=3,
            replace_existing=True,
        )

        logger.info(f"[KnowledgeAcquisitionPipeline] Scheduled recurring acquisition: {job_id} (every {interval_hours}h)")
        return job_id

    def setup_file_watch_triggers(self, watcher) -> None:
        """Set up automatic acquisition triggers from file watcher events."""
        if not self.config.auto_trigger_on_file_watch:
            return

        def on_file_created(event):
            path = event.data.get("path", "")
            if path.endswith((".md", ".rst", ".txt", ".py", ".json", ".yaml", ".toml")):
                self.acquire(path)

        def on_file_modified(event):
            path = event.data.get("path", "")
            if path.endswith((".md", ".rst", ".txt", ".py", ".json", ".yaml", ".toml")):
                self.acquire(path)

        self.event_bus.subscribe("file.created", on_file_created)
        self.event_bus.subscribe("file.modified", on_file_modified)
        logger.info("[KnowledgeAcquisitionPipeline] File watch triggers configured")

    def get_stats(self) -> Dict[str, Any]:
        """Get pipeline statistics."""
        stats = self._stats.to_dict()
        stats["active_jobs"] = len(self._active_jobs)
        stats["extraction_stats"] = self.extraction_pipeline.get_stats()
        stats["validator_stats"] = self.validator.get_validation_stats()
        # Storage stats - basic count
        stats["storage_stats"] = {
            "total_items": len(self.storage._items) if hasattr(self.storage, '_items') else 0,
        }
        return stats

    def reset_stats(self) -> None:
        """Reset pipeline statistics."""
        self._stats = PipelineStats()
        self.extraction_pipeline.reset_stats()

    async def close(self) -> None:
        """Close external connections."""
        await self.external_importer.close()


def create_acquisition_pipeline(
    config: Optional[KnowledgeAcquisitionConfig] = None,
    storage_path: Optional[Path] = None,
    agent=None,  # Optional Freya agent for retrieval adapters
) -> KnowledgeAcquisitionPipeline:
    """Factory function to create a fully configured acquisition pipeline.

    Args:
        config: Optional custom configuration
        storage_path: Optional storage path (uses config if not provided)
        agent: Optional Freya agent to create retrieval adapters from

    Returns:
        Configured KnowledgeAcquisitionPipeline
    """
    # Create retrieval pipeline with adapters if agent provided
    retrieval_pipeline = None
    if agent:
        from app.knowledge_retrieval import create_pipeline_from_agent
        retrieval_pipeline = create_pipeline_from_agent(agent)

    return KnowledgeAcquisitionPipeline(
        config=config,
        storage_path=storage_path,
        retrieval_pipeline=retrieval_pipeline,
    )