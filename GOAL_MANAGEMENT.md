# GOAL_MANAGEMENT.md

# Goal Management

Status: 🔵 FOUNDATION

Priority: ⭐⭐⭐⭐⭐ Critical

Completion: 100%

Last Updated: 2026-07-30

Related Roadmap Phase: [Phase 8 — Long-Term Autonomy](ROADMAP.md) (objective: "Autonomous goal management")

Cross-Reference: [LONG_TERM_AUTONOMY.md § Persistent Goal Management](LONG_TERM_AUTONOMY.md) · [IMPLEMENTATION_STATUS.md § Goal Management](IMPLEMENTATION_STATUS.md)

---

# Current Implementation

Phases 1 (Goal Data Model), 2 (Persistent Goal Storage), 3 (Goal Tree), 4 (Goal Progress Tracking), 5 (Goal Scheduler), 6 (Automatic Goal Decomposition + Manual Approval), 7 (Autonomous Goal Review — stall detection + pause / resume + cancellation + priority recommendations), and 8 (Planner Integration — `FreyaAgent.run_goal()` / `run_goal_loop()` wire the active goal into the planner + executor loop with automatic completion propagation) are implemented. The runtime data substrate (`Goal` dataclass + JSON-file persistence + CRUD + tree reads + completion propagation + progress metrics + active-goal indicator + scheduler + decomposition + review surface + **planner integration**) lives in `app/memory/goals.py` and is exported through `app/memory/__init__.py`. It is now wired into `FreyaAgent` via `GoalStorage` and the new goal-driven execution entry points.

Concretely:

