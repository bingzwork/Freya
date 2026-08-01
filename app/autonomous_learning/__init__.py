"""
Autonomous Learning Package

This package provides the end-to-end autonomous learning pipeline that:
1. Collects experiences from task execution
2. Analyzes outcomes and extracts lessons
3. Validates knowledge before storage
4. Automatically persists validated knowledge with provenance
5. Detects knowledge gaps and triggers autonomous research
6. Runs as a background process for continuous learning

Components:
- AutonomousLearningPipeline: Main orchestrator for Experience → Extraction → Validation → Storage
- KnowledgeGapDetector: Detects missing knowledge categories, concepts, tools, frameworks
- AutonomousResearchLoop: Automatically searches, extracts, validates, and stores knowledge for gaps
- AutonomousLearningScheduler: Background scheduler for periodic autonomous learning runs
"""

from .models import (
    LearningPipelineResult,
    KnowledgeGap,
    GapPriority,
    GapStatus,
    ResearchTask,
    ResearchSource,
    ResearchStatus,
    LearningEvent,
    LearningEventType,
    AutonomousLearningConfig,
)
from .pipeline import AutonomousLearningPipeline
from .gap_detection import KnowledgeGapDetector
from .research_loop import AutonomousResearchLoop
from .scheduler import AutonomousLearningScheduler

__all__ = [
    "LearningPipelineResult",
    "KnowledgeGap",
    "GapPriority",
    "GapStatus",
    "ResearchTask",
    "ResearchSource",
    "ResearchStatus",
    "LearningEvent",
    "LearningEventType",
    "AutonomousLearningConfig",
    "AutonomousLearningPipeline",
    "KnowledgeGapDetector",
    "AutonomousResearchLoop",
    "AutonomousLearningScheduler",
]