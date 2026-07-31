# Goal Management

**Status:** ✅ COMPLETE
**Completion:** 100%
**Last Updated:** 2026-07-31

---

## Quick Summary

| Capability | Status | Completion | Key Files |
|------------|--------|------------|-----------|
| Goal Data Model & Persistence | ✅ Complete | 100% | `app/memory/goals.py` |
| Goal Hierarchy & Tree Operations | ✅ Complete | 100% | `app/memory/goals.py` |
| Progress Tracking & Completion Propagation | ✅ Complete | 100% | `app/memory/goals.py` |
| Goal Scheduler & Priority Queue | ✅ Complete | 100% | `app/memory/goals.py` |
| Automatic Goal Decomposition | ✅ Complete | 100% | `app/memory/goals.py` |
| Autonomous Goal Review (Stall Detection, Pause/Resume, Cancellation) | ✅ Complete | 100% | `app/memory/goals.py` |
| Planner Integration (`run_goal` / `run_goal_loop`) | ✅ Complete | 100% | `app/agent/core_agent.py` |

---

## What Works Today (✅ Implemented)

### Goal Data Model (`app/memory/goals.py`)

Full `Goal` dataclass with:
- Unique ID, name, description, status, priority
- Parent/child hierarchy (`parent_goal_id`, `child_goal_ids`)
- Dependency tracking (`depends_on_ids`)
- Timestamps (`created_at`, `updated_at`)
- Metadata dictionary for lifecycle bookkeeping (`previous_status`, `pause_reason`, `stall_reason`, `recommend_reason`, `abandon_reason`)
- Backwards-compatible JSON serialization

### Persistent Goal Storage (`GoalStorage`)

Atomic JSON persistence at `data/memory/goals.json` with:
- Thread-safe CRUD: `create`, `update`, `delete`, `list`, `count`, `save`, `load`, `all`
- Goals survive application restarts (verified in tests)
- Automatic `updated_at` bump on actual field changes
- Atomic write via `.tmp` + `replace`

### Goal Hierarchy & Tree Operations

- Parent/child relationships: `parent_of`, `children_of`, `descendants_of`
- Automatic completion propagation: `complete(goal_id)` marks goal completed and recursively promotes ancestors whose children are all completed
- Unbounded nesting depth
- Progress tracking: `progress(goal_id)` → `{total_children, completed_children, percentage}`
- `is_completed(goal_id)` check

### Goal Scheduler

- Priority-based queue: `queue()` returns eligible goals sorted by priority (CRITICAL → OPTIONAL)
- `select_next()` picks highest-priority eligible goal, marks it active, auto-resumes paused goals
- Dependency checking: `dependencies_of`, `is_blocked` (explicit blocked status, incomplete deps, missing dep IDs)
- Active goal indicator: `set_active`, `active_goal`, `clear_active` (persisted in metadata block)

### Automatic Goal Decomposition (Phase 6)

- `decompose_goal(goal_id, max_subtasks=N)` → non-mutating list of `SubtaskSuggestion` drafts
- Deterministic template: Plan / Implement / Test / Document / Review
- Subtask priorities inherit from parent goal
- Manual approval gate: `apply_decomposition(goal_id, suggestions, plan_manager=None)` materializes suggestions as child goals
- Optional `plan_manager` hook mirrors approved subtasks as parallel `Task` objects in planner

### Autonomous Goal Review (Phase 7)

| Capability | Method | Description |
|------------|--------|-------------|
| Stall Detection | `list_stalled(threshold_seconds=604800, include_paused=False)` | Returns non-terminal goals older than threshold; paused excluded by default |
| Block Reasons | `block_reasons(goal_id)` | Human-readable reasons why goal is blocked |
| Pause/Resume | `pause_goal(goal_id, reason)`, `resume_goal(goal_id)`, `is_paused(goal_id)` | Flips status to `paused`, stashes prior status in metadata |
| Bulk Pause | `pause_inactive(threshold_seconds, reason, include_paused)` | Wraps `list_stalled` + `pause_goal` |
| Cancellation Recommendation | `recommend_cancellation(stall_threshold, pause_threshold=0)` | Read-side; requires BOTH thresholds exceeded |
| Priority Recommendation | `recommend_priorities()` | Read-side; bumps priority down by signal count (blocked/stalled/paused) |
| Auto-resume in Select | `select_next()` | Automatically resumes paused goal if it's the highest-priority eligible |

### Planner Integration (Phase 8) — `app/agent/core_agent.py`

