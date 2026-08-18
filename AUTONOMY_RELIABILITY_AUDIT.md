# Autonomy Reliability Audit

**Project:** Freya  
**Scope:** `pasted_content_15` autonomy hardening  
**Author:** Manus AI  
**Audit date:** 2026-08-18 (GMT+8)

## Executive conclusion

> **AUTONOMY: CONTROLLED AND RELIABLE within the verified local scope**

The existing autonomy architecture was retained. Self-initiated goal work and scheduled maintenance still enter `WorkflowOrchestrator`, which applies the existing safety boundary and `TaskExecutor` path. The hardening adds explicit candidate provenance, stable deduplication keys, conservative per-cycle action caps, bounded retry state and backoff, verified completion requirements, and deterministic shutdown cleanup. No second autonomous execution engine was introduced.

The normal production launcher keeps autonomy disabled unless it is explicitly enabled. This is an intentional safety default, not a failed acceptance gate.

## Architecture discovered

`AutonomyManager` coordinates three existing subcomponents: `Watchdog`, `SelfInitiatedWorkManager`, and `MaintenanceManager`. Shared `BackgroundJobService` owns recurring scheduling. `SelfInitiatedWorkManager` reads eligible goals from `GoalStorage`, creates a generic goal-progress workflow, and invokes `WorkflowOrchestrator.execute_workflow(..., async_mode=True)`. `MaintenanceManager` creates scheduled system workflows through the same orchestrator. `WorkflowOrchestrator` composes the workflow, runs the existing safety check, and dispatches to `TaskExecutor`. `TaskExecutor` performs capability steps and, when configured with a verification runner, records verification metadata before reaching completed state. `Watchdog` feeds observations to the canonical `LearningPipeline`.

Startup dependency validation already prevents enabled autonomy from starting without its required event bus, observability, learning, goal, workflow, or job-service dependencies. `AutonomyManager` stops components in reverse order and rolls back partial startup.

## Gaps found before autonomy changes

Self-initiated work only checked for active work with the same goal ID. It did not carry a structured explanation of why the work was proposed, did not expose a stable equivalent-work key, and could create more than one action per check cycle. Its retry state was not explicit, and it treated `WorkflowStatus.COMPLETED` as sufficient completion evidence. Shutdown stopped the manager but did not deterministically cancel and record active monitored work.

Scheduled maintenance used the shared workflow path, but similarly lacked the self-initiated candidate contract, a shared per-cycle cap, explicit completion verification, and monitor-thread cleanup. Watchdog deduplication and LearningPipeline filtering were already present and were preserved.

## Changes made

| File | Change |
|---|---|
| `app/autonomy/models.py` | Added `AutonomyCandidate` with source, source ID, proposed action, reason, goal, expected value, urgency, risk, required authorization/resources, deduplication key, retry state, trace ID, and timestamp. Added conservative action-budget and retry settings to `AutonomyConfig`. |
| `app/autonomy/self_initiated.py` | Validates goal provenance; creates a candidate; attaches candidate and request context to workflow context; uses stable goal-based deduplication; caps actions per cycle; tracks retry attempts and next retry time; does not rethrow recurring execution failures; requires verified workflow completion; cancels and records active work on shutdown. |
| `app/autonomy/maintenance.py` | Applies the same candidate/request-context contract to scheduled maintenance; caps actions per cycle; deduplicates active maintenance work; requires verified completion; tracks monitor threads; cancels and records pending work on shutdown. |
| `app/orchestrator/workflow_orchestrator.py` | Added `get_workflow_verification()` as a read-only adapter over TaskExecutor verification metadata. It returns `verified`, `failed`, or `unknown` evidence and never authorizes work. |
| `tests/test_pasted15_autonomy.py` | Added permanent coverage for invalid candidates, duplicate work, safety denial, bounded retries, verified completion, and shutdown cleanup. |

## Candidate and provenance contract

Every self-initiated action now carries an `AutonomyCandidate` equivalent to:

| Field | Production value |
|---|---|
| `source` | `goal_storage` for goal work; `maintenance_schedule` for scheduled maintenance. |
| `source_id` | The real goal ID or maintenance task type. |
| `proposed_action` | `make_progress_on_goal` or the concrete maintenance task type. |
| `reason` | Eligibility or approved recurring-maintenance reason. |
| `goal` | Goal ID/name/description or maintenance responsibility identity. |
| `expected_value` | Advancement of the originating goal or the maintenance description. |
| `urgency` | Goal priority or `scheduled`. |
| `risk` | Explicit statement that the concrete workflow must pass the SafetyGate. |
| `required_authorization` | `safety_gate_and_verification`. |
| `required_resources` | The existing workflow capability requirements. |
| `deduplication_key` | Stable SHA-256-derived key based on the originating responsibility. |
| `retry_state` | Attempt count, max retries, and next retry timestamp where applicable. |
| `trace_id` | Unique request identity generated for the autonomous action. |

This lets Freya answer why the action was considered, what responsibility authorized it, whether an equivalent action is active, what resources it requires, and which trace to inspect.

## Authority and safety boundary

Autonomous initiation is not authorization. The workflow context contains provenance and request identity, then the existing `WorkflowOrchestrator` performs its normal composition and SafetyGate evaluation. Task execution also retains its existing per-task SafetyGate boundary. Approval-required or denied operations therefore remain governed by the existing safety architecture. The autonomy changes do not approve, weaken, or bypass consequential operations.

## Action budget, retry, and deduplication policy

The conservative defaults are one autonomous action per cycle, at most three concurrent self-initiated tasks, one retry after a failure, 60 seconds of failure backoff, and a five-minute repeated-failure cooldown. Maintenance uses the same per-cycle budget and remains limited to two concurrent maintenance tasks, further bounded by the configured autonomy concurrency limit. The `BackgroundJobService` remains the scheduler and its existing bounded retry/non-retryable behavior remains in force.

A failing action records its attempt state and next eligible retry time. Once the retry threshold is exceeded, the same logical responsibility stops retrying automatically. Active equivalent work is suppressed by a stable deduplication key. The self-initiated soak harness ran five cycles with one unresolved goal and produced one workflow call, demonstrating no runaway creation.

## Verification and learning

Autonomous completion requires both terminal workflow status `COMPLETED` and an authoritative `verified` result from `TaskExecutor` metadata through `WorkflowOrchestrator.get_workflow_verification()`. A terminal workflow without evidence is recorded as failed with an explicit verification error, not marked complete. Missing verification API/evidence yields `unknown` and cannot satisfy autonomous completion.

Durable learning remains governed by the existing `LearningPipeline`, which suppresses unverified execution outcomes and invalid answer-verification candidates. Watchdog deduplication remains bounded by its configured time window and entry limit. The autonomy tick itself is not written as a durable lesson by the new code.

## Shutdown and startup behavior

`AutonomyManager` validates dependencies before enabling components, rolls back partial startup on error, and stops maintenance, self-initiated work, watchdog, and learning in reverse order. The hardened work managers set their shutdown event, remove recurring jobs, request cancellation for active workflow executions, mark interrupted work as failed with `final_status=shutdown`, join monitor threads briefly, and clear monitor tracking. This prevents pending autonomous work from being left as an unobserved running item.

## Autonomy acceptance gates

