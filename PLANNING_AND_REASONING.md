# PLANNING_AND_REASONING.md

# Planning & Reasoning

- Status: 🟢 MOSTLY COMPLETE — 50% (Phase 1 complete: PlanManager integrated into FreyaAgent; Planner creates Plan objects; Executor consumes Plan objects. Phase 2 complete: TaskGraph wired into runtime. Phase 3 complete: Scheduler and ResourceAllocator wired into execution pipeline.)
- Priority: ⭐⭐⭐⭐⭐ Critical
- Source of truth: codebase; legacy planner is foundation-only and `app/planner/` modules now wired into the runtime (ROADMAP Phase 2 — Planner Modernization).

---

---

# Overview

Planning & Reasoning is Freya's executive decision-making system.

While Goal Management decides **what** Freya should accomplish, Planning & Reasoning determines **how** to accomplish it.

Instead of immediately reacting to a request, Freya evaluates the situation, considers multiple approaches, selects the most effective strategy, and continuously adapts as new information becomes available.

This capability is one of the foundations of autonomous software engineering.

---

# Why Planning & Reasoning Matters

Without Planning & Reasoning, Freya behaves like a task executor.

User:

> Implement Goal Management.

Freya:

- Starts writing code immediately.

With Planning & Reasoning, Freya first determines:

- What files are involved?
- What already exists?
- What architecture should be preserved?
- Which implementation is simplest?
- What risks exist?
- What should be completed first?
- What should wait until later?

Only after answering these questions does execution begin.

This greatly improves reliability, efficiency, and code quality.

---

# Current Implementation Status

Status symbols: ✅ Implemented · 🟡 Partial / Foundation · ❌ Not Implemented · 🔮 Future

| Area                                  | Status | Notes |
| ------------------------------------- | ------ | ----- |
| Structured plan generation            | ✅      | `Planner.create_plan()` emits a flat JSON plan (max 5 steps) via a single LLM call with task-specific engineering templates (Build, Debug/Fix, Refactor, Create/Implement, Review, Test, Optimize) and intent-aware handling that returns `{"steps": []}` for non-engineering requests. |
| Plan execution                        | ✅      | `Executor.execute_plan()` runs up to 8 steps; each step maps to a tool (`_map_step_to_tool`) with an LLM fallback (`_select_tool_with_llm`); mutating tools are permission-gated. |
| Memory context in plans               | ✅      | `Planner.create_plan()` injects top-3 `memory.search(task, limit=3)` hits as `Relevant past experience:`. |
| Engineering Lessons in plans          | ✅      | `Planner._build_lessons_context()` (SELF_LEARNING Priority 3) injects severity-filtered PATTERN lessons; `Executor._build_pre_execute_lessons_block()` and `_log_anti_pattern_hints()` (Priority 4) surface lessons in the LLM fallback tool-selection prompt and after failed steps. |
| Experience Memory in run() prompt     | ✅      | `FreyaAgent.run()` reads matching `ExperienceMemory` entries into `Past Experiences:` for the post-execute LLM prompt. |
| Iterative solve loop                  | ✅      | `FreyaAgent.solve()` repeatedly calls `planner.create_plan()` + `apply_and_verify()` until success or `max_iterations`. |
| Repair with ANTI_PATTERN lessons      | ✅      | `FreyaAgent.repair()` surfaces matching ANTI_PATTERN lessons on retries. |
| PlanManager integration (Phase 1)     | ✅      | `PlanManager` is the single source of truth for plans; `Planner.create_plan()` populates a `Plan` object with tasks; `Executor.execute_plan()` consumes the `Plan` object. Backward compatibility with dict plans maintained. |
| Task decomposition (parent/child)     | 🟡      | Sequential dependencies now create parent/child `TaskNode` relationships in `TaskGraph`; `Planner.create_plan()` adds `step i+1 → step i` edges. Automatic subtask decomposition not yet implemented. |
| Task graph (`TaskGraph`)              | ✅      | Module exists in `app/planner/task_graph.py` with unit tests; **now wired into the runtime** via `PlanManager` → `Plan._graph`, sequential dependencies created by `Planner.create_plan()`, validated on creation, and `Executor.execute_plan()` uses topological sort from TaskGraph. |
| Scheduler                             | ✅     | `app/planner/scheduler.py` (ASAP, Priority, Longest-Duration, Deadline, Resource-Optimized) integrated into `Executor.execute_plan()`; tasks scheduled in dependency-correct topological order; ASAP and PRIORITY_FIRST strategies wired. |
| Resource Allocator                    | ✅     | `app/planner/resource_allocator.py` integrated into `Executor`; default MACHINE and TOOL resources allocated per task; allocations released after execution. |
| Progress Tracker                      | 🟡     | `app/planner/progress_tracker.py` + `ProgressSnapshot` exist; not producing runtime progress data. |
| Plan Manager                          | ✅     | `app/planner/plan_manager.py` exposes `Plan` / `PlanConfig` / `PlanManager`; now used by `FreyaAgent`. |
| Plan Visualizer                       | 🟡     | `app/planner/plan_visualizer.py` present; not exposed in the runtime. |
| Multiple solution evaluation          | ❌      | Single LLM-generated plan; alternatives are not generated or compared. |
| Difficulty / Risk scoring             | ❌      | No explicit difficulty, risk, or confidence scoring for plans; `app/risk/`, `app/confidence/` operate elsewhere in the pipeline, not on the plan itself. |
| Adaptive replanning (formal)          | 🟡     | `solve()` re-plans per iteration and `repair()` retries with lessons; there is no dedicated replan cycle that preserves completed work on dependency change. |
| Long-term / downstream forecasting    | ❌      | No multi-step forecasting or future-task awareness. |
| Reasoning transparency (plan rationale) | ❌   | The chosen plan is logged as JSON only; the selection rationale is not surfaced in plain language. |
| Human plan review / modify / reject   | ❌      | The user can approve/deny individual tool calls (`permission_prompt` in `Executor`), but cannot review, modify, reorder, or reject the plan itself. |
| Planning horizon classification       | ❌      | All tasks use the same 5-step cap; no short/medium/long-horizon policy. |

