# Freya — Remaining Work

# Completion Progress

Overall Freya Functional Completion: 42.5%

Completed Tasks: 2 / 17
Remaining Tasks: 15 / 17

Last Updated: 2026-08-14

Next Active Task: Task 3 — Repair production autonomy startup and scheduled jobs

> The percentage retains the documented capability-weighted operational method: functionality receives credit only when its production path is implemented, wired, reachable, safe where required, and supported by runtime evidence. The task counts are the rolling queue counts and do not replace that capability-weighted percentage.

---

> This document contains only remaining work identified in the existing `PROJECT_STATUS.md`.
> Completed, working, and verified items have been removed from the execution queue.
> Tasks are ordered by documented dependency and execution sequence, not simply by priority.
>
> **Verified operational completion:** 42.5% (the current verified estimate in the source document supersedes the earlier 76.6% estimate).

---

# Critical Execution Path

1. 🔴 Task 3 — Repair production autonomy startup and scheduled jobs
   ↓
2. 🟡 Task 4 — Restore the shared event contract and event-driven improvement flow
   ↓
3. 🟡 Task 5 — Connect execution outcomes to learning and durable memory
   ↓
4. 🔴 Task 6 — Consolidate retrieval and restore cross-session knowledge recall
   ↓
5. 🔴 Task 7 — Replace obsolete tests with production-path integration evidence
   ↓
6. 🔴 Task 8 — Implement provider resilience
   ↓
7. 🟡 Task 9 — Repair monitoring and hardware-health evidence

Tasks 10–17 are parallel or independent work where the existing status document does not establish a prerequisite beyond the relationships stated in each task.

---

# Active Work


## Task 3 — Repair production autonomy startup and scheduled jobs

**Size:** 🔴 RED — BIG / COMPLEX
**Priority:** P0
**Execution Order:** 3

**Location**

- `app/long_term_autonomy/manager.py`: `_register_background_jobs()`, `_run_learning_pipeline_job()`, `_autonomy_watchdog_checkpoint()`, `_autonomy_self_initiated_work_job()`
- `app/long_term_autonomy/manager.py`: `_learn()`, `_execute_specific_task()`

**Problem**

The autonomy manager constructed by `SystemInitializer` fails production startup because `JobStatus` is undefined; `start()` returns failure and `AUTONOMY_RUNNING=False`. Scheduled callbacks call absent methods such as `run_cycle`, `checkpoint`, and `discover_work`. The learning step does not perform actual learning-pipeline work, and autonomous task execution references an uninitialized planner and can mark work complete without verified execution.

**Required Work**

- Import and use the correct job-state type.
- Align every scheduled callback with an implemented interface.
- Make failed autonomy startup propagate as an initialization failure.
- Instantiate and inject a planner and executor explicitly.
- Implement the actual learning handoff.
- Prevent completion status unless execution is verified.
- Add production-startup and recurring-job integration tests.

**Dependencies**

- Must come after Tasks 1 and 2.
- Blocks long-running autonomy, autonomous learning, maintenance, recovery, and health-observation claims.

**Why This Order**

The source document identifies autonomy startup as a critical blocker and states that it must be repaired before long-running autonomy and recovery work.

**Acceptance Criteria**

- [ ] Production autonomy starts successfully.
- [ ] All registered recurring callbacks target implemented interfaces.
- [ ] Startup failure is visible as initialization failure.
- [ ] Autonomous work receives explicit planner/executor dependencies.
- [ ] Work cannot be marked complete without verified execution.

---

## Task 4 — Restore the shared event contract and event-driven improvement flow

**Size:** 🔴 RED — BIG / COMPLEX
**Priority:** P1
**Execution Order:** 4

**Location**

- `app/core/initializer.py`: lines 110, 164–167, 290–304
- `app/safe_self_improvement/self_improvement.py`: constructor and `create_self_improvement_engine()`
- `app/diagnostics/diagnostic_engine.py`: `_emit_diagnostic_event()`

