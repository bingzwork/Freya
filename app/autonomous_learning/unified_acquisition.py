"""Unified Knowledge Acquisition Pipeline for Freya.

This module provides a single orchestration layer that combines:
1. Internal autonomous learning (from experiences, task execution)
2. External knowledge acquisition (documentation, web research)
3. Knowledge validation and consolidation
4. Continuous knowledge base maintenance

The pipeline unifies all knowledge acquisition sources into a coherent workflow.
"""

import asyncio
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Callable, Set
from pathlib import Path

from app.core.logger import logger
from app.core.events import EventBus, Event, EventPriority

# Internal learning components
from app.autonomous_learning import (
    AutonomousLearningPipeline,
    KnowledgeGapDetector,
    AutonomousResearchLoop,
    AutonomousLearningScheduler,
    AutonomousLearningConfig,
    LearningPipelineResult,
    KnowledgeGap,
)
from app.autonomous_learning.pipeline import AutonomousLearningPipeline as InternalPipeline
from app.memory.experience_memory import ExperienceMemory
from app.memory.engineering_lessons import EngineeringLessonStorage
from app.memory.long_term_memory import LongTermMemory
from app.memory.semantic_memory import SemanticMemory
from app.memory.validation import KnowledgeValidator

# External knowledge components
from app.software_engineering_knowledge.external_import import (
    ExternalKnowledgeImporter,
    EXTERNAL_SOURCES,
    ExternalSource,
    ExtractionResult,
)
from app.software_engineering_knowledge.consolidation import (
    ConsolidationEngine,
    ConsolidationConfig,
    create_consolidation_engine,
)
from app.software_engineering_knowledge.storage import get_knowledge_storage
from app.software_engineering_knowledge.models import (
    EngineeringKnowledgeItem,
    EngineeringDomain,
    KnowledgeSource,
)


# Also import for experience-based extraction
from app.knowledge_extraction.pipeline import KnowledgeExtractionPipeline
from app.knowledge_extraction.models import KnowledgeObject, KnowledgeCategory, SourceType
from app.memory.validation import ValidationSourceType


class AcquisitionMode(Enum):
    """Modes of knowledge acquisition."""
    INTERNAL_ONLY = "internal_only"      # Only from experiences
    EXTERNAL_ONLY = "external_only"      # Only from external sources
    UNIFIED = "unified"                  # Both internal and external
    REACTIVE = "reactive"                # Triggered by queries/gaps


class AcquisitionPriority(Enum):
    """Priority levels for acquisition tasks."""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class AcquisitionTask:
    """A knowledge acquisition task."""
    id: str = field(default_factory=lambda: f"acq_{int(time.time() * 1000)}")
    query: str = ""
    mode: AcquisitionMode = AcquisitionMode.UNIFIED
    priority: AcquisitionPriority = AcquisitionPriority.NORMAL
    sources: List[str] = field(default_factory=list)  # Specific external sources to use
    domains: List[EngineeringDomain] = field(default_factory=list)  # Target domains
    max_results: int = 10
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str = "pending"


@dataclass
class AcquisitionResult:
    """Result of a knowledge acquisition operation."""
    task_id: str
    success: bool
    items_acquired: int = 0
    items_validated: int = 0
    items_stored: int = 0
    items_merged: int = 0
    gaps_addressed: int = 0
    research_tasks_completed: int = 0
    duration_seconds: float = 0.0
    errors: List[str] = field(default_factory=list)
    sources_used: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class UnifiedAcquisitionConfig:
    """Configuration for the unified knowledge acquisition pipeline."""
    # Internal learning
    internal_learning_enabled: bool = True
    internal_learning_interval_hours: float = 6.0

    # External acquisition
    external_acquisition_enabled: bool = True
    external_sources: List[str] = field(default_factory=lambda: [
        "python_docs", "mdn", "rust_docs", "go_docs",
        "kubernetes_docs", "terraform_docs",
    ])
    external_acquisition_interval_hours: float = 24.0

    # Consolidation
    consolidation_enabled: bool = True
    consolidation_interval_hours: float = 12.0
    auto_merge_threshold: float = 0.95

    # Validation
    validation_enabled: bool = True
    min_confidence_threshold: float = 0.6

    # Event-driven
    event_driven_enabled: bool = True
    subscribe_to_patterns: List[str] = field(default_factory=lambda: [
        "task.completed",
        "task.failed",
        "goal.completed",
        "file.modified",
    ])

    # Scheduling
    run_on_startup: bool = True
    max_concurrent_tasks: int = 3