- ✅ Goal data model (Goal class with id, name, description, status, priority, parent_goal_id, child_goal_ids, **depends_on_ids**, created_at, updated_at, **`metadata` — Phase 7 lifecycle bookkeeping side-channel (`previous_status` / `pause_reason` / `stall_reason` / `recommend_reason` / `abandon_reason`); backwards compatible — pre-Phase-7 files load with `{}` default**)
- ✅ Persistent goal storage (atomic JSON at `data/memory/goals.json`, threaded, loadable across restarts; backwards compatible — files pre-Phase 4 / pre-Phase 5 / pre-Phase 7 still load with added-field defaults)
- ✅ Save / load / update / delete: `GoalStorage.create` / `update` / `delete` / `list` / `save` / `load` / `all` / `count`
- ✅ Goals survive application restarts (verified in `tests/test_goals.py`)
- ✅ Goal timestamps: `created_at` is stamped on `create`; `updated_at` is bumped when `update` actually changes a field; both are ISO UTC strings
- ✅ Parent / child relationships are persisted as part of each goal (`parent_goal_id` + `child_goal_ids` round-trip through `to_dict` / `from_dict`)
- ✅ Goal tree reads: `GoalStorage.parent_of` / `children_of` / `descendants_of`
- ✅ Automatic completion propagation: `GoalStorage.complete(goal_id)` marks a goal `status="completed"` and recursively promotes any ancestor whose observed children are all completed
- ✅ Nested goals work correctly: depth is unbounded; propagation walks the full `parent_goal_id` chain
- ✅ Progress tracking: `GoalStorage.progress(goal_id)` returns `{total_children, completed_children, percentage}` derived live from the in-memory map; updates automatically as children are added, completed, or removed (and as `complete()` propagation fires)
- ✅ Completed-goal detection: `GoalStorage.is_completed(goal_id)` returns True iff the goal exists and is `status="completed"`
- ✅ Active goal indicator: `GoalStorage.set_active(goal_id)` / `active_goal()` / `clear_active()` track a single persisted active id (lives in the storage `metadata` block; survives restarts)
- ✅ Goal dependencies: `GoalStorage.dependencies_of(goal_id)` reads declared prereqs; `is_blocked(goal_id)` returns True on explicit `status="blocked"`, on any unmet dep (`!="completed"`), or on any unsatisified dep id (missing goal)
- ✅ Goal scheduler: `GoalStorage.queue()` returns eligible goals sorted by priority rank (`critical` → `optional`; unknown priorities sort to the bottom) and stable across ties; `GoalStorage.select_next()` picks the highest-priority eligible goal, marks it active, and returns it; both skip blocked / completed / currently-active goals; **`select_next` auto-resumes a paused goal when it would otherwise be chosen** (Phase 7 integration — callers do not need to invoke `resume_goal` first)
- ✅ Automatic goal decomposition (Phase 6): `GoalStorage.decompose_goal(goal_id, max_subtasks=N)` returns a list of `SubtaskSuggestion` drafts (read-side, non-mutating) generated from a deterministic Phase-6 template (`Plan / Implement / Test / Document / Review`); subtask priorities inherit from the parent goal; the parent description is appended to the first suggestion so reviewers can see the linkage
- ✅ Manual approval gate (Phase 6): `GoalStorage.apply_decomposition(goal_id, suggestions, plan_manager=None)` is the explicit opt-in that materialises suggestions as real child goals via the Phase-1 `create(parent_goal_id=...)` path (so Phase-3 completion propagation still applies); the optional `plan_manager` parameter is the **Planner integration** hook — when supplied, each approved suggestion is mirrored as a parallel `Task` in the manager's active plan via the existing `PlanManager.add_task(...)` surface (no new planner surface is added in Phase 6 — the goal side is the source of truth and the planner side is a parallel projection); suggestions can be edited / dropped before approval
- ✅ **Stall detection (Phase 7): `GoalStorage.list_stalled(stall_threshold_seconds=604800, include_paused=False, now=None)` returns goals whose `updated_at` is older than the threshold (default one week) and that are not in a terminal status (`completed` / `cancelled`); paused goals are excluded by default to distinguish intentional dormancy from organic staleness; read-side, non-mutating**
- ✅ **Block-reason description (Phase 7): `GoalStorage.block_reasons(goal_id)` returns the human-readable reasons why a goal is blocked (explicit `status="blocked"`, incomplete named deps, missing dependency ids); builds on Phase 5 `is_blocked` without mutating it**
- ✅ **Pause / resume surface (Phase 7): `GoalStorage.pause_goal(goal_id, reason="")` flips status to `"paused"` and stashes the prior status in `metadata["previous_status"]` (plus optional `metadata["pause_reason"]`); `resume_goal(goal_id)` restores from `metadata["previous_status"]` (fallback `"pending"`) and clears the keys; `is_paused(goal_id)` returns the paused-state bool; terminal goals (`completed`, `cancelled`) are never paused; re-pausing an already-paused goal is idempotent**
- ✅ **Bulk pause (Phase 7): `GoalStorage.pause_inactive(stall_threshold_seconds, reason="", include_paused=False)` wraps `list_stalled` + `pause_goal`; returns only the goals whose status actually flipped during the call**
- ✅ **Cancellation recommendation (Phase 7): `GoalStorage.recommend_cancellation(stall_threshold_seconds, pause_threshold_seconds=0.0, now=None)` is read-side and returns a list of `{goal_id, name, reason, status, paused_seconds, stall_seconds}` records — but the bar is high: a goal only surfaces here when *both* thresholds are exceeded (two independent signals are required because cancellation is higher stakes than stall or pause alone); single-condition flags belong to `list_stalled` / `is_blocked`**
- ✅ **Priority recommendation (Phase 7): `GoalStorage.recommend_priorities(now=None)` is read-side and returns a list of `{goal_id, name, current, recommended, reason}` records; the heuristic counts signals (`blocked` / `stalled` / `paused`) and bumps the priority *down* by that count of steps (`critical` → `optional` ceiling); the currently-active goal is always left alone (the Phase 5 selection loop is undisturbed); goals whose heuristic recommendation equals the current priority are not emitted (manual priorities are preserved unless there is a clear reason to flag a change)**
- ✅ **Planner integration (Phase 8): `FreyaAgent.goal_storage` wires the full GoalStorage surface into the agent; `FreyaAgent.run_active_goal(goal_id=None, allow_mutations=True, max_iterations=3)` resolves the active goal (or selects the next eligible via `select_next()`), plans from the goal description via `Planner.create_plan()`, executes via `Executor.execute_plan()`, records the outcome to memory, and marks the goal `completed` if all children are done (Phase 3 upward propagation). `FreyaAgent.run_goal_loop(allow_mutations=True, max_goals=10, max_iterations_per_goal=3)` runs the continuous loop: select next → run_active_goal → repeat until queue exhausted.**
- ❌ Hierarchy invariant management — `update(parent_goal_id=...)` does not rewire the old / new parent's `child_goal_ids`; `delete` does not detach children or cascade. Explicit later-phase work.
- ❌ Standardised `status` / `priority` enums (string-typed today; later phases formalise the value set)
- ❌ Human oversight UI for goal create / pause / resume / cancel