**Problem**

The initializer uses a local `EventBus`, while safe self-improvement calls the global `get_event_bus()` and its factory does not accept dependency injection. Production learning and diagnostics events therefore do not reach the improvement engine. Diagnostic event emission also uses `EventPriority.NORMAL` without importing `EventPriority`; a broad exception handler hides the failure.

**Required Work**

- Add explicit event-bus injection to the self-improvement engine and factory.
- Pass the initializer-local bus to all related components.
- Import the correct event-priority type.
- Surface event-publication failures appropriately.
- Add real integration tests for learning→improvement and diagnostics→improvement.

**Dependencies**

- Must come after Task 1.
- The event and dependency-injection contract must be fixed before improvement-flow testing.
- Diagnostics event delivery should coordinate with the event-bus injection fix.

**Why This Order**

The existing status explicitly identifies incompatible event-bus ownership and broken diagnostic emission as critical blockers.

**Acceptance Criteria**

- [ ] Learning and diagnostics publish to the bus consumed by safe self-improvement.
- [ ] Diagnostic completion events are delivered or failures are surfaced.
- [ ] Improvement candidates are created through the production event path.
- [ ] End-to-end event tests pass with real component wiring.

---

## Task 5 — Connect execution outcomes to learning and durable memory

**Size:** 🟡 YELLOW — MEDIUM
**Priority:** P1
**Execution Order:** 5

**Location**

- `app/verification/execution_verifier.py`: `_route_to_learning_pipeline()`
- `app/execution/engine.py`
- `app/learning/pipeline.py`

**Problem**

`ExecutionVerifier` calls `LearningPipeline.add_experience()`, but the initialized pipeline exposes `run(candidate)`. The normal execution engine also does not construct or call `ExecutionVerifier`, so actual task outcomes do not reliably reach learning, especially successful work.

**Required Work**

- Define one typed learning-outcome contract.
- Replace the incompatible method call with the supported pipeline handoff.
- Connect `ExecutionVerifier` to the normal execution state machine.
- Ensure successful and failed task outcomes persist to memory.
- Add integration tests for both outcomes.

**Dependencies**

- Must come after Task 2.
- Blocks completion of execution-learning claims.

**Why This Order**

The source document explicitly states that execution learning depends on the P0 execution state-machine repair.

**Acceptance Criteria**

- [ ] Execution verification reaches `LearningPipeline.run(candidate)` through the production path.
- [ ] Successful and failed outcomes are persisted.
- [ ] The typed contract prevents silent API mismatch.
- [ ] Integration tests cover both outcome classes.

---

## Task 6 — Consolidate retrieval and restore cross-session knowledge recall

**Size:** 🔴 RED — BIG / COMPLEX
**Priority:** P1/P2
**Execution Order:** 6

**Location**

- `app/memory/unified_retrieval.py`
- `app/knowledge_retrieval/pipeline.py`
- `app/memory/conversation_memory.py`
- Vector-memory integration tests

**Problem**

Production routes use `UnifiedRetrieval`, while the more advanced calibration, learned ranking, analytics, and retrieval-decision pipeline is orphaned. The APIs and data models diverge. All three conversation/vector integration tests fail, so cross-session semantic recall is not established.

**Required Work**

- Integrate the advanced pipeline behind the production retrieval interface or remove/consolidate it.
- Preserve one observable retrieval contract.
- Diagnose vector persistence/retrieval mismatch.
- Define restart semantics.
- Add deterministic persistence-and-retrieval integration tests.

**Dependencies**

- Must follow Task 1's runtime-architecture decision.
- Vector recall work is independent after the supported retrieval stack is selected.

**Why This Order**

The document lists retrieval consolidation after the canonical runtime decision and before final production-path verification.

**Acceptance Criteria**

- [ ] One retrieval implementation is supported in production.
- [ ] Calibration, ranking, analytics, and decision behavior are either reachable or explicitly retired.
- [ ] Cross-session vector recall works deterministically across restart.
- [ ] Production retrieval has one stable contract.

