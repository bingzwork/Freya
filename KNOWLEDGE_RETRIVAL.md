# Knowledge Retrieval

## Status
✅ **IMPLEMENTED**

## Overview
Knowledge Retrieval allows Freya to search, rank, and reuse stored knowledge before acquiring new information. It provides a unified interface that queries multiple knowledge sources, applies confidence calibration, ranks results using a multi-signal ranking engine, and tracks usage analytics for continuous improvement.

## Core Responsibilities
- Search across all knowledge sources (semantic memory, episodic memory, project memory, working memory, conversation memory, long-term memory, experience memory, engineering lessons, extracted knowledge, documentation, external knowledge, user knowledge)
- Rank results by relevance, confidence, source quality, usage frequency, recency, completeness, reliability, freshness, and historical usefulness
- Calibrate confidence scores for better decision making
- Track real-time usage analytics to continuously refine ranking weights
- Detect insufficient knowledge and trigger acquisition only when needed
- Return the best matching knowledge with detailed ranking explanation

## Workflow
1. **Analyze Request** – Understand the user's intent and create a RetrievalQuery
2. **Search Knowledge Sources** – Query all available knowledge source adapters
3. **Calibrate Confidence** – Apply statistical calibration to raw confidence scores
4. **Rank Results** – Combine multiple ranking signals into a single score using unified ranking formula
5. **Make Decision** – Determine if knowledge is sufficient (USE_DIRECTLY, USE_WITH_CAUTION, ACQUIRE_MORE, ASK_USER, NO_KNOWLEDGE)
6. **Return Knowledge** – Provide ranked results with explanations and metadata
7. **Track Analytics** – Record usage events for continuous improvement

## Search Methods
| Method | Description |
|--------|-------------|
| **Topic Search** | Exact topic lookup (e.g., "OAuth") |
| **Keyword Search** | Match important keywords (e.g., "auth token") |
| **Semantic Search** | Find concepts with similar meaning, even if wording differs |
| **Related Topic Search** | Return closely related subjects (e.g., "JWT" → "OAuth") |

## Ranking Signals
The unified ranking engine combines the following signals with configurable weights:

| Signal | Weight | Description |
|--------|--------|-------------|
| **Relevance** | 30% | Semantic/keyword match to query |
| **Confidence** | 20% | Calibrated confidence of the knowledge |
| **Source Quality** | 15% | Trustworthiness of source type |
| **Usage Frequency** | 10% | How often this knowledge is accessed |
| **Recency** | 10% | How recently knowledge was updated |
| **Completeness** | 5% | Content richness (summary, tags, examples, etc.) |
| **Reliability** | 5% | Historical accuracy of this source |
| **Freshness** | 3% | How fresh/up-to-date (faster decay than recency) |
| **Historical Usefulness** | 2% | Past utility in solving problems |

## Confidence Calibration
Three calibration methods are implemented:

- **Isotonic Regression** (default) - Non-parametric, monotonic calibration using PAVA algorithm
- **Platt Scaling** - Sigmoid/Logistic regression calibration
- **Temperature Scaling** - Single parameter scaling of logits
- **No Op** - Passthrough (for disabled calibration)

Calibration improves downstream decisions:
- **High Confidence** (≥ 90%) → Use knowledge directly
- **Medium Confidence** (70-89%) → Use with caution; may add context
- **Low Confidence** (< 70%) → Trigger Knowledge Acquisition or ask user

## Retrieval Decision
| Decision | Condition | Action |
|----------|-----------|--------|
| **USE_DIRECTLY** | Confidence ≥ 90% | Return knowledge as-is |
| **USE_WITH_CAUTION** | Confidence 70-89% | Use with added context |
| **ACQUIRE_MORE** | Confidence < 70% | Trigger Knowledge Acquisition |
| **ASK_USER** | Ambiguous confidence | Request clarification |
| **NO_KNOWLEDGE** | No results found | Initiate acquisition workflow |

## Real-Time Usage Analytics
Tracks how retrieved knowledge is used:
- Retrieval frequency per result/source
- Selection rate (top result vs ignored)
- User feedback (positive/negative)
- Task success/failure attribution
- Query pattern analysis

Analytics drive adaptive ranking:
- Weights automatically adjust based on feedback correlation
- Source reliability scores updated from task outcomes
- Usefulness scores computed per result