Foundation modules in `app/planner/` (`task.py`, `task_graph.py`, `scheduler.py`, `resource_allocator.py`, `progress_tracker.py`, `plan_visualizer.py`, `plan_manager.py`) are covered by `tests/test_planner.py` and `tests/test_planner_agent.py`. The runtime path is now `FreyaAgent.run() → Planner.create_plan() → PlanManager → Plan → Executor.execute_plan() → tool.run()` — `PlanManager` is the single source of truth for plans.

---

# Objectives

Freya should always be able to answer:

- What is the objective?
- What information is missing?
- What is the simplest solution?
- What are the available approaches?
- Which approach has the lowest risk?
- What should happen first?
- What should happen next?
- What should happen after that?
- What could go wrong?
- How can I recover if it fails?

---

# Design Principles

Planning & Reasoning should be:

- Logical
- Efficient
- Explainable
- Adaptive
- Minimal
- Context-aware
- Safe

Planning should avoid unnecessary complexity. The preferred solution is usually the simplest one that satisfies the requirements.

---

# Planning Workflow (Target)

Every engineering task should follow this reasoning cycle.

Understand → Gather Context → Analyze Constraints → Generate Possible Solutions → Compare Solutions → Select Best Approach → Create Execution Plan → Execute → Observe Results → Replan if Necessary

Only "Create Execution Plan → Execute → Observe Results" are wired today; everything before plan creation and after execution is the open work listed in the implementation table above.

---

# Implementation Priority

A practical build order that matches `ROADMAP.md` Phase 2 ("Planner Modernization") and unblocks the higher-order phases. Each row must be promoted from ✗ to ✓ before dependent work can start.

## 1. Critical — Wire `PlanManager` into `FreyaAgent` ⭐⭐⭐⭐⭐ **✅ COMPLETE**