---

## Task 7 — Replace obsolete tests with production-path integration evidence

**Size:** 🔴 RED — BIG / COMPLEX
**Priority:** P1
**Execution Order:** 7

**Location**

- `tests/`
- `tests/test_integration_autonomous.py`
- Production startup and runtime paths

**Problem**

The audited suite collected successfully but produced 1,942 passed, 69 failed, 36 errors, and 43 skipped tests. Existing tests often target duplicate or isolated implementations rather than the normal application graph. The production autonomy manager has no direct test coverage.

**Required Work**

- Repair or retire obsolete tests after runtime consolidation.
- Add black-box tests for `FreyaApp` startup, chat, task execution, verification, safety denial, event propagation, restart/persistence, and background autonomy jobs.
- Add production-path tests for retrieval, learning, safe self-improvement, diagnostics, monitoring, and recovery.
- Require a clean critical-path suite.

**Dependencies**

- Must follow Task 1 and the relevant implementation repairs in Tasks 2–6.
- Blocks the claim that the production architecture is operational.

**Why This Order**

The existing document states that duplicate runtime paths must be consolidated before tests can prove the actual architecture.

**Acceptance Criteria**

- [ ] Tests exercise the normal production graph.
- [ ] Obsolete-path tests are migrated or retired.
- [ ] Critical-path failures and errors are resolved.
- [ ] Startup, safety, verification, learning, persistence, and autonomy are covered end to end.

---

## Task 8 — Implement provider resilience

**Size:** 🔴 RED — BIG / COMPLEX
**Priority:** P1
**Execution Order:** 8

**Location**

- `app/providers/factory.py`: lines 227–231

**Problem**

The provider factory registers only `OllamaProvider`; `local` is merely an alias. There is no real multi-provider routing, failover, health-aware selection, or graceful capability degradation beyond one local service.

**Required Work**

- Implement the intended provider-abstraction contract.
- Add provider health checks.
- Add configured fallback ordering.
- Classify timeout and provider errors.
- Implement safe no-provider behavior.
- Test outage and fallback scenarios.

**Dependencies**

- Can proceed independently.
- The final contract should be consumed by execution resilience and tested in Task 7.

**Why This Order**

The source document explicitly marks provider resilience as independently actionable, while placing it after runtime, execution, and learning-path repairs in the path to 100%.

**Acceptance Criteria**

- [ ] More than one provider can be selected under the supported contract.
- [ ] Health-aware fallback and timeout/error classification work.
- [ ] No-provider behavior is safe and observable.
- [ ] Provider outage tests pass.

---

## Task 9 — Repair monitoring and hardware-health evidence

**Size:** 🟡 YELLOW — MEDIUM
**Priority:** P2
**Execution Order:** 9

**Location**

- `app/monitoring/*`
- `tests/test_network_monitor.py`
- `tests/test_gpu_monitor.py`

**Problem**

Fifteen network-monitoring tests and two GPU-monitoring tests fail. Endpoint/session/error handling and hardware fallback behavior are not dependable enough for operational feedback.

**Required Work**

- Repair endpoint, session, and error handling.
- Repair hardware fallback behavior.
- Add environment-independent tests.
- Connect verified health results to production readiness decisions.

**Dependencies**

- Independent, but required before autonomy can act on health observations.

**Why This Order**

The status document places monitoring repair before dependable watchdog and operational decisions, while not documenting a prerequisite on the critical implementation chain.

**Acceptance Criteria**

- [ ] Network and GPU monitoring tests pass in environment-independent form.
- [ ] Health results are reliable and observable.
- [ ] Production readiness decisions consume verified health signals.

---

## Task 10 — Enforce workflow capability and safety behavior

**Size:** 🟡 YELLOW — MEDIUM
**Priority:** P2
**Execution Order:** 10

**Location**

- `app/orchestrator/workflow_orchestrator.py`: `_start_background_jobs()`
- `app/orchestrator/capabilities.py`
- `app/orchestrator/safety_gate.py`

