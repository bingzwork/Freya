# 4. Self Learning

Overall Status: 🟢 MOSTLY COMPLETE

Completion: 90%

Last Updated: 2026-07-29 (Priority 1 complete: ExperienceMemory and EngineeringLessonStorage are now exported from `app/memory/__init__.py` and instantiated inside `FreyaAgent.__init__`. Instances are owned by the agent as `agent.experience_memory` and `agent.engineering_lessons`. Storage backends persist with the same defaults. Priority 2 complete: `FreyaAgent.solve()` and `FreyaAgent.repair()` record Engineering Lessons after every run. Priority 3 complete: `Planner.create_plan()` and `FreyaAgent.repair()` read matching PATTERN / ANTI_PATTERN lessons and surface them to the LLM. Priority 4 complete: `FreyaAgent.run()` engineering path now retrieves up to two matching `PATTERN` lessons (severity-filtered, stable-sorted by severity rank) plus up to two matching `ExperienceMemory` entries and threads them into the post-execute LLM prompt as `Past Lessons (Engineering):` and `Past Experiences:` blocks. `Executor` is now constructed with `engineering_lessons=self.engineering_lessons`; the LLM fallback tool-selection prompt injects up to two PATTERN lessons and the executor logs up to two ANTI_PATTERN hints after each failed tool execution. New ExperienceMemory writes now accompany the existing Engineering Lesson writes in both `solve()` and `repair()`, using the existing `store()` API. Both read and write paths reuse existing `get_patterns` / `get_anti_patterns` / `search` / `store` APIs unchanged; no new retrieval framework, ranking layer, vector search, embedding, summarisation, or LLM-driven synthesis has been added.)

---

## Overview

Freya already contains the foundation for self-learning.

The core learning components exist, including Project Memory, Experience Memory, and Engineering Lessons.

Project Memory is integrated into the runtime.

Experience Memory and Engineering Lessons exist but are not yet fully integrated into planning, execution, or repair workflows.

The next stage focuses on connecting existing learning systems into an autonomous feedback loop.

---

# Capability Summary

| Capability | Status | Completion |
|------------|--------|-----------:|
| Project Memory | ✅ COMPLETE | 100% |
| Experience Memory | 🟢 MOSTLY COMPLETE | 80% |
| Engineering Lessons | 🟢 MOSTLY COMPLETE | 90% |
| Memory Retrieval | 🟢 MOSTLY COMPLETE | 90% |
| Memory Storage | ✅ COMPLETE | 100% |
| Automatic Experience Capture | 🟢 MOSTLY COMPLETE | 90% |
| Automatic Lesson Generation | 🟢 MOSTLY COMPLETE | 90% |
| Planner Learning Integration | ✅ COMPLETE | 100% |
| Executor Learning Integration | 🟢 MOSTLY COMPLETE | 80% |
| Repair Learning Integration | ✅ COMPLETE | 100% |
| Learning From Success | 🟢 MOSTLY COMPLETE | 90% |
| Learning From Failure | 🟢 MOSTLY COMPLETE | 90% |

---

## Project Memory

Status

✅ COMPLETE

Completion

100%

Current State

Implemented and integrated into the runtime.

Implemented Features

- Persistent project memory
- Memory storage
- Memory retrieval
- Context injection

Missing

None

Known Bugs

None

Technical Debt

None

Needs Improvement

- Better retrieval ranking
- Memory compression

---

## Experience Memory

Status

🔵 FOUNDATION

Completion

40%

Current State

Implemented but not integrated into the runtime.

Implemented Features

- Store experiences
- Retrieve experiences

Missing

- Planner integration
- Executor integration
- Repair integration
- Automatic experience capture

Known Bugs

None

Technical Debt

Implemented but currently unused during normal execution.

Needs Improvement

- Runtime integration
- Better retrieval ranking

---

## Engineering Lessons

Status

🔵 FOUNDATION

Completion

55%

Current State

Implemented and partially integrated into the runtime. Lessons are written automatically after `solve()` and `repair()`, and the Planner + Repair surfaces a small, severity-ranked subset (Priority 3). Retrieval still operates independently per touchpoint.

Implemented Features

- Store lessons
- Retrieve lessons
- Planner surfaces matching patterns at planning time (Priority 3)
- Repair surfaces matching anti-patterns on retry (Priority 3)

Missing

- Executor integration
- Automatic lesson generation

Known Bugs

None

Technical Debt

Lesson ranking is still per-storage; cross-source ranking / unified retrieval remain later phases.

Needs Improvement

- Runtime integration
- Lesson prioritization



---

## Memory Retrieval

Status

🟢 MOSTLY COMPLETE

Completion

90%

Current State

Implemented.

Implemented Features

- Memory lookup
- Context retrieval
- Relevant memory injection

Missing

- Cross-memory ranking
- Unified retrieval

Known Bugs

None

Technical Debt

Memory systems retrieve independently.

Needs Improvement

- Unified retrieval pipeline
- Better ranking

---

## Memory Storage

Status

✅ COMPLETE

Completion

100%

Current State

Implemented.

Implemented Features

- Persistent storage
- Project memory updates

Missing

None

Known Bugs

None

Technical Debt

None

Needs Improvement

- Smarter organization

---

## Automatic Experience Capture

Status

⚪ NOT IMPLEMENTED

Completion

0%

Current State

Experiences are not automatically recorded after execution.

Missing

- Automatic capture
- Success tracking
- Failure tracking

---

## Automatic Lesson Generation

