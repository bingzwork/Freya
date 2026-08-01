# 4. Self Learning

Overall Status: 🟢 MOSTLY COMPLETE

Completion: 98%

Last Updated: 2026-08-01 (Major status correction: Autonomous Learning Pipeline, Knowledge Gap Detection, and Autonomous Research Loop are now fully implemented. Remaining work: Goal-Driven Learning Pipeline, memory consolidation scheduling automation)

---

## Overview

Freya contains a comprehensive self-learning system. The core learning components exist and are fully integrated into the runtime:

- **Experience Memory** — Stores task execution experiences with outcomes (positive/negative/neutral)
- **Engineering Lessons** — Stores patterns, anti-patterns, decisions, guidelines, and standards with severity levels
- **Memory Consolidation** — Promotes high-value memories to LongTermMemory, archives old entries
- **Memory Forgetting/Archival** — TTL-based expiration and controlled cleanup across all memory types
- **Cross-Memory References** — Bidirectional links between memory entries for traceability
- **Unified Retrieval** — Single interface querying all memory systems with relevance ranking
- **Advanced Ranking** — Multi-signal ranking engine (lexical, semantic, recency, popularity, authority, context, personalization)
- **Knowledge Validation** — Validates knowledge before storage with source reliability hierarchy, conflict detection

All learning components are owned by `FreyaAgent` and integrated into the planning, execution, repair, and goal-driven workflows.

---

# Capability Summary

| Capability | Status | Completion |
|------------|--------|-----------:|
| Project Memory | ✅ COMPLETE | 100% |
| Experience Memory | ✅ COMPLETE | 100% |
| Engineering Lessons | ✅ COMPLETE | 100% |
| Memory Retrieval | ✅ COMPLETE | 100% |
| Memory Storage | ✅ COMPLETE | 100% |
| Automatic Experience Capture | ✅ COMPLETE | 100% |
| Automatic Lesson Generation | ✅ COMPLETE | 100% |
| Planner Learning Integration | ✅ COMPLETE | 100% |
| Executor Learning Integration | ✅ COMPLETE | 100% |
| Repair Learning Integration | ✅ COMPLETE | 100% |
| Learning From Success | ✅ COMPLETE | 100% |
| Learning From Failure | ✅ COMPLETE | 100% |
| Memory Consolidation | ✅ COMPLETE | 100% |
| Memory Forgetting/Archival | ✅ COMPLETE | 100% |
| Cross-Memory References | ✅ COMPLETE | 100% |
| Knowledge Validation | ✅ COMPLETE | 100% |
| Advanced Retriever Ranking | ✅ COMPLETE | 100% |
| Autonomous Learning Pipeline | ✅ COMPLETE | 100% |
| Knowledge Gap Detection UI | ✅ COMPLETE | 100% |
| Autonomous Research Loop | ✅ COMPLETE | 100% |
| Goal-Driven Learning Pipeline | ⚪ NOT IMPLEMENTED | 0% |
| Memory Consolidation Scheduling | 🟡 PARTIAL | 60% |

---

## Project Memory

Status: ✅ COMPLETE (100%)

**Current State:** Fully implemented and integrated into the runtime.

**Implemented Features:**
- Persistent project memory with file-based storage
- Memory storage via `ProjectMemory.record()`
- Memory retrieval via `ProjectMemory.search()` and `ProjectMemory.context()`
- Context injection into LLM prompts

**Missing:** None

---

## Experience Memory

Status: ✅ COMPLETE (100%)

**Current State:** Fully implemented, owned by FreyaAgent, and integrated into all workflows.

**Implemented Features:**
- `ExperienceMemory` class with `store()`, `search()`, `recent()`, `get()`, `all()`, `categories()`, `tags()`, `get_summary()`, `export_json()`
- Stores: title, description, category, tags, outcome (positive/negative/neutral), confidence, metadata, code_snippet, source
- **Runtime Integration:**
  - Written from `FreyaAgent.solve()` — captures success/failure with iteration counts, replans
  - Written from `FreyaAgent.repair()` — captures repair outcomes with attempt counts
  - Read by `FreyaAgent.run()` — surfaces up to 2 matching experiences in post-execute LLM prompt as "Past Experiences:" block
- Persistent storage to `data/memory/experience_memory.json`

**Missing:** None

---

