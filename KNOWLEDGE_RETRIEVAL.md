# Knowledge Retrieval Capability

> **Status:** ✅ COMPLETE (100%)  
> **Priority:** ⭐⭐⭐⭐⭐ Critical  
> **Last Updated:** 2026-07-31  
> **Implementation:** `app/knowledge_retrieval/`  
> **Tests:** `tests/test_knowledge_retrieval.py` (27 passing)

---

## Overview

The Knowledge Retrieval capability provides a unified, intelligent system for finding, ranking, and returning the most useful knowledge from every available knowledge source in Freya. It gives Freya one reliable, ranked view of all available knowledge so that Planning, Reasoning, Memory, Decision Making, Autonomous Learning, Natural Conversation, and Autonomous Software Engineering always receive the best available information.

**This capability ONLY retrieves and ranks knowledge. It does NOT:**
- Acquire knowledge (Knowledge Acquisition)
- Extract knowledge (Knowledge Extraction)
- Validate knowledge (Knowledge Validation)
- Consolidate knowledge (Knowledge Maintenance)
- Generate new knowledge

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    KnowledgeRetrievalPipeline                       │
├─────────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌───────────────┐  ┌────────────┐  ┌──────────┐  │
│  │   Sources    │──▶│  Calibration  │──▶│  Ranking   │──▶│ Decision │  │
│  │  (Adapters)  │  │   Manager     │  │  Engine    │  │  Maker   │  │
│  └──────────────┘  └───────────────┘  └────────────┘  └──────────┘  │
│        ▲                                    │                  │     │
│        │                                    ▼                  ▼     │
│        └─────────────────────────────▶  Analytics  ◀───────────────┘  │
│              (feedback loop)           Tracking                        │
└─────────────────────────────────────────────────────────────────────┘
```

### Core Components

| Component | File | Purpose |
|-----------|------|---------|
| **KnowledgeRetrievalPipeline** | `pipeline.py` | Main orchestration: retrieval → calibration → ranking → decision → analytics |
| **RankingEngine** | `ranking.py` | Combines 9 ranking signals into single score (0-1) |
| **AdaptiveRankingEngine** | `ranking.py` | Learns optimal weights from usage feedback |
| **CalibrationManager** | `calibration.py` | Statistical calibration (Isotonic, Platt, Beta, Temperature) |
| **UsageAnalytics** | `analytics.py` | Real-time usage tracking, usefulness scoring, adaptation |
| **KnowledgeSourceAdapter** | `sources.py` | Abstract interface + 9 concrete adapters |

---

## Knowledge Sources Supported

The system supports 14 knowledge source types via adapters:

| Source Type | Adapter | Quality Score |
|-------------|---------|---------------|
| `SEMANTIC_MEMORY` | `SemanticMemoryAdapter` | 0.90 |
| `KNOWLEDGE_BASE` | — | 0.95 |
| `ENGINEERING_LESSONS` | `EngineeringLessonsAdapter` | 0.85 |
| `DOCUMENTATION` | `DocumentationAdapter` | 0.85 |
| `USER_KNOWLEDGE` | — | 0.90 |
| `LONG_TERM_MEMORY` | `LongTermMemoryAdapter` | 0.85 |
| `EXTRACTED_KNOWLEDGE` | `ExtractedKnowledgeAdapter` | 0.80 |
| `PROJECT_MEMORY` | `ProjectMemoryAdapter` | 0.80 |
| `WORKING_MEMORY` | `WorkingMemoryAdapter` | 0.75 |
| `EXPERIENCE_MEMORY` | `ExperienceMemoryAdapter` | 0.75 |
| `EPISODIC_MEMORY` | `EpisodicMemoryAdapter` | 0.70 |
| `CONVERSATION_MEMORY` | — | 0.65 |
| `EXTERNAL_KNOWLEDGE` | — | 0.60 |
| `UNKNOWN` | — | 0.50 |

---

## Unified Ranking Engine

The ranking engine combines **9 signals** into a single relevance score (0-1):

| Signal | Weight | Description |
|--------|--------|-------------|
| **RELEVANCE** | 30% | Semantic/keyword match to query (Jaccard + phrase bonus) |
| **CONFIDENCE** | 20% | Calibrated confidence score from source |
| **SOURCE_QUALITY** | 15% | Trustworthiness of the knowledge source |
| **USAGE_FREQUENCY** | 10% | How often this knowledge is accessed (log-scaled) |
| **RECENCY** | 10% | How recently knowledge was updated (exponential decay, 1yr half-life) |
| **COMPLETENESS** | 5% | Content richness (summary, tags, related concepts, length, category) |
| **RELIABILITY** | 5% | Historical accuracy of this source type |
| **FRESHNESS** | 3% | Faster decay for time-sensitive knowledge (1w=0.9, 1m=0.5, 6m=0.2) |
| **HISTORICAL_USEFULNESS** | 2% | Past utility in solving problems (from analytics) |

### Ranking Features

- **Transparent explanations**: Every ranked result includes per-factor breakdown
- **Extensible**: Register custom signal calculators via `register_calculator()`
- **Adaptive**: `AdaptiveRankingEngine` adjusts weights based on positive/negative feedback
- **MMR diversification**: Built-in Maximal Marginal Relevance for result diversity

### Ranking Explanation

```python
result.ranking_explanation.explain_simple()
# Total score: 0.847
#   relevance: 0.75 x 0.30 = 0.225
#   confidence: 0.90 x 0.20 = 0.180
#   source_quality: 0.90 x 0.15 = 0.135
#   ...
```

---

## Confidence Calibration

Calibration transforms raw confidence scores into statistically reliable probabilities, improving downstream decisions:

- **USE_DIRECTLY** (calibrated ≥ 0.90)
- **USE_WITH_CAUTION** (0.70 ≤ calibrated < 0.90)
- **ACQUIRE_MORE** (0.10 ≤ calibrated < 0.70)
- **ASK_USER** (ambiguous)
- **NO_KNOWLEDGE** (no results)

### Calibration Methods

| Method | Algorithm | Best For | Min Samples |
|--------|-----------|----------|-------------|
| **Isotonic** (default) | PAVA (Pool Adjacent Violators) | Non-parametric, monotonic calibration | 20 |
| **Platt** | Logistic regression (sigmoid) | Small datasets | 10 |
| **Beta** | Generalized Platt scaling | Flexible calibration curves | 15 |
| **Temperature** | Single-parameter logit scaling | Neural network outputs | 10 |
| **None** | Passthrough | Disabled / baseline | — |

### Features

- Per-source-type calibration data
- Persistent JSON storage with auto-save/load
- Minimum sample requirements before calibration activates
- Beta calibration for high-confidence scenarios
- Full metadata for debugging/transparency

---

## Real-Time Usage Analytics

The analytics system continuously tracks how retrieved knowledge is used to improve ranking:

### Tracked Events

- `retrieved` — Result appeared in retrieval results
- `selected` — User/system chose this result
- `ignored` — Result was presented but not used
- `feedback_positive` / `feedback_negative` — Explicit feedback
- `task_success` / `task_failure` — Downstream task outcome

### Derived Metrics

```python
# Per-result
selection_rate = selections / retrievals
success_rate = task_successes / (task_successes + task_failures)
usefulness_score = 0.3*selection + 0.4*feedback + 0.3*task_success