class UnifiedKnowledgeAcquisitionPipeline:
    """
    Unified pipeline for all knowledge acquisition activities.

    This pipeline orchestrates:
    1. Internal learning from experiences (AutonomousLearningPipeline)
    2. External knowledge acquisition from documentation/web (ExternalKnowledgeImporter)
    3. Knowledge validation and consolidation (KnowledgeValidator, ConsolidationEngine)
    4. Event-driven reactive acquisition
    5. Scheduled periodic acquisition runs
    """

    def __init__(
        self,
        # Memory systems (required for internal learning)
        experience_memory: ExperienceMemory,
        engineering_lessons: EngineeringLessonStorage,
        long_term_memory: LongTermMemory,
        semantic_memory: SemanticMemory,
        knowledge_validator: KnowledgeValidator,
        # Optional external components
        external_importer: Optional[ExternalKnowledgeImporter] = None,
        consolidation_engine: Optional[ConsolidationEngine] = None,
        external_sources: Optional[List[ExternalSource]] = None,
        # Event bus for event-driven acquisition
        event_bus: Optional[EventBus] = None,
        # Configuration
        config: Optional[UnifiedAcquisitionConfig] = None,
        # Scheduler (optional)
        scheduler: Optional[AutonomousLearningScheduler] = None,
    ):
        """Initialize the unified knowledge acquisition pipeline.

        Args:
            experience_memory: Experience memory storage
            engineering_lessons: Engineering lessons storage
            long_term_memory: Long-term memory storage
            semantic_memory: Semantic memory storage
            knowledge_validator: Knowledge validator
            external_importer: External knowledge importer (created if None)
            consolidation_engine: Consolidation engine (created if None)
            external_sources: List of external sources to use (uses defaults if None)
            event_bus: Event bus for reactive acquisition
            config: Pipeline configuration
            scheduler: Learning scheduler (created if None)
        """
        # Core memory systems
        self.experience_memory = experience_memory
        self.engineering_lessons = engineering_lessons
        self.long_term_memory = long_term_memory
        self.semantic_memory = semantic_memory
        self.knowledge_validator = knowledge_validator

        # External components
        self.external_importer = external_importer or ExternalKnowledgeImporter()
        self.consolidation_engine = consolidation_engine or create_consolidation_engine()
        self.external_sources = external_sources or list(EXTERNAL_SOURCES.values())
        self.event_bus = event_bus

        # Configuration
        self.config = config or UnifiedAcquisitionConfig()

        # Internal pipelines
        self._internal_pipeline: Optional[AutonomousLearningPipeline] = None
        self._gap_detector: Optional[KnowledgeGapDetector] = None
        self._research_loop: Optional[AutonomousResearchLoop] = None
        self._scheduler: Optional[AutonomousLearningScheduler] = scheduler

        # Knowledge extraction pipeline (shared)
        self._extraction_pipeline = KnowledgeExtractionPipeline()

        # State
        self._lock = threading.RLock()
        self._running = False
        self._acquisition_tasks: Dict[str, AcquisitionTask] = {}
        self._task_history: List[AcquisitionResult] = []
        self._stats = {
            "total_acquisitions": 0,
            "total_items_acquired": 0,
            "total_items_validated": 0,
            "total_items_stored": 0,
            "total_consolidated": 0,
            "last_run_time": None,
            "last_external_run": None,
            "last_consolidation_run": None,
        }

        # Subscriptions
        self._event_subscriptions: List[str] = []

    def initialize(self) -> None:
        """Initialize all sub-components."""
        logger.info("Initializing Unified Knowledge Acquisition Pipeline")

        # Initialize internal learning pipeline
        if self.config.internal_learning_enabled:
            from app.autonomous_learning.gap_detection import KnowledgeGapDetector
            from app.autonomous_learning.research_loop import AutonomousResearchLoop

            self._gap_detector = KnowledgeGapDetector(
                experience_memory=self.experience_memory,
                engineering_lessons=self.engineering_lessons,
                long_term_memory=self.long_term_memory,
                semantic_memory=self.semantic_memory,
            )

            self._research_loop = AutonomousResearchLoop(
                knowledge_extractor=self._extraction_pipeline,
                knowledge_validator=self.knowledge_validator,
                experience_memory=self.experience_memory,
                engineering_lessons=self.engineering_lessons,
                long_term_memory=self.long_term_memory,
                semantic_memory=self.semantic_memory,
                gap_detector=self._gap_detector,
            )

            self._internal_pipeline = AutonomousLearningPipeline(
                experience_memory=self.experience_memory,
                engineering_lessons=self.engineering_lessons,
                long_term_memory=self.long_term_memory,
                semantic_memory=self.semantic_memory,
                knowledge_validator=self.knowledge_validator,
                knowledge_extraction_pipeline=self._extraction_pipeline,
                gap_detector=self._gap_detector,
                research_loop=self._research_loop,
            )

        # Initialize scheduler
        if self._scheduler is None:
            self._scheduler = AutonomousLearningScheduler(
                pipeline=self._internal_pipeline,
                config=self._create_scheduler_config(),
            )

        # Subscribe to events if enabled
        if self.config.event_driven_enabled and self.event_bus:
            self._subscribe_to_events()

        logger.info("Unified Knowledge Acquisition Pipeline initialized")

    def _create_scheduler_config(self) -> AutonomousLearningConfig:
        """Create scheduler config from unified config."""
        return AutonomousLearningConfig(
            enabled=self.config.internal_learning_enabled,
            run_interval_minutes=int(self.config.internal_learning_interval_hours * 60),
            max_concurrent_research=self.config.max_concurrent_tasks,
        )

    def _subscribe_to_events(self) -> None:
        """Subscribe to relevant events for reactive acquisition."""
        if not self.event_bus:
            return

        for pattern in self.config.subscribe_to_patterns:
            sub_id = self.event_bus.subscribe(
                pattern,
                self._handle_event,
                priority=10,
                async_mode=True,
            )
            self._event_subscriptions.append(sub_id)
            logger.debug(f"Subscribed to '{pattern}' for reactive acquisition")

    def _handle_event(self, event: Event) -> None:
        """Handle incoming events by triggering relevant acquisition."""
        try:
            # Extract relevant information from event
            event_data = event.data if isinstance(event.data, dict) else {}

            # Create acquisition task based on event
            task = AcquisitionTask(
                query=event_data.get("query", "") or event_data.get("task", "") or event.name,
                mode=AcquisitionMode.REACTIVE,
                priority=AcquisitionPriority.HIGH if event.priority == EventPriority.CRITICAL else AcquisitionPriority.NORMAL,
                metadata={
                    "trigger_event": event.name,
                    "trigger_source": event.source,
                    "trigger_data": event_data,
                },
                tags=["reactive", event.name.replace(".", "_")],
            )

            # Add domain hints from event
            if "domain" in event_data:
                task.domains.append(EngineeringDomain(event_data["domain"]))

            # Queue the task
            self._queue_task(task)

        except Exception as e:
            logger.error(f"Error handling event for acquisition: {e}")

    def _queue_task(self, task: AcquisitionTask) -> str:
        """Queue an acquisition task."""
        with self._lock:
            self._acquisition_tasks[task.id] = task
        logger.debug(f"Queued acquisition task: {task.id} ({task.mode.value})")
        return task.id

    def acquire_knowledge(
        self,
        query: str,
        mode: AcquisitionMode = AcquisitionMode.UNIFIED,
        priority: AcquisitionPriority = AcquisitionPriority.NORMAL,
        sources: Optional[List[str]] = None,
        domains: Optional[List[EngineeringDomain]] = None,
        max_results: int = 10,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AcquisitionResult:
        """
        Execute a knowledge acquisition task.

        Args:
            query: The search query or topic
            mode: Acquisition mode (internal, external, unified, reactive)
            priority: Task priority
            sources: Specific external sources to use
            domains: Target engineering domains
            max_results: Maximum results to acquire
            tags: Additional tags
            metadata: Additional metadata

        Returns:
            AcquisitionResult with operation details
        """
        task = AcquisitionTask(
            query=query,
            mode=mode,
            priority=priority,
            sources=sources or [],
            domains=domains or [],
            max_results=max_results,
            tags=tags or [],
            metadata=metadata or {},
        )

        self._queue_task(task)
        return self._execute_task(task)

    def _execute_task(self, task: AcquisitionTask) -> AcquisitionResult:
        """Execute a single acquisition task."""
        start_time = time.time()
        result = AcquisitionResult(task_id=task.id, success=False)

        try:
            logger.info(f"Executing acquisition task: {task.id} - {task.query[:50]}...")

            items_acquired = 0

            # Internal learning
            if task.mode in (AcquisitionMode.INTERNAL_ONLY, AcquisitionMode.UNIFIED, AcquisitionMode.REACTIVE):
                internal_results = self._run_internal_learning(task)
                items_acquired += internal_results.get("items_stored", 0)
                result.gaps_addressed = internal_results.get("gaps_addressed", 0)
                result.research_tasks_completed = internal_results.get("research_tasks", 0)

            # External acquisition
            if task.mode in (AcquisitionMode.EXTERNAL_ONLY, AcquisitionMode.UNIFIED):
                external_results = self._run_external_acquisition(task)
                items_acquired += external_results.get("items_stored", 0)
                result.sources_used.extend(external_results.get("sources_used", []))

            # Consolidation
            if self.config.consolidation_enabled and items_acquired > 0:
                consolidation_results = self._run_consolidation()
                result.items_merged = consolidation_results.get("merged", 0)

            result.success = items_acquired > 0
            result.items_acquired = items_acquired
            result.duration_seconds = time.time() - start_time

            # Update stats
            with self._lock:
                self._stats["total_acquisitions"] += 1
                self._stats["total_items_acquired"] += items_acquired
                self._stats["total_items_stored"] += result.items_stored
                self._stats["total_consolidated"] += result.items_merged
                self._stats["last_run_time"] = datetime.now(timezone.utc).isoformat()
                self._task_history.append(result)

            logger.info(
                f"Acquisition task {task.id} completed in {result.duration_seconds:.2f}s: "
                f"{items_acquired} items, {result.items_validated} validated, "
                f"{result.items_stored} stored, {result.items_merged} merged"
            )

        except Exception as e:
            logger.error(f"Acquisition task {task.id} failed: {e}")
            result.success = False
            result.errors.append(str(e))
            result.duration_seconds = time.time() - start_time

        return result

    def _run_internal_learning(self, task: AcquisitionTask) -> Dict[str, Any]:
        """Run internal autonomous learning pipeline."""
        results = {"items_stored": 0, "gaps_addressed": 0, "research_tasks": 0}

        if not self._internal_pipeline:
            return results

        try:
            # Run the internal pipeline
            pipeline_result = self._internal_pipeline()

            results["items_stored"] = pipeline_result.knowledge_objects_stored
            results["gaps_addressed"] = pipeline_result.gaps_detected
            results["research_tasks"] = pipeline_result.research_tasks_started

            # If we have a specific query, we could also do targeted research
            if task.query and self._research_loop and self._gap_detector:
                # Detect gaps (general detection, not query-specific)
                gaps = self._gap_detector.detect_gaps()
                if gaps:
                    # Filter gaps related to query
                    query_lower = task.query.lower()
                    relevant_gaps = [g for g in gaps if any(kw in g.category.lower() or kw in g.description.lower() for kw in query_lower.split())]
                    if relevant_gaps:
                        research_tasks = self._research_loop.research_knowledge_gaps(relevant_gaps[:3])
                        results["research_tasks"] += len(research_tasks)

        except Exception as e:
            logger.error(f"Internal learning failed: {e}")

        return results

    def _run_external_acquisition(self, task: AcquisitionTask) -> Dict[str, Any]:
        """Run external knowledge acquisition."""
        results = {"items_stored": 0, "sources_used": []}

        if not self.external_importer:
            return results

        try:
            # Determine which sources to use
            sources_to_use = task.sources if task.sources else [s.name for s in self.external_sources]

            # Limit concurrency
            sources_to_use = sources_to_use[:self.config.max_concurrent_tasks]

            # Run async import
            external_results = asyncio.run(self._import_from_multiple_sources(
                sources_to_use, task.query, task.max_results, task.domains
            ))

            results["items_stored"] = external_results.get("items_stored", 0)
            results["sources_used"] = external_results.get("sources_used", [])

            with self._lock:
                self._stats["last_external_run"] = datetime.now(timezone.utc).isoformat()

        except Exception as e:
            logger.error(f"External acquisition failed: {e}")

        return results

    async def _import_from_multiple_sources(
        self,
        source_names: List[str],
        query: str,
        max_results: int,
        domains: List[EngineeringDomain],
    ) -> Dict[str, Any]:
        """Import from multiple external sources concurrently."""
        tasks = []
        for source_name in source_names:
            source = EXTERNAL_SOURCES.get(source_name)
            if source and (not domains or self._domain_matches_source(domains, source)):
                task = self.external_importer.import_from_source(source_name, query, max_results)
                tasks.append((source_name, task))

        if not tasks:
            return {"items_stored": 0, "sources_used": []}

        # Execute all imports concurrently
        import_results = await asyncio.gather(*[t[1] for t in tasks], return_exceptions=True)

        items_stored = 0
        sources_used = []

        storage = get_knowledge_storage()

        for (source_name, _), result in zip(tasks, import_results):
            if isinstance(result, Exception):
                logger.error(f"Import from {source_name} failed: {result}")
                continue

            if not result.success:
                logger.warning(f"Import from {source_name} returned no results: {result.errors}")
                continue

            sources_used.append(source_name)

            # Store items
            for item in result.items:
                # Validate if enabled
                if self.config.validation_enabled:
                    validation = self.knowledge_validator.validate_item(item)
                    if validation.confidence < self.config.min_confidence_threshold:
                        logger.debug(f"Item {item.id} below confidence threshold: {validation.confidence}")
                        continue

                # Store
                storage.add(item)
                items_stored += 1

        return {"items_stored": items_stored, "sources_used": sources_used}

    def _domain_matches_source(self, domains: List[EngineeringDomain], source: ExternalSource) -> bool:
        """Check if an external source matches any of the target domains."""
        domain_map = {
            "python_docs": EngineeringDomain.LANGUAGES,
            "mdn": EngineeringDomain.WEB_DEVELOPMENT,
            "rust_docs": EngineeringDomain.LANGUAGES,
            "go_docs": EngineeringDomain.LANGUAGES,
            "aws_docs": EngineeringDomain.CLOUD,
            "kubernetes_docs": EngineeringDomain.CLOUD,
            "terraform_docs": EngineeringDomain.DEVOPS,
            "rfc_editor": EngineeringDomain.STANDARDS,
        }
        source_domain = domain_map.get(source.name.lower().replace(" ", "_"))
        return source_domain in domains if source_domain else True

    def _run_consolidation(self) -> Dict[str, Any]:
        """Run knowledge consolidation."""
        results = {"merged": 0}

        if not self.consolidation_engine:
            return results

        try:
            consolidation_result = self.consolidation_engine.consolidate()
            results["merged"] = consolidation_result.duplicates_merged

            with self._lock:
                self._stats["total_consolidated"] += results["merged"]
                self._stats["last_consolidation_run"] = datetime.now(timezone.utc).isoformat()

        except Exception as e:
            logger.error(f"Consolidation failed: {e}")

        return results

    def run_full_cycle(self) -> AcquisitionResult:
        """Run a full acquisition cycle (internal + external + consolidation)."""
        task = AcquisitionTask(
            query="full_cycle",
            mode=AcquisitionMode.UNIFIED,
            priority=AcquisitionPriority.NORMAL,
            tags=["scheduled", "full_cycle"],
        )
        self._queue_task(task)
        return self._execute_task(task)

    def start_scheduler(self) -> None:
        """Start the background scheduler."""
        if self._scheduler:
            self._scheduler.start()
            logger.info("Knowledge acquisition scheduler started")

    def stop_scheduler(self) -> None:
        """Stop the background scheduler."""
        if self._scheduler:
            self._scheduler.stop()
            logger.info("Knowledge acquisition scheduler stopped")

    def start(self) -> None:
        """Start the pipeline (initialize and start scheduler)."""
        with self._lock:
            if self._running:
                return

            self.initialize()
            if self.config.run_on_startup:
                self.start_scheduler()

            self._running = True
            logger.info("Unified Knowledge Acquisition Pipeline started")

    def stop(self) -> None:
        """Stop the pipeline."""
        with self._lock:
            if not self._running:
                return

            self.stop_scheduler()

            # Unsubscribe from events
            if self.event_bus:
                for sub_id in self._event_subscriptions:
                    self.event_bus.unsubscribe(sub_id)
                self._event_subscriptions.clear()

            self._running = False
            logger.info("Unified Knowledge Acquisition Pipeline stopped")

    def get_stats(self) -> Dict[str, Any]:
        """Get pipeline statistics."""
        with self._lock:
            stats = dict(self._stats)
            stats["pending_tasks"] = len(self._acquisition_tasks)
            stats["history_size"] = len(self._task_history)
            stats["running"] = self._running

            # Add sub-component stats
            if self._internal_pipeline:
                stats["internal_pipeline"] = {
                    "experiences_processed": self._internal_pipeline.stats.experiences_processed,
                    "knowledge_extracted": self._internal_pipeline.stats.knowledge_objects_extracted,
                    "gaps_detected": self._internal_pipeline.stats.gaps_detected,
                }

            if self.consolidation_engine:
                stats["consolidation"] = self.consolidation_engine.get_consolidation_stats()

        return stats

    def get_recent_results(self, limit: int = 10) -> List[AcquisitionResult]:
        """Get recent acquisition results."""
        with self._lock:
            return self._task_history[-limit:]


def create_unified_acquisition_pipeline(
    experience_memory: ExperienceMemory,
    engineering_lessons: EngineeringLessonStorage,
    long_term_memory: LongTermMemory,
    semantic_memory: SemanticMemory,
    knowledge_validator: KnowledgeValidator,
    event_bus: Optional[EventBus] = None,
    config: Optional[UnifiedAcquisitionConfig] = None,
) -> UnifiedKnowledgeAcquisitionPipeline:
    """Factory function to create a unified knowledge acquisition pipeline."""
    return UnifiedKnowledgeAcquisitionPipeline(
        experience_memory=experience_memory,
        engineering_lessons=engineering_lessons,
        long_term_memory=long_term_memory,
        semantic_memory=semantic_memory,
        knowledge_validator=knowledge_validator,
        event_bus=event_bus,
        config=config,
    )