The pre-existing in-memory `goal: str` field on `AgentState` (`app/brain/state.py:10`) is untouched and remains the immediate-task description passed to `FreyaAgent.solve()` / `run()`.

---

# Implementation Priority

A practical build order, aligned with [Phase 8 — Long-Term Autonomy](ROADMAP.md). Each stage produces something testable on its own; later stages assume earlier ones are stable. The legacy "Phase 1 … Phase 8" sections below remain the granular task breakdown for whichever stage is being worked on.

**Important scope note:** Goal Management focuses on what Freya should work toward and why. Time-based recurring or cron-style execution belongs to the separate [`TASK_SCHEDULING.md`](TASK_SCHEDULING.md) and "Background Scheduler" capability in [`LONG_TERM_AUTONOMY.md`](LONG_TERM_AUTONOMY.md); this document does not duplicate that work.

---

## Stage 1 — Foundation

**Priority:** Critical

**Description:** Establish the underlying data model and persistence so everything else has a stable substrate.

**Includes:**
- Goal data model (ID, name, description, status, priority, parent/child links, timestamps)
- Persistent goal storage (file-backed JSON / SQLite; survives restarts)
- Goal lifecycle states and transitions
- Basic CRUD operations

**Why at this stage:** Every later stage assumes a goal is representable, addressable, and writable to disk. Without it, scheduling, decomposition, and review have nothing to operate on.

**Dependencies:** None beyond existing project memory patterns in `app/memory/`.

**Expected outcome:** Goals can be created, listed, edited, and deleted through a stable API, and they persist across restarts.

---

## Stage 2 — Core Goal Management

**Priority:** Critical

**Description:** Add structural relationships and visibility into goal progress without yet involving the planner or autonomy loop.

**Includes:**
- Goal hierarchy (parent → child)
- Progress tracking (% complete, completed subtasks, active indicator)
- Status management (transitions: Pending → Ready → In Progress → Completed / Failed / Blocked / Cancelled)
- Parent completion propagation (a parent auto-completes when all children are done)

**Why at this stage:** Once goals exist, they need structure. Hierarchy is a prerequisite for decomposition; progress tracking is a prerequisite for the scheduler to make real decisions later.

**Dependencies:** Stage 1 (data model + storage).

**Expected outcome:** Freya can represent goal trees, reflect child completion upward, and report accurate status and progress.

---

## Stage 3 — Planning Integration

**Priority:** High

**Description:** Wire the existing planner to goals so the goal, rather than the user prompt, becomes the planning root.

**Includes:**
- Planner consumes the active goal as planning context
- Automatic goal decomposition (a large goal expands into child goals / tasks via the planner)
- Task generation from goal plans
- Progress updates flowing back from executed steps to the owning goal

**Why at this stage:** The modern planner (`app/planner/`) and `FreyaAgent.solve()` / `run()` are already mature. Wiring them to goals is more valuable than building a parallel path. Decomposition needs the hierarchy from Stage 2.

**Dependencies:** Stage 2 (hierarchy); existing `app/planner/`, `app/agent/`, and Self-Learning read-side wiring (Priority 3 / 4).

**Expected outcome:** Every engineering task originates from an active goal, and completed work updates goal status automatically.

---

## Stage 4 — Autonomous Goal Management

**Priority:** High

**Description:** Move from "Freya executes the user's stated goal" to "Freya chooses and re-evaluates goals itself within safe bounds."

**Includes:**
- Goal prioritization (priority, deadline, dependencies, impact)
- Goal-internal scheduling logic (which active goal runs next; not the cross-cutting task scheduler)
- Stall detection (a goal that is no longer progressing)
- Automatic replanning or re-prioritization when conditions change

**Why at this stage:** With planning wired to goals in Stage 3, Freya can safely take ownership of *what* it works on next. Pure execution is already mostly complete, so the marginal cost here is relatively low.

**Dependencies:** Stage 3 (planning integration); existing observation / diagnostics subsystems for stall signals.

**Expected outcome:** Freya advances through goals on its own, detects stalled work, and reprioritizes when the situation changes — without waiting for a user prompt.