**Description.** Replace the ad-hoc `Planner.create_plan()` JSON dict with `app.planner.plan_manager.PlanManager` as the source of truth for plans. `Planner.create_plan()` becomes the LLM call that populates a `Plan`, and `Executor.execute_plan()` consumes it.

**Why now.** Every later step (TaskGraph, Scheduler, Resource Allocator, Progress Tracker, replanning) is impossible until plans are first-class objects with an ID, config, and lifecycle.

**Dependencies.** None — `PlanManager`, `Plan`, `PlanConfig` already exist and are unit-tested.

**Expected outcome.** A `Plan` is created, retained, and consumed end-to-end by the agent; the legacy code path can remain as the default LLM populator.

---

## 2. Critical — Wire `TaskGraph` into the runtime ⭐⭐⭐⭐⭐ **✅ COMPLETE**

**Description.** After plan generation, build a `TaskGraph` for the steps with `DependencyEdge` instances and parent/child `TaskNode` relationships. Reject cyclic plans.

**Why now.** This is the foundation for decomposition, declarative planning, and replanning without losing completed work.

**Dependencies.** Priority 1 (`PlanManager`).

**Expected outcome.** Plans are represented as DAGs; downstream components (Scheduler, Resource Allocator) can operate on graph topology.

**Implementation completed (2026-07-30):**
- `Planner.create_plan()` creates sequential dependencies between steps (task i+1 depends on task i)
- `PlanManager.add_dependency()` validates against cycles via `CycleDetectedError` propagation
- `Plan` class exposes `validate_graph()` and `get_task_graph()` methods
- `Executor.execute_plan()` uses `TaskGraph.topological_sort()` for execution order
- Preserves completed tasks for future replanning

---

## 3. High — Wire `Scheduler` and `ResourceAllocator` ⭐⭐⭐⭐ **✅ COMPLETE**

**Description.** Use `Scheduler` (start with `ASAP` and `PRIORITY_FIRST`) and `ResourceAllocator` (default machine + tool resources) at execution time, honouring `Task.dependencies`.

**Why now.** Step ordering and resource contention are the first pain points once `solve()` runs on multi-step tasks.

**Dependencies.** Prioritities 1 and 2.

**Expected outcome.** Steps run in dependency-correct order with explicit resource reservations, replacing the current linear step loop.

**Implementation completed (2026-07-30):**
- `Executor.execute_plan()` now uses `Scheduler` to generate execution schedule from `TaskGraph`
- `ASAP` and `PRIORITY_FIRST` scheduling strategies wired and functional
- `ResourceAllocator` initialized with default `MACHINE` and `TOOL` resources in `Executor.__init__`
- Tasks allocate required resources before execution and release them after
- Linear step execution loop replaced with scheduler-driven execution respecting `ScheduleItem` order
- Backward compatibility maintained for dict-based plans
- All 153 existing tests pass

---

## 4. High — `ProgressTracker` integration ⭐⭐⭐⭐

**Description.** Emit `ProgressSnapshot` objects after each task transitions (`PENDING → READY → IN_PROGRESS → COMPLETED / FAILED`) and expose them via the agent response and the diagnostics/monitoring layer.

**Why now.** Phases 4 (Self-Improvement) and 8 (Long-Term Autonomy) need structured progress data to drive backlog generation and runtime dashboards.

**Dependencies.** Priorities 1–3.

**Expected outcome.** Every engineering run produces a chronological progress trail consumable by `app/diagnostics/`, `app/monitoring/`, and `app/backlog/`.

---

## 5. High — Adaptive replanning ⭐⭐⭐⭐

**Description.** Promote the implicit `solve()/repair()` loop to an explicit replan cycle that updates the existing `Plan`/`TaskGraph` on failure instead of restarting from scratch. Preserve completed tasks.

**Why now.** The current loop re-plans from zero each iteration, which is wasteful and unstable on multi-step work.

**Dependencies.** Priorities 1–4.

**Expected outcome.** Failures invalidate only the affected subgraph; completed `Task`s remain `COMPLETED`; the agent surfaces replan events through `ProgressTracker`.