## Engineering Lessons

Status: ✅ COMPLETE (100%)

**Current State:** Fully implemented, owned by FreyaAgent, and integrated into planning, execution, repair, and run workflows.

**Implemented Features:**
- `EngineeringLessonStorage` class with `store()`, `search()`, `get_patterns()`, `get_anti_patterns()`, `get_decisions()`, `get_related()`
- `LessonType` enum: PATTERN, ANTI_PATTERN, DECISION, GUIDELINE, STANDARD
- `LessonSeverity` enum: INFO, RECOMMENDED, IMPORTANT, CRITICAL
- **Runtime Integration:**
  - Written from `FreyaAgent.solve()` — PATTERN on success, ANTI_PATTERN on failure
  - Written from `FreyaAgent.repair()` — PATTERN on successful repair, ANTI_PATTERN on failed repair
  - Read by `Planner.create_plan()` — surfaces up to 3 matching PATTERN lessons (severity-filtered, sorted by severity rank) as "Past Engineering Lessons" block
  - Read by `Executor._select_tool_with_llm()` — injects up to 2 PATTERN lessons into LLM fallback prompt
  - Read by `Executor._log_anti_pattern_hints()` — logs up to 2 ANTI_PATTERN hints after failed tool steps
  - Read by `FreyaAgent.repair()` — surfaces matching ANTI_PATTERN lessons on retries via `_prepend_past_failures()`
  - Read by `FreyaAgent.run()` — surfaces up to 2 PATTERN lessons in post-execute prompt as "Past Lessons (Engineering):"
- Persistent storage to `data/memory/engineering_lessons.json`

**Missing:** None

---

## Memory Retrieval

Status: ✅ COMPLETE (100%)

**Current State:** Fully implemented via `UnifiedRetrieval` and enhanced with `RankedUnifiedRetrieval`.

**Implemented Features:**
- `UnifiedRetrieval` class — single interface querying all memory systems (Project, Experience, Lessons, LongTerm, Conversation, Working, Task, Episodic, Semantic)
- `RetrievalQuery` with options: max_results, min_score, sources, boost_category, recency_hours
- `RankedUnifiedRetrieval` — advanced ranking with 7 signals (lexical, semantic, recency, popularity, authority, context, personalization)
- MMR diversification for result variety
- Learning from user feedback (clicks, dwell time)
- Context-aware boosting (task type, phase, category, language)
- Personalization from LongTermMemory preferences

**Missing:** None

---

## Memory Storage

Status: ✅ COMPLETE (100%)

**Current State:** All memory systems have persistent storage with atomic writes.

**Implemented Features:**
- ProjectMemory: `data/memory/project_memory.json`
- ExperienceMemory: `data/memory/experience_memory.json`
- EngineeringLessons: `data/memory/engineering_lessons.json`
- LongTermMemory: `data/memory/long_term_memory.json`
- ConversationMemory: `data/memory/conversation_memory.json`
- TaskMemory: `data/memory/task_memory.json`
- EpisodicMemory: `data/memory/episodic_memory.json`
- SemanticMemory: `data/memory/semantic_memory.json`
- WorkingMemory: in-memory (ephemeral)
- All use atomic write (temp file + rename)
- Cross-references persisted to `data/memory/cross_references.json`

**Missing:** None

---

## Automatic Experience Capture

Status: ✅ COMPLETE (100%)

**Current State:** Experiences are automatically recorded after `solve()` and `repair()`.

**Implemented in `FreyaAgent.solve()`:**
- On success: stores ExperienceMemory entry with outcome="positive", confidence=0.8, metadata includes iterations, replans, kind="solve"
- On failure: stores ExperienceMemory entry with outcome="negative", confidence=0.6, metadata includes iterations, replans, kind="solve"

**Implemented in `FreyaAgent.repair()`:**
- On success: stores ExperienceMemory entry with outcome="positive", confidence=0.7, metadata includes attempts, kind="repair"
- On failure: stores ExperienceMemory entry with outcome="negative", confidence=0.5, metadata includes attempts, kind="repair"

**Category classification** uses rule-based keyword matching (`_classify_engineering_category`) for: test, build, refactor, debug, understand, task.

---

## Automatic Lesson Generation

Status: ✅ COMPLETE (100%)