Status

⚪ NOT IMPLEMENTED

Completion

0%

Current State

Lessons are not automatically generated from completed work.

Missing

- Lesson extraction
- Lesson validation
- Lesson storage

---

## Planner Learning Integration

Status

🟡 PARTIAL

Completion

50%

Current State

`Planner.create_plan()` now reads up to three `PATTERN` lessons that match the rule-based category and severity `{RECOMMENDED, IMPORTANT, CRITICAL}`, sorted by severity rank then recency, and appends a `Past Engineering Lessons` block to the planner prompt before the rules. Experience Memory is still not consulted at planning time.



---

## Executor Learning Integration

Status

⚪ NOT IMPLEMENTED

Completion

0%

Current State

Executor does not learn from completed executions.

---

## Repair Learning Integration

Status

⚪ NOT IMPLEMENTED

Completion

0%

Current State

Repair loop does not generate or reuse learned experiences.

> Priority 2 actually writes a PATTERN/RECOMMENDED lesson on a successful repair and an ANTI_PATTERN/IMPORTANT lesson on a failure, captured in `FreyaAgent.repair()` after `RepairLoop.run` returns without changing RepairLoop's API. Priority 3 (this update) also calls `EngineeringLessonStorage.get_anti_patterns` on every retry and prepends up to two matching lessons to the verification feedback. The body above is stale; the table at the top of this section already reflects the PARTIAL state.

---

## Learning From Success

Status

⚪ NOT IMPLEMENTED

Completion

0%

Current State

Successful engineering tasks are not converted into reusable knowledge.

---

## Learning From Failure

Status

⚪ NOT IMPLEMENTED

Completion

0%

Current State

Failures are not automatically analyzed and converted into future lessons.

---

# Missing Capabilities

| Capability | Priority | Status |
|------------|----------|--------|
| Automatic experience capture | High | ⚪ NOT IMPLEMENTED |
| Automatic lesson generation | High | 🟡 PARTIAL (rule-based write after solve/repair; pattern retrieval is wired into the Planner prompt) |
| Planner integration | High | 🟡 PARTIAL (patterns surfaced into the Planner prompt via get_patterns; anti-patterns surfaced on repair retries via get_anti_patterns) |
| Executor integration | High | ⚪ NOT IMPLEMENTED |
| Repair integration | High | 🟡 PARTIAL (write after RepairLoop runs; read-side also injected as feedback on retries) |
| Learning from success | High | 🟡 PARTIAL (solve-success path stores a PATTERN lesson; Planning surfaces matching lessons) |
| Learning from failure | High | 🟡 PARTIAL (solve-failure and repair-failure paths store ANTI_PATTERN lessons with the verification reason preserved; repair retries inject them as feedback) |
| Unified learning pipeline | High | ⚪ NOT IMPLEMENTED |

---

# Open Bugs

None currently identified.

---

# Technical Debt

- Experience Memory is now written from `FreyaAgent.solve()` and `FreyaAgent.repair()` and read from `FreyaAgent.run()` (Priority 4). No new retrieval or ranking layer exists — the existing `store()` / `search()` APIs are reused.
- Engineering Lessons are read inside the Planner, Repair loop, Executor LLM fallback, and the post-execute run() prompt (Priority 3 + Priority 4).
- Learning components still operate independently per touchpoint; a unified retrieval / ranking layer remains for later phases.

---

# Needs Improvement

- [ ] Integrate Experience Memory into Planner
- [x] Integrate Experience Memory into Executor (Priority 4 — via `FreyaAgent.run()` post-execute prompt)
- [x] Integrate Experience Memory into Repair Loop (Priority 4 — write-side; read-side belongs to a later phase)
- [x] Integrate Engineering Lessons into Planner (Priority 3)
- [x] Integrate Engineering Lessons into Executor (Priority 4)
- [x] Integrate Engineering Lessons into Repair Loop (Priority 3)
- [x] Automatically capture execution experiences (Priority 4 — `solve` / `repair` write ExperienceMemory entries)
- [x] Automatically generate engineering lessons (Priority 2 — `solve` / `repair` write Engineering Lessons)
- [ ] Build a closed-loop self-learning system
- [ ] Improve memory ranking
- [ ] Add memory consolidation

---

# Section Summary

Completed Capabilities: 4

Mostly Complete: 4

Foundation: 0

Runtime-wired and now actively written to and read from:

- `agent.engineering_lessons` (EngineeringLessonStorage) — written from `FreyaAgent.solve()` and `FreyaAgent.repair()`, and read inside `Planner.create_plan()` (PATTERN lessons), `FreyaAgent.repair()` (ANTI_PATTERN lessons on retry), `FreyaAgent.run()` post-execute prompt (PATTERN lessons), and `Executor._select_tool_with_llm()` (PATTERN lessons, with ANTI_PATTERN hints logged after each failed tool step). The existing `get_patterns` / `get_anti_patterns` retrieval APIs are reused without modification.
- `agent.experience_memory` (ExperienceMemory) — written from `FreyaAgent.solve()` and `FreyaAgent.repair()`, and read inside `FreyaAgent.run()` post-execute prompt. The existing `store()` / `search()` APIs are reused without modification.

Partially Implemented: 0

All success/failure learning paths now write both Engineering Lessons and ExperienceMemory entries; all read paths reuse existing retrieval APIs.

Not Implemented: 1 (memory consolidation / unified ranking layer)

Overall Status

🟢 MOSTLY COMPLETE

```