---

## Stage 5 — Long-Term Autonomy

**Priority:** Medium

**Description:** Make goal management durable, self-improving, and silent across sessions.

**Includes:**
- Persistent cross-session goals (resume where last session ended)
- Periodic goal review (is this goal still relevant?)
- Goal optimization (re-rank based on measured outcomes)
- Learning from completed goals (feed goal-completion signals back into planning)

**Why at this stage:** This layer only becomes meaningful once the lower stages produce real goal-completion signals that can be reviewed, optimized, and learned from. The learn-from-completed-goals piece reuses the Self-Learning write paths already in place (`solve()` / `repair()` record lessons and experiences).

**Dependencies:** Stages 1–4; existing ExperienceMemory + EngineeringLessonStorage write paths.

**Expected outcome:** Goals survive sessions, Freya periodically re-evaluates them, and goal outcomes feed forward into future planning.

---

# Overview

Goal Management gives Freya the ability to work toward objectives over long periods of time instead of only reacting to the latest user message.

Instead of asking:

> "What should I do now?"

Freya begins asking:

> "What should I do next to achieve my goal?"

This is one of the core capabilities required for true autonomous behavior.

---

# Why Goal Management Matters

Without Goal Management, Freya only responds to immediate requests.

Example:

User:
> Fix the failing tests.

Freya:
- Fixes tests
- Stops

---

With Goal Management:

Main Goal:
Finish Phase 7

Freya understands:

- Fix tests
- Verify all tests pass
- Update documentation
- Review changes
- Commit
- Mark Phase 7 complete

Then continue to the next objective.

This transforms Freya from reactive to proactive.

---

# Objectives

Freya should always know:

- What am I trying to achieve?
- Why am I doing this?
- Which goal is the highest priority?
- Which task should I execute next?
- Which tasks are completed?
- Which tasks are blocked?
- Which goals can be paused?
- Which goals should be abandoned?
- When is a goal considered finished?

---

# Design Principles

Goal Management should be:

- Lightweight
- Explainable
- Persistent
- Safe
- Autonomous
- Human overridable

Freya should never hide her current goals.

Users can always inspect them.

---

# Goal Hierarchy

Goals are organized as a tree.

Example

Main Goal
│
├── Finish Phase 7
│
├── Fix failing tests
│
├── Update documentation
│
└── Commit changes

Goals may contain unlimited child goals.

Example

Project
│
├── Build GUI
│   ├── Create Window
│   ├── Chat Panel
│   ├── Avatar
│   └── Settings
│
├── Improve AI
│   ├── Memory
│   ├── Planning
│   ├── Learning
│   └── Self Improvement
│
└── Release v1

---

# Goal States

Every goal should have a state.

Possible states:

- Pending
- Ready
- In Progress
- Waiting
- Blocked
- Paused
- Completed
- Cancelled
- Failed
- Archived

Example

Fix tests

Status:
In Progress

---

# Goal Priority

Each goal has a priority.

Example

Critical

High

Medium

Low

Optional

Priority influences planning.

---

# Goal Dependencies

Some goals cannot begin until others finish.

Example

Update Documentation

Depends On

✓ Fix Tests

Freya should automatically recognize when a dependency has been satisfied.

---

# Progress Tracking

Each goal tracks progress.

Example

Goal

Finish Phase 7

Progress

72%

Subtasks

✓ Planner

✓ Tool Selection

✓ Logging

○ Testing

○ Documentation

---

# Goal Completion Rules

Goals complete automatically when every required child goal completes.

Example

Finish Phase 7

✓ Tests

✓ Documentation

✓ Review

✓ Commit

↓

Automatically marked Completed.

---

# Goal Persistence

Goals must survive restarts.

Store goals inside the persistent memory system.

Possible storage

goals.json

or

SQLite

or

Knowledge Base

Implementation is flexible.

---

# Goal Scheduler

Freya periodically evaluates goals.

Example cycle

Observe

↓

Check Goal Status

↓

Find Highest Priority Goal

↓

Check Dependencies

↓

Generate Plan

↓

Execute

↓

Update Goal

↓

Repeat

---

# Goal Selection Logic

When multiple goals exist, Freya should evaluate:

Priority

↓

Dependencies

↓

Deadline

↓

Estimated effort

↓

Potential impact

↓

User preference

↓

Current context

