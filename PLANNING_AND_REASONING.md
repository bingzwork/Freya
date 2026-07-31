# Planning & Reasoning

**Status:** 🟢 MOSTLY COMPLETE
**Completion:** ~85%
**Last Updated:** 2026-07-31

---

## Quick Summary

| Capability | Status | Completion | Key Files |
|------------|--------|------------|-----------|
| Structured Plan Generation | ✅ Complete | 100% | `app/planner/plan_manager.py`, `app/planner/planner.py` |
| Plan Execution | ✅ Complete | 100% | `app/planner/executor.py` |
| Memory Context in Plans | ✅ Complete | 100% | `app/planner/planner.py` |
| Engineering Lessons in Plans | ✅ Complete | 100% | `app/planner/planner.py`, `app/planner/executor.py` |
| PlanManager Integration | ✅ Complete | 100% | `app/planner/plan_manager.py` |
| Task Graph (`TaskGraph`) | ✅ Complete | 100% | `app/planner/task_graph.py` |
| Scheduler (ASAP, PRIORITY_FIRST, etc.) | ✅ Complete | 100% | `app/planner/scheduler.py` |
| Resource Allocator | ✅ Complete | 100% | `app/planner/resource_allocator.py` |
| Progress Tracker | ✅ Complete | 100% | `app/planner/progress_tracker.py` |
| Adaptive Replanning (Phase 5) | ✅ Complete | 100% | `app/planner/task_graph.py`, `app/planner/plan_manager.py`, `app/agent/core_agent.py` |
| Multiple Solution Evaluation | ❌ Not Implemented | 0% | — |
| Risk/Difficulty Scoring on Plans | ❌ Not Implemented | 0% | — |
| Human Plan Review/Modify/Reject | ❌ Not Implemented | 0% | — |
| Reasoning Transparency (Rationale) | ❌ Not Implemented | 0% | — |
| Planning Horizon Classification | ❌ Not Implemented | 0% | — |
| Long-horizon / Downstream Forecasting | ❌ Not Implemented | 0% | — |
| Plan Visualizer (Runtime Exposure) | 🟡 Partial | 50% | `app/planner/plan_visualizer.py` |
| Task Decomposition (Auto) | 🟡 Partial | 60% | `app/planner/planner.py` |

---

## What Works Today (✅ Implemented)

### Structured Plan Generation (`Planner.create_plan()`)
- Flat JSON plan (max 5 steps) via single LLM call
- Task-specific engineering templates: Build, Debug/Fix, Refactor, Create/Implement, Review, Test, Optimize
- Intent-aware handling returns `{"steps": []}` for non-engineering requests

### Plan Execution (`Executor.execute_plan()`)
- Runs up to 8 steps
- Each step maps to a tool (`_map_step_to_tool`) with LLM fallback (`_select_tool_with_llm`)
- Mutating tools permission-gated via `permission_prompt`

### Memory & Learning Integration
- Top-3 `memory.search(task, limit=3)` hits injected as "Relevant past experience"
- `Planner._build_lessons_context()` injects severity-filtered PATTERN lessons
- `Executor._build_pre_execute_lessons_block()` + `_log_anti_pattern_hints()` surface lessons in LLM fallback and after failed steps
- `FreyaAgent.run()` reads matching `ExperienceMemory` into "Past Experiences" for post-execute prompt
- `FreyaAgent.repair()` surfaces matching ANTI_PATTERN lessons on retries

### Iterative Solve Loop (`FreyaAgent.solve()`)
- Repeatedly calls `planner.create_plan()` + `apply_and_verify()` until success or `max_iterations`

### PlanManager (Phase 1)
- Single source of truth for plans
- `Planner.create_plan()` populates `Plan` object with tasks
- `Executor.execute_plan()` consumes `Plan` object
- Backward compatibility with dict plans maintained

### Task Graph (Phase 2) — `app/planner/task_graph.py`
- `TaskGraph` with `TaskNode` and `DependencyEdge`
- Sequential dependencies: `Planner.create_plan()` adds `step i+1 → step i` edges
- Cycle detection via `CycleDetectedError`
- `Plan.validate_graph()` and `Plan.get_task_graph()` methods
- `Executor.execute_plan()` uses `TaskGraph.topological_sort()` for execution order

### Scheduler (Phase 3) — `app/planner/scheduler.py`
- Strategies: ASAP, PRIORITY_FIRST, Longest-Duration-First, Deadline-Aware, Resource-Optimized
- Integrated into `Executor.execute_plan()`
- Tasks scheduled in dependency-correct topological order
- ASAP and PRIORITY_FIRST strategies wired and functional

### Resource Allocator (Phase 3) — `app/planner/resource_allocator.py`
- Default MACHINE and TOOL resources initialized in `Executor.__init__`
- Tasks allocate required resources before execution, release after
- Linear step loop replaced with scheduler-driven execution respecting `ScheduleItem` order