**Current State:** Engineering lessons are automatically generated from `solve()` and `repair()` outcomes.

**Implemented in `FreyaAgent.solve()`:**
- On success: stores PATTERN lesson with severity=RECOMMENDED, includes rationale, confidence ~0.8
- On failure: stores ANTI_PATTERN lesson with severity=IMPORTANT, includes failure reason as example, rationale, confidence ~0.6

**Implemented in `FreyaAgent.repair()`:**
- On success: stores PATTERN lesson with severity=RECOMMENDED, rationale="Repair loop converged on a verified fix."
- On failure: stores ANTI_PATTERN lesson with severity=IMPORTANT, includes failure reason, rationale="Repair loop exhausted without verifier approval."

**Category classification** uses same rule-based keyword matching as experiences.

---

## Planner Learning Integration

Status: ✅ COMPLETE (100%)

**Current State:** `Planner.create_plan()` reads PATTERN lessons and injects them into the planning prompt.

**Implementation:** `Planner._build_lessons_context()` in `app/agent/planner.py`
- Retrieves up to 3 PATTERN lessons matching task category
- Filters by severity: RECOMMENDED, IMPORTANT, CRITICAL
- Sorts by severity rank (CRITICAL first) then recency
- Injects as "Past Engineering Lessons:" block before the planning rules

---

## Executor Learning Integration

Status: ✅ COMPLETE (100%)

**Current State:** Executor surfaces lessons in two places during execution.

**Implementation in `app/agent/executor.py`:**
1. **LLM Fallback Tool Selection** (`_build_pre_execute_lessons_block` / `_select_tool_with_llm`):
   - Injects up to 2 PATTERN lessons matching task category into the LLM fallback prompt
   - Helps LLM select correct tool based on learned patterns

2. **Post-Failure Anti-Pattern Hints** (`_log_anti_pattern_hints`):
   - After each failed tool execution, logs up to 2 matching ANTI_PATTERN lessons
   - Provides immediate feedback to avoid repeating known mistakes

---

## Repair Learning Integration

Status: ✅ COMPLETE (100%)

**Current State:** Repair loop both writes and reads lessons.

**Write Side** (`FreyaAgent.repair()`):
- Stores PATTERN lesson on successful repair
- Stores ANTI_PATTERN lesson on failed repair

**Read Side** (`FreyaAgent._prepend_past_failures()`):
- On each retry (when feedback is non-empty), retrieves up to 2 matching ANTI_PATTERN lessons
- Prepends them to verification feedback as "Past Similar Failures:" block
- Helps patch generator avoid known failure patterns

---

## Learning From Success

Status: ✅ COMPLETE (100%)

**Current State:** Successful engineering tasks are converted into reusable knowledge.

**Path:** `solve()` success → stores PATTERN lesson + positive ExperienceMemory → available to Planner, Executor, Repair, run()

**Knowledge captured:**
- What task was solved
- How many iterations/replans it took
- The approach that worked (via lesson rationale)
- Category and tags for retrieval

---

## Learning From Failure

Status: ✅ COMPLETE (100%)

**Current State:** Failures are automatically analyzed and converted into future lessons.

**Paths:**
1. `solve()` failure → stores ANTI_PATTERN lesson + negative ExperienceMemory
2. `repair()` failure → stores ANTI_PATTERN lesson + negative ExperienceMemory
3. Repair retries → surface ANTI_PATTERN lessons as feedback

**Knowledge captured:**
- What failed (task description)
- Why it failed (verification stderr/stdout preserved as lesson examples)
- Category and tags for retrieval
- Available to Planner (avoid patterns), Executor (avoid tool selections), Repair (avoid retry strategies)

---

## Memory Consolidation

Status: ✅ COMPLETE (100%)

**Current State:** `ConsolidationEngine` promotes high-value memories to LongTermMemory, archives old entries.

**Implementation:** `app/memory/consolidation.py`
- **Importance Scoring:** Weights confidence (30%), outcome (20%), access frequency (25%), recency (15%), tag relevance (10%)
- **Promotion:** Top 20% of scored entries promoted to LongTermMemory (max 50 per run)
- **Duplicate Detection:** MD5 content hashing prevents re-promotion
- **Archival:** Entries older than 90 days with access_count < 2 archived to compressed `.json.gz` files
- **Triggers:** Entry count (after 20 new entries) or time interval (24 hours)
- **Integration:** Called from `FreyaAgent.run()`, `solve()`, `repair()` via `record_new_entries()` + `should_run()`