# Per-source
top_result_selection_rate
task_success_contribution
avg_calibrated_confidence
```

### Automatic Adaptation

`AdaptiveRankingEngine` adjusts signal weights based on feedback:
- Signals correlating with positive feedback → weight increased
- Signals correlating with negative feedback → weight decreased
- Renormalized after each adaptation cycle
- Configurable adaptation rate (default: 1%)

### Persistence

- Bounded in-memory storage (100k events)
- Periodic JSON persistence (every 100 events)
- Atomic writes via temp file + rename

---

## Retrieval Pipeline Flow

```python
from app.knowledge_retrieval import create_pipeline_from_agent, RetrievalQuery

# Create pipeline from Freya agent (auto-detects available memory systems)
pipeline = create_pipeline_from_agent(agent)

# Query
query = RetrievalQuery(
    query="How to implement singleton pattern in Python?",
    max_results=10,
    min_score=0.1,
    boost_category="best_practice",
    boost_language="python",
    context={"task_type": "implementation"},
)

# Retrieve
response = pipeline.retrieve(query)

# Results are ranked KnowledgeRetrievalResult objects
for result in response.results:
    print(f"Score: {result.rank_score:.3f}")
    print(f"Confidence: {result.calibrated_confidence:.3f}")
    print(f"Source: {result.source_type.value}")
    print(result.content[:200])
    print("---")