### Progress Tracker (Phase 4) — `app/planner/progress_tracker.py`
- `ProgressSnapshot` emitted after each task transition (`PENDING → READY → IN_PROGRESS → COMPLETED/FAILED`)
- Export methods for diagnostics (`export_for_diagnostics`), monitoring (`export_for_monitoring`), backlog (`export_for_backlog`)
- `PlanManager` exposes `get_progress_for_diagnostics()`, `get_progress_for_monitoring()`, `get_progress_for_backlog()`, `get_all_active_progress()`
- `FreyaAgent` stores last execution progress in `last_execution_progress` with `get_last_execution_progress()`

### Adaptive Replanning (Phase 5)
- `TaskGraph.get_affected_subgraph(failed_task_id)` — identifies failed task + all transitive dependents via BFS
- `TaskGraph.invalidate_subgraph(task_ids)` — marks affected tasks FAILED, clears execution state
- `TaskGraph.add_tasks_with_dependencies(tasks, parent_task_ids)` — adds replacement tasks with proper edges
- `Plan.get_completed_task_ids()` — preserves COMPLETED tasks across replans
- `Plan.invalidate_from_failure(failed_task_id)` — wraps TaskGraph invalidation
- `Plan.add_replacement_tasks(new_tasks, parent_task_ids)` — adds replacement tasks to plan and graph
- `Plan.replan_after_failure(failed_task_id, context)` — orchestrates full adaptive replan cycle
- `Executor.execute_plan_partial(plan, ..., incomplete_only=True)` — runs only non-COMPLETED tasks
- `FreyaAgent._replan_after_failure()` — generates replacement tasks via LLM, preserves COMPLETED, emits ProgressTracker replanning events
- `FreyaAgent.solve()` and `run_active_goal()` rewritten with adaptive replanning loop (incremental, not restart-from-scratch)

---

## What's Missing (❌ Not Implemented)

| Capability | Needed For |
|------------|------------|
| **Multiple Solution Evaluation** | Comparing alternative plans (minimal-diff vs refactor) |
| **Risk/Difficulty Scoring on Plans** | High-risk plan gating, human approval triggers |
| **Human Plan Review Flow** | User can review, edit, reorder, or reject plan before execution |
| **Reasoning Transparency** | Plain-English rationale for each step and plan selection |
| **Planning Horizon Classification** | Short/medium/long-horizon policies instead of fixed 5-step cap |
| **Long-horizon / Downstream Forecasting** | Anticipating cross-cutting changes 2-3 steps ahead |

---

## Partially Implemented (🟡 Partial)

| Capability | Current State | Missing |
|------------|---------------|---------|
| **Plan Visualizer** | `app/planner/plan_visualizer.py` exists | Not exposed in runtime/diagnostics |
| **Auto Task Decomposition** | Sequential deps created; basic parent/child | No automatic subtask breakdown for complex steps |

---

## Remaining Implementation Tasks

### ⭐⭐⭐⭐ Critical (Major Capabilities)

| Task | Objective | Why It Matters | Dependencies | Success Criteria |
|------|-----------|----------------|--------------|------------------|
| **Risk & Difficulty Scoring on Plans** | Combine `app/risk/` + lightweight difficulty estimate into per-plan scores | High-risk plans need human approval; feeds Safe Self-Improvement gates | PlanManager, Risk/Confidence modules | Every `Plan` carries `risk_score` and `difficulty`; agent flags high-risk before mutating tools |
| **Human Plan Review Flow** | Extend `permission_prompt` to render plan, allow reorder/edit/delete, confirm before execution | HUMAN_OVERSIGHT requires review/reject for high-risk actions; plan is highest-leverage surface | PlanManager, Risk scoring | User can review plan text, edit steps, request alternative, or reject before `Executor.execute_plan()` |
| **Multiple Solution Evaluation** | Planner emits 2-3 candidate `Plan` variants; risk/difficulty scorer picks or surfaces to user | Competing approaches made explicit and auditable | PlanManager, Risk scoring, Human review | 2-3 variants generated for non-trivial tasks; selection logged in ProgressTracker |

### ⭐⭐⭐ High (Important Improvements)

| Task | Objective | Why It Matters | Dependencies | Success Criteria |
|------|-----------|----------------|--------------|------------------|
| **Reasoning Transparency** | Add `rationale` field to `Task` and `Plan`; use `app/confidence/` calibration | Explain plans in plain English without re-deriving LLM prompt | PlanManager, Confidence module | Plan explainable in plain English via `plan.explain()` |
| **Planning Horizon Classification** | Short/medium/long-horizon policies instead of fixed 5-step cap | Complex tasks need deeper planning; simple tasks need less | PlanManager, Scheduler | Plans tagged with horizon; step cap varies by horizon |

### ⭐⭐ Medium (Nice to Have)

| Task | Objective | Why It Matters | Dependencies | Success Criteria |
|------|-----------|----------------|--------------|------------------|
| **Plan Visualizer Runtime Exposure** | Wire `plan_visualizer.py` into diagnostics/monitoring | Visual plan introspection for debugging | PlanManager, ProgressTracker | `Plan.to_mermaid()` / `to_dot()` exposed via `PlanManager` |
| **Auto Task Decomposition** | Break complex steps into subtasks automatically | Reduces manual planning burden | Planner, TaskGraph | Steps > threshold auto-decompose into child TaskNodes |

