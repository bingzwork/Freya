# Freya Roadmap

**Source of Truth:** Current Implementation
**Version:** v0.4.x
**Status:** Active Development

---

# Vision

Freya is a local autonomous software engineering AI designed to solve software engineering tasks with minimal user intervention while remaining safe, observable, and continuously improving.

Development follows one principle:

> **Integrate existing systems before creating new ones.**

The codebase already contains mature foundation modules across planning, memory, monitoring, risk analysis, retrieval, tooling, and verification. Future work should focus primarily on connecting these systems into one coherent autonomous agent.

---

# Current Project Status

## Overall Progress

| Area                            | Status                         |
| ------------------------------- | ------------------------------ |
| Natural Conversation            | Mostly Complete                |
| Goal Management                 | Functional (Phases 1–8)         |
| Memory System                   | Core Modules Complete (85% Overall) |
| Planning and Reasoning          | Phase 5 Complete (Adaptive Replanning wired) |
| Decision Making                 | Partially Implemented (core components exist, integration needed) |
| Failure Recovery                | Complete (Foundation + High Priority) |
| World Model                     | Partial                        |
| Autonomous Software Engineering | Core Complete                  |
| Self Observation                | Complete (Integration Partial) |
| Learning System                 | Mostly Complete                 |
| Safe Self Improvement           | Partial                        |
| Task Scheduling                 | Complete (ASAP, PRIORITY_FIRST)                       |
| Knowledge Base                  | Complete (Project Scope)       |
| Software Engineering Knowledge  | Not Implemented                |
| Tool Ecosystem                  | Complete                       |
| Business Productivity           | Minimal                        |
| Creative Media                  | Not Implemented                |
| Human Oversight                 | Functional                     |
| Long-Term Autonomy              | Partial                        |
| Resource Management             | Complete (default MACHINE, TOOL, GPU resources)      |
| Multi Agent Coordination        | Not Implemented                |
| Self Evaluation                 | ✅ COMPLETE | 100% |
| Performance Optimization        | Partial                        |

---

# Development Philosophy

* Avoid over-engineering.
* Extend existing architecture.
* Reuse implemented modules.
* Keep implementations simple.
* Prioritize integration over replacement.
* Maintain backward compatibility.
* Every new capability must improve autonomy.

---

# Phase 1 — Foundation Integration

## Goal

Connect existing systems that already exist but are currently isolated.

### Objectives

* Integrate ExperienceMemory into planning and execution.
* Integrate EngineeringLessonStorage into planning and repair.
* Connect monitoring, diagnostics, confidence, and health systems into a unified runtime view.
* Wire risk analysis into execution decisions.
* Connect backlog generation with diagnostics.
* Improve runtime observability.
* **Wire confidence, risk, and decision components into a unified decision pipeline.**

### Expected Outcome

Freya begins learning from previous work instead of only storing project history.

---

# Phase 2 — Planner Modernization

## Goal

Replace the legacy planner pipeline with the modern planning framework.

### Objectives

* Integrate PlanManager as the single source of truth for plans. ✅ **COMPLETE (Phase 1)**
* Integrate TaskGraph. ✅ **COMPLETE (2026-07-30)**
* Integrate Scheduler. ✅ **COMPLETE (2026-07-30)**
* Integrate ResourceAllocator. ✅ **COMPLETE (2026-07-30)**
* Integrate ProgressTracker. ✅ **COMPLETE (2026-07-30)**
* **Implement Adaptive Replanning.** ✅ **COMPLETE (2026-07-30)**
* Replace legacy planner implementation.
* Preserve current planner behavior while expanding capability.

### Expected Outcome

Freya gains structured execution plans capable of managing complex engineering tasks.

### Progress

