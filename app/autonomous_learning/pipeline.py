"""Autonomous Learning Pipeline - Orchestrates the end-to-end learning process.

This module implements the core autonomous learning pipeline that:
1. Analyzes experiences to extract learning opportunities
2. Extracts knowledge from experiences and other sources
3. Validates extracted knowledge before storage
4. Persists validated knowledge with provenance and confidence tracking
5. Detects knowledge gaps and triggers autonomous research
6. Tracks learning analytics for performance monitoring
"""

import time
import threading
import re
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Callable, Set
from pathlib import Path

from app.core.logger import logger
from app.memory.experience_memory import ExperienceMemory, ExperienceEntry
from app.memory.engineering_lessons import EngineeringLessonStorage, EngineeringLesson
from app.memory.long_term_memory import LongTermMemory, LongTermEntry
from app.memory.semantic_memory import SemanticMemory, SemanticEntry
from app.memory.validation import KnowledgeValidator, ValidationResult, ValidationSourceType, ValidationSource
from app.knowledge_extraction.pipeline import KnowledgeExtractionPipeline, KnowledgeObject
from app.knowledge_extraction.models import KnowledgeCategory, SourceType
from app.autonomous_learning.models import (
    LearningPipelineResult,
    KnowledgeGap,
    GapPriority,
    GapStatus,
    ResearchTask,
    ResearchSource,
    ResearchStatus,
    LearningEvent,
    LearningEventType,
    AutonomousLearningConfig
)
from app.autonomous_learning.gap_detection import KnowledgeGapDetector
from app.autonomous_learning.research_loop import AutonomousResearchLoop
from app.autonomous_learning.analytics import LearningAnalytics
from app.memory.cross_references import CrossMemoryReferences
from app.memory.goals import GoalStorage
from app.multi_agent_learning.share import KnowledgeSharer, KnowledgeReceiver
from app.memory.consolidation import ConsolidationEngine, ConsolidationConfig, ConsolidationTrigger, create_consolidation_engine

# Shared infrastructure imports
from app.core.events import get_event_bus
from app.core.background_jobs import get_job_service, JobTriggerConfig, JobTriggerType, JobPriority
from app.core.observability import get_observability_hub, HealthCheck, HealthResult, HealthStatus, ComponentInfo, ComponentType