---

## 6. High — Risk and difficulty scoring on plans ⭐⭐⭐⭐

**Description.** Combine `app/risk/` (architectural impact, regression risk, dependency churn) and a lightweight difficulty estimate (file count, test surface, blast radius) into a per-plan risk + difficulty score. High-risk plans require explicit human approval before execution.

**Why now.** `app/risk/` and `app/confidence/` already exist; connecting them to the planner closes Phase 1 (Risk Analysis → Execution Decisions) and Phase 4 (Safe Self-Improvement gates).

**Dependencies.** Priorities 1–3.

**Expected outcome.** Every `Plan` carries a `risk_score` and `difficulty`; the agent flags high-risk plans before invoking mutating tools.

---

## 7. Medium — Human plan review flow ⭐⭐⭐

**Description.** Extend the existing `permission_prompt` UI to render the plan, allow reorder/edit/delete of individual `Task`s, and call `confirm` before `Executor.execute_plan()` runs.

**Why now.** `HUMAN_OVERSIGHT.md` requires review/reject paths for high-risk actions; plans are the highest-leverage review surface.

**Dependencies.** Priorities 1, 2, and 6.

**Expected outcome.** Before execution, the user can review the plan text, edit steps, request an alternative, or reject outright.

---

## 8. Medium — Multi-solution evaluation ⭐⭐⭐

**Description.** For non-trivial tasks, have the planner emit 2–3 candidate `Plan` variants (e.g., minimal-diff vs. refactor; SQLite vs. JSON) and the risk/difficulty scorer picks one or surfaces them to the user.

**Why now.** Cheap once `Plan` objects, scoring, and the human review flow from Priorities 1, 6, and 7 exist.

**Dependencies.** Priorities 1, 2, 6, and 7.

**Expected outcome.** Decisions between competing approaches are explicit and auditable in `ProgressTracker` and logs.

---

## 9. Medium — Reasoning transparency ⭐⭐⭐

**Description.** Add a `rationale` field to each `Task` (and to the `Plan`) capturing *why* this step was chosen (smallest diff, lowest risk, matches existing pattern). Use the new `app/confidence/` calibration to express certainty.

**Why now.** `app/confidence/` exists and is conceptually paired with planning but unused there today.

**Dependencies.** Priorities 1 and 6.

**Expected outcome.** The plan can be explained in plain English without re-deriving the LLM prompt.

---

## 10. Low — Long-horizon / downstream forecasting 🔮

**Description.** When the planner knows a step changes shared APIs or modifies imports, emit a `downstream_impact` annotation pointing at next steps the agent will likely need to revisit.

**Why now.** Useful but speculative; requires a stable symbol-index / dependency-graph integration (`app/intelligence/dependency_graph.py`).

**Dependencies.** Priorities 1–6.

**Expected outcome.** Plans anticipate two or three steps ahead on cross-cutting changes.

---

# Why Each Priority Sits Where It Does

- **Critical** items unblock all later work and do not depend on other capabilities.
- **High** items depend on Critical and feed separately into ROADMAP phases 4 (Safe Self-Improvement), 8 (Long-Term Autonomy), and 9 (Performance).
- **Medium** items improve quality (review, multi-solution, transparency) without changing what the agent can do.
- **Low** items are speculative and should only start once a stable, observable runtime plan pipeline is live.

---

# Final Vision

Planning & Reasoning gives Freya the ability to think before acting.

Rather than immediately executing requests, Freya evaluates objectives, compares possible solutions, estimates risk, plans several steps ahead, and adapts when circumstances change.

Combined with Goal Management, this capability forms Freya's executive function — coordinating intelligent decision-making across planning, execution, learning, and long-term autonomous software engineering.

When the Implementation Priorities above are complete, the runtime path becomes:

`FreyaAgent.run() → Planner (LLM) → PlanManager → TaskGraph → Scheduler + ResourceAllocator → Executor.execute_plan() → ProgressTracker → diagnostics/monitoring/backlog/safety gates`