* Objective 1: `PlanManager` integrated into `FreyaAgent` as the single source of truth; `Planner.create_plan()` creates and populates `Plan` objects; `Executor.execute_plan()` consumes `Plan` objects; backward compatibility with dict plans maintained. ✅ **Complete (2026-07-30)**
* Objective 2: `Planner.create_plan()` builds `TaskGraph` with sequential dependencies; `TaskGraph.topological_sort()` drives `Executor.execute_plan()` execution order; cycle detection rejects cyclic graphs; completed TaskNode state preserved for replanning. ✅ **Complete (2026-07-30)**
* Objective 3: `Executor.execute_plan()` uses `Scheduler` (ASAP and PRIORITY_FIRST strategies) to generate execution schedule from TaskGraph; tasks execute in dependency-correct topological order. ✅ **Complete (2026-07-30)**
* Objective 4: `Executor` initializes `ResourceAllocator` with default MACHINE, TOOL, and GPU resources; tasks allocate required resources before execution and release them after; linear step loop replaced with scheduler-driven execution. ✅ **Complete (2026-07-30)**
* Objective 5: `Executor` emits `ProgressSnapshot` objects via `ProgressTracker` on every task state transition (PENDING → READY → IN_PROGRESS → COMPLETED/FAILED); `FreyaAgent.last_execution_progress` exposes progress summary; `PlanManager` exports progress data for diagnostics, monitoring, and backlog integration. ✅ **Complete (2026-07-30)**
* Objective 6: `FreyaAgent.solve()` and `run_active_goal()` use adaptive replanning via `_replan_after_failure()` which calls `TaskGraph.get_affected_subgraph()` and `invalidate_subgraph()` to identify failed task and dependents, then adds replacement tasks preserving COMPLETED tasks; replanning events emitted via `ProgressTracker` with `replanning=True` flag in `ProgressSnapshot`. `Executor.execute_plan_partial()` executes only incomplete tasks. ✅ **Complete (2026-07-30)**

---

# Phase 2 — Decision Making Integration

## Goal

Wire existing decision components (confidence, risk, goals, intent, replanning) into a unified judgment layer that governs every autonomous action.

### Objectives

* Create `app/decision/` package with DecisionManager, DecisionWorkflow, DecisionHistory ✅ **COMPLETE (2026-07-30)**
* Implement Decision Framework (Phase 1) — core engine, data models, interfaces ✅ **COMPLETE (2026-07-30)**
* Implement Context & Information Decisions (Phase 2) — explicit context sufficiency checks, memory retrieval decisions ✅ **COMPLETE (2026-07-30)**
* Wire Risk & Confidence Evaluation (Phase 3) — connect existing risk analyzer and confidence scoring to decision pipeline ✅ **COMPLETE (2026-07-30)**
* Implement Execution Decisions (Phase 4) — Continue/Pause/Retry/Stop/Switch/Skip as explicit decision outcomes ✅ **COMPLETE (2026-07-30)**
* Implement Adaptive Decision Making (Phase 5) — outcome monitoring, decision reevaluation, dynamic action selection ✅ **COMPLETE (2026-07-30)**
* Add Decision History (Phase 6) — persistent logs with reasons, outcomes, confidence ✅ **COMPLETE (2026-07-30)**
* Add Explainable Decisions — human-readable rationale for major choices ✅ **COMPLETE (2026-07-30)**
* Add Human Oversight Gates — approval requirements for high-risk actions ✅ **COMPLETE (2026-07-30)**

### Expected Outcome

Freya evaluates every autonomous action through an explicit decision workflow: observe → gather context → identify options → evaluate risk/confidence → choose → execute → observe → learn.

### Progress

* Phase 1 Decision Framework: **COMPLETE** — `DecisionManager`, `DecisionWorkflow`, `DecisionHistory`, `DecisionCategory`, `DecisionType`, `DecisionContext`, `DecisionOption`, `DecisionResult`, `DecisionRecord` implemented in `app/decision/`
* Phase 2 Context Decisions: **COMPLETE** — `decide_context_sufficiency()`, `_handle_information_decision()` with confidence thresholds
* Phase 3 Risk/Confidence: **COMPLETE** — Integrated `ConfidenceCalculator` and `RiskAnalyzer` into workflow `_step_evaluate_options()` and `_step_estimate_risk_benefit()`
* Phase 4 Execution Decisions: **COMPLETE** — `_handle_execution_decision()` with approval gates for high risk/low confidence
* Phase 5 Adaptive Decisions: **COMPLETE** — `_replan_after_failure()` uses DecisionManager, `decide_replanning_strategy()` convenience function
* Phase 6 Decision History: **COMPLETE** — `DecisionHistory` with JSON persistence, querying by type/category/component/outcome/time, summary statistics
* Explainable Decisions: **COMPLETE** — `DecisionResult.explain()`, `DecisionManager.explain_decision()` 
* Human Oversight Gates: **COMPLETE** — Auto-approval for low risk/high confidence; human approval required for high risk/critical risk or low confidence
* Integration into `FreyaAgent`: **COMPLETE** — `decide_simple()` called in `run()`, `solve()`, `_replan_after_failure()`, `run_active_goal()`

### Implementation Files

| File | Purpose |
|------|---------|
| `app/decision/__init__.py` | Package exports |
| `app/decision/models.py` | Core data models (DecisionCategory, DecisionType, DecisionContext, DecisionOption, DecisionResult, DecisionRecord, DecisionManagerConfig) |
| `app/decision/workflow.py` | DecisionWorkflow with 6-step pipeline (Observe→Gather→Identify→Evaluate→Estimate→Choose) |
| `app/decision/history.py` | DecisionHistory with JSON persistence and querying |
| `app/decision/manager.py` | DecisionManager orchestrating workflow, category handlers, convenience functions |
| `tests/test_decision_management.py` | 20 tests covering models, history, workflow, manager, handlers, convenience functions |