# Decision tells you what to do
print(f"Decision: {response.decision.value}")  # use_directly, use_with_caution, etc.
print(f"Reason: {response.decision_reason}")
```

### Decision Logic

| Top Result Score | Decision | Meaning |
|------------------|----------|---------|
| ≥ 0.90 | `USE_DIRECTLY` | High confidence, use as-is |
| 0.70–0.89 | `USE_WITH_CAUTION` | Medium confidence, add context |
| 0.10–0.69 | `ACQUIRE_MORE` | Low confidence, trigger acquisition |
| < 0.10 | `NO_KNOWLEDGE` | Nothing useful found |
| Ambiguous | `ASK_USER` | Need clarification |

---

## Adding New Knowledge Sources

### 1. Create Adapter

```python
from app.knowledge_retrieval.sources import KnowledgeSourceAdapter
from app.knowledge_retrieval.models import KnowledgeSourceType, KnowledgeRetrievalResult, RetrievalQuery

class MyCustomAdapter(KnowledgeSourceAdapter):
    @property
    def source_type(self) -> KnowledgeSourceType:
        return KnowledgeSourceType.EXTERNAL_KNOWLEDGE  # or add new enum value
    
    def is_available(self) -> bool:
        return self.my_client.is_connected()
    
    def retrieve_candidates(self, query: RetrievalQuery, max_results: int = 50) -> List[KnowledgeRetrievalResult]:
        # Query your source, convert to KnowledgeRetrievalResult
        results = []
        for item in my_source.search(query.query, limit=max_results):
            results.append(KnowledgeRetrievalResult(
                content=item.content,
                title=item.title,
                source_type=self.source_type,
                source_id=item.id,
                raw_confidence=item.confidence,
                category=item.category,
                tags=item.tags,
                last_updated=item.updated_at,
            ))
        return results
    
    def get_source_quality(self) -> float:
        return 0.75  # Trustworthiness 0-1
```

### 2. Register

```python
pipeline.register_adapter(MyCustomAdapter(my_client))
```

The engine automatically includes new sources in retrieval, ranking, and analytics.

---

## Adding New Ranking Signals

```python
from app.knowledge_retrieval.models import RankingSignal, RankingFactor
from app.knowledge_retrieval.ranking import RankingEngine

def my_custom_signal_calculator(result, query, analytics):
    # Compute signal value 0-1
    value = compute_my_signal(result, query)
    return value, {"my_metadata": "value"}

engine = RankingEngine()
engine.register_calculator(RankingSignal.RELEVANCE, my_custom_signal_calculator)
# Or add new signal to RankingSignal enum and config.weights
```

---

## Adding New Calibration Methods

```python
from app.knowledge_retrieval.calibration import Calibrator, CalibrationMethod

class MyCalibrator(Calibrator):
    def calibrate(self, confidence: float, source_type: str = None) -> float:
        return my_calibration_function(confidence)
    
    def update(self, predicted: float, actual: bool, source_type: str = None):
        # Learn from observations
        pass
    
    def get_metadata(self, confidence: float) -> dict:
        return {"method": "my_method"}

# Register in CalibrationManager._create_calibrator()
```

---

## Integration Points

| Capability | Integration |
|------------|-------------|
| **Natural Conversation** | `retrieve_knowledge()` for factual Q&A without planning |
| **Planning & Reasoning** | `pipeline.retrieve_for_planner()` injects ranked knowledge |
| **Memory System** | Adapters for all 9 memory types (semantic, episodic, project, etc.) |
| **Decision Making** | Calibrated confidence feeds `decide_context_sufficiency()` |
| **Reflection/Self-Evaluation** | Analytics track retrieval quality for evaluation |
| **Autonomous Learning** | `ACQUIRE_MORE` decisions trigger knowledge acquisition |
| **Knowledge Acquisition** | Pipeline integrates with acquisition for low-confidence gaps |
| **Knowledge Validation** | Calibrated confidence + source reliability inform validation |
| **Software Engineering** | Engineering lessons, docs, patterns ranked by relevance |
| **Tool Ecosystem** | Tool outputs stored in working memory, retrievable |

---

## Configuration

```python
from app.knowledge_retrieval.models import RankingConfig
from app.knowledge_retrieval.pipeline import KnowledgeRetrievalPipeline

config = RankingConfig(
    weights={
        RankingSignal.RELEVANCE: 0.30,
        RankingSignal.CONFIDENCE: 0.20,
        RankingSignal.SOURCE_QUALITY: 0.15,
        # ...
    },
    source_quality_scores={
        KnowledgeSourceType.KNOWLEDGE_BASE: 0.95,
        # ...
    },
    calibration_enabled=True,
    calibration_method="isotonic",
    adaptation_enabled=True,
    adaptation_rate=0.01,
    use_directly_threshold=0.90,
    use_with_caution_threshold=0.70,
)