The highest scoring goal becomes active.

---

# Goal Creation

Goals may come from:

User instructions

Project roadmap

Autonomous observations

Long-term objectives

Recurring maintenance

Example

User

Implement better logging.

↓

Freya creates

Goal

Implement Better Logging

---

# Automatic Task Generation

Large goals should automatically become smaller goals.

Example

Goal

Create GUI

Automatically expands into

Window

Sidebar

Chat

Avatar

Settings

Themes

The planner decides when decomposition is needed.

---

# Goal Review

Freya periodically asks:

Is this goal still relevant?

Has the user changed priorities?

Is the goal blocked?

Should I continue?

Should I pause?

Should I abandon it?

---

# Blocked Goals

If a goal cannot continue:

Status

Blocked

Reason

Missing dependency

Permission required

External API unavailable

Missing information

Freya should explain the blockage clearly.

---

# Human Oversight

Freya must always allow the user to:

Create goals

Delete goals

Pause goals

Resume goals

Reorder priorities

Approve autonomous goals

Reject autonomous goals

Users always have final authority.

---

# Future Integration

Goal Management should integrate with:

- Planner
- Memory
- Learning System
- Self Improvement
- Tool Selection
- Project Knowledge
- Autonomous Runtime
- Human Oversight
- Task Queue
- Performance Optimizer

It becomes the central coordinator of autonomous behavior.

---

# Incremental Implementation Roadmap

The system should be built in small, testable phases.

---

## Phase 1 — Goal Data Model ⭐ ✅ COMPLETE

Objective

Create the basic goal structure.

Implement

- Goal class
- Unique Goal ID
- Name
- Description
- Status
- Priority
- Parent Goal
- Child Goals

Success Criteria

- Goals can be created.
- Goals can be edited.
- Goals can be deleted.
- Goals can be loaded and saved.

**Delivered (Phase 1 + Phase 2).** See `app/memory/goals.py` (`Goal` dataclass + `GoalStorage` with `create` / `update` / `delete` / `list` / `save` / `load`) and `tests/test_goals.py` (24 tests, including restart-survival). Persistence file: `data/memory/goals.json`. Hierarchy invariant management (auto-sync of `parent_goal_id` ↔ `child_goal_ids`, cascade / dangling-reference repair on delete) is intentionally out of scope and belongs to a later phase.

---

## Phase 2 — Persistent Goal Storage ⭐⭐ ✅ COMPLETE

Objective

Allow goals to survive application restarts.

Implement

- Save goals
- Load goals
- Update goals
- Delete goals

Success Criteria

- Goals remain after restarting Freya.
- Goal hierarchy is preserved.

**Delivered.** `GoalStorage` auto-loads `data/memory/goals.json` on construction; every CRUD verb (`create` / `update` / `delete`) writes back through the same atomic `.tmp` + `replace` path. Hierarchy is preserved by serialising `parent_goal_id` and `child_goal_ids` per-goal, not by enforcing parent/child invariants — re-parenting and orphan-handling are out of scope here. Verified end-to-end in `tests/test_goals.py` (`test_persistence_across_instances`, `test_save_then_load_returns_same_goal`, `test_save_is_upsert`, `test_delete_is_persisted`, `test_crud_roundtrip`).

---


## Phase 3 — Goal Tree ⭐⭐⭐

Objective

Support parent and child goals.

Implement

- Goal hierarchy
- Subtasks
- Automatic completion propagation

Success Criteria

- Parent goals reflect child completion.
- Nested goals are supported.

---

## Phase 4 — Goal Progress Tracking ⭐⭐⭐

Objective

Track execution progress.

Implement

- Progress percentage
- Completed subtasks
- Active goal indicator
- Goal timestamps

Success Criteria

- Progress updates automatically.
- Completed goals are recognized correctly.

---

## Phase 5 — Goal Scheduler ⭐⭐⭐⭐

Objective

Continuously determine what Freya should work on next.

Implement

- Active goal selection
- Priority sorting
- Dependency checking
- Goal queue

Success Criteria

- Freya automatically selects the next valid goal.
- Blocked goals are skipped.

---

## Phase 6 — Automatic Goal Decomposition ⭐⭐⭐⭐ ✅ COMPLETE

Objective

Break large goals into manageable subtasks.

Implement