## Implementation Summary
- **Implementation:** Complete
- **Priority:** ⭐⭐⭐⭐⭐ Critical
- **Location:** `app/knowledge_retrieval/`
- **Tests:** `tests/test_knowledge_retrieval.py` (27 tests passing)

## Architecture

### Core Components

#### KnowledgeRetrievalPipeline (`app/knowledge_retrieval/pipeline.py`)
Main orchestrator that coordinates the complete retrieval process:
- Multi-source retrieval via registered adapters
- Confidence calibration integration
- Unified ranking with detailed explanations
- Usage analytics tracking
- Retrieval decision logic
- Statistics and monitoring

#### RankingEngine / AdaptiveRankingEngine (`app/knowledge_retrieval/ranking.py`)
Unified ranking engine:
- Combines 9 ranking signals into single score
- Configurable weights per signal
- Source quality scores per source type
- Detailed ranking explanations
- Adaptive version adjusts weights from feedback

#### CalibrationManager (`app/knowledge_retrieval/calibration.py`)
Statistical confidence calibration:
- Multiple methods: Isotonic, Platt, Temperature, Beta
- Per-source calibration data
- Persistent storage
- Minimum sample requirements

#### UsageAnalytics (`app/knowledge_retrieval/analytics.py`)
Real-time usage tracking:
- Event recording (retrieved, selected, ignored, feedback, task outcome)
- Result-level statistics (selection rate, usefulness score)
- Source-level statistics
- Query analytics
- Persistent storage with auto-save

#### KnowledgeSourceAdapter (`app/knowledge_retrieval/sources.py`)
Adapter pattern for knowledge sources:
| Adapter | Source Type | Description |
|---------|-------------|-------------|
| SemanticMemoryAdapter | SEMANTIC_MEMORY | General programming knowledge |
| EpisodicMemoryAdapter | EPISODIC_MEMORY | Event history with outcomes |
| ProjectMemoryAdapter | PROJECT_MEMORY | Project-specific knowledge |
| WorkingMemoryAdapter | WORKING_MEMORY | Current execution context |
| LongTermMemoryAdapter | LONG_TERM_MEMORY | User preferences, permanent facts |
| ExperienceMemoryAdapter | EXPERIENCE_MEMORY | Past task experiences |
| EngineeringLessonsAdapter | ENGINEERING_LESSONS | Patterns and anti-patterns |
| ExtractedKnowledgeAdapter | EXTRACTED_KNOWLEDGE | From knowledge_extraction pipeline |
| DocumentationAdapter | DOCUMENTATION | Markdown/RST docs |

## Usage Examples

### Basic Retrieval
```python
from app.knowledge_retrieval import (
    KnowledgeRetrievalPipeline,
    RetrievalQuery,
    KnowledgeSourceType,
)
from app.knowledge_retrieval.sources import create_adapters_from_agent

# Create pipeline with adapters from agent
pipeline = create_pipeline_from_agent(agent)

# Query
query = RetrievalQuery(
    query="How to implement singleton pattern in Python?",
    max_results=5,
    boost_category="design_pattern",
    boost_language="python",
)
response = pipeline.retrieve(query)

# Get top result
if response.results:
    best = response.results[0]
    print(f"Decision: {response.decision.value}")
    print(f"Score: {best.rank_score:.3f}")
    print(f"Confidence: {best.calibrated_confidence:.3f}")
    print(best.content)
```

### With Custom Adapters
```python
from app.knowledge_retrieval import KnowledgeRetrievalPipeline
from app.knowledge_retrieval.sources import SemanticMemoryAdapter
from app.memory.semantic_memory import create_semantic_memory

semantic = create_semantic_memory(workspace=".")
pipeline = KnowledgeRetrievalPipeline()
pipeline.register_adapter(SemanticMemoryAdapter(semantic))

response = pipeline.retrieve("decorator pattern")
```

### Recording Usage Feedback
```python
# After using a result
pipeline.record_selection(
    result_id=best.retrieval_id,
    source_type=best.source_type,
    rank_position=1,
    rank_score=best.rank_score,
    query=query.query,
)

# Positive/negative feedback
pipeline.record_feedback(
    result_id=best.retrieval_id,
    source_type=best.source_type,
    positive=True,  # or False
    query=query.query,
)

# Task outcome
pipeline.record_task_outcome(
    result_id=best.retrieval_id,
    source_type=best.source_type,
    success=True,  # or False
)
```

