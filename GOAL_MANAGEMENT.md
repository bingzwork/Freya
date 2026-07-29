# GOAL_MANAGEMENT.md

# Goal Management

Status: 🔵 FOUNDATION

Priority: ⭐⭐⭐⭐⭐ Critical

Completion: 95%

Last Updated: 2026-07-29

Related Roadmap Phase: [Phase 8 — Long-Term Autonomy](ROADMAP.md) (objective: "Autonomous goal management")

Cross-Reference: [LONG_TERM_AUTONOMY.md § Persistent Goal Management](LONG_TERM_AUTONOMY.md) · [IMPLEMENTATION_STATUS.md § Goal Management](IMPLEMENTATION_STATUS.md)

---

# Current Implementation

Phases 1 (Goal Data Model), 2 (Persistent Goal Storage), 3 (Goal Tree), 4 (Goal Progress Tracking), and 5 (Goal Scheduler) are implemented. The runtime data substrate (`Goal` dataclass + JSON-file persistence + CRUD + tree reads + completion propagation + progress metrics + active-goal indicator + scheduler) lives in `app/memory/goals.py` and is exported through `app/memory/__init__.py`. It is **not yet wired into FreyaAgent / Planner / the autonomous loop** — that is the work of the higher phases.

Concretely:

- ✅ Goal data model (Goal class with id, name, description, status, priority, parent_goal_id, child_goal_ids, **depends_on_ids**, created_at, updated_at)
- ✅ Persistent goal storage (atomic JSON at `data/memory/goals.json`, threaded, loadable across restarts; backwards compatible — files pre-Phase 4 / pre-Phase 5 still load with added-field defaults)
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
- ✅ Goal scheduler: `GoalStorage.queue()` returns eligible goals sorted by priority rank (`critical` → `optional`; unknown priorities sort to the bottom) and stable across ties; `GoalStorage.select_next()` picks the highest-priority eligible goal, marks it active, and returns it; both skip blocked / completed / currently-active goals
- ❌ Hierarchy invariant management — `update(parent_goal_id=...)` does not rewire the old / new parent's `child_goal_ids`; `delete` does not detach children or cascade. Explicit later-phase work.
- ❌ Standardised `status` / `priority` enums (string-typed today; later phases formalise the value set)
- ❌ Automatic goal decomposition into subtasks
- ❌ Autonomous goal review, stall detection, or reprioritization
- ❌ Planner integration driven by active goals
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

## Phase 6 — Automatic Goal Decomposition ⭐⭐⭐⭐

Objective

Break large goals into manageable subtasks.

Implement

- Planner integration
- Goal expansion
- Suggested subtasks
- Manual approval (if required)

Success Criteria

- Large goals become structured task trees.
- Users can review or edit generated subtasks.

---

## Phase 7 — Autonomous Goal Review ⭐⭐⭐⭐⭐

Objective

Allow Freya to continuously evaluate ongoing work.

Implement

- Detect stalled goals
- Detect blocked goals
- Pause inactive goals
- Recommend cancellation
- Resume paused goals
- Reprioritize when appropriate

Success Criteria

- Freya keeps long-running projects organized.
- Goal selection adapts to changing circumstances.

---

## Phase 8 — Planner Integration ⭐⭐⭐⭐⭐

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

Success Criteria

- Every engineering task originates from an active goal.
- Completed work updates goal status automatically.

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