---

# Phase 3 — Autonomous Learning

## Goal

Transform stored knowledge into actionable intelligence.

### Objectives

* Automatically record engineering experiences.
* Automatically record engineering lessons.
* Retrieve relevant experiences during planning.
* Retrieve lessons during repair.
* Improve future planning using historical outcomes.
* Build cross-session engineering memory.

### Expected Outcome

Freya improves from previous successes and failures.

### Progress

* Priority 1: EngineeringLessonStorage and ExperienceMemory are owned by `FreyaAgent` at runtime and exported from `app/memory/__init__.py`. ✅ Complete (Priority 2 / 3 / 4 wired on top of this.)
* Priority 2: `FreyaAgent.solve()` and `FreyaAgent.repair()` write Engineering Lessons after every run. ✅ Complete.
* Priority 3: `Planner.create_plan()` surfaces matching PATTERN lessons (`Past Engineering Lessons:`); `FreyaAgent.repair()` surfaces matching ANTI_PATTERN lessons (`Past Similar Failures:`) on retries only. ✅ Complete.
* Priority 4: `FreyaAgent.run()` engineering path builds matching PATTERN + ExperienceMemory blocks; `Executor` surfaces PATTERN lessons in the LLM fallback tool-selection prompt and logs ANTI_PATTERN hints after failed tool execution. New ExperienceMemory writes run alongside the existing Engineering Lesson writes for both `solve` and `repair`. ✅ Complete.
* Remaining Phase 3 items (retrieval ranking, consolidation, embeddings) belong to later phases and remain out of scope per SELF_LEARNING.md.

---

# Phase 4 — Safe Self Improvement

## Goal

Allow Freya to safely improve its own implementation.

### Objectives

Create a closed-loop pipeline:

Diagnostics

↓

Risk Analysis

↓

Improvement Backlog

↓

Planning

↓

Patch Generation

↓

Verification

↓

Promotion

### Additional Work

* File allowlists
* Regression protection
* Automated verification
* Improvement prioritization
* Safety gates

### Expected Outcome

Freya can safely evolve itself under controlled conditions.

---

# Phase 5 — Advanced Software Engineering

## Goal

Expand engineering capabilities.

### Objectives

* AST-based refactoring
* Line-level editing
* Multi-file atomic patches
* Delete patch operations
* Cross-file symbol resolution
* Impact analysis
* Parallel execution
* Sub-agent orchestration

### Expected Outcome

Freya handles larger and more complex engineering tasks.

---

### Software Engineering Knowledge

Status: 🟢 Supported through the Knowledge Base

Software Engineering Knowledge is a primary knowledge domain maintained by the Knowledge Base.

It contains reusable engineering knowledge, best practices, architecture patterns, debugging techniques, testing strategies, security guidance, and engineering lessons learned.

Knowledge Acquisition continuously expands this domain over time through project experience, validated external knowledge, and autonomous learning.

---

# Phase 6 — Knowledge Expansion

## Goal

Extend knowledge beyond the current project.

### Objectives

* Web knowledge acquisition
* Documentation ingestion
* External repository retrieval
* Global knowledge base
* Knowledge summarization
* Knowledge curation

### Expected Outcome

Freya learns from external sources while retaining project-specific understanding.

---

# Phase 7 — Multi-Provider AI

## Goal

Support multiple LLM providers.

### Objectives

* Claude provider
* OpenAI provider
* Gemini provider
* DeepSeek provider
* Provider routing
* Health-based failover
* Cost-aware model selection

### Expected Outcome

Freya can select the most appropriate model for each task.

---

# Phase 8 — Long-Term Autonomy

## Goal

Move from reactive assistance toward proactive operation.

### Objectives

* Background task scheduler
* Autonomous goal management
* Periodic backlog review
* Persistent user preferences
* Long-running jobs
* Automatic recovery

### Expected Outcome

Freya operates continuously with minimal supervision.

### Progress