- **Planner integration** — the optional `plan_manager` kwarg on `GoalStorage.apply_decomposition`; each approved suggestion is mirrored as a parallel `Task` via the existing `PlanManager.add_task(...)` surface
- **Goal expansion** — `GoalStorage.decompose_goal(goal_id, max_subtasks=5)` expands a goal into up to five `SubtaskSuggestion` drafts from a deterministic Phase-6 template (`Plan / Implement / Test / Document / Review`); subtask priorities inherit from the parent goal and the parent description is appended to the first suggestion for reviewer linkage
- **Suggested subtasks** — `SubtaskSuggestion(name, description, priority, planner_category=None, estimated_hours=None)` dataclass returned by `decompose_goal`; the planner fields are forwarded only when an explicit `plan_manager` is supplied at approval time
- **Manual approval (if required)** — `decompose_goal` is non-mutating; `apply_decomposition(goal_id, suggestions, plan_manager=None)` is the explicit opt-in that materialises suggestions as real child goals; users can edit / drop suggestions before calling it

Success Criteria

- **Large goals become structured task trees.** ✅ `decompose_goal` covers Plan / Implement / Test / Document / Review by default; `max_subtasks` truncates; an applied decomposition creates child goals that inherit the parent's priority by default
- **Users can review or edit generated subtasks.** ✅ Suggestions are returned as plain `SubtaskSuggestion` objects (no persistence on `decompose_goal`); callers can `suggestion.name = ...` / `suggestion.priority = "critical"` etc. before invoking `apply_decomposition`

**Delivered (Phase 6).** Added `SubtaskSuggestion` dataclass + `GoalStorage.decompose_goal` (read-side) + `GoalStorage.apply_decomposition` (write-side, with optional `plan_manager` for the planner hook). The goal side stays the source of truth — the planner side is a parallel projection, never an alternative. Children created by decomposition go through the existing `create(parent_goal_id=...)` path so the Phase-3 completion-propagation rule still fires when all the synthesized children complete. Verified in `tests/test_goals.py::TestGoalDecomposition` (19 tests, including non-mutating `decompose_goal`, user-editable suggestions, manual-approval apply, planner mirror via a `FakePlanManager`, and Phase-3 auto-completion propagation).

## Phase 7 — Autonomous Goal Review ⭐⭐⭐⭐⭐ ✅ COMPLETE

Objective

Allow Freya to continuously evaluate ongoing work.

Implement

- **Stall detection** — `GoalStorage.list_stalled(stall_threshold_seconds, include_paused, now)` returns goals older than the threshold that are not terminal (`completed` / `cancelled`); paused goals excluded by default to distinguish intentional dormancy from organic staleness; defaults to a one-week threshold; read-side, non-mutating
- **Block-reason description** — `GoalStorage.block_reasons(goal_id)` returns human-readable reasons why a goal is blocked (explicit `status="blocked"`, incomplete named deps, missing dependency ids); builds on Phase 5 `is_blocked` without changing it
- **Pause inactive goals** — `GoalStorage.pause_goal(goal_id, reason="")` flips status to `"paused"` and stashes the prior status in `metadata["previous_status"]` (plus optional `metadata["pause_reason"]`); terminal goals are never paused; re-pausing an already-paused goal is idempotent. `GoalStorage.pause_inactive(stall_threshold_seconds, reason="", include_paused=False)` bulk-pauses everything in `list_stalled(...)` and returns the goals whose status actually flipped
- **Recommend cancellation** — `GoalStorage.recommend_cancellation(stall_threshold_seconds, pause_threshold_seconds=0.0, now)` is read-side and returns a list of `{goal_id, name, reason, status, paused_seconds, stall_seconds}` records; the bar is intentionally high — a goal only surfaces when *both* thresholds are exceeded (two independent signals are required because cancellation is higher stakes than stall or pause alone)
- **Resume paused goals** — `GoalStorage.resume_goal(goal_id)` restores `status` from `metadata["previous_status"]` (fallback `"pending"`) and clears the bookkeeping keys; `GoalStorage.is_paused(goal_id)` returns the paused-state bool
- **Reprioritize when appropriate** — `GoalStorage.recommend_priorities(now)` is read-side and returns a list of `{goal_id, name, current, recommended, reason}` records; the heuristic counts signals (`blocked` / `stalled` / `paused`) and bumps the priority *down* by that many steps (`critical` → `optional` ceiling); the currently-active goal is always left alone so Phase 5 selection is undisturbed; goals whose heuristic recommendation equals the current priority are not emitted (manual priorities are preserved unless there is a clear reason to flag a change)
- **`select_next` auto-resumes paused goals** — when a paused goal is the highest-priority eligible candidate, it is implicitly `resume_goal`-ed before being marked active; the phase 5 selection loop continues to work without callers needing to call `resume_goal` first