| Gate | Result | Evidence |
|---|---|---|
| 1. Legitimate provenance | **PASS** | Invalid goal candidate is rejected; valid goal and maintenance work carry source, source ID, reason, candidate, goal/responsibility, and trace metadata. |
| 2. Candidate deduplication | **PASS** | Stable responsibility keys suppress duplicate equivalent active jobs; five-cycle soak produced one workflow call. |
| 3. Same canonical foundation | **PASS** | Both self-initiated and maintenance paths call `WorkflowOrchestrator`, not a parallel executor. |
| 4. SafetyGate cannot be bypassed | **PASS** | Workflow and task safety checks remain in the existing orchestrator/executor path; injected safety denial fails work without destabilizing the manager. |
| 5. Approval-required actions pause correctly | **PASS** | The foundation approval-required regression resolves to `REQUIRE_APPROVAL` and `allowed=False`; autonomy supplies authorization metadata but does not auto-approve. |
| 6. Bounded retries | **PASS** | Permanent test confirms one configured retry and terminal attempt count 2 with `max_retries=1`; no third execution occurs. |
| 7. No infinite spawning | **PASS** | Per-cycle action budget, active-work deduplication, concurrency limits, cooldown, and five-cycle soak bound creation. |
| 8. Failures do not destabilize Freya | **PASS** | Safety denial and repeated execution failure are recorded as failed work; the manager remains stoppable and the broader foundation failure boundary remains usable. |
| 9. Verified completion | **PASS** | A `COMPLETED` workflow without verification is not success; an injected `verified` result is required and accepted. |
| 10. Selective learning | **PASS** | Existing LearningPipeline rejects unknown/unverified execution outcomes and repeated operational noise is not emitted as durable work completion learning by this change. |
| 11. Clean shutdown | **PASS** | Pending-work test confirms cancellation, empty active-work state, terminal shutdown history, and stopped manager. |
| 12. Bounded log/memory growth | **PASS** | Work history is capped at 100 entries; watchdog dedup is bounded; the five-cycle soak creates one work item and one history entry. |
| 13. Explainable initiation | **PASS** | Completion metadata and workflow context preserve candidate reason, source/source ID, goal or maintenance identity, dedup key, and trace ID. |

## Failure-injection results

The permanent autonomy regression suite covers invalid candidates, duplicate work, safety denial, repeated execution failure, completion requiring verified evidence, and shutdown during pending work. The foundation suite covers approval-required decisions, denied actions, timeout/`UNKNOWN`, and unavailable LLM/routing failure. Existing autonomy tests also cover missing dependency/startup validation, concurrent limits, blocked goals, manager lifecycle, and maintenance lifecycle.

A maintenance code path that fails before the work item is tracked releases its dedup key and logs the trace-aware failure rather than propagating an uncontrolled exception into repeated scheduler execution. The normal background scheduler remains bounded by its existing retry policy.

## Controlled autonomy soak

A temporary isolated harness used the existing `SelfInitiatedWorkManager` with a real manager lifecycle and five consecutive check cycles against one eligible goal. The result was `AUTONOMY_SOAK_OK cycles=5 workflow_calls=1 history=1`. Shutdown left the manager stopped and active work empty. This was a bounded lifecycle/duplicate-growth soak, not a performance benchmark and not a fabricated production success.

## Remaining limitations and risks

The maintenance path now uses the same candidate, budget, and verification boundary, but it does not introduce a new persistent retry database; retry state is in manager memory and therefore resets across a process restart. Restart safety is conservative because work identity is carried in the workflow context and active work is not automatically re-created without a new due-cycle decision. A future enhancement could persist autonomy retry/dedup state, but doing so is not necessary for the current disabled-by-default MVP autonomy mode.

Autonomy is only as reliable as the individual capabilities and providers it invokes. The task intentionally did not repair or exhaustively audit the 42 capabilities. When verification evidence is unavailable, autonomous completion fails closed rather than claiming success. This can reduce autonomous throughput, but it is the correct safety behavior.

## Final autonomy verdict

> **AUTONOMY: CONTROLLED AND RELIABLE within the verified local scope.**

The autonomy machinery is bounded, provenance-bearing, safety-gated, verification-dependent, selectively learnable, and cleanly stoppable. No new autonomous behavior, capability, provider, purchase flow, account action, avatar behavior, or self-modification system was added.

## References

[1]: https://github.com/bingzwork/Freya/blob/main/app/autonomy/models.py "Freya autonomy models"
[2]: https://github.com/bingzwork/Freya/blob/main/app/autonomy/self_initiated.py "Freya self-initiated work manager"
[3]: https://github.com/bingzwork/Freya/blob/main/app/autonomy/maintenance.py "Freya maintenance manager"
[4]: https://github.com/bingzwork/Freya/blob/main/app/orchestrator/workflow_orchestrator.py "Freya workflow orchestrator"