* Goal Management Phase 1 — Goal Data Model: ✅ Complete. `Goal` dataclass + JSON-file persistence (`GoalStorage` with `create` / `update` / `delete` / `list` / `save` / `load`) live in `app/memory/goals.py`; exported via `app/memory/__init__.py`.
* Goal Management Phase 2 — Persistent Goal Storage: ✅ Complete. Same `GoalStorage` (no new module). Goals auto-load from `data/memory/goals.json` on construction; every CRUD verb flushes through the atomic `.tmp` + `replace` write path; restart-survival and `parent_goal_id` / `child_goal_ids` round-trip verified.
* Goal Management Phase 3 — Goal Tree: ✅ Complete. `parent_of` / `children_of` / `descendants_of` / `complete(goal_id)` added to `GoalStorage`. Children are derived by scanning for `parent_goal_id == X` (no auto-wiring required on `create` / `update`); `complete()` recursively promotes any ancestor whose observed children are all `status="completed"`, stopping at the first ancestor that still has a non-completed child.
* Goal Management Phase 4 — Goal Progress Tracking: ✅ Complete. `Goal` gained `created_at` / `updated_at` (ISO UTC strings; bumped only when an `update()` call actually changes a field). `GoalStorage` gained `progress(goal_id) -> {total_children, completed_children, percentage}`, `is_completed(goal_id)`, and a single-tenant active-goal indicator (`set_active` / `active_goal` / `clear_active`) persisted in the storage `metadata` block so the active marker survives restarts.
* Goal Management Phase 5 — Goal Scheduler: ✅ Complete. `Goal` gained `depends_on_ids: List[str]` (backwards compatible — pre-Phase-5 files load with `[]` defaults). `GoalStorage` gained `dependencies_of(goal_id)` (read prereqs, skipping dangling ids), `is_blocked(goal_id)` (explicit `status="blocked"` / unmet dep / unsatisfiable missing dep), `queue()` (eligible — non-completed, non-blocked, non-active — goals sorted by priority rank critical → high → medium → low → optional with unknown priorities last via stable sort), and `select_next()` (picks the highest-priority eligible goal, marks it active, persists the marker; returns `None` when nothing eligible). Test suite is 100 / 100 green in `tests/test_goals.py`.
* Goal Management Phase 6 — Automatic Goal Decomposition: ✅ Complete. `SubtaskSuggestion` dataclass + `GoalStorage.decompose_goal(goal_id, max_subtasks=5)` (read-only, returns up to five draft suggestions from a deterministic Plan / Implement / Test / Document / Review template; subtask priorities inherit from the parent goal and the parent description is appended to the first suggestion) and `GoalStorage.apply_decomposition(goal_id, suggestions, plan_manager=None)` (the manual-approval opt-in that materialises suggestions as real child goals via the existing `create(parent_goal_id=...)` path; the optional `plan_manager` kwarg is the **Planner integration** hook — each approved suggestion is mirrored as a parallel `Task` via the existing `PlanManager.add_task(...)` surface; the goal side stays the source of truth and planner failures cannot roll back the goal side). Test suite is 119 / 119 green in `tests/test_goals.py`.
* Goal Management Phase 7 — Autonomous Goal Review: ✅ Complete. `Goal` gained `metadata: Dict[str, Any]` (backwards compatible — pre-Phase-7 files load with `{}` default) for lifecycle bookkeeping (`previous_status`, `pause_reason`, `stall_reason`, `recommend_reason`, `abandon_reason`); new `paused` status treated distinctly from existing values. `GoalStorage` gained `list_stalled(stall_threshold_seconds, include_paused, now)` (read-side: goals older than threshold, not terminal `completed`/`cancelled`, paused excluded by default), `block_reasons(goal_id)` (read: human-readable reasons — explicit `blocked` status, incomplete named deps, missing dep ids), `pause_goal(goal_id, reason="")` (write: flips to `"paused"`, stashes prior status in `metadata["previous_status"]` + optional `metadata["pause_reason"]`; terminal goals never paused; re-pausing paused goal is idempotent), `pause_inactive(stall_threshold_seconds, reason="", include_paused=False)` (bulk pause via `list_stalled` → `pause_goal`; returns only goals whose status actually flipped), `resume_goal(goal_id)` (write: restores from `metadata["previous_status"]` (fallback `"pending"`), clears bookkeeping keys), `is_paused(goal_id)` (read: paused-state bool), `recommend_cancellation(stall_threshold_seconds, pause_threshold_seconds=0.0, now)` (read: returns goals exceeding *both* thresholds — two-signal gate because cancellation is higher stakes), `recommend_priorities(now)` (read: signal-count heuristic bumps priority down, active goal preserved, manual priorities unchanged unless clear signal); `select_next()` updated to auto-resume a paused goal when it would otherwise be the highest-priority eligible candidate (Phase 5/7 integration; callers need not call `resume_goal` first). Test suite 119/119 green. Pre-Phase-4/5/7 `goals.json` files load cleanly. Phase 8-onward work remains: planner integration driven by active goals (running the agent *from* goals), autonomous-loop wiring, human oversight UI for create/pause/resume/cancel, hierarchy-invariant management, formalised `status`/`priority` enums.
* Goal Management Phase 8 — Planner Integration: ✅ Complete. Added `GoalStorage` to `FreyaAgent` (`app/agent/core_agent.py`); new execution entry point `FreyaAgent.run_goal(goal_id: Optional[str] = None, allow_mutations: bool = True)` resolves the active goal (uses current active or falls back to `select_next()`), plans from the goal description via existing `Planner.create_plan()`, executes via `Executor.execute_plan()`, then advances goal state — calls `complete()` if all children done (Phase 3 propagation) for leaf goals marks `status="completed"` after max iterations. Also added `FreyaAgent.run_goal_loop(max_goals=10, max_iterations_per_goal=3)` for continuous autonomous operation: repeatedly calls `select_next()` → `run_goal()` until no eligible goals or limit reached. Backwards compatible: existing `run()` / `solve()` / `repair()` untouched; callers opt into goal-driven behavior by calling `run_goal()`. Test suite 119/119 green.