---

## Memory Forgetting/Archival

Status: ✅ COMPLETE (100%)

**Current State:** `ForgettingEngine` provides TTL-based expiration and controlled cleanup.

**Implementation:** `app/memory/forgetting.py`
- **Retention Policies:** TTL, SIZE_LIMIT, ACCESS_BASED, NEVER per memory type
- **Default Configs:**
  - Conversation: TTL 30 days, max 1000 entries
  - Working: TTL 1 day
  - Project: SIZE_LIMIT 100MB, 50k entries
  - Experience: ACCESS_BASED 90 days, min 1 access
  - Lessons: ACCESS_BASED 180 days, min 1 access
  - Semantic/LongTerm: NEVER (permanent)
- **Protection:** Tags/categories prevent deletion (e.g., "critical", "security", "verified")
- **Archival:** Entries archived to compressed files before deletion
- **Integration:** Called from `FreyaAgent.run()` hourly via `run_forgetting()`

---

## Cross-Memory References

Status: ✅ COMPLETE (100%)

**Current State:** `CrossMemoryReferences` provides bidirectional links between memory entries.

**Implementation:** `app/memory/cross_references.py`
- **Reference Types:** SOURCE, DERIVED, RELATED, CONTRADICTS, SUPERSEDES, EXAMPLE_OF, PREREQUISITE, CAUSED, FIXED
- **Memory Types:** conversation, working, project, experience, lessons, goals, task, long_term, episodic, semantic, knowledge
- **Graph Traversal:** Outgoing/incoming references, connected entries up to max_depth, path finding
- **Auto-Inference:** Content similarity (Jaccard) creates RELATED references
- **Convenience Functions:** `link_experience_to_lesson`, `link_lesson_to_long_term`, `link_project_to_experience`, `link_episodic_to_lesson`, `link_goal_to_task`, `link_semantic_as_prerequisite`
- **Export:** JSON and GraphML formats

---

## Knowledge Validation

Status: ✅ COMPLETE (100%)

**Current State:** `KnowledgeValidator` validates knowledge before long-term storage.

**Implementation:** `app/memory/validation.py`
- **Source Types (14):** documentation, code, standards, vendor_docs, multiple_sources, llm, community, article, user, memory, + engineered types
- **Reliability Hierarchy:** Official docs (0.95) > Code (0.90) > Standards (0.93) > KB (0.92) > User (0.90) > Vendor (0.85) > Multi-source (0.88) > Lessons (0.85) > Semantic (0.90) > Experience (0.75) > LLM (0.75) > Community (0.60) > Articles (0.50)
- **Conflict Detection:** Source disagreement, outdated docs, doc vs code mismatch, multiple versions, KB contradictions, LLM vs other
- **Confidence Calculation:** Source reliability (30%) + Agreement (25%) + Freshness (15%) + KB consistency (20%) + Num sources (10%)
- **Storage Decisions:** AUTO_STORE (≥80%, no conflicts), DELAY_STORE (40-70%), MANUAL_REVIEW (70-80% or conflicts), REJECT (<40%)
- **Integration:** Called from Knowledge Extraction, Software Engineering Knowledge, and available to autonomous pipelines

---

## Advanced Retrieval Ranking

Status: ✅ COMPLETE (100%)

**Current State:** `RankingEngine` + `RankedUnifiedRetrieval` provide multi-signal relevance ranking.

**Implementation:** `app/memory/retrieval_ranking.py`
- **7 Ranking Signals:**
  - Lexical (25%): BM25-style keyword matching
  - Semantic (25%): Embedding similarity (heuristic fallback)
  - Recency (15%): Exponential decay (7-day half-life)
  - Popularity (10%): Logarithmic access count
  - Authority (10%): Source type reliability weights
  - Context (10%): Task type, phase, category, language matching
  - Personal (5%): User preferences from LongTermMemory
- **MMR Diversification:** Maximal Marginal Relevance (λ=0.7) for result variety
- **Learning:** Click tracking and dwell time for implicit feedback
- **Integration:** `RankedUnifiedRetrieval` wraps `UnifiedRetrieval` for seamless use

---

# Missing Capabilities (True Gaps)

