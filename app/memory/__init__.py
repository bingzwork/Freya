from app.memory.conversation_memory import ConversationMemory, ConversationTurn, ConversationSummary
from app.memory.engineering_lessons import EngineeringLessonStorage
from app.memory.episodic_memory import EpisodicMemory, EpisodicEvent, EventType, create_episodic_memory
from app.memory.experience_memory import ExperienceMemory
from app.memory.goals import Goal, GoalStorage, SubtaskSuggestion
from app.memory.long_term_memory import LongTermMemory, LongTermEntry, create_long_term_memory
from app.memory.preference_learning import (
    PreferenceCategory,
    PreferenceSource,
    UserPreference,
    PreferenceLearner,
    PreferenceApplier,
    get_preference_learner,
    get_preference_applier,
    learn_from_interaction,
    get_preference,
    set_preference,
    apply_preferences,
    reset_global_learner,
)
from app.memory.project_memory import ProjectMemory
from app.memory.semantic_memory import SemanticMemory, SemanticEntry, KnowledgeCategory, create_semantic_memory
from app.memory.task_memory import TaskMemory, TaskState, TaskStep, create_task_memory
from app.memory.unified_retrieval import UnifiedRetrieval, RetrievalQuery, RetrievalResult, create_unified_retrieval
from app.memory.working_memory import WorkingMemory, ExecutionPlan, ToolOutput, ReasoningStep

# Phase C: Memory Optimization
from app.memory.consolidation import (
    ConsolidationEngine,
    ConsolidationConfig,
    ConsolidationStats,
    ConsolidationTrigger,
    ImportanceScorer,
    DuplicateDetector,
    create_consolidation_engine,
)
from app.memory.forgetting import (
    ForgettingEngine,
    MemoryRetentionConfig,
    ForgettingStats,
    RetentionPolicy,
    create_forgetting_engine,
)
from app.memory.cross_references import (
    CrossMemoryReferences,
    CrossReference,
    ReferenceType,
    MemoryType,
    MemoryNode,
    create_cross_memory_references,
    link_experience_to_lesson,
    link_lesson_to_long_term,
    link_project_to_experience,
    link_episodic_to_lesson,
    link_goal_to_task,
    link_semantic_as_prerequisite,
)
from app.memory.retrieval_ranking import (
    RankingEngine,
    RankedResult,
    RankingConfig,
    RankingSignal,
    create_ranking_engine,
    RankedUnifiedRetrieval,
)

__all__ = [
    "ConversationMemory",
    "ConversationTurn",
    "ConversationSummary",
    "ProjectMemory",
    "ExperienceMemory",
    "EngineeringLessonStorage",
    "Goal",
    "GoalStorage",
    "SubtaskSuggestion",
    "WorkingMemory",
    "ExecutionPlan",
    "ToolOutput",
    "ReasoningStep",
    "UnifiedRetrieval",
    "RetrievalQuery",
    "RetrievalResult",
    "create_unified_retrieval",
    # Phase B: Extended Memory
    "TaskMemory",
    "TaskState",
    "TaskStep",
    "create_task_memory",
    "LongTermMemory",
    "LongTermEntry",
    "create_long_term_memory",
    "EpisodicMemory",
    "EpisodicEvent",
    "EventType",
    "create_episodic_memory",
    "SemanticMemory",
    "SemanticEntry",
    "KnowledgeCategory",
    "create_semantic_memory",
    # Preference Learning
    "PreferenceCategory",
    "PreferenceSource",
    "UserPreference",
    "PreferenceLearner",
    "PreferenceApplier",
    "get_preference_learner",
    "get_preference_applier",
    "learn_from_interaction",
    "get_preference",
    "set_preference",
    "apply_preferences",
    "reset_global_learner",
    # Phase C: Memory Optimization
    "ConsolidationEngine",
    "ConsolidationConfig",
    "ConsolidationStats",
    "ConsolidationTrigger",
    "ImportanceScorer",
    "DuplicateDetector",
    "create_consolidation_engine",
    "ForgettingEngine",
    "MemoryRetentionConfig",
    "ForgettingStats",
    "RetentionPolicy",
    "create_forgetting_engine",
    "CrossMemoryReferences",
    "CrossReference",
    "ReferenceType",
    "MemoryType",
    "MemoryNode",
    "create_cross_memory_references",
    "link_experience_to_lesson",
    "link_lesson_to_long_term",
    "link_project_to_experience",
    "link_episodic_to_lesson",
    "link_goal_to_task",
    "link_semantic_as_prerequisite",
    "RankingEngine",
    "RankedResult",
    "RankingConfig",
    "RankingSignal",
    "create_ranking_engine",
    "RankedUnifiedRetrieval",
]
