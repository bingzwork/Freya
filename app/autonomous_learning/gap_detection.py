"""Knowledge Gap Detection

This module identifies knowledge gaps in the system by analyzing experiences,
identifying missing concepts, tools, frameworks, and determining priorities
for autonomous research.
"""

import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Set, Tuple
from enum import Enum

from app.memory.experience_memory import ExperienceMemory, ExperienceEntry
from app.memory.engineering_lessons import EngineeringLessonStorage, EngineeringLesson
from app.memory.long_term_memory import LongTermMemory, LongTermEntry
from app.memory.semantic_memory import SemanticMemory, SemanticEntry
from app.core.logger import logger
from app.autonomous_learning.models import (
    KnowledgeGap,
    GapPriority,
    GapStatus,
    AutonomousLearningConfig
)


class GapDetectionStrategy(Enum):
    """Strategies for detecting knowledge gaps."""
    EXPERIODIC = "periodic"
    EXPERIENCE_TRIGGERED = "experience_triggered"
    GOAL_TRIGGERED = "goal_triggered"
    MANUAL = "manual"


class KnowledgeGapDetector:
    """Detects knowledge gaps by analyzing experiences and system state.

    Identifies missing knowledge by examining:
    - Patterns in failed experiences
    - Missing concepts/tools/frameworks in successful experiences
    - Trends in experience categories that lack sufficient knowledge
    - Explicit knowledge requests or failures
    """

    def __init__(
        self,
        experience_memory: ExperienceMemory,
        engineering_lessons: EngineeringLessonStorage,
        long_term_memory: LongTermMemory,
        semantic_memory: SemanticMemory,
        config: Optional[AutonomousLearningConfig] = None,
    ):
        """Initialize the knowledge gap detector.

        Args:
            experience_memory: Storage for experiences
            engineering_lessons: Storage for engineering lessons
            long_term_memory: Storage for long-term knowledge
            semantic_memory: Storage for semantic knowledge
            config: Detector configuration
        """
        self.experience_memory = experience_memory
        self.engineering_lessons = engineering_lessons
        self.long_term_memory = long_term_memory
        self.semantic_memory = semantic_memory
        self.config = config or AutonomousLearningConfig()

        # Cache for performance
        self._last_detection_time: Optional[datetime] = None
        self._cached_gaps: List[KnowledgeGap] = []

    def detect_gaps(self, since_time: Optional[datetime] = None) -> List[KnowledgeGap]:
        """Detect knowledge gaps in the system.

        Args:
            since_time: Only consider experiences since this time (None for all)

        Returns:
            List of detected KnowledgeGap objects
        """
        try:
            logger.debug("Starting knowledge gap detection")

            # Clear previous gaps if doing full detection
            if since_time is None:
                self._cached_gaps = []

            # Get experiences to analyze
            experiences = self._get_experiences_for_analysis(since_time)
            if not experiences:
                logger.debug("No experiences found for gap analysis")
                return self._cached_gaps

            # Analyze experiences for gaps
            gaps = self._analyze_experiences_for_gaps(experiences)

            # Analyze system state for gaps
            system_gaps = self._analyze_system_state_for_gaps()
            gaps.extend(system_gaps)

            # Deduplicate and prioritize gaps
            unique_gaps = self._deduplicate_and_prioritize_gaps(gaps)

            # Apply limits
            max_gaps = self.config.max_gaps_per_run
            if len(unique_gaps) > max_gaps:
                unique_gaps = sorted(
                    unique_gaps,
                    key=lambda g: (g.priority.value, g.confidence),
                    reverse=True
                )[:max_gaps]

            self._cached_gaps.extend(unique_gaps)
            self._last_detection_time = datetime.now(timezone.utc)

            logger.info(f"Detected {len(unique_gaps)} new knowledge gaps")
            return unique_gaps

        except Exception as e:
            logger.error(f"Error detecting knowledge gaps: {e}")
            return []

    def _get_experiences_for_analysis(self, since_time: Optional[datetime]) -> List[ExperienceEntry]:
        """Get experiences for gap analysis.

        Args:
            since_time: Only return experiences after this time

        Returns:
            List of ExperienceEntry objects
        """
        try:
            if since_time:
                # Get experiences since specified time
                all_experiences = self.experience_memory.all()
                filtered_experiences = [
                    exp for exp in all_experiences
                    if datetime.fromisoformat(exp.timestamp.replace('Z', '+00:00')) > since_time
                ]
                return filtered_experiences
            elif self._last_detection_time:
                # Get experiences since last detection
                all_experiences = self.experience_memory.all()
                filtered_experiences = [
                    exp for exp in all_experiences
                    if datetime.fromisoformat(exp.timestamp.replace('Z', '+00:00')) > self._last_detection_time
                ]
                return filtered_experiences
            else:
                # First run - get recent experiences
                return self.experience_memory.recent(limit=100)
        except Exception as e:
            logger.error(f"Error retrieving experiences for gap analysis: {e}")
            return []

    def _analyze_experiences_for_gaps(self, experiences: List[ExperienceEntry]) -> List[KnowledgeGap]:
        """Analyze experiences to identify knowledge gaps.

        Args:
            experiences: List of experiences to analyze

        Returns:
            List of detected KnowledgeGap objects
        """
        gaps = []

        try:
            # Group experiences by outcome and category
            negative_experiences = [exp for exp in experiences if exp.outcome == "negative"]
            positive_experiences = [exp for exp in experiences if exp.outcome == "positive"]

            # Detect gaps from negative experiences (failures)
            failure_gaps = self._detect_gaps_from_failures(negative_experiences)
            gaps.extend(failure_gaps)

            # Detect gaps from positive experiences (missing optimizations)
            optimization_gaps = self._detect_gaps_from_optimizations(positive_experiences)
            gaps.extend(optimization_gaps)

            # Detect experience patterns that suggest missing knowledge
            pattern_gaps = self._detect_gaps_from_patterns(experiences)
            gaps.extend(pattern_gaps)

            # Detect explicit knowledge needs from experience metadata
            explicit_gaps = self._detect_explicit_knowledge_needs(experiences)
            gaps.extend(explicit_gaps)

        except Exception as e:
            logger.error(f"Error analyzing experiences for gaps: {e}")

        return gaps

    def _detect_gaps_from_failures(self, failures: List[ExperienceEntry]) -> List[KnowledgeGap]:
        """Detect knowledge gaps from failed experiences.

        Args:
            failures: List of failed experiences

        Returns:
            List of KnowledgeGap objects from failures
        """
        gaps = []

        try:
            # Group failures by category/tags
            failure_patterns = defaultdict(list)
            for exp in failures:
                # Use category, tags, or title to group similar failures
                key = exp.category or "_".join(exp.tags[:2]) if exp.tags else "unknown"
                failure_patterns[key].append(exp)

            # For each pattern, if it occurs frequently, suggest a gap
            for pattern_key, pattern_failures in failure_patterns.items():
                if len(pattern_failures) >= 2:  # At least 2 similar failures
                    # Analyze what's missing
                    missing_concepts, missing_tools, missing_frameworks = self._analyze_failure_pattern(pattern_failures)

                    if missing_concepts or missing_tools or missing_frameworks:
                        gap = KnowledgeGap(
                            title=f"Recurring failures in {pattern_key}",
                            description=f"Experienced {len(pattern_failures)} similar failures suggesting missing knowledge in {pattern_key}",
                            category="failure_pattern",
                            sub_category=pattern_key,
                            missing_concepts=missing_concepts,
                            missing_tools=missing_tools,
                            missing_frameworks=missing_frameworks,
                            priority=self._calculate_failure_priority(pattern_failures),
                            confidence=min(0.9, 0.5 + (len(pattern_failures) * 0.1)),
                            estimated_effort_hours=len(pattern_failures) * 0.5,
                            status=GapStatus.DETECTED,
                            trigger_context="failure_analysis",
                            source_experiences=[exp.id for exp in pattern_failures],
                            tags=["failure_based", pattern_key]
                        )
                        gaps.append(gap)

        except Exception as e:
            logger.error(f"Error detecting gaps from failures: {e}")

        return gaps

    def _analyze_failure_pattern(self, failures: List[ExperienceEntry]) -> Tuple[List[str], List[str], List[str]]:
        """Analyze a pattern of failures to determine what knowledge is missing.

        Args:
            failures: List of failed experiences with similar patterns

        Returns:
            Tuple of (missing_concepts, missing_tools, missing_frameworks)
        """
        missing_concepts = set()
        missing_tools = set()
        missing_frameworks = set()

        try:
            # Look for common themes in failure descriptions and metadata
            all_descriptions = " ".join([exp.description.lower() for exp in failures if exp.description])
            all_tags = []
            for exp in failures:
                all_tags.extend(exp.tags)

            # Simple keyword-based detection (could be enhanced with NLP)
            concept_indicators = ["concept", "theory", "principle", "understanding", "know how"]
            tool_indicators = ["tool", "utility", "program", "application", "software"]
            framework_indicators = ["framework", "library", "platform", "sdk", "api"]

            for indicator in concept_indicators:
                if indicator in all_descriptions:
                    missing_concepts.add(f"Understanding of {indicator} related to failures")

            for indicator in tool_indicators:
                if indicator in all_descriptions:
                    missing_tools.add(f"Tool for {indicator}")

            for indicator in framework_indicators:
                if indicator in all_descriptions:
                    missing_frameworks.add(f"Framework for {indicator}")

            # Look at metadata for explicit missing items
            for exp in failures:
                metadata = exp.metadata
                if isinstance(metadata, dict):
                    if "missing_knowledge" in metadata:
                        missing_items = metadata["missing_knowledge"]
                        if isinstance(missing_items, list):
                            for item in missing_items:
                                if isinstance(item, str):
                                    if any(word in item.lower() for word in ["concept", "theory", "principle"]):
                                        missing_concepts.add(item)
                                    elif any(word in item.lower() for word in ["tool", "utility", "program"]):
                                        missing_tools.add(item)
                                    elif any(word in item.lower() for word in ["framework", "library", "platform"]):
                                        missing_frameworks.add(item)
                                    else:
                                        # Default to concept
                                        missing_concepts.add(item)

        except Exception as e:
            logger.error(f"Error analyzing failure pattern: {e}")

        return (list(missing_concepts), list(missing_tools), list(missing_frameworks))

    def _detect_gaps_from_optimizations(self, positives: List[ExperienceEntry]) -> List[KnowledgeGap]:
        """Detect knowledge gaps from successful experiences that could be optimized.

        Args:
            positives: List of successful experiences

        Returns:
            List of KnowledgeGap objects from optimization opportunities
        """
        gaps = []

        try:
            # Look for successful experiences that took many steps or replans
            # These might indicate missing knowledge that could make them more efficient
            inefficient_successes = [
                exp for exp in positives
                if exp.metadata.get("iterations", 0) > 3 or exp.metadata.get("replans", 0) > 1
            ]

            for exp in inefficient_successes:
                # Suggest that better knowledge could make this more efficient
                gap = KnowledgeGap(
                    title=f"Optimization opportunity: {exp.title}",
                    description=f"Successful experience required {exp.metadata.get('iterations', 0)} iterations suggesting missing efficient approach knowledge",
                    category="optimization",
                    sub_category=exp.category or "general",
                    missing_concepts=[f"More efficient approach for {exp.category or 'task type'}"],
                    missing_tools=[],
                    missing_frameworks=[],
                    priority=GapPriority.LOW,
                    confidence=0.4,
                    estimated_effort_hours=1.0,
                    status=GapStatus.DETECTED,
                    trigger_context="optimization_analysis",
                    source_experiences=[exp.id],
                    tags=["optimization", "efficiency"]
                )
                gaps.append(gap)

        except Exception as e:
            logger.error(f"Error detecting gaps from optimizations: {e}")

        return gaps

    def _detect_gaps_from_patterns(self, experiences: List[ExperienceEntry]) -> List[KnowledgeGap]:
        """Detect gaps from experience patterns and trends.

        Args:
            experiences: List of experiences to analyze

        Returns:
            List of KnowledgeGap objects from pattern analysis
        """
        gaps = []

        try:
            # Analyze experience categories to see which have low success rates
            category_stats = defaultdict(lambda: {"total": 0, "success": 0})

            for exp in experiences:
                category = exp.category or "unknown"
                category_stats[category]["total"] += 1
                if exp.outcome == "positive":
                    category_stats[category]["success"] += 1

            # Find categories with low success rates
            for category, stats in category_stats.items():
                if stats["total"] >= 3:  # Need sufficient sample size
                    success_rate = stats["success"] / stats["total"]
                    if success_rate < 0.5:  # Less than 50% success rate
                        gap = KnowledgeGap(
                            title=f"Low success rate in {category} tasks",
                            description=f"Category '{category}' has only {success_rate:.1%} success rate ({stats['success']}/{stats['total']})",
                            category="success_rate",
                            sub_category=category,
                            missing_concepts=[f"Effective techniques for {category} tasks"],
                            missing_tools=[f"Better tools for {category}"],
                            missing_frameworks=[f"Established frameworks for {category}"],
                            priority=GapPriority.MEDIUM if success_rate < 0.3 else GapPriority.LOW,
                            confidence=0.7,
                            estimated_effort_hours=2.0,
                            status=GapStatus.DETECTED,
                            trigger_context="success_rate_analysis",
                            tags=["low_success_rate", category]
                        )
                        gaps.append(gap)

        except Exception as e:
            logger.error(f"Error detecting gaps from patterns: {e}")

        return gaps

    def _detect_explicit_knowledge_needs(self, experiences: List[ExperienceEntry]) -> List[KnowledgeGap]:
        """Detect explicit knowledge needs from experience metadata.

        Args:
            experiences: List of experiences to analyze

        Returns:
            List of KnowledgeGap objects from explicit needs
        """
        gaps = []

        try:
            for exp in experiences:
                metadata = exp.metadata
                if isinstance(metadata, dict):
                    # Check for explicit knowledge requests
                    if metadata.get("needs_research") or metadata.get("knowledge_gap"):
                        gap = KnowledgeGap(
                            title=f"Explicit knowledge need: {exp.title}",
                            description=metadata.get("gap_description", f"Experience {exp.title} indicates missing knowledge"),
                            category="explicit_request",
                            sub_category=exp.category or "general",
                            missing_concepts=metadata.get("missing_concepts", []),
                            missing_tools=metadata.get("missing_tools", []),
                            missing_frameworks=metadata.get("missing_frameworks", []),
                            priority=GapPriority.HIGH if metadata.get("urgent") else GapPriority.MEDIUM,
                            confidence=0.8,
                            estimated_effort_hours=metadata.get("estimated_effort", 2.0),
                            status=GapStatus.DETECTED,
                            trigger_context="explicit_request",
                            source_experiences=[exp.id],
                            tags=["explicit_request"]
                        )
                        gaps.append(gap)

        except Exception as e:
            logger.error(f"Error detecting explicit knowledge needs: {e}")

        return gaps

    def _analyze_system_state_for_gaps(self) -> List[KnowledgeGap]:
        """Analyze current system state for knowledge gaps.

        Returns:
            List of KnowledgeGap objects from system analysis
        """
        gaps = []

        try:
            # Check for imbalances in knowledge coverage
            # For example, if we have lots of experience in an area but little knowledge stored

            # Get recent experiences
            recent_experiences = self.experience_memory.recent(limit=50)

            # Get stored knowledge
            recent_lessons = self.engineering_lessons.recent(limit=50)
            recent_semantic = []
            try:
                recent_semantic = list(self.semantic_memory.all().values())[:50] if hasattr(self.semantic_memory, 'all') else []
            except:
                pass

            # Categorize experiences
            exp_categories = defaultdict(int)
            for exp in recent_experiences:
                exp_categories[exp.category or "unknown"] += 1

            # Categorize lessons
            lesson_categories = defaultdict(int)
            for lesson in recent_lessons:
                lesson_categories[lesson.category or "unknown"] += 1

            # Find imbalances
            for exp_category, exp_count in exp_categories.items():
                lesson_count = lesson_categories.get(exp_category, 0)
                ratio = lesson_count / max(exp_count, 1)

                # If we have much more experience than lessons, there might be a gap
                if exp_count >= 5 and ratio < 0.2:  # Much more experience than documented knowledge
                    gap = KnowledgeGap(
                        title=f"Knowledge documentation gap for {exp_category}",
                        description=f"Have {exp_count} experiences in {exp_category} but only {lesson_count} documented lessons",
                        category="documentation_gap",
                        sub_category=exp_category,
                        missing_concepts=[f"Best practices for {exp_category}"],
                        missing_tools=[f"Recommended tools for {exp_category}"],
                        missing_frameworks=[f"Standard frameworks for {exp_category}"],
                        priority=GapPriority.MEDIUM,
                        confidence=0.6,
                        estimated_effort_hours=exp_count * 0.2,
                        status=GapStatus.DETECTED,
                        trigger_context="documentation_imbalance",
                        tags=["documentation_gap", exp_category]
                    )
                    gaps.append(gap)

        except Exception as e:
            logger.error(f"Error analyzing system state for gaps: {e}")

        return gaps

    def _calculate_failure_priority(self, failures: List[ExperienceEntry]) -> GapPriority:
        """Calculate priority for a failure-based gap.

        Args:
            failures: List of failed experiences

        Returns:
            GapPriority level
        """
        try:
            # Check if any failures are blocking or critical
            blocking_indicators = ["block", "critical", "urgent", "break", "fail"]
            high_priority_count = 0

            for exp in failures:
                description_lower = (exp.description or "").lower()
                title_lower = (exp.title or "").lower()
                combined_text = description_lower + " " + title_lower

                if any(indicator in combined_text for indicator in blocking_indicators):
                    high_priority_count += 1
                # Also check metadata for priority indicators
                metadata = exp.metadata
                if isinstance(metadata, dict):
                    if metadata.get("blocking") or metadata.get("priority") == "high":
                        high_priority_count += 1

            if high_priority_count >= len(failures) * 0.5:
                return GapPriority.CRITICAL
            elif high_priority_count >= len(failures) * 0.3:
                return GapPriority.HIGH
            elif len(failures) >= 5:
                return GapPriority.MEDIUM
            else:
                return GapPriority.LOW

        except Exception as e:
            logger.error(f"Error calculating failure priority: {e}")
            return GapPriority.MEDIUM

    def _deduplicate_and_prioritize_gaps(self, gaps: List[KnowledgeGap]) -> List[KnowledgeGap]:
        """Deduplicate gaps and prioritize them.

        Args:
            gaps: List of detected gaps (may contain duplicates)

        Returns:
            List of unique, prioritized gaps
        """
        try:
            if not gaps:
                return gaps

            # Simple deduplication based on title similarity
            unique_gaps = []
            seen_titles = set()

            for gap in gaps:
                # Create a simplified title for comparison
                simple_title = gap.title.lower().strip()
                # Remove common variations
                simple_title = simple_title.replace("experience:", "").replace("knowledge need:", "").strip()

                if simple_title not in seen_titles and len(simple_title) > 5:
                    seen_titles.add(simple_title)
                    unique_gaps.append(gap)

            # Sort by priority and confidence
            priority_order = {
                GapPriority.CRITICAL: 4,
                GapPriority.HIGH: 3,
                GapPriority.MEDIUM: 2,
                GapPriority.LOW: 1
            }

            unique_gaps.sort(
                key=lambda g: (priority_order[g.priority], g.confidence),
                reverse=True
            )

            return unique_gaps

        except Exception as e:
            logger.error(f"Error deduplicating and prioritizing gaps: {e}")
            return gaps

    def get_gap_statistics(self) -> Dict[str, Any]:
        """Get statistics about detected gaps.

        Returns:
            Dictionary containing gap statistics
        """
        try:
            if not self._cached_gaps:
                return {
                    "total_gaps": 0,
                    "by_priority": {},
                    "by_status": {},
                    "by_category": {}
                }

            stats = {
                "total_gaps": len(self._cached_gaps),
                "by_priority": defaultdict(int),
                "by_status": defaultdict(int),
                "by_category": defaultdict(int)
            }

            for gap in self._cached_gaps:
                stats["by_priority"][gap.priority.value] += 1
                stats["by_status"][gap.status.value] += 1
                stats["by_category"][gap.category or "unknown"] += 1

            return dict(stats)

        except Exception as e:
            logger.error(f"Error getting gap statistics: {e}")
            return {"error": str(e)}