## Configuration
The RankingConfig allows full customization:
```python
from app.knowledge_retrieval import RankingConfig

config = RankingConfig(
    weights={
        RankingSignal.RELEVANCE: 0.35,
        RankingSignal.CONFIDENCE: 0.25,
        # ... adjust weights
    },
    source_quality_scores={
        KnowledgeSourceType.SEMANTIC_MEMORY: 0.95,
        # ... adjust per source
    },
    calibration_method="isotonic",
    use_directly_threshold=0.90,
    use_with_caution_threshold=0.70,
    adaptation_enabled=True,
)
```

## Extensibility

### Adding New Ranking Signals
```python
from app.knowledge_retrieval.ranking import RankingEngine, RankingSignal

engine = RankingEngine()

def my_custom_signal(result, query, analytics):
    # Compute value 0-1
    return 0.5, {"custom_data": "value"}

engine.register_calculator(RankingSignal.HISTORICAL_USEFULNESS, my_custom_signal)
```

### Adding New Knowledge Sources
```python
from app.knowledge_retrieval.sources import KnowledgeSourceAdapter
from app.knowledge_retrieval.models import KnowledgeSourceType

class MyCustomAdapter(KnowledgeSourceAdapter):
    @property
    def source_type(self) -> KnowledgeSourceType:
        return KnowledgeSourceType.EXTERNAL_KNOWLEDGE

    def is_available(self) -> bool:
        return True

    def retrieve_candidates(self, query, max_results=50):
        # Your retrieval logic
        return []

    def get_source_quality(self) -> float:
        return 0.7

pipeline.register_adapter(MyCustomAdapter())
```

### Adding New Calibration Methods
Subclass `Calibrator` base class and implement:
- `calibrate(confidence, source_type)`
- `update(predicted, actual, source_type)`
- `get_metadata(confidence)`

## Integration Points
Knowledge Retrieval integrates with:
- **Natural Conversation** - Answer knowledge questions from stored knowledge
- **Planning & Reasoning** - Retrieve relevant patterns, best practices, and experiences
- **Memory** - Unified access to all memory systems (semantic, episodic, working, etc.)
- **Decision Making** - Provide ranked knowledge for informed decisions
- **Reflection** - Access past experiences and lessons for analysis
- **Autonomous Learning** - Find existing knowledge before acquiring new
- **Knowledge Acquisition** - Trigger acquisition when retrieval confidence is low
- **Knowledge Validation** - Provide retrieved knowledge for validation
- **Software Engineering** - Retrieve engineering lessons and patterns
- **Tool Ecosystem** - As a tool for knowledge queries

## Error Handling
- Empty knowledge sources handled gracefully
- Unavailable adapters skipped with logging
- Corrupted entries ignored
- Invalid ranking data defaults to neutral scores
- Missing confidence values default to 0.5
- Pipeline never crashes - returns empty results with NO_KNOWLEDGE decision

## Current Limitations
1. **No semantic vector search** - Currently uses keyword/phrase matching; could integrate with FAISS
2. **No cross-project retrieval** - Single workspace only
3. **No UI dashboard** - Analytics accessible only programmatically
4. **Calibration requires minimum samples** - Needs ~20 observations per source
5. **Adaptation is simple** - Gradient-like weight adjustment only

## Future Enhancements
- Semantic vector search integration
- Multi-project/federated retrieval
- Retrieval UI dashboard for observability
- More sophisticated adaptive ranking (bandit algorithms)
- Query expansion and reformulation
- Knowledge graph traversal for related topics
- Personalized ranking per user/context

## Success Criteria Met
✅ Unified Retrieval Ranking Engine fully functional
✅ Retrieval results from multiple sources merged into one ranked list
✅ Ranking combines relevance, confidence, usage, source quality, recency, completeness, reliability, freshness, historical usefulness
✅ Confidence calibration improves decision quality (isotonic, Platt, temperature scaling)
✅ Real-time usage analytics continuously refine ranking weights
✅ Highest ranked result consistently matches user intent
✅ Errors handled gracefully
✅ Architecture modular and extensible (adapter pattern, plugin calculators)
✅ Existing architecture compatible (integrates with memory systems, agent)
✅ Tests pass (27 tests)
✅ Documentation updated

---

*Last Updated: 2026-07-31 - Implementation Complete*