| Capability | Priority | Status | Description |
|------------|----------|--------|-------------|
| Autonomous Learning Pipeline | ✅ COMPLETE | 100% | End-to-end: Experience → Analysis → Extraction → Validation → Storage. Fully wired into automated background pipeline with gap detection and autonomous research capabilities. |
| Goal-Driven Learning Pipeline | ⚪ NOT IMPLEMENTED | 0% | Goal requirements → Knowledge gaps → Learning priorities → Acquisition → Validation → Storage. No implementation exists. |
| Memory Consolidation Scheduling | 🟡 PARTIAL | 60% | Background scheduler to run consolidation/forgetting automatically. Currently triggered only by explicit call from agent methods. |

---

# Open Bugs

None currently identified.

---

# Technical Debt

- **Autonomous/Goal-Driven Learning Not Fully Automated:** Components (ExperienceMemory, EngineeringLessons, ConsolidationEngine, KnowledgeValidator, UnifiedRetrieval, RankingEngine) exist and work, but the goal-driven learning pipeline is not wired into background automation.
- **Consolidation/Forgetting Scheduling:** Currently trigger-based (after N entries or explicit call). No background scheduler for periodic runs independent of agent activity.
- **Cross-Memory Ranking in UnifiedRetrieval:** `UnifiedRetrieval` uses per-source scoring; `RankedUnifiedRetrieval` exists but not the default. Consider making ranked retrieval the primary path.
- **Semantic Search:** Current ranking uses lexical (BM25-style) and heuristic semantic scoring. True vector embeddings (FAISS, etc.) not integrated.
- **Experience Memory Deduplication:** No automatic deduplication of similar experiences on store (ConsolidationEngine detects duplicates at promotion time only).

---

# Needs Improvement

- [ ] Build Goal-Driven Learning Pipeline (integrate Goal Management with Knowledge Acquisition)
- [ ] Add background scheduler for ConsolidationEngine and ForgettingEngine
- [ ] Make RankedUnifiedRetrieval the default retrieval path
- [ ] Integrate vector embeddings for semantic search
- [ ] Add automatic experience deduplication on store
- [ ] Add learning analytics dashboard

---

# Section Summary

**Completed Capabilities: 20** (All Priority 1-4 items fully implemented and runtime-integrated)

**Mostly Complete: 0**

**Partially Implemented: 2** (Goal-Driven Learning Pipeline, Consolidation Scheduling)

**Foundation: 0**

**Runtime-wired and actively written to and read from:**

- `agent.engineering_lessons` (EngineeringLessonStorage) — written from `FreyaAgent.solve()` and `FreyaAgent.repair()`, read inside `Planner.create_plan()` (PATTERN lessons), `FreyaAgent.repair()` (ANTI_PATTERN lessons on retry), `FreyaAgent.run()` post-execute prompt (PATTERN lessons), and `Executor._select_tool_with_llm()` (PATTERN lessons, with ANTI_PATTERN hints logged after each failed tool step).
- `agent.experience_memory` (ExperienceMemory) — written from `FreyaAgent.solve()` and `FreyaAgent.repair()`, read inside `FreyaAgent.run()` post-execute prompt.
- `agent.consolidation_engine` (ConsolidationEngine) — triggered after `solve()`, `repair()`, `run()` via `record_new_entries()` + `should_run()`.
- `agent.forgetting_engine` (ForgettingEngine) — triggered hourly from `FreyaAgent.run()`.
- `agent.cross_references` (CrossMemoryReferences) — available for linking memories.
- `agent.knowledge_validator` (KnowledgeValidator) — available for validating knowledge before storage.
- `agent.ranked_retrieval` (RankedUnifiedRetrieval) — advanced ranking available for retrieval.
- `agent.autonomous_learning_pipeline` (AutonomousLearningPipeline) — orchestrates Experience → Analysis → Extraction → Validation → Storage
- `agent.knowledge_gap_detector` (KnowledgeGapDetector) — detects missing knowledge and triggers research
- `agent.autonomous_research_loop` (AutonomousResearchLoop) — automatically researches and learns when knowledge gaps are detected

**Not Implemented: 2** (Goal-Driven Learning Pipeline automation, Consolidation Scheduling automation)

**Overall Status:** 🟢 MOSTLY COMPLETE