**Problem**

Workflow background-job startup is empty, selected capabilities include placeholder or unsupported actions, and safety-gate behavior has failing tests.

**Required Work**

- Implement or remove nonfunctional execution paths.
- Validate capability registration against callable actions.
- Make safety outcomes observable and enforced.

**Dependencies**

- Must come after Task 2's execution and safety repair.

**Why This Order**

The existing issue explicitly depends on the P0 execution/safety repair.

**Acceptance Criteria**

- [ ] Background workflow jobs perform supported work or are removed.
- [ ] Every registered capability maps to a callable action.
- [ ] Safety outcomes are enforced and testable.

---

## Task 11 — Complete autonomy learning and verified task execution

**Size:** 🔴 RED — BIG / COMPLEX
**Priority:** P1
**Execution Order:** 11

**Location**

- `app/autonomous_learning/pipeline.py`
- `app/long_term_autonomy/manager.py`
- `app/core/initializer.py`

**Problem**

`AutonomousLearningPipeline` is a complete parallel system but is not imported, instantiated, or started. Its default-enabled configuration is unused. Long-term autonomy has the documented missing learning handoff and uninitialized planner/executor behavior.

**Required Work**

- Instantiate and schedule the selected autonomous learning implementation in the canonical initializer.
- Connect gap detection, research, consolidation, and memory persistence.
- Implement the actual learning handoff.
- Inject planner and executor dependencies.
- Require verified execution before reporting completion.

**Dependencies**

- Must come after Tasks 1, 2, and 3.
- Task 3 repairs the production autonomy lifecycle before this feature is enabled.

**Why This Order**

The status document says the autonomous learning system cannot be enabled until autonomy startup and execution reliability are repaired.

**Acceptance Criteria**

- [ ] Autonomous learning starts through the production initializer.
- [ ] Background learning reaches memory through the selected pipeline.
- [ ] Autonomous tasks use injected planner/executor components.
- [ ] Completion is based on verified work.

---

## Task 12 — Remove or migrate the legacy orchestrator path

**Size:** 🟡 YELLOW — MEDIUM
**Priority:** P2
**Execution Order:** 12

**Location**

- `app/orchestrator/orchestrator.py`
- `tests/test_integration_autonomous.py`
- `app/orchestrator/capability_registry.py`

**Problem**

The legacy orchestrator passes unsupported `auto_discovery` to `CapabilityRegistry`, producing start failures. Integration tests exercise this obsolete path while production initializes `workflow_orchestrator.py`.

**Required Work**

- Remove or migrate the legacy orchestrator.
- Repoint integration tests to the actual production orchestrator.
- Preserve one supported orchestration contract.

**Dependencies**

- Must follow Task 1's runtime-architecture decision.

**Why This Order**

The status document identifies this as stale migration work caused by duplicate runtime paths.

**Acceptance Criteria**

- [ ] The unsupported `auto_discovery` path is removed or migrated.
- [ ] Integration tests target the production orchestrator.
- [ ] Duplicate orchestration claims are eliminated.

---

## Task 13 — Repair conversation/vector persistence and recall

**Size:** 🟡 YELLOW — MEDIUM
**Priority:** P2
**Execution Order:** 13

**Location**

- `app/memory/conversation_memory.py`
- Vector-memory integration tests

**Problem**

All three conversation/vector integration tests fail, so cross-session semantic recall is not established.

**Required Work**

- Diagnose the vector persistence/retrieval mismatch.
- Define restart semantics.
- Add deterministic persistence-and-retrieval integration tests.

**Dependencies**

- Independent after Task 1 selects the supported retrieval stack.

**Why This Order**

The status document explicitly permits this work independently after the retrieval-stack decision.

**Acceptance Criteria**

- [ ] Conversation data survives the documented restart boundary.
- [ ] Cross-session semantic retrieval is deterministic.
- [ ] The three failing integration scenarios pass.

---

