"""Autonomous Learning Pipeline - Orchestrates the end-to-end learning process.

This module implements the core autonomous learning pipeline that:
1. Analyzes experiences to extract learning opportunities
2. Extracts knowledge from experiences and other sources
3. Validates extracted knowledge before storage
4. Persists validated knowledge with provenance and confidence tracking
5. Detects knowledge gaps and triggers autonomous research
"""

import time
import threading
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Callable
from pathlib import Path

from app.core.logger import logger
from app.memory.experience_memory import ExperienceMemory, ExperienceEntry
from app.memory.engineering_lessons import EngineeringLessonStorage, EngineeringLesson
from app.memory.long_term_memory import LongTermMemory, LongTermEntry
from app.memory.semantic_memory import SemanticMemory, SemanticEntry
from app.memory.validation import KnowledgeValidator, ValidationResult, ValidationSourceType
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
from app.memory.cross_references import CrossMemoryReferences


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
        config: Optional[AutonomousLearningConfig] = None,
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
            config: Pipeline configuration
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
        self.config = config or AutonomousLearningConfig()

        # Pipeline state
        self._lock = threading.RLock()
        self._is_running = False
        self._last_run_time: Optional[datetime] = None

        # Statistics
        self.stats = LearningPipelineResult()

    def run_pipeline(self) -> LearningPipelineResult:
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

                # Step 5: Detect knowledge gaps
                if self.config.gap_detection_enabled:
                    self._detect_knowledge_gaps()

                # Step 6: Execute autonomous research to fill gaps
                if self.config.research_enabled:
                    self._execute_autonomous_research()

                # Update final statistics
                self.stats.duration_seconds = time.time() - start_time
                self._last_run_time = datetime.now(timezone.utc)

                # Log completion
                logger.info(
                    f"Autonomous learning pipeline completed in {self.stats.duration_seconds:.2f}s. "
                    f"Processed {self.stats.experiences_processed} experiences, "
                    f"extracted {self.stats.knowledge_objects_extracted := self.stats.knowledge_objects_extracted} knowledge objects, "
                    f"validated {self.stats.knowledge_objects_validated}, "
                    f"stored {self.stats.knowledge_objects_stored}, "
                    f"detected {self.stats.gaps_detected} gaps, "
                    f"started {self.stats.research_tasks_started} research tasks"
                )

                return self.stats

            except Exception as e:
                logger.error(f"Autonomous learning pipeline failed: {e}")
                self.stats.errors.append(f"Pipeline execution failed: {str(e)}")
                self.stats.duration_seconds = time.time() - start_time
                return self.stats
            finally:
                self._is_running = False

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

    def reset_stats(self) -> None:
        """Reset pipeline statistics."""
        with self._lock:
            self.stats = LearningPipelineResult()