### ⭐ Low (Future)

| Task | Objective | Why It Matters | Dependencies |
|------|-----------|----------------|--------------|
| **Long-horizon / Downstream Forecasting** | Emit `downstream_impact` annotations for cross-cutting changes | Anticipate 2-3 steps ahead on shared API/import changes | Dependency graph (`app/intelligence/dependency_graph.py`) |

---

## Architecture

```
FreyaAgent.run()
    │
    ├─► Planner.create_plan()          # LLM generates plan steps
    │       │
    │       └─► PlanManager → Plan     # Plan object with TaskGraph
    │
    ├─► TaskGraph                      # DAG with dependencies
    │       │
    │       ├─► Scheduler              # ASAP / PRIORITY_FIRST / etc.
    │       │
    │       └─► ResourceAllocator      # MACHINE / TOOL / GPU
    │
    └─► Executor.execute_plan()        # Schedule-driven execution
            │
            ├─► ProgressTracker        # ProgressSnapshot per transition
            │
            └─► On failure → _replan_after_failure()
                    │
                    ├─► TaskGraph.get_affected_subgraph()
                    ├─► TaskGraph.invalidate_subgraph()
                    ├─► Plan.add_replacement_tasks()
                    └─► Executor.execute_plan_partial(incomplete_only=True)
```

---

## Integration Points

| Consumer | Uses Planning Data For |
|----------|------------------------|
| `Executor.execute_plan()` | Task execution order, resource allocation |
| `Scheduler` | Strategy selection, dependency-aware ordering |
| `ResourceAllocator` | Per-task resource reservation |
| `ProgressTracker` | Progress snapshots, diagnostics, monitoring, backlog |
| `DecisionManager` | Risk assessment (planned — not yet wired) |
| `WorldModel` | Environment snapshot, plan context |
| `GoalManager` | Goal-driven plan generation (`run_goal` / `run_goal_loop`) |
| `MemorySystem` | Experience recording, lesson retrieval |
| `Diagnostics/Monitoring/Backlog` | Progress data export |

---

## Files

| File | Purpose | Status |
|------|---------|--------|
| `app/planner/plan_manager.py` | Plan, PlanConfig, PlanManager | ✅ Complete |
| `app/planner/planner.py` | Planner.create_plan() with templates | ✅ Complete |
| `app/planner/executor.py` | Executor.execute_plan() / _partial() | ✅ Complete |
| `app/planner/task_graph.py` | TaskGraph, TaskNode, DependencyEdge | ✅ Complete |
| `app/planner/scheduler.py` | Scheduler strategies (ASAP, PRIORITY_FIRST, etc.) | ✅ Complete |
| `app/planner/resource_allocator.py` | ResourceAllocator (MACHINE/TOOL/GPU) | ✅ Complete |
| `app/planner/progress_tracker.py` | ProgressTracker, ProgressSnapshot | ✅ Complete |
| `app/planner/plan_visualizer.py` | Mermaid/DOT export | 🟡 Partial (not wired) |
| `app/agent/core_agent.py` | FreyaAgent.solve(), run_goal(), _replan_after_failure() | ✅ Complete |
| `tests/test_planner.py` | Unit tests for planner modules | ✅ Complete |
| `tests/test_planner_agent.py` | Integration tests | ✅ Complete |

---

## Success Criteria (Definition of Done)

| Criterion | Target | Status |
|-----------|--------|--------|
| Structured plan generation with templates | ✅ | Complete |
| Plan execution with tool mapping | ✅ | Complete |
| Memory context injection | ✅ | Complete |
| Engineering lessons integration | ✅ | Complete |
| PlanManager as single source of truth | ✅ | Complete |
| TaskGraph with dependencies | ✅ | Complete |
| Scheduler strategies (ASAP, PRIORITY_FIRST) | ✅ | Complete |
| Resource Allocator integration | ✅ | Complete |
| ProgressTracker with exports | ✅ | Complete |
| Adaptive replanning (preserves COMPLETED) | ✅ | Complete |
| Risk/difficulty scoring on plans | ❌ | Not Started |
| Human plan review flow | ❌ | Not Started |
| Multi-solution evaluation | ❌ | Not Started |
| Reasoning transparency (rationale) | ❌ | Not Started |
| Planning horizon classification | ❌ | Not Started |

---

## Related Documentation

- [GOAL_MANAGEMENT.md](GOAL_MANAGEMENT.md) — Goal-driven planning (`run_goal` / `run_goal_loop`)
- [TASK_SCHEDULING.md](TASK_SCHEDULING.md) — Scheduler strategies and resource allocation
- [RESOURCE_MANAGEMENT.md](RESOURCE_MANAGEMENT.md) — Resource allocator details
- [ROADMAP.md](ROADMAP.md) — Phase 2 Planner Modernization
- [DECISION_MAKING.md](DECISION_MAKING.md) — Risk analysis integration