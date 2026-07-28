# 4. Self Learning

Overall Status: 🔵 FOUNDATION

Completion: 75%

Last Updated: 2026-07-28 (Priority 1 complete: ExperienceMemory and EngineeringLessonStorage are now exported from `app/memory/__init__.py` and instantiated inside `FreyaAgent.__init__`. Instances are owned by the agent as `agent.experience_memory` and `agent.engineering_lessons`. Storage backends persist with the same defaults. Priority 2 complete: `FreyaAgent.solve()` records a `PATTERN`/`RECOMMENDED` Engineering Lesson on success and an `ANTI_PATTERN`/`IMPORTANT` lesson on failure, with the final verification reason preserved in `examples`. `FreyaAgent.repair()` does the same for the repair-loop outcome, captured after `RepairLoop.run` returns without changing RepairLoop's API. A rule-based classifier maps every task into the shared vocabulary `task | test | build | refactor | debug | understand`; unknown categories default to `task`. Priority 3 complete: `Planner.create_plan()` now reads up to three `PATTERN` lessons that match the rule-based category and have severity in `{RECOMMENDED, IMPORTANT, CRITICAL}`, sorted by severity rank then recency, and appends a `Past Engineering Lessons` block to the planner prompt. `FreyaAgent.repair()` now reads up to two matching `ANTI_PATTERN` lessons and prepends a `Past Similar Failures` block to the verification feedback on every retry that follows a failed attempt. The existing `EngineeringLessonStorage.get_patterns` / `get_anti_patterns` retrieval APIs are reused unchanged; no new retrieval framework, ranking layer, vector search, or LLM-driven summarisation has been added. ExperienceMemory write integration still belongs to a later phase.)

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
| Experience Memory | 🔵 FOUNDATION | 40% |
| Engineering Lessons | 🔵 FOUNDATION | 55% |
| Memory Retrieval | 🟢 MOSTLY COMPLETE | 90% |
| Memory Storage | ✅ COMPLETE | 100% |
| Automatic Experience Capture | ⚪ NOT IMPLEMENTED | 0% |
| Automatic Lesson Generation | ⚪ NOT IMPLEMENTED | 0% |
| Planner Learning Integration | 🟡 PARTIAL | 50% |
| Executor Learning Integration | ⚪ NOT IMPLEMENTED | 0% |
| Repair Learning Integration | 🟡 PARTIAL | 50% |
| Learning From Success | 🟡 PARTIAL | 50% |
| Learning From Failure | 🟡 PARTIAL | 50% |

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

- Experience Memory is instantiated by `FreyaAgent` but no call site writes to or reads from it yet.
- Engineering Lessons are read-only inside the Planner and the Repair loop (Priority 3); no call site writes to them from Executor yet.
- Learning components operate independently.
- No autonomous learning feedback loop exists.

---

# Needs Improvement

- [ ] Integrate Experience Memory into Planner
- [ ] Integrate Experience Memory into Executor
- [ ] Integrate Experience Memory into Repair Loop
- [x] Integrate Engineering Lessons into Planner (Priority 3)
- [ ] Integrate Engineering Lessons into Executor
- [x] Integrate Engineering Lessons into Repair Loop (Priority 3)
- [ ] Automatically capture execution experiences
- [ ] Automatically generate engineering lessons
- [ ] Build a closed-loop self-learning system
- [ ] Improve memory ranking
- [ ] Add memory consolidation

---

# Section Summary

Completed Capabilities: 2

Mostly Complete: 1

Foundation: 2

Runtime-wired and now actively written to and read from:

- `agent.engineering_lessons` (EngineeringLessonStorage) — written from `FreyaAgent.solve()` and `FreyaAgent.repair()`, and read inside `Planner.create_plan()` (PATTERN lessons) and `FreyaAgent.repair()` (ANTI_PATTERN lessons on retry). The existing `get_patterns` / `get_anti_patterns` retrieval APIs are reused without modification.

Runtime-wired but not yet consumed:

- `agent.experience_memory` (ExperienceMemory)

Partially Implemented: 4 (lesson generation, repair integration, success learning, failure learning)

Planner reads are wired (Priority 3); Executor reads and Experience Memory wiring remain for later phases.

Not Implemented: 3 (experience capture, executor integration, unified learning pipeline)

Overall Status

🔵 FOUNDATION

```