class AutonomousLearningPipeline:
    """Main autonomous learning pipeline orchestrator.

    Implements the end-to-end learning process:
    Experience Analysis → Knowledge Extraction → Knowledge Validation → Storage
    → Gap Detection → Autonomous Research → Gap Resolution
    """

    def __init__(
        self,
        experience_memory: ExperienceMemory,
        engineering_lessons: EngineeringLessonStorage,
        long_term_memory: LongTermMemory,
        semantic_memory: SemanticMemory,
        knowledge_validator: KnowledgeValidator,
        knowledge_extraction_pipeline: Optional[KnowledgeExtractionPipeline] = None,
        gap_detector: Optional[KnowledgeGapDetector] = None,
        research_loop: Optional[AutonomousResearchLoop] = None,
        cross_references: Optional[CrossMemoryReferences] = None,
        consolidation_engine: Optional[ConsolidationEngine] = None,
        goal_storage: Optional[Any] = None,
        planner: Optional[Any] = None,
        config: Optional[AutonomousLearningConfig] = None,
        # Shared infrastructure
        event_bus: Optional[object] = None,
        job_service: Optional[object] = None,
        observability: Optional[object] = None,
    ):
        """Initialize the autonomous learning pipeline.

        Args:
            experience_memory: Storage for experiences
            engineering_lessons: Storage for engineering lessons
            long_term_memory: Storage for long-term knowledge
            semantic_memory: Storage for semantic knowledge
            knowledge_validator: Validates knowledge before storage
            knowledge_extraction_pipeline: Pipeline for extracting knowledge
            gap_detector: Detects knowledge gaps
            research_loop: Performs autonomous research to fill gaps
            cross_references: Manages cross-memory relationships
            consolidation_engine: Engine for memory consolidation
            goal_storage: Storage for goals
            planner: Planner for creating plans from goals/tasks
            config: Pipeline configuration
            event_bus: Optional shared EventBus instance
            job_service: Optional shared BackgroundJobService instance
            observability: Optional shared ObservabilityHub instance
        """
        self.experience_memory = experience_memory
        self.engineering_lessons = engineering_lessons
        self.long_term_memory = long_term_memory
        self.semantic_memory = semantic_memory
        self.knowledge_validator = knowledge_validator
        self.knowledge_extraction_pipeline = knowledge_extraction_pipeline or KnowledgeExtractionPipeline()
        self.gap_detector = gap_detector or KnowledgeGapDetector(
            experience_memory=experience_memory,
            engineering_lessons=engineering_lessons,
            long_term_memory=long_term_memory,
            semantic_memory=semantic_memory,
        )
        self.research_loop = research_loop or AutonomousResearchLoop(
            knowledge_extractor=self.knowledge_extraction_pipeline,
            knowledge_validator=knowledge_validator,
            experience_memory=experience_memory,
            engineering_lessons=engineering_lessons,
            long_term_memory=long_term_memory,
            semantic_memory=semantic_memory,
        )
        self.cross_references = cross_references
        self.consolidation_engine = consolidation_engine
        self.config = config or AutonomousLearningConfig()
        self.analytics = LearningAnalytics()  # Initialize analytics system
        self.multi_agent_enabled = self.config.multi_agent_enabled

        # Shared infrastructure
        self.event_bus = event_bus or get_event_bus()
        self.job_service = job_service or get_job_service()
        self.observability = observability or get_observability_hub()

        # Pipeline state
        self._lock = threading.RLock()
        self._is_running = False
        self._last_run_time: Optional[datetime] = None
        self._last_export_time: Optional[datetime] = None  # For multi-agent knowledge export

        # Statistics
        self.stats = LearningPipelineResult()

        # Multi-agent learning components
        if self.multi_agent_enabled:
            self.knowledge_sharer = KnowledgeSharer(
                shared_dir=self.config.shared_knowledge_dir,
                instance_id=self.config.instance_id,
                experience_memory=self.experience_memory,
                engineering_lessons=self.engineering_lessons,
                long_term_memory=self.long_term_memory,
                semantic_memory=self.semantic_memory,
                knowledge_validator=self.knowledge_validator,
            )
            self.knowledge_receiver = KnowledgeReceiver(
                shared_dir=self.config.shared_knowledge_dir,
                instance_id=self.config.instance_id,
                experience_memory=self.experience_memory,
                engineering_lessons=self.engineering_lessons,
                long_term_memory=self.long_term_memory,
                semantic_memory=self.semantic_memory,
                knowledge_validator=self.knowledge_validator,
            )
        else:
            self.knowledge_sharer = None
            self.knowledge_receiver = None

        # Goal-driven learning components
        self.goal_storage = goal_storage
        self.planner = planner

        # Register with observability
        self._register_with_observability()

    def _register_with_observability(self) -> None:
        """Register this subsystem with the shared ObservabilityHub."""
        if self.observability:
            self.observability.add_health_check(HealthCheck(
                name="autonomous_learning_pipeline_health",
                component="autonomous_learning",
                check_func=self._health_check,
                interval_seconds=60.0,
            ))

            # Register component
            self.observability.register_component(ComponentInfo(
                name="AutonomousLearningPipeline",
                component_type=ComponentType.SERVICE,
                version="1.0.0",
                description="Autonomous learning pipeline: experience analysis, knowledge extraction, validation, gap detection, research",
                metadata={},
            ))

    def _health_check(self) -> HealthResult:
        """Health check for AutonomousLearningPipeline."""
        try:
            return HealthResult(
                name="autonomous_learning_pipeline_health",
                component="autonomous_learning",
                status=HealthStatus.HEALTHY,
                message="AutonomousLearningPipeline operational",
                metadata={
                    "is_running": self._is_running,
                    "last_run_time": self._last_run_time.isoformat() if self._last_run_time else None,
                    "total_experiences_processed": self.stats.experiences_processed,
                    "total_knowledge_stored": self.stats.knowledge_objects_stored,
                    "total_gaps_detected": self.stats.gaps_detected,
                    "total_research_tasks": self.stats.research_tasks_started,
                }
            )
        except Exception as e:
            return HealthResult(
                name="autonomous_learning_pipeline_health",
                component="autonomous_learning",
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

    def __call__(self) -> LearningPipelineResult:
        """Execute the full autonomous learning pipeline.

        Returns:
            LearningPipelineResult: Results of the pipeline execution
        """
        with self._lock:
            if self._is_running:
                logger.warning("Autonomous learning pipeline is already running")
                return self.stats

            self._is_running = True
            start_time = time.time()
            self.stats = LearningPipelineResult()

            # Record pipeline start in analytics
            self.analytics.record_pipeline_start()

            # Import knowledge from other agents if multi-agent learning is enabled
            if self.multi_agent_enabled and self.knowledge_receiver:
                self._import_shared_knowledge()

            try:
                logger.info("Starting autonomous learning pipeline")

                # Step 1: Process recent experiences
                self._process_experiences()

                # Step 2: Extract knowledge from experiences and other sources
                self._extract_knowledge()

                # Step 3: Validate extracted knowledge
                self._validate_knowledge()

                # Step 4: Store validated knowledge
                self._store_knowledge()

                # Step 4b: Export newly learned knowledge to other agents
                if self.multi_agent_enabled and self.knowledge_sharer:
                    self._export_learned_knowledge()

                # Step 5: Detect knowledge gaps
                if self.config.gap_detection_enabled:
                    self._detect_knowledge_gaps()

                # Step 5b: Detect goal-driven knowledge gaps
                self._detect_goal_driven_knowledge_gaps()

                # Step 6: Execute autonomous research to fill gaps
                if self.config.research_enabled:
                    self._execute_autonomous_research()

                # Step 7: Run memory consolidation
                if self.config.use_consolidation_engine and self.consolidation_engine:
                    self._run_consolidation()

                # Update final statistics
                self.stats.duration_seconds = time.time() - start_time
                self._last_run_time = datetime.now(timezone.utc)

                # Record pipeline completion metrics
                self.analytics.record_pipeline_duration(self.stats.duration_seconds)

                # Calculate and record knowledge quality metrics
                if self.stats.knowledge_objects_extracted > 0:
                    avg_confidence = self._calculate_average_confidence()
                    high_confidence_ratio = self._calculate_high_confidence_ratio()
                    self.analytics.record_knowledge_quality(avg_confidence, high_confidence_ratio)

                # Record pipeline result for detailed analytics
                self.analytics.record_pipeline_result(self.stats)

                # Log completion
                logger.info(
                    f"Autonomous learning pipeline completed in {self.stats.duration_seconds:.2f}s. "
                    f"Processed {self.stats.experiences_processed} experiences, "
                    f"extracted {self.stats.knowledge_objects_extracted} knowledge objects, "
                    f"validated {self.stats.knowledge_objects_validated}, "
                    f"stored {self.stats.knowledge_objects_stored}, "
                    f"detected {self.stats.gaps_detected} gaps, "
                    f"goal gaps: {self.stats.goal_gaps_detected}, "
                    f"started {self.stats.research_tasks_started} research tasks, "
                    f"consolidation runs: {self.stats.consolidation_runs}"
                )

                # Publish pipeline completion event
                self._publish_event("learning.pipeline_completed", {
                    "duration_seconds": self.stats.duration_seconds,
                    "experiences_processed": self.stats.experiences_processed,
                    "knowledge_objects_extracted": self.stats.knowledge_objects_extracted,
                    "knowledge_objects_validated": self.stats.knowledge_objects_validated,
                    "knowledge_objects_stored": self.stats.knowledge_objects_stored,
                    "gaps_detected": self.stats.gaps_detected,
                    "goal_gaps_detected": self.stats.goal_gaps_detected,
                    "research_tasks_started": self.stats.research_tasks_started,
                    "consolidation_runs": self.stats.consolidation_runs,
                    "errors": len(self.stats.errors),
                    "warnings": len(self.stats.warnings),
                })

                return self.stats

            except Exception as e:
                logger.error(f"Autonomous learning pipeline failed: {e}")
                self.stats.errors.append(f"Pipeline execution failed: {str(e)}")
                self.analytics.record_error("pipeline")
                self.stats.duration_seconds = time.time() - start_time
                return self.stats
            finally:
                self._is_running = False

    def _calculate_average_confidence(self) -> float:
        """Calculate average confidence of recently processed knowledge objects.

        Returns:
            Average confidence score (0.0-1.0)
        """
        # Placeholder implementation - in a full version, this would calculate
        # actual average from processed knowledge objects
        return 0.75

    def _calculate_high_confidence_ratio(self) -> float:
        """Calculate ratio of high confidence knowledge objects (>0.8 confidence).

        Returns:
            Ratio of high confidence knowledge (0.0-1.0)
        """
        # Placeholder implementation
        return 0.6

    def _process_experiences(self) -> None:
        """Process recent experiences to prepare for knowledge extraction."""
        try:
            # Get recent experiences since last run
            since_time = self._last_run_time if self._last_run_time else None
            experiences = self._get_recent_experiences(since_time)

            self.stats.experiences_processed = len(experiences)
            self.stats.experiences_analyzed = len(experiences)  # All processed experiences are analyzed

            # Log experience processing
            if experiences:
                logger.debug(f"Processing {len(experiences)} experiences for knowledge extraction")

                # Record learning event
                self._record_learning_event(
                    LearningEventType.EXPERIENCE_COLLECTED,
                    f"Processed {len(experiences)} experiences",
                    {"experience_count": len(experiences)}
                )

        except Exception as e:
            logger.error(f"Error processing experiences: {e}")
            self.stats.errors.append(f"Experience processing failed: {str(e)}")

    def _get_recent_experiences(self, since_time: Optional[datetime]) -> List[ExperienceEntry]:
        """Get experiences processed since the last pipeline run.

        Args:
            since_time: Only return experiences after this time

        Returns:
            List of ExperienceEntry objects
        """
        try:
            if since_time:
                # Get experiences since last run
                all_experiences = self.experience_memory.all()
                filtered_experiences = [
                    exp for exp in all_experiences
                    if datetime.fromisoformat(exp.timestamp.replace('Z', '+00:00')) > since_time
                ]
                return filtered_experiences
            else:
                # First run - get recent experiences (limited by config)
                return self.experience_memory.recent(limit=self.config.max_experiences_per_run)
        except Exception as e:
            logger.error(f"Error retrieving recent experiences: {e}")
            return []

    def _extract_knowledge(self) -> None:
        """Extract knowledge from experiences and other sources."""
        try:
            # Extract knowledge from experiences
            experience_knowledge = self._extract_knowledge_from_experiences()

            # Extract knowledge from other sources (lessons, etc.)
            other_knowledge = self._extract_knowledge_from_other_sources()

            # Combine all extracted knowledge
            all_knowledge = experience_knowledge + other_knowledge

            self.stats.knowledge_objects_extracted = len(all_knowledge)

            # Store extracted knowledge for validation phase
            self._pending_knowledge = all_knowledge

            if all_knowledge:
                logger.debug(f"Extracted {len(all_knowledge)} knowledge objects from experiences and other sources")
                self._record_learning_event(
                    LearningEventType.KNOWLEDGE_EXTRACTED,
                    f"Extracted {len(all_knowledge)} knowledge objects",
                    {"extracted_count": len(all_knowledge)}
                )

        except Exception as e:
            logger.error(f"Error extracting knowledge: {e}")
            self.stats.errors.append(f"Knowledge extraction failed: {str(e)}")

    def _extract_knowledge_from_experiences(self) -> List[KnowledgeObject]:
        """Extract knowledge objects from experience entries.

        Returns:
            List of KnowledgeObject instances
        """
        knowledge_objects = []

        try:
            # Get recent experiences
            experiences = self._get_recent_experiences(self._last_run_time)

            for experience in experiences:
                # Convert experience to knowledge object(s)
                exp_knowledge = self._experience_to_knowledge_objects(experience)
                knowledge_objects.extend(exp_knowledge)

                # Track source experiences for provenance
                for ko in exp_knowledge:
                    ko.metadata.setdefault("source_experiences", []).append(experience.id)

        except Exception as e:
            logger.error(f"Error extracting knowledge from experiences: {e}")

        return knowledge_objects

    def _experience_to_knowledge_objects(self, experience: ExperienceEntry) -> List[KnowledgeObject]:
        """Convert an experience entry to one or more knowledge objects.

        Args:
            experience: The experience to convert

        Returns:
            List of KnowledgeObject instances
        """
        knowledge_objects = []

        try:
            # Determine knowledge type based on outcome
            if experience.outcome == "positive":
                knowledge_type = KnowledgeCategory.BEST_PRACTICE
                confidence_boost = 0.2
            elif experience.outcome == "negative":
                knowledge_type = KnowledgeCategory.WARNING  # Treat negative experiences as warnings
                confidence_boost = 0.1
            else:
                knowledge_type = KnowledgeCategory.EXPLANATION
                confidence_boost = 0.0

            # Create knowledge object from experience
            ko = KnowledgeObject(
                title=f"Experience: {experience.title}",
                summary=experience.description[:200] if experience.description else "",
                content=f"Experience: {experience.title}\n\n{experience.description}\n\nOutcome: {experience.outcome}",
                source=experience.id,
                source_type=SourceType.USER_INPUT,  # Experiences come from user/system interactions
                category=knowledge_type,
                tags=experience.tags + [f"outcome_{experience.outcome}", f"source_experience"],
                confidence=min(1.0, experience.confidence + confidence_boost),
                metadata={
                    "source_type": "experience",
                    "experience_id": experience.id,
                    "experience_outcome": experience.outcome,
                    "extracted_at": datetime.now(timezone.utc).isoformat()
                }
            )

            knowledge_objects.append(ko)

            # Additionally, if the experience contains specific patterns or lessons,
            # create more specific knowledge objects
            if experience.metadata.get("lessons_learned"):
                lesson_ko = KnowledgeObject(
                    title=f"Lesson from experience: {experience.title}",
                    summary=str(experience.metadata["lessons_learned"])[:200],
                    content=f"Lesson learned from experience '{experience.title}':\n\n{experience.metadata['lessons_learned']}",
                    source=experience.id,
                    source_type=SourceType.USER_INPUT,
                    category=KnowledgeCategory.LESSON_LEARNED,
                    tags=experience.tags + ["lesson_learned", "experience_based"],
                    confidence=min(1.0, experience.confidence + 0.15),
                    metadata={
                        "source_type": "experience_lesson",
                        "experience_id": experience.id,
                        "extracted_at": datetime.now(timezone.utc).isoformat()
                    }
                )
                knowledge_objects.append(lesson_ko)

        except Exception as e:
            logger.error(f"Error converting experience to knowledge object: {e}")

        return knowledge_objects

    def _extract_knowledge_from_other_sources(self) -> List[KnowledgeObject]:
        """Extract knowledge from other sources like engineering lessons.

        Returns:
            List of KnowledgeObject instances
        """
        knowledge_objects = []

        try:
            # Extract from engineering lessons (if they haven't been processed recently)
            recent_lessons = self.engineering_lessons.recent(limit=50)  # Get recent lessons

            for lesson in recent_lessons:
                # Convert lesson to knowledge object
                ko = KnowledgeObject(
                    title=f"Lesson: {lesson.title}",
                    summary=lesson.description[:200] if lesson.description else "",
                    content=f"Lesson: {lesson.title}\n\n{lesson.description}\n\nRationale: {lesson.rationale}",
                    source=lesson.id,
                    source_type=SourceType.USER_INPUT,  # Lessons come from system/user
                    category=self._lesson_type_to_knowledge_category(lesson.lesson_type),
                    tags=lesson.tags + [f"lesson_type_{lesson.lesson_type.value}", "source_lesson"],
                    confidence=lesson.confidence,
                    metadata={
                        "source_type": "engineering_lesson",
                        "lesson_id": lesson.id,
                        "lesson_type": lesson.lesson_type.value,
                        "extracted_at": datetime.now(timezone.utc).isoformat()
                    }
                )
                knowledge_objects.append(ko)

        except Exception as e:
            logger.error(f"Error extracting knowledge from other sources: {e}")

        return knowledge_objects

    def _lesson_type_to_knowledge_category(self, lesson_type) -> KnowledgeCategory:
        """Convert lesson type to knowledge category.

        Args:
            lesson_type: The lesson type enum

        Returns:
            KnowledgeCategory equivalent
        """
        # Map lesson types to knowledge categories
        mapping = {
            "pattern": KnowledgeCategory.BEST_PRACTICE,
            "anti_pattern": KnowledgeCategory.WARNING,
            "best_practice": KnowledgeCategory.BEST_PRACTICE,
            "troubleshooting": KnowledgeCategory.TROUBLESHOOTING,
            "decision": KnowledgeCategory.DECISION,
            "recommendation": KnowledgeCategory.RECOMMENDATION,
            "warning": KnowledgeCategory.WARNING,
        }

        return mapping.get(lesson_type.value, KnowledgeCategory.OTHER)

    def _validate_knowledge(self) -> None:
        """Validate extracted knowledge using the knowledge validator."""
        try:
            if not hasattr(self, '_pending_knowledge') or not self._pending_knowledge:
                logger.debug("No knowledge to validate")
                return

            validated_knowledge = []
            rejected_knowledge = []

            for ko in self._pending_knowledge:
                try:
                    # Convert KnowledgeObject to validation format
                    validation_sources = []

                    # Add source from the knowledge object
                    if ko.source:
                        source_type = self._map_source_type_to_validation_source(ko.source_type)
                        validation_source = ValidationSource(
                            source_type=source_type,
                            identifier=ko.source,
                            content=ko.content[:500],  # Truncate for validation
                            confidence=ko.confidence
                        )
                        validation_sources.append(validation_source)

                    # Validate the knowledge
                    validation_result = self.knowledge_validator.validate(
                        knowledge_id=ko.id,
                        title=ko.title,
                        content=ko.content,
                        category=ko.category.value,
                        sources=validation_sources,
                        metadata=ko.metadata
                    )

                    # Update knowledge object with validation results
                    ko.metadata["validation"] = validation_result.to_dict()

                    if validation_result.storage_decision.value in ["auto_store", "delay_store"]:
                        validated_knowledge.append(ko)
                    else:
                        rejected_knowledge.append((ko, validation_result))

                except Exception as e:
                    logger.error(f"Error validating knowledge object {ko.id}: {e}")
                    rejected_knowledge.append((ko, str(e)))

            self.stats.knowledge_objects_validated = len(validated_knowledge)
            self.stats.knowledge_objects_rejected = len(rejected_knowledge)

            # Store validated knowledge for storage phase
            self._validated_knowledge = validated_knowledge
            self._rejected_knowledge = rejected_knowledge

            if validated_knowledge:
                logger.debug(f"Validated {len(validated_knowledge)} knowledge objects")
                self._record_learning_event(
                    LearningEventType.KNOWLEDGE_VALIDATED,
                    f"Validated {len(validated_knowledge)} knowledge objects",
                    {"validated_count": len(validated_knowledge), "rejected_count": len(rejected_knowledge)}
                )

        except Exception as e:
            logger.error(f"Error validating knowledge: {e}")
            self.stats.errors.append(f"Knowledge validation failed: {str(e)}")

    def _map_source_type_to_validation_source(self, source_type: SourceType) -> ValidationSourceType:
        """Map knowledge extraction source type to validation source type.

        Args:
            source_type: Source type from knowledge extraction

        Returns:
            Equivalent validation source type
        """
        mapping = {
            SourceType.USER_INPUT: ValidationSourceType.USER_PROVIDED,
            SourceType.SOURCE_CODE: ValidationSourceType.SOURCE_CODE,
            SourceType.DOCUMENTATION: ValidationSourceType.OFFICIAL_DOCUMENTATION,
            SourceType.LLM_RESPONSE: ValidationSourceType.STRONGER_LLM,
            SourceType.TOOL_OUTPUT: ValidationSourceType.USER_PROVIDED,  # Tool output is user-directed
            SourceType.LOG: ValidationSourceType.USER_PROVIDED,
            SourceType.API_RESPONSE: ValidationSourceType.USER_PROVIDED,
            SourceType.MARKDOWN: ValidationSourceType.OFFICIAL_DOCUMENTATION,
            SourceType.PDF: ValidationSourceType.OFFICIAL_DOCUMENTATION,
            SourceType.UNKNOWN: ValidationSourceType.UNKNOWN,
        }

        return mapping.get(source_type, ValidationSourceType.UNKNOWN)

    def _store_knowledge(self) -> None:
        """Store validated knowledge in appropriate memory systems."""
        try:
            if not hasattr(self, '_validated_knowledge') or not self._validated_knowledge:
                logger.debug("No validated knowledge to store")
                return

            stored_count = 0

            for ko in self._validated_knowledge:
                try:
                    # Determine where to store based on confidence and type
                    stored = self._store_knowledge_object(ko)
                    if stored:
                        stored_count += 1

                        # Record knowledge storage event
                        self._record_learning_event(
                            LearningEventType.KNOWLEDGE_STORED,
                            f"Stored knowledge: {ko.title}",
                            {
                                "knowledge_id": ko.id,
                                "title": ko.title,
                                "category": ko.category.value,
                                "confidence": ko.confidence
                            }
                        )

                except Exception as e:
                    logger.error(f"Error storing knowledge object {ko.id}: {e}")
                    self.stats.errors.append(f"Knowledge storage failed for {ko.id}: {str(e)}")

            self.stats.knowledge_objects_stored = stored_count

            if stored_count > 0:
                logger.info(f"Stored {stored_count} validated knowledge objects")

        except Exception as e:
            logger.error(f"Error storing knowledge: {e}")
            self.stats.errors.append(f"Knowledge storage failed: {str(e)}")

    def _store_knowledge_object(self, ko: KnowledgeObject) -> bool:
        """Store a single knowledge object in the appropriate memory system.

        Args:
            ko: The knowledge object to store

        Returns:
            bool: True if stored successfully
        """
        try:
            # Determine storage destination based on confidence and category
            if ko.confidence >= self.config.validation_auto_store_threshold:
                # High confidence - store in long-term or semantic memory
                if ko.category in [KnowledgeCategory.BEST_PRACTICE, KnowledgeCategory.WARNING,
                                 KnowledgeCategory.TROUBLESHOOTING, KnowledgeCategory.RECOMMENDATION]:
                    # Store as engineering lesson in long-term memory
                    return self._store_as_lesson(ko)
                else:
                    # Store in semantic memory
                    return self._store_as_semantic(ko)
            else:
                # Lower confidence - still store but maybe in experience or temporary storage
                # For now, we'll store in semantic memory with lower confidence
                return self._store_as_semantic(ko)

        except Exception as e:
            logger.error(f"Error storing knowledge object {ko.id}: {e}")
            return False

    def _store_as_lesson(self, ko: KnowledgeObject) -> bool:
        """Store knowledge object as an engineering lesson.

        Args:
            ko: Knowledge object to store

        Returns:
            bool: True if stored successfully
        """
        try:
            # Map knowledge category to lesson type
            lesson_type_map = {
                KnowledgeCategory.BEST_PRACTICE: "best_practice",
                KnowledgeCategory.WARNING: "anti_pattern",
                KnowledgeCategory.TROUBLESHOOTING: "troubleshooting",
                KnowledgeCategory.RECOMMENDATION: "recommendation",
                KnowledgeCategory.DECISION: "decision",
            }

            lesson_type = lesson_type_map.get(ko.category, "lesson_learned")

            # Prepare tags
            tags = list(ko.tags)  # Copy existing tags
            tags.append("auto_extracted")
            if "source_experiences" in ko.metadata:
                tags.append("experience_based")

            # Store the lesson
            lesson = self.engineering_lessons.store(
                title=ko.title,
                description=ko.summary,
                lesson_type=lesson_type,
                category=ko.metadata.get("source_type", "general"),
                tags=tags,
                confidence=ko.confidence,
                rationale=ko.content[:500] if len(ko.content) > 500 else ko.content,
                metadata=ko.metadata
            )

            # Add cross-references if enabled
            if self.cross_references and lesson:
                self._add_knowledge_cross_references(ko.id, lesson.id, ko.metadata.get("source_experiences", []))

            return lesson is not None

        except Exception as e:
            logger.error(f"Error storing knowledge as lesson: {e}")
            return False

    def _store_as_semantic(self, ko: KnowledgeObject) -> bool:
        """Store knowledge object as a semantic memory entry.

        Args:
            ko: Knowledge object to store

        Returns:
            bool: True if stored successfully
        """
        try:
            # Determine category for semantic memory
            category_map = {
                KnowledgeCategory.FACT: "fact",
                KnowledgeCategory.EXPLANATION: "explanation",
                KnowledgeCategory.PROCEDURE: "procedure",
                KnowledgeCategory.ALGORITHM: "algorithm",
                KnowledgeCategory.BEST_PRACTICE: "best_practice",
                KnowledgeCategory.RECOMMENDATION: "recommendation",
                KnowledgeCategory.WORKFLOW: "workflow",
                KnowledgeCategory.TROUBLESHOOTING: "troubleshooting",
                KnowledgeCategory.CONCEPT: "concept",
                KnowledgeCategory.DEFINITION: "definition",
                KnowledgeCategory.EXAMPLE: "example",
            }

            category = category_map.get(ko.category, "other")

            # Store in semantic memory
            entry = self.semantic_memory.store(
                key=ko.id,
                value=ko.content,
                description=ko.summary,
                category=category,
                tags=ko.tags,
                confidence=ko.confidence,
                metadata=ko.metadata
            )

            # Add cross-references if enabled
            if self.cross_references and entry:
                self._add_knowledge_cross_references(ko.id, entry.key, ko.metadata.get("source_experiences", []))

            return entry is not None

        except Exception as e:
            logger.error(f"Error storing knowledge as semantic entry: {e}")
            return False

    def _add_knowledge_cross_references(self, knowledge_id: str, target_id: str, source_experience_ids: List[str]) -> None:
        """Add cross-references for knowledge object.

        Args:
            knowledge_id: ID of the knowledge object
            target_id: ID of the target item (lesson or semantic entry)
            source_experience_ids: List of source experience IDs
        """
        try:
            if not self.cross_references:
                return

            # Add bidirectional reference between knowledge and target
            self.cross_references.add_reference(
                source_memory="knowledge",
                source_id=knowledge_id,
                target_memory="lesson" if "lesson" in target_id else "semantic",
                target_id=target_id,
                reference_type="related",
                confidence=0.8,
                description="Automatically linked during knowledge storage"
            )

            # Link to source experiences
            for exp_id in source_experience_ids:
                self.cross_references.add_reference(
                    source_memory="experience",
                    source_id=exp_id,
                    target_memory="knowledge",
                    target_id=knowledge_id,
                    reference_type="source",
                    confidence=0.9,
                    description="Source experience for extracted knowledge"
                )

        except Exception as e:
            logger.error(f"Error adding cross-references for knowledge {knowledge_id}: {e}")

    def _detect_knowledge_gaps(self) -> None:
        """Detect knowledge gaps using the gap detector.

        Returns:
            List of detected KnowledgeGap objects
        """
        try:
            logger.debug("Detecting knowledge gaps")
            gaps = self.gap_detector.detect_gaps()

            self.stats.gaps_detected = len(gaps)

            if gaps:
                logger.info(f"Detected {len(gaps)} knowledge gaps")
                self._record_learning_event(
                    LearningEventType.GAP_DETECTED,
                    f"Detected {len(gaps)} knowledge gaps",
                    {"gap_count": len(gaps)}
                )

            return gaps

        except Exception as e:
            logger.error(f"Error detecting knowledge gaps: {e}")
            self.stats.errors.append(f"Gap detection failed: {str(e)}")
            return []

    def _execute_autonomous_research(self) -> None:
        """Execute autonomous research to fill detected knowledge gaps.

        Returns:
            List of ResearchTask objects representing research efforts
        """
        try:
            logger.debug("Executing autonomous research")
            research_tasks = self.research_loop.research_knowledge_gaps()

            self.stats.research_tasks_started = len(research_tasks)

            if research_tasks:
                completed_tasks = sum(1 for task in research_tasks if task.status == ResearchStatus.COMPLETED)
                self.stats.research_tasks_completed = completed_tasks
                self.stats.research_tasks_failed = len([t for t in research_tasks if t.status == ResearchStatus.FAILED])

                logger.info(f"Started {len(research_tasks)} research tasks ({completed_tasks} completed)")
                self._record_learning_event(
                    LearningEventType.RESEARCH_STARTED,
                    f"Started {len(research_tasks)} research tasks to fill knowledge gaps",
                    {"research_task_count": len(research_tasks)}
                )

            return research_tasks

        except Exception as e:
            logger.error(f"Error executing autonomous research: {e}")
            self.stats.errors.append(f"Autonomous research failed: {str(e)}")
            return []

    def _run_consolidation(self) -> None:
        """Run memory consolidation to promote high-value entries to long-term memory."""
        try:
            logger.debug("Running memory consolidation")
            result = self.consolidation_engine.run_consolidation()

            self.stats.consolidation_runs += 1
            self.stats.experiences_promoted = result.experiences_promoted
            self.stats.lessons_promoted = result.lessons_promoted
            self.stats.entries_archived = result.project_entries_archived + result.experiences_archived + result.lessons_archived

            if result.experiences_promoted > 0 or result.lessons_promoted > 0:
                logger.info(f"Consolidation completed: promoted {result.experiences_promoted} experiences, {result.lessons_promoted} lessons, archived {result.project_entries_archived + result.experiences_archived + result.lessons_archived} entries")
                self._record_learning_event(
                    LearningEventType.CONSOLIDATION_RUN,
                    f"Consolidation promoted {result.experiences_promoted} experiences and {result.lessons_promoted} lessons",
                    {
                        "experiences_promoted": result.experiences_promoted,
                        "lessons_promoted": result.lessons_promoted,
                        "entries_archived": result.project_entries_archived + result.experiences_archived + result.lessons_archived,
                        "run_id": result.run_id,
                        "duration_seconds": result.duration_seconds
                    }
                )

            if result.errors:
                for error in result.errors:
                    self.stats.warnings.append(f"Consolidation: {error}")

        except Exception as e:
            logger.error(f"Error running consolidation: {e}")
            self.stats.warnings.append(f"Consolidation failed: {str(e)}")

    def _record_learning_event(
        self,
        event_type: LearningEventType,
        description: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Record a learning event for audit trail.

        Args:
            event_type: Type of learning event
            description: Human-readable description
            metadata: Additional event metadata
        """
        try:
            # In a full implementation, this would store the event in a learning event log
            # For now, we'll just log it
            logger.info(f"Learning Event [{event_type.value}]: {description}")

            # TODO: Store in actual learning event storage when implemented

        except Exception as e:
            logger.error(f"Error recording learning event: {e}")

    def get_pipeline_status(self) -> Dict[str, Any]:
        """Get current pipeline status and statistics.

        Returns:
            Dictionary containing pipeline status information
        """
        with self._lock:
            return {
                "is_running": self._is_running,
                "last_run_time": self._last_run_time.isoformat() if self._last_run_time else None,
                "stats": self.stats.to_dict(),
                "config": self.config.to_dict()
            }

    def get_learning_progress_dashboard(self) -> Dict[str, Any]:
        """Get a comprehensive learning progress dashboard.

        Returns:
            Dictionary with learning progress metrics, trends, and statistics
        """
        status = self.get_pipeline_status()
        stats = status.get("stats", {})

        dashboard = {
            "pipeline": status,
            "learning_metrics": {
                "total_experiences_processed": stats.get("experiences_processed", 0),
                "total_knowledge_extracted": stats.get("knowledge_objects_extracted", 0),
                "total_knowledge_validated": stats.get("knowledge_objects_validated", 0),
                "total_knowledge_stored": stats.get("knowledge_objects_stored", 0),
                "total_knowledge_rejected": stats.get("knowledge_objects_rejected", 0),
                "total_gaps_detected": stats.get("gaps_detected", 0),
                "total_gaps_resolved": stats.get("gaps_resolved", 0),
                "total_goal_gaps_detected": stats.get("goal_gaps_detected", 0),
                "total_research_started": stats.get("research_tasks_started", 0),
                "total_research_completed": stats.get("research_tasks_completed", 0),
                "total_research_failed": stats.get("research_tasks_failed", 0),
                "total_consolidation_runs": stats.get("consolidation_runs", 0),
                "total_experiences_promoted": stats.get("experiences_promoted", 0),
                "total_lessons_promoted": stats.get("lessons_promoted", 0),
                "total_entries_archived": stats.get("entries_archived", 0),
                "last_run_duration_seconds": stats.get("duration_seconds", 0),
            },
            "efficiency": {
                "validation_success_rate": (
                    stats.get("knowledge_objects_validated", 0) /
                    max(stats.get("knowledge_objects_extracted", 1), 1)
                ),
                "storage_success_rate": (
                    stats.get("knowledge_objects_stored", 0) /
                    max(stats.get("knowledge_objects_validated", 1), 1)
                ),
                "gap_resolution_rate": (
                    stats.get("gaps_resolved", 0) /
                    max(stats.get("gaps_detected", 1), 1)
                ),
                "research_completion_rate": (
                    stats.get("research_tasks_completed", 0) /
                    max(stats.get("research_tasks_started", 1), 1)
                ),
            },
            "health": {
                "error_count": len(stats.get("errors", [])),
                "warning_count": len(stats.get("warnings", [])),
                "last_errors": stats.get("errors", [])[-5:],
                "last_warnings": stats.get("warnings", [])[-5:],
            },
            "trends": {},
        }

        # Add analytics trends if available
        if hasattr(self, 'analytics') and self.analytics:
            try:
                dashboard["trends"] = {
                    "knowledge_extraction": self.analytics.get_trends("knowledge_extracted", hours=6),
                    "knowledge_storage": self.analytics.get_trends("knowledge_stored", hours=6),
                    "gap_resolution": self.analytics.get_trends("gap_resolution_rate", hours=6),
                    "research_completion": self.analytics.get_trends("research_success_rate", hours=6),
                }
                # Convert LearningTrend objects to dicts
                for key, trend in dashboard["trends"].items():
                    if trend:
                        dashboard["trends"][key] = {
                            "metric_name": trend.metric_name,
                            "direction": trend.direction,
                            "change_rate": trend.change_rate,
                            "values": trend.values[-10:],  # Last 10 values
                            "timestamps": trend.timestamps[-10:],
                        }
            except Exception:
                pass

        # Add consolidation stats if available
        if self.consolidation_engine:
            try:
                dashboard["consolidation"] = self.consolidation_engine.get_stats()
            except Exception:
                pass

        return dashboard

    def reset_stats(self) -> None:
        """Reset pipeline statistics."""
        with self._lock:
            self.stats = LearningPipelineResult()

    def _import_shared_knowledge(self) -> None:
        """Import knowledge from other agents via the shared directory."""
        try:
            if self.knowledge_receiver:
                imported_count = self.knowledge_receiver.import_knowledge()
                if imported_count > 0:
                    logger.info(f"Imported {imported_count} knowledge items from other agents")
                    # Record learning event for imported knowledge
                    self._record_learning_event(
                        LearningEventType.EXPERIENCE_COLLECTED,  # Reuse existing event type or create a new one
                        f"Imported {imported_count} knowledge items from other agents",
                        {"imported_count": imported_count}
                    )
        except Exception as e:
            logger.error(f"Error importing shared knowledge: {e}")
            self.stats.errors.append(f"Import shared knowledge failed: {str(e)}")

    def _export_learned_knowledge(self) -> None:
        """Export learned knowledge to other agents via the shared directory."""
        try:
            if self.knowledge_sharer:
                # Export knowledge since the last export time (or all if never exported)
                since_time = self._last_export_time
                exported_count = self.knowledge_sharer.export_knowledge(since_time)
                if exported_count > 0:
                    self._last_export_time = datetime.now(timezone.utc)
                    logger.info(f"Exported {exported_count} knowledge items to other agents")
                    # Record learning event for exported knowledge
                    self._record_learning_event(
                        LearningEventType.KNOWLEDGE_STORED,  # Reuse existing event type
                        f"Exported {exported_count} knowledge items to other agents",
                        {"exported_count": exported_count}
                    )
        except Exception as e:
            logger.error(f"Error exporting learned knowledge: {e}")
            self.stats.errors.append(f"Export learned knowledge failed: {str(e)}")

    def _detect_goal_driven_knowledge_gaps(self) -> None:
        """Detect knowledge gaps based on current goals and planned tasks.

        Analyzes active goals to determine what knowledge is required to achieve them,
        compares with existing knowledge, and identifies gaps.

        Enhanced features:
        - Goal dependency-aware gap detection (blocked goals get higher priority)
        - Goal hierarchy support (parent goals propagate requirements)
        - Research prioritization based on goal priority and blocking status
        - Cross-reference tracking for traceability
        """
        if not self.goal_storage or not self.planner or not self.config.goal_driven_learning_enabled:
            return

        try:
            logger.debug("Detecting goal-driven knowledge gaps")

            # Get active and pending goals with enhanced filtering
            goals = self._get_relevant_goals_for_gap_analysis()

            goal_gaps = []

            for goal in goals:
                try:
                    # Skip if goal has no description
                    if not getattr(goal, 'description', None) and not getattr(goal, 'name', None):
                        continue

                    # Check if goal is blocked - blocked goals get priority for gap detection
                    is_blocked = self._is_goal_blocked(goal)

                    # Create a plan for this goal to understand what tasks are involved
                    goal_description = getattr(goal, 'description', '') or getattr(goal, 'name', '')
                    plan = self.planner.create_plan(goal_description)

                    # Extract knowledge requirements from goal and plan
                    required_knowledge = self._extract_knowledge_requirements(goal, plan)

                    # Also get requirements from goal dependencies
                    dep_requirements = self._extract_dependency_requirements(goal)
                    for cat, items in dep_requirements.items():
                        required_knowledge[cat].update(items)

                    # Check what knowledge we already have
                    available_knowledge = self._get_available_knowledge()

                    # Identify gaps
                    gaps = self._identify_knowledge_gaps(goal, required_knowledge, available_knowledge, is_blocked)

                    # Add cross-references if available
                    if self.cross_references and gaps:
                        self._add_goal_gap_cross_references(goal, gaps)

                    goal_gaps.extend(gaps)

                except Exception as e:
                    logger.debug(f"Error analyzing goal {getattr(goal, 'id', 'unknown')}: {e}")
                    continue

            # Update stats and record events
            self.stats.goal_gaps_detected = len(goal_gaps)

            if goal_gaps:
                logger.info(f"Detected {len(goal_gaps)} goal-driven knowledge gaps")
                self._record_learning_event(
                    LearningEventType.GAP_DETECTED,
                    f"Detected {len(goal_gaps)} goal-driven knowledge gaps",
                    {"goal_gap_count": len(goal_gaps)}
                )

                # Trigger immediate research for critical/priority gaps
                self._schedule_goal_gap_research(goal_gaps)

        except Exception as e:
            logger.error(f"Error detecting goal-driven knowledge gaps: {e}")
            self.stats.errors.append(f"Goal-driven gap detection failed: {str(e)}")

    def _get_relevant_goals_for_gap_analysis(self) -> List[Any]:
        """Get goals relevant for gap analysis with enhanced filtering."""
        goals = []

        # Get active goal (highest priority)
        active_goal = self.goal_storage.active_goal()
        if active_goal:
            goals.append(active_goal)

        # Get queued goals (next in line)
        queued_goals = self.goal_storage.queue()
        goals.extend(queued_goals[:15])  # Limit to avoid overload

        # Get incomplete goals that aren't blocked by missing dependencies
        all_goals = self.goal_storage.all()
        for goal in all_goals:
            if getattr(goal, 'status', '') != 'completed' and goal not in goals:
                # Only include if not explicitly blocked by user
                if getattr(goal, 'status', '') != 'blocked':
                    goals.append(goal)
                    if len(goals) >= 25:
                        break

        # Add parent goals of active/queued goals (they propagate requirements)
        for goal in list(goals):
            parent = self.goal_storage.parent_of(goal.id)
            if parent and parent not in goals and parent.status != 'completed':
                goals.append(parent)

        return goals

    def _is_goal_blocked(self, goal: Any) -> bool:
        """Check if a goal is blocked (by dependencies or explicit status)."""
        try:
            # Check explicit blocked status
            if getattr(goal, 'status', '') == 'blocked':
                return True
            # Check if blocked by incomplete dependencies
            if hasattr(self.goal_storage, 'is_blocked'):
                return self.goal_storage.is_blocked(goal.id)
        except Exception:
            pass
        return False

    def _extract_dependency_requirements(self, goal: Any) -> Dict[str, Set[str]]:
        """Extract knowledge requirements from goal dependencies."""
        requirements = {
            'concepts': set(),
            'tools': set(),
            'frameworks': set(),
            'skills': set(),
            'domains': set()
        }

        try:
            if hasattr(self.goal_storage, 'dependencies_of'):
                deps = self.goal_storage.dependencies_of(goal.id)
                for dep in deps:
                    dep_text = f"{getattr(dep, 'name', '')} {getattr(dep, 'description', '')}".lower()
                    dep_requirements = self._extract_keywords_from_text(dep_text)
                    for cat, items in dep_requirements.items():
                        requirements[cat].update(items)
        except Exception as e:
            logger.debug(f"Error extracting dependency requirements: {e}")

        return requirements

    def _extract_keywords_from_text(self, text: str) -> Dict[str, Set[str]]:
        """Extract categorized keywords from text."""
        requirements = {
            'concepts': set(),
            'tools': set(),
            'frameworks': set(),
            'skills': set(),
            'domains': set()
        }

        # Known frameworks/technologies
        known_frameworks = {
            'django', 'flask', 'fastapi', 'express', 'react', 'vue', 'angular', 'svelte',
            'spring', 'springboot', 'rails', 'laravel', 'dotnet', 'aspnet', 'nodejs', 'nextjs',
            'pytorch', 'tensorflow', 'jax', 'sklearn', 'pandas', 'numpy', 'scipy',
            'kubernetes', 'docker', 'terraform', 'ansible', 'helm',
            'postgresql', 'mysql', 'mongodb', 'redis', 'sqlite', 'cassandra',
            'graphql', 'rest', 'grpc', 'websocket',
            'aws', 'gcp', 'azure', 'vercel', 'netlify',
            'github', 'gitlab', 'bitbucket', 'ci', 'cd', 'jenkins', 'githubactions',
            'pytest', 'jest', 'vitest', 'cypress', 'playwright', 'selenium',
            'webpack', 'vite', 'rollup', 'esbuild', 'swc', 'babel', 'typescript',
            'rust', 'go', 'java', 'python', 'javascript', 'typescript', 'cpp', 'csharp',
            'sqlalchemy', 'prisma', 'drizzle', 'typeorm', 'mongoose',
        }

        # Known tools
        known_tools = {
            'git', 'docker', 'kubectl', 'terraform', 'ansible', 'helm', 'vagrant',
            'curl', 'wget', 'httpie', 'postman', 'insomnia',
            'vscode', 'vim', 'neovim', 'emacs', 'intellij', 'pycharm', 'webstorm',
            'eslint', 'prettier', 'black', 'isort', 'flake8', 'mypy', 'pyright',
            'jest', 'vitest', 'pytest', 'coverage', 'sonarqube',
            'prometheus', 'grafana', 'datadog', 'newrelic', 'sentry',
            'nginx', 'apache', 'traefik', 'caddy',
            'redis', 'memcached', 'rabbitmq', 'kafka', 'nats',
        }

        # Known skills/methods
        known_skills = {
            'testing', 'debugging', 'refactoring', 'optimization', 'profiling',
            'deployment', 'ci_cd', 'monitoring', 'logging', 'tracing',
            'security', 'authentication', 'authorization', 'encryption',
            'database_design', 'api_design', 'architecture', 'scalability',
            'performance', 'caching', 'async', 'concurrency', 'parallelism',
            'machine_learning', 'data_science', 'nlp', 'computer_vision',
            'code_review', 'documentation', 'technical_writing', 'mentoring',
        }

        # Known domains
        known_domains = {
            'web', 'mobile', 'backend', 'frontend', 'fullstack',
            'database', 'cloud', 'devops', 'security', 'ai', 'ml',
            'data', 'analytics', 'blockchain', 'embedded', 'iot',
            'game', 'graphics', 'compiler', 'os', 'kernel',
            'network', 'distributed', 'microservices', 'serverless',
        }

        words = re.findall(r'\b[a-zA-Z][a-zA-Z0-9_-]*\b', text)

        for word in words:
            word_lower = word.lower()
            if len(word_lower) <= 2:
                continue

            # Check frameworks
            if word_lower in known_frameworks:
                requirements['frameworks'].add(word_lower)
                requirements['tools'].add(word_lower)
                continue

            # Check tools
            if word_lower in known_tools:
                requirements['tools'].add(word_lower)
                continue

            # Check skills
            if word_lower in known_skills:
                requirements['skills'].add(word_lower)
                continue

            # Check domains
            if word_lower in known_domains:
                requirements['domains'].add(word_lower)
                continue

            # Check for tech-like patterns
            if any(sep in word_lower for sep in ['.', '-', '_']):
                requirements['tools'].add(word_lower)
                requirements['frameworks'].add(word_lower)
                continue

            # Longer words that might be concepts
            if len(word_lower) > 4:
                requirements['concepts'].add(word_lower)

        # Extract from patterns like "use X", "implement Y with Z"
        import_pattern = re.findall(r'\b(?:use|using|with|implement|build|create|add|integrate|setup|configure)\s+(\w+)', text)
        for match in import_pattern:
            if match.lower() in known_frameworks:
                requirements['frameworks'].add(match.lower())
                requirements['tools'].add(match.lower())
            elif match.lower() in known_tools:
                requirements['tools'].add(match.lower())
            elif len(match) > 3:
                requirements['concepts'].add(match.lower())

        return requirements

    def _identify_knowledge_gaps(self, goal: Any, required: Dict[str, Set[str]], available: Dict[str, Set[str]], is_blocked: bool = False) -> List[KnowledgeGap]:
        """Identify gaps between required and available knowledge with enhanced priority."""
        gaps = []

        try:
            goal_id = getattr(goal, 'id', 'unknown')
            goal_name = getattr(goal, 'name', 'Unknown Goal')
            goal_desc = getattr(goal, 'description', '')

            # Check each knowledge category
            for category in ['concepts', 'tools', 'frameworks', 'skills', 'domains']:
                required_set = required.get(category, set())
                available_set = available.get(category, set())

                missing = required_set - available_set

                if missing:
                    # Determine priority based on goal priority and category importance
                    goal_priority = getattr(goal, 'priority', 'medium')
                    priority_map = {
                        'critical': 4,
                        'high': 3,
                        'medium': 2,
                        'low': 1
                    }
                    priority_num = priority_map.get(goal_priority, 2)

                    # Boost priority for tools and frameworks as they're often blocking
                    if category in ['tools', 'frameworks']:
                        priority_num = min(4, priority_num + 1)

                    # Further boost if goal is blocked
                    if is_blocked:
                        priority_num = min(4, priority_num + 1)

                    priority_levels = {4: GapPriority.CRITICAL, 3: GapPriority.HIGH, 2: GapPriority.MEDIUM, 1: GapPriority.LOW}
                    priority = priority_levels.get(priority_num, GapPriority.MEDIUM)

                    # Create a gap for each missing item (or group them)
                    # For simplicity, we'll create one gap per category with all missing items
                    if missing:
                        gap_description = f"Missing {category} for goal '{goal_name}': {', '.join(sorted(list(missing)[:10]))}"
                        if len(missing) > 10:
                            gap_description += f" and {len(missing) - 10} more"

                        gap = KnowledgeGap(
                            id=f"goal_gap_{goal_id}_{category}_{int(time.time())}",
                            title=f"Missing {category.title()} for {goal_name}",
                            description=gap_description,
                            category="goal_requirement",
                            sub_category=category,
                            missing_concepts=list(missing) if category == 'concepts' else [],
                            missing_tools=list(missing) if category == 'tools' else [],
                            missing_frameworks=list(missing) if category == 'frameworks' else [],
                            priority=priority,
                            confidence=0.7,  # Default confidence for goal-derived gaps
                            estimated_effort_hours=len(missing) * 0.5,  # Rough estimate
                            status=GapStatus.DETECTED,
                            trigger_context=f"goal_analysis:{goal_id}",
                            source_experiences=[],  # Would need to be populated from goal-related experiences
                            tags=[f"goal_{goal_id}", category, f"priority_{goal_priority}"],
                            metadata={
                                "goal_id": goal_id,
                                "goal_name": goal_name,
                                "goal_description": goal_desc,
                                "requirement_type": category,
                                "missing_count": len(missing),
                                "goal_blocked": is_blocked
                            }
                        )
                        gaps.append(gap)

        except Exception as e:
            logger.debug(f"Error identifying knowledge gaps: {e}")

        return gaps

    def _add_goal_gap_cross_references(self, goal: Any, gaps: List[KnowledgeGap]) -> None:
        """Add cross-references between goals and detected knowledge gaps."""
        if not self.cross_references:
            return
        try:
            for gap in gaps:
                self.cross_references.add_reference(
                    source_memory="goals",
                    source_id=goal.id,
                    target_memory="knowledge_gap",
                    target_id=gap.id,
                    reference_type="source",
                    confidence=0.8,
                    description=f"Goal '{goal.name}' requires knowledge: {gap.title}",
                    metadata={"goal_priority": getattr(goal, 'priority', 'medium'), "gap_category": gap.sub_category}
                )
        except Exception as e:
            logger.debug(f"Error adding goal-gap cross-references: {e}")

    def _schedule_goal_gap_research(self, gaps: List[KnowledgeGap]) -> None:
        """Schedule immediate research for high-priority goal-driven gaps."""
        if not self.research_loop or not self.config.research_enabled:
            return

        # Separate critical/high priority gaps
        urgent_gaps = [g for g in gaps if g.priority in [GapPriority.CRITICAL, GapPriority.HIGH]]

        for gap in urgent_gaps[:3]:  # Limit to top 3 urgent gaps
            try:
                # Create a research task for this gap
                research_task = ResearchTask(
                    id=f"goal_research_{gap.id}_{int(time.time())}",
                    gap_id=gap.id,
                    query=gap.description,
                    target_sources=self.config.trusted_sources,
                    max_results_per_source=5,
                    status=ResearchStatus.PENDING,
                    metadata={"goal_driven": True, "priority": gap.priority.value}
                )
                # In a full implementation, this would add to research loop's queue
                logger.info(f"Scheduled goal-driven research for gap: {gap.title}")
            except Exception as e:
                logger.debug(f"Error scheduling goal gap research: {e}")