Success Criteria

- **Freya keeps long-running projects organized.** ✅ Stall detection + block-reason narration surfaced via `list_stalled` and `block_reasons`. Bulk pause available via `pause_inactive`. Pause / resume single goals via `pause_goal` / `resume_goal` / `is_paused`.
- **Goal selection adapts to changing circumstances.** ✅ `select_next` automatically resumes a paused goal when it would otherwise be the highest-priority eligible candidate, so paused work can be promoted without a separate user step.

**Delivered (Phase 7).** Added `Goal.metadata: Dict[str, Any]` (backwards compatible — pre-Phase-7 files default to `{}`) for lifecycle bookkeeping; new `paused` status treated distinctly from the existing status values; new helper constants (`_TERMINAL_STATUSES = ("completed", "cancelled")`, metadata keys `previous_status` / `pause_reason` / `stall_reason` / `recommend_reason` / `abandon_reason`); `GoalStorage` gained `list_stalled` (read), `block_reasons` (read), `pause_goal` (write), `pause_inactive` (write), `resume_goal` (write), `is_paused` (read), `recommend_cancellation` (read), `recommend_priorities` (read); `select_next` was updated to auto-resume a paused highest-priority eligible goal before marking it active (a Phase 5 / Phase 7 integration tight-coupling — no other Phase 5 verb was touched). Phase 7 is non-mutating for `list_stalled` / `block_reasons` / `recommend_cancellation` / `recommend_priorities` (read-side surface; callers decide whether to act); `pause_goal` / `pause_inactive` / `resume_goal` mutate storage with the same atomic-on-disk semantics as the rest of `GoalStorage`. Phase 8-onward work remains: planner integration driven by active goals (running the agent *from* goals), autonomous-loop wiring, human oversight UI for create / pause / resume / cancel, hierarchy-invariant management, and formalised `status` / `priority` enums.

---

## Phase 8 — Planner Integration ⭐⭐⭐⭐⭐ ✅ COMPLETE

Objective

Make Goal Management the starting point for planning.

Workflow

Goal

↓

Planner

↓

Task Plan

↓

Tool Selection

↓

Execution

↓

Memory Update

↓

Goal Update

↓

Repeat

Implementation

- Added `GoalStorage` to `FreyaAgent` (`app/agent/core_agent.py`) — instantiated with the workspace path during agent initialization, exposing the full Phase 1–7 surface to the runtime loop.
- New goal-driven execution entry point: `FreyaAgent.run_goal(goal_id: Optional[str] = None, allow_mutations: bool = True)` — resolves the active goal (uses current active goal if set, otherwise calls `select_next()`), builds a plan from the goal's description via the existing `Planner.create_plan()`, executes it through `Executor.execute_plan()`, then inspects results and advances the goal: marks the goal `completed` if all its children are complete (Phase 3 propagation), otherwise leaves it as `in_progress` so the next `run_goal()` call can continue or the scheduler can pick another.
- Backwards compatible: existing `run()` / `solve()` / `repair()` methods are untouched; callers that want goal-driven behavior simply call `run_goal()`.
- The Planner uses the active goal's description as the planning root — the goal becomes the "why" and the planner produces the "how".

Success Criteria

- Every engineering task originates from an active goal. ✅ `run_goal()` uses the goal's description as the task input to the planner.
- Completed work updates goal status automatically. ✅ After execution, `run_goal()` checks `progress()` and calls `complete()` if all children are done, triggering Phase 3 upward propagation.

---

# Final Vision

Goal Management transforms Freya from a request-response assistant into a long-term autonomous software engineering AI.

Instead of simply waiting for the next prompt, Freya continuously understands:

- What needs to be achieved.
- Why it matters.
- What has already been completed.
- What should happen next.
- When to pause, continue, or stop.

This capability serves as the executive control layer that coordinates planning, execution, learning, memory, and autonomy across the entire system.