---

# Self-Evaluation

## Goal

Implement Freya's ability to objectively assess her own work quality before declaring a task complete.

## Critical Capabilities Implemented (100%)

| # | Objective | Status | Description |
|---|-----------|--------|-------------|
| 1 | **Evaluation Framework** | ✅ Complete | Core architecture: EvaluationManager, data models, pipeline, interfaces in `app/evaluation/` |
| 2 | **Requirement Verification** | ✅ Complete | Checks completed work against original request/objectives via RequirementVerifier |
| 3 | **Functional Validation** | ✅ Complete | Auto-runs tests, build checks, execution verification via ValidationRunner |
| 4 | **Confidence Scoring** | ✅ Complete | Measurable quality indicators + completion thresholds; deliver/rework/review decisions |

## Implementation Details

**Module:** `app/evaluation/`
- `models.py` — Data models (Requirement, RequirementVerification, ValidationCheck, ValidationResult, EvaluationConfig, EvaluationResult, ConfidenceLevel, etc.)
- `pipeline.py` — EvaluationPipeline, RequirementVerifier, ValidationRunner
- `manager.py` — EvaluationManager, EvaluationHistory, evaluate_before_delivery()

**Agent Integration (`app/agent/core_agent.py`):**
- `EvaluationManager` initialized in `FreyaAgent.__init__`
- Evaluation runs after `solve()` success
- Evaluation runs after `run_active_goal()` completion
- Evaluation runs after `run()` for engineering tasks
- Results logged with summary and rework/review warnings

**Tests:** `tests/test_evaluation.py` — 31 tests, all passing

---

# Phase 9 — Performance Optimization

## Goal

Improve speed, scalability, and efficiency.

### Objectives

* Streaming responses
* Token accounting
* Cost metrics
* Latency metrics
* Incremental semantic indexing
* Plan caching
* Parallel execution
* Hardware acceleration

### Expected Outcome

Higher throughput with lower latency.

---

# Phase 10 — Productivity Ecosystem

## Goal

Expand beyond software engineering.

### Objectives

* Calendar integration
* Email integration
* Document generation
* Spreadsheet support
* PDF support
* Cloud storage
* Issue tracker integration
* Release note generation

### Expected Outcome

Freya becomes a complete engineering productivity assistant.

---

# Phase 11 — Creative Media

## Goal

Support multimedia workflows.

### Objectives

* Speech-to-text
* Text-to-speech
* Image understanding
* Image generation
* Audio analysis
* Video transcription
* Screenshot-to-code

### Expected Outcome

Freya supports multimodal engineering workflows.

---

# Phase 12 — GUI Evolution

## Goal

Create a polished desktop experience.

### Objectives

* Modern desktop interface
* Runtime dashboard
* Approval center
* Memory browser
* Planner visualization
* Health monitoring
* Tool activity viewer
* Future avatar support

### Expected Outcome

A user-friendly interface for autonomous software engineering.

---

# Long-Term Vision

Freya will evolve into a local autonomous software engineering system capable of:

* Understanding complex engineering requests.
* Planning complete solutions.
* Editing code safely.
* Verifying every change.
* Learning from experience.
* Improving its own capabilities.
* Expanding its knowledge.
* Operating with minimal human intervention while maintaining human oversight for high-impact actions.

---

# Guiding Principles

* Safety before autonomy.
* Simplicity before complexity.
* Integration before expansion.
* Verification before modification.
* Learning before repetition.
* Human approval for high-risk operations.
* Continuous incremental improvement.