pipeline = KnowledgeRetrievalPipeline(
    config=config,
    calibration_method="isotonic",
    calibration_storage=Path("data/knowledge_retrieval/calibration.json"),
    analytics_storage=Path("data/knowledge_retrieval/usage_analytics.json"),
    adaptive_ranking=True,
    analytics_enabled=True,
)
```

---

## Error Handling

| Failure Mode | Handling |
|--------------|----------|
| Empty knowledge sources | Returns empty list, graceful degradation |
| Unavailable adapters | Skipped with debug log, pipeline continues |
| Corrupted entries | Caught per-result, logged, other results proceed |
| Invalid ranking data | Default scores applied, warning logged |
| Missing confidence values | Default 0.5 used, calibration skipped |
| Calibration load failure | Starts fresh, logs warning |
| Analytics save failure | Non-blocking, logs warning, continues |

Never crashes the retrieval pipeline.

---

## Testing

Run tests:
```bash
python -m pytest tests/test_knowledge_retrieval.py -v
```

Test coverage (27 tests):
- Data models (result, query, response, config, factors)
- Ranking engine (basic, explanation, custom calculators)
- Adaptive ranking (weight adaptation from feedback)
- Calibration (isotonic, Platt, Beta, Temperature, None, persistence)
- Analytics (recording, usefulness, source stats, query analytics)
- Pipeline (empty, mock adapters, string queries, stats, calibration)
- Source adapters (semantic memory adapter)

---

## Known Limitations

1. **No semantic vector search** – Keyword/phrase matching only (could integrate FAISS)
2. **No cross-project retrieval** – Single workspace only
3. **No UI dashboard** – Analytics via programmatic access only
4. **Calibration requires minimum samples** – ~20 observations per source
5. **Adaptation is simple** – Gradient-like weight adjustment only (no bandit algorithms)
6. **No query expansion/reformulation** – Exact query terms only

---

## Future Enhancements

- [ ] Semantic vector search integration (FAISS)
- [ ] Multi-project/federated retrieval
- [ ] Retrieval UI dashboard for observability
- [ ] More sophisticated adaptive ranking (contextual bandits)
- [ ] Query expansion and reformulation
- [ ] Knowledge graph traversal for related topics
- [ ] Personalized ranking per user/context
- [ ] Cross-source deduplication and consolidation

---

## Files

```
app/knowledge_retrieval/
├── __init__.py          # Exports, convenience functions
├── models.py            # Data models (Result, Query, Response, Config, Signals, etc.)
├── ranking.py           # RankingEngine, AdaptiveRankingEngine, 9 signal calculators
├── calibration.py       # 4 Calibrators + CalibrationManager
├── analytics.py         # UsageAnalytics, ResultUsageStats, SourceUsageStats
├── sources.py           # KnowledgeSourceAdapter + 9 concrete adapters
├── pipeline.py          # KnowledgeRetrievalPipeline orchestration

tests/
└── test_knowledge_retrieval.py  # 27 passing tests
```

---

## Quick Reference

### Main Entry Points

```python
from app.knowledge_retrieval import (
    KnowledgeRetrievalPipeline,
    RetrievalQuery,
    create_pipeline_from_agent,
    retrieve_knowledge,
    get_default_pipeline,
    register_knowledge_source,
)

# From agent (recommended)
pipeline = create_pipeline_from_agent(agent)

# Quick one-off
response = retrieve_knowledge("query string")

# Manual pipeline
pipeline = KnowledgeRetrievalPipeline()
pipeline.register_adapters(adapters)
response = pipeline.retrieve(RetrievalQuery(query="..."))
```

### Result Structure

```python
result = response.results[0]
result.content              # Full content
result.title                # Short title
result.summary              # Summary/preview
result.source_type          # KnowledgeSourceType enum
result.source_id            # Unique ID within source
result.rank_score           # Final combined score (0-1)
result.raw_confidence       # Original confidence from source
result.calibrated_confidence # Calibrated confidence
result.ranking_explanation  # RankingExplanation with per-factor breakdown
result.category             # Knowledge category
result.tags                 # List of tags
result.language             # Programming language
result.last_updated         # ISO timestamp
result.access_count         # How many times retrieved
```

### Decision

```python
response.decision                    # RetrievalDecision enum
response.decision_reason             # Human-readable reason
response.total_candidates            # Before ranking/filtering
response.retrieval_time              # Seconds
```

---

*Last updated: 2026-07-31 — Implementation complete, all tests passing*