## Task 14 — Add production health/readiness surface

**Size:** 🔵 BLUE — EASY / SMALL
**Priority:** P1/P3
**Execution Order:** 14

**Location**

- `main.py`
- `app/core/observability.py`

**Problem**

No health/readiness endpoint exposes initialization state, provider availability, background-service state, or dependency readiness. The earlier status also identifies this as a P1 operational gap; the authoritative current section classifies the remaining implementation as P3.

**Required Work**

- Add a read-only health/readiness surface.
- Drive it from the same observability state used at runtime.
- Expose initialization, provider, background-service, and dependency readiness.

**Dependencies**

- Should follow repair of the underlying component health signals, especially Tasks 3 and 9.

**Why This Order**

The source document states that the endpoint should follow repair of the signals it reports.

**Acceptance Criteria**

- [ ] Readiness distinguishes a live process from a usable agent.
- [ ] Provider and background-service state are represented.
- [ ] The surface is read-only and backed by runtime observability.

---

## Task 15 — Add configurable learning and repair policy

**Size:** 🔵 BLUE — EASY / SMALL
**Priority:** P3
**Execution Order:** 15

**Location**

- `app/learning/pipeline.py`
- `app/verification/answer_repair_loop.py`

**Problem**

Learning thresholds and repair-loop behavior remain hardcoded, limiting controlled tuning and environment-specific policy.

**Required Work**

- Move supported thresholds to validated configuration.
- Move retry and prompt policy to validated configuration.
- Preserve safe defaults and add configuration tests.

**Dependencies**

- Independent after Task 5 fixes the execution-learning contract.

**Why This Order**

The status document places configuration tuning after the learning contract and core implementation repairs.

**Acceptance Criteria**

- [ ] Thresholds and repair policy are configurable.
- [ ] Invalid values are rejected safely.
- [ ] Default behavior remains safe and tested.

---

## Task 16 — Resolve remaining memory and retrieval quality gaps

**Size:** 🟡 YELLOW — MEDIUM
**Priority:** P2/P3
**Execution Order:** 16

**Location**

- `app/memory/unified_retrieval.py`
- Memory retriever implementations
- Cross-memory reference integration

**Problem**

The earlier status identifies duplicate retriever classes in `UnifiedRetrieval`, missing calibration/ranking/analytics, nine of sixteen memory modules with zero tests, no custom serialization framework, and `CrossMemoryReferences` auto-inference that is not triggered.

**Required Work**

- Consolidate duplicate retriever classes.
- Provide the selected retrieval stack with calibration, ranking, and analytics where retained.
- Add tests for currently untested memory modules.
- Define or implement the required serialization behavior.
- Trigger cross-memory reference auto-inference through the production flow.

**Dependencies**

- Retrieval portions must follow Task 1 and Task 6.
- Cross-memory and test work may proceed independently once the supported memory contract is established.

**Why This Order**

These are remaining lower-priority memory and retrieval-quality items that depend on selecting a single supported retrieval architecture.

**Acceptance Criteria**

- [ ] Duplicate retriever behavior is consolidated.
- [ ] Retained retrieval features are reachable through production.
- [ ] Previously untested memory modules have coverage.
- [ ] Serialization and cross-memory inference behavior are defined and exercised.

---

## Task 17 — Resolve stale documentation and test contracts

**Size:** 🔵 BLUE — EASY / SMALL
**Priority:** P3
**Execution Order:** 17

**Location**

- `tests/test_user_communication.py`
- Repository root

**Problem**

Tests expect a missing `NATURAL_CONVERSATION.md`, and some expectations no longer match current runtime names or behavior.

**Required Work**

- Resolve stale documentation/test contracts after runtime architecture consolidation.
- Align test expectations with the supported runtime names and behavior.

**Dependencies**

- Must follow the P1/P2 migration work, especially Tasks 1, 7, and 12.

**Why This Order**

The source document explicitly places this hygiene work after runtime consolidation.

**Acceptance Criteria**

