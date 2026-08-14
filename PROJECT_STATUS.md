# Freya Project Status

## Scope and current position

Freya’s canonical runtime follows the component ownership and flow boundaries in [`TARGET_ARCHITECTURE.md`](TARGET_ARCHITECTURE.md). The implementation remains intentionally **minimal**: it preserves existing components, introduces only narrow adapters where a declared target edge was absent, and relies on late-bound dependencies rather than replacement subsystems.

> **Current P0 status:** All P0 work identified in the preceding status report is complete. The canonical graph now has clean-process lifecycle coverage, claim-level fallback grounding, bounded provider outcomes, and a reproducible package-installed validation command.

## Completed focused implementation work

| Area | Completed implementation | Result |
|---|---|---|
| Clean-process canonical runtime | Added `tests/test_clean_process_runtime.py` and its standalone probe. The probe starts the intended optional components, verifies shared-service identity, exercises local-memory, capability, unsupported-question, and read-only verified execution paths, and checks owned worker shutdown. | The canonical runtime is covered in a fresh Python process without requiring a local-model download. |
| Claim-level fallback verification | Replaced answer-wide lexical-overlap acceptance with per-claim checks against individual local evidence records. Rejected claims and their supporting/rejection evidence are retained in learning context. | A multi-claim answer now requires local support for every material claim; a single unsupported statement rejects the draft. |
| Safe fallback failure handoff | Added explicit claim-verification context to repair and safe-failure handling, and prevented nested repair attempts from recursively starting additional repair loops. | Failed repairs remain bounded and emit a knowledge-gap observation through the existing learning boundary. |
| Provider failure semantics | Added `LLMOutcome` and `LLMOutcomeKind` to `PriorityLLMProvider`, including bounded timeout, unavailable-provider, malformed-output, and shutdown outcomes. The canonical facade consumes these outcomes before answer verification. | The fallback path does not return a raw provider failure or unverified draft, and provider failure enters the normal safe-disclosure and learning flow. |
| Reproducible canonical validation | Added [`scripts/run_canonical_tests.sh`](scripts/run_canonical_tests.sh), which installs the declared development extra and runs the focused canonical suite without setting `PYTHONPATH`. | A contributor has one package-installation-based command for the canonical validation suite. |
| Safe Self-Improvement workflow handoff | Added a minimal `WorkflowOrchestrator.execute_safe_self_improvement()` adapter. Approved candidates now pass through the orchestrator and its `SafetyGate` before the existing risk executor runs; workflow, applied, verification, rejection, and rollback outcomes are emitted on the shared `EventBus`. | No self-improvement mutation is applied when the workflow boundary is absent, while existing rollback and promotion logic remains intact. |
| Runtime lifecycle ownership | Bound Safe Self-Improvement to the canonical workflow orchestrator during initialization and stopped it before infrastructure teardown. | The initialized runtime graph retains explicit ownership and shutdown order for the added handoff. |

## Reproducible validation

From the repository root, run the following command. It installs Freya with the declared `dev` extra and executes the clean-process, architecture, routing, execution, learning, workflow, and provider-outcome contracts without manual import-path configuration.

```bash
./scripts/run_canonical_tests.sh
```

The suite intentionally replaces only true external boundaries in its clean-process probe: the optional local model, planner generation for the one read-only execution fixture, and the operating-system verification command. The production `SystemInitializer` object graph, safety gate, capability routing, verification, learning, and shutdown paths remain live.

| Latest validation | Result |
|---|---|
| `python3 -m compileall -q app main.py tests/clean_runtime_probe.py` | Passed. |
| `git diff --check` | Passed. |
| `./scripts/run_canonical_tests.sh` | **99 passed**. |

## Remaining dependency-first hardening plan

The resolved priorities have been removed from this list. The order below remains dependency-first for the next iteration.

| Priority | Dependency-first work item | Necessary implementation or fix | Definition of done |
|---|---|---|---|
| **P1.2** | Bound and deduplicate autonomy observations | Enforce bounded de-duplication for repeated Watchdog, EventBus, and observability observations before they enter LearningPipeline. | Replayed health or memory events cannot create unbounded learning candidates, autonomous work, or background jobs. |
| **P1.3** | Propagate correlation metadata | Carry one request/workflow identifier through conversation events, router decisions, capability dispatch, tools, execution verification, learning, diagnostics, and observability. | One identifier reconstructs an answer, task result, or safe failure end-to-end. |
| **P1.4** | Verify capability metadata at startup | Add a startup audit for registered actions, required injected collaborators, unsafe discoverability, and ToolManager availability. | Every active capability is callable, has its required collaborators, and either exposes a safe query contract or is deliberately non-discoverable. |
| **P2.1** | Validate future extension ports | Add concise contract tests for capability registration, EventBus observers, BackgroundJobService scheduling, and MemoryCoordinator-only durable writes. | A representative extension uses only the four target extension ports and cannot bypass the registry, shared infrastructure, or memory boundary. |
| **P2.2** | Establish operational readiness checks | Extend readiness to include target-path dependency health, bounded shutdown timing, and recovery from unavailable optional local-model services. | Readiness distinguishes healthy, degraded, and unavailable-but-safe local-model states without breaking local memory and capability behavior. |
| **P2.3** | Trim or isolate obsolete parallel implementations | Mark legacy, experimental, and duplicate route/orchestrator modules as compatibility-only or remove them after migration tests prove no public caller needs them. | Documentation and default imports identify exactly one canonical runtime path. |

## Explicit MVP boundary

Freya is **MVP-ready** when its canonical runtime can be started in a clean process and reliably execute grounded local-memory questions, registered local capabilities, verified fallback disclosure, safety-gated execution, execution-result verification, terminal-failure reporting, and validated learning promotion through `MemoryCoordinator`.

The clean-process lifecycle, claim verification, provider resilience, reproducible validation, and Safe Self-Improvement workflow handoff are now complete. The remaining entries are P1/P2 hardening tasks rather than required MVP redesign work.