- `FreyaAgent.goal_storage` — full `GoalStorage` surface wired into agent
- `run_goal(goal_id=None, allow_mutations=True, max_iterations=3)` — resolves active goal, plans from goal description via `Planner.create_plan()`, executes via `Executor.execute_plan()`, records outcome to memory, marks goal completed if all children done
- `run_goal_loop(allow_mutations=True, max_goals=10, max_iterations_per_goal=3)` — continuous autonomous loop: select next → run_goal → repeat until queue exhausted
- Backwards compatible: existing `run()` / `solve()` / `repair()` unchanged

---

## What's Missing (❌ Not Implemented)

| Capability | Priority | Description |
|------------|----------|-------------|
| Hierarchy Invariant Management | Medium | `update(parent_goal_id=...)` doesn't rewire old/new parent `child_goal_ids`; `delete` doesn't detach children or cascade |
| Standardized Status/Priority Enums | Low | String-typed today; formal enum values planned |
| Human Oversight UI | Medium | No UI for goal create/pause/resume/cancel |

---

## Remaining Implementation Tasks

### ⭐⭐ Medium (Important Improvements)

| Task | Objective | Why It Matters | Dependencies | Success Criteria |
|------|-----------|----------------|--------------|------------------|
| **Hierarchy Invariant Management** | Auto-sync parent/child links on re-parent/delete | Prevent orphaned goals, maintain tree integrity | GoalStorage CRUD | `update` rewires `child_goal_ids`; `delete` detaches or cascades |
| **Status/Priority Enums** | Replace string literals with typed enums | Compile-time safety, IDE autocomplete | Goal dataclass | `GoalStatus` and `GoalPriority` enums used throughout |

### ⭐ Low (Optional Improvements)

| Task | Objective | Why It Matters | Dependencies | Success Criteria |
|------|-----------|----------------|--------------|------------------|
| **Human Oversight UI** | CLI/UX for goal create/pause/resume/cancel | Human-in-the-loop control | GoalStorage API | Interactive goal management session |

---

## Integration Points

| Consumer | Uses Goal Data For |
|----------|-------------------|
| `FreyaAgent.run_goal()` | Active goal selection, planning context, execution loop |
| `FreyaAgent.run_goal_loop()` | Autonomous multi-goal execution |
| `Planner.create_plan()` | Goal description as planning root |
| `Executor.execute_plan()` | Task execution with resource allocation |
| `MemorySystem` | Goal outcomes recorded as experiences/lessons |
| `ProgressTracker` | Goal completion propagates to plan progress |

---

## Files

| File | Purpose | Status |
|------|---------|--------|
| `app/memory/goals.py` | Goal dataclass, GoalStorage, all Phases 1-7 | ✅ Complete |
| `app/memory/__init__.py` | Exports Goal, GoalStorage, SubtaskSuggestion | ✅ Complete |
| `app/agent/core_agent.py` | FreyaAgent.run_goal / run_goal_loop (Phase 8) | ✅ Complete |
| `tests/test_goals.py` | 50+ tests covering all phases | ✅ Complete |
| `data/memory/goals.json` | Persistent storage file | ✅ Working |

---

## Success Criteria (Definition of Done)

| Criterion | Target | Status |
|-----------|--------|--------|
| Goals persist across restarts | ✅ | Complete |
| Goal hierarchy with parent/child | ✅ | Complete |
| Automatic completion propagation | ✅ | Complete |
| Progress tracking (% complete) | ✅ | Complete |
| Priority-based scheduling | ✅ | Complete |
| Dependency tracking & blocking | ✅ | Complete |
| Automatic decomposition (Phase 6) | ✅ | Complete |
| Stall detection & pause/resume (Phase 7) | ✅ | Complete |
| Priority/cancellation recommendations (Phase 7) | ✅ | Complete |
| Planner integration (Phase 8) | ✅ | Complete |
| Autonomous goal loop (`run_goal_loop`) | ✅ | Complete |

---

## Related Documentation

- [LONG_TERM_AUTONOMY.md](LONG_TERM_AUTONOMY.md) — Persistent Goal Management section
- [TASK_SCHEDULING.md](TASK_SCHEDULING.md) — Background Scheduler (separate capability)
- [PLANNING_AND_REASONING.md](PLANNING_AND_REASONING.md) — Planner pipeline integration
- [ROADMAP.md](ROADMAP.md) — Phase 8 Long-Term Autonomy