- [ ] Tests no longer depend on stale or missing documentation contracts.
- [ ] Runtime names and expected behavior are aligned.
- [ ] Remaining failures represent actionable implementation issues.

---

# Parallel / Independent Work

These tasks do not have a documented prerequisite on the critical execution chain, or the source document explicitly allows them to proceed independently:

- 🟡 **Task 8 — Implement provider resilience**. It can proceed independently, although execution resilience should consume its final contract.
- 🟡 **Task 9 — Repair monitoring and hardware-health evidence**. It can proceed independently, but autonomy should not act on health observations until it is complete.
- 🟡 **Task 13 — Repair conversation/vector persistence and recall**. It can proceed after the supported retrieval stack is selected.
- 🔵 **Task 15 — Add configurable learning and repair policy**. It can proceed after the execution-learning contract is fixed.
- 🟡 **Task 16 — Resolve remaining memory and retrieval quality gaps**. Its cross-memory and coverage portions can proceed after the supported memory contract is established.

---

# Dependency Notes

The documented order to reach 100% is: establish one canonical runtime graph; repair execution safety and verification; repair autonomy startup and background jobs; restore the shared event contract; connect execution outcomes to learning and durable memory; consolidate retrieval and cross-session recall; implement provider resilience and health/observability; replace stale tests with production-path evidence; and only then tune configuration, documentation, and optional capability breadth.

No dependency has been added where the existing status document did not establish one. Where the source document did not specify a prerequisite, the task states: **Dependencies: Not specified in existing status document.**

---

# Remaining Work Summary

| Size | Remaining tasks |
|---|---:|
| 🔴 RED — Big / Complex | 6 |
| 🟡 YELLOW — Medium | 7 |
| 🔵 BLUE — Easy / Small | 3 |
| **Total** | **16** |

| Priority | Remaining work |
|---|---|
| **P0 — Critical** | Tasks 2–3: production autonomy startup and execution/safety enforcement |
| **P1 — High** | Tasks 4–5, 7–8, 11, 14: event wiring, execution learning, production tests, provider resilience, autonomous learning, readiness surface |
| **P2 — Medium** | Tasks 6, 9–10, 12–13, 16: retrieval, monitoring, workflow capability/safety, legacy migration, vector recall, memory quality |
| **P3 — Low** | Tasks 14–17: readiness completion, configurable policy, memory-quality tail work, stale contracts |

**Current verified completion:** 42.5%. The existing status document records 0 P0 issues in its earlier consolidated summary, but the authoritative current section explicitly identifies two remaining P0 critical blockers: autonomy startup and execution/safety enforcement. This roadmap preserves that later authoritative classification.

---

# Critical Blockers

1. Production autonomy does not start successfully and scheduled autonomy jobs target absent interfaces.
2. Learning, diagnostics, and safe self-improvement are disconnected by incompatible event-bus ownership, and diagnostic event emission is broken.
3. The runtime is fragmented across production, legacy, and test-only implementations, leaving key features unreachable and tests disconnected from the normal application graph.

---

# Path to 100%

Freya reaches 100% only when a normal `FreyaApp` startup reliably composes one supported architecture; safely accepts or rejects actions; plans, executes, verifies, repairs, and persists outcomes; learns from those outcomes; uses persistent and retrievable knowledge across sessions; runs healthy autonomous background work; routes diagnostics and learning through controlled improvement safeguards; survives configured provider and tool failures; and demonstrates these chains through a clean, production-path test suite.

The current verified operational completion is **42.5%**. The earlier 76.6% estimate is superseded by the current verified assessment and is not used as the completion baseline.

---

# COMPLETED WORK HISTORY

## Task 1 — Canonical Production Runtime Graph

**Status:** COMPLETE

**Implementation summary**

- **Canonical implementations selected:** `AgentFacadeImpl` remains the production Agent boundary; `WorkflowOrchestrator` is the canonical orchestrator; `MemoryCoordinator.unified_retrieval` / `UnifiedRetrieval` remains the production Retrieval contract; `LearningPipeline` plus `app.autonomy.manager.AutonomyManager` are the canonical learning/autonomy components.
- **Runtime wiring established:** `SystemInitializer` now constructs the canonical WorkflowOrchestrator before AutonomyManager and injects the shared router, execution engine, safety gate, event bus, job service, learning pipeline, goal storage, and workflow orchestrator.
- **Legacy-path isolation:** The agent package no longer eagerly imports the legacy `FreyaAgent`; the orchestrator package no longer eagerly imports the legacy `CentralOrchestrator`. Both remain available as lazy compatibility exports without being pulled into the canonical production startup path.
- **Interfaces/adapters changed:** No broad subsystem rewrite or new parallel implementation was added. The initializer now uses the existing dependency-injection contracts of `app.autonomy.manager.AutonomyManager` and `WorkflowOrchestrator`.
- **Tests/verification performed:** Python compilation passed for the changed initializer and orchestration modules. A focused production-graph smoke test passed, verifying the Agent facade, WorkflowOrchestrator, UnifiedRetrieval, LearningPipeline, and AutonomyManager are instantiated, connected, reachable, and running. The targeted workflow unit test was attempted; one pre-existing rejection-test failure remains because the test's mocked safety setup does not raise as expected. The repository does not have a `pytest` executable in the environment.
- **Remaining limitations:** Task 3 autonomy reliability hardening and other queued work remain unfinished. Capability registration currently emits duplicate-replacement warnings during startup but does not prevent the canonical graph from starting.
- **Code commit:** `a456860b0565c8802b74895484e5e061a81d1d0d`

---

## Task 2 — Execution Safety & Verification State Machine

**Status:** COMPLETE

**Implementation summary**

- **Files changed:** `app/agent/executor.py`, `app/execution/engine.py`, `app/orchestrator/task_executor.py`, `app/orchestrator/workflow_orchestrator.py`, and `tests/test_execution_safety_state_machine.py`.
- **State machine repaired:** The facade path now records proposal, validation, safety checking, authorization, execution, verification, repair, success, and failure states. The orchestrator path now exposes safety-checking, authorization, verification, verification-failure, safety-denied, and terminal failure states through `ExecutionState` and workflow status mapping.
- **Safety enforcement repaired:** The shared `SafetyGate` is invoked before each plan and concrete task/workflow action. Safety denial is terminal, observable, and prevents dispatch to the executor.
- **Verification and repair repaired:** Normal execution now invokes `VerificationRunner`; failed verification invokes the existing `RepairLoop`, and unsuccessful repair leaves execution in an accurate safe-failure state rather than reporting success.
- **Failure handling repaired:** Capability lookup failures, execution exceptions, unsuccessful tool results, invalid or incomplete results, cancellation, and verification failures no longer become successful completion. Final outcome metadata is persisted through `PlanManager` and workflow events/status.
- **Tests and verification:** The focused lifecycle, workflow, and executor suite passes: `35 passed`. A deterministic production-path smoke test also passed through `WorkflowOrchestrator` → `TaskExecutor`, covering allowed and safety-denied execution. The repository-wide pytest configuration still contains a Windows-only `C:/temp/pytest_tmp` basetemp; targeted runs used an equivalent Linux-safe override. The broader component run had unrelated pre-existing failures in interactive permission fixtures and `FreyaAgent.experience_memory`.
- **Remaining Task 2 limitations:** The normal `WorkflowOrchestrator.start()` path still encounters the documented unrelated `CapabilityRegistry(auto_discovery=...)` constructor defect, and the smoke harness injected the registry/composed workflow to isolate Task 2. That startup issue remains queued under later work and was not modified.
- **Implementation commit:** pending until commit.

---

# Source Boundary

This file is a rolling prioritized work queue. It contains the remaining implementation tasks at the top and records completed task summaries at the bottom. Task 1 and Task 2 completion histories reflect the actual code changes and targeted verification performed.
