# Freya Project Status

## Scope and current position

Freya’s canonical runtime now follows the component ownership and flow boundaries in [`TARGET_ARCHITECTURE.md`](TARGET_ARCHITECTURE.md). This implementation is intentionally **minimal**: it preserves existing components, introduces only small adapters where a declared target edge was absent, and uses late-bound dependencies rather than replacement subsystems.

> **Architecture status:** The target Mermaid diagram is preserved literally at the beginning of [`CURRENT_ARCHITECTURE.md`](CURRENT_ARCHITECTURE.md). The production path now has explicit, testable contracts for question ingress, capability registration and dispatch, target initialization order, planner preflight, execution safety, terminal failure reporting, and learning handoff.

## Delivered in the focused architecture alignment

| Area | Completed implementation | Result |
|---|---|---|
| Architecture documentation | Replaced `CURRENT_ARCHITECTURE.md` with the complete, unchanged `TARGET_ARCHITECTURE.md` diagram and appended implementation notes below it. | All target nodes, subgraphs, initialization labels, and cross-group edges remain explicit. |
| Initialization order | Reordered `SystemInitializer` to construct the target components in this sequence: Infrastructure, LLMStack, MemoryCoordinator, IntelligenceEngine, CapabilityRegistry, UnifiedRouter, ExecutionEngine, WorkflowOrchestrator, ConversationControl, AgentFacadeImpl, AutonomyManager, LearningPipeline, Diagnostics, and Safe Self-Improvement. | Components dependent on learning are late-bound after step 12 rather than being constructed early. |
| Late-bound learning | Added minimal setter-based late binding to `AnswerVerifier`, `AnswerSafeFailure`, `ExecutionVerifier`, `ExecutionEngine`, and the existing `AutonomyManager` integration. | The verifier and autonomy paths retain learning behavior without violating target construction order. |
| Question ingress | Routed normal `AgentFacadeImpl.chat()` requests through `ConversationControl` before `UnifiedRouter`. | ConversationControl now supplies bounded coordinator-owned conversation context and active-goal state, invokes routing, emits chat activity, and persists both conversation turns through `MemoryCoordinator`. |
| Knowledge-first path | Retained `UnifiedRouter → KnowledgeFirstResolver → UnifiedRetrieval → IntelligenceEngine` as the authoritative question route. | Local knowledge remains first; a local capability is selected before local-model fallback; fallback evidence is passed to `AnswerVerifier`. |
| Capability registration | Added `CapabilityRegistrationBridge`, an adapter rather than a new registry. | `CapabilityRegistry → CapabilityRouter → Capability Handlers → ToolManager` is now one registration and execution path in the initialized runtime. |
| Capability execution | Added deterministic named execution in `CapabilityRouter`. | An already approved action cannot be rematched to a different capability by query keywords. |
| Planner preflight | Added a small `UnifiedRouter.get_planning_context()` contract. | `UnifiedPlanner` obtains router-owned knowledge and available-capability context before using the existing planner. |
| Execution dispatch | Registered a non-discoverable `tool_dispatch` capability with the canonical registry. | After `SafetyGate` approval, executor tool calls use `UnifiedRouter → CapabilityRouter → registered handler → ToolManager`; results return to the existing executor and verifier. |
| Terminal execution failure | Added the target-named `ExecutionSafeFailure` adapter inside the existing execution module. | Terminal failures request gated compensation, report partial failure through ConversationControl, and emit a bounded diagnostics failure pattern. |
| Learning promotion | Preserved the existing staged learning pipeline and `MemoryCoordinator` as the only durable promotion boundary. | Answer, execution, watchdog, and event-originated learning continue to use typed candidates rather than direct memory writes. |
| Dependency metadata | Added `aiohttp` to `pyproject.toml`, matching the monitoring subsystem’s existing import and `requirements.txt`. | A standard project installation declares the async HTTP dependency used at runtime. |
| Contract coverage | Added `tests/test_target_architecture_contracts.py`. | Tests cover literal architecture preservation, registry/router/handler/tool dispatch, ConversationControl question ingress, planner router context, and execution safe-failure edges. |

## Validation completed

| Validation command or contract set | Result |
|---|---|
| `python3 -m compileall -q app main.py` | Passed. |
| `git diff --check` | Passed before the final status replacement; it must be rerun before commit. |
| Focused architecture and compatibility suite | Passed: `tests/test_target_architecture_contracts.py`, `test_target_architecture_behavior.py`, `test_workflow_capability_safety.py`, `test_shared_event_improvement_flow.py`, `test_task5_execution_learning.py`, `test_capability_routing.py`, `test_execution_safety_state_machine.py`, and `test_learning_repair_policy.py`. |
| Focused test count | **90 passed** across the canonical routing, capability, execution, learning, safety, shared-event, and architecture contracts. |
| Legacy conversation suite | Not yet green. `tests/test_agent_conversation.py` reports that legacy `FreyaAgent` construction lacks `experience_memory`. This legacy path is outside the canonical `SystemInitializer → AgentFacadeImpl` runtime, but it remains an MVP blocker for a fully green repository. |

## Dependency-first plan to reach 100% MVP

The items below are the remaining work identified from the target architecture, source review, and validation. The order is mandatory: later tasks rely on the contracts and testability established by earlier tasks.

| Priority | Dependency-first work item | Necessary implementation or fix | Definition of done |
|---|---|---|---|
| **P0.1** | Repair or retire the legacy `FreyaAgent` conversation entry point | Initialize or correctly inject `experience_memory` for the legacy agent path, or explicitly migrate its public callers to `SystemInitializer → AgentFacadeImpl` and remove the unsupported duplicate path. | `tests/test_agent_conversation.py` and `tests/test_agent_conversation_simple.py` pass without creating a private memory graph. |
| **P0.2** | Run the canonical runtime in a clean process | Add one clean-process integration test that starts the default runtime with the intended optional components, sends a known-memory question, a capability request, an unsupported question, and a safe execution request, then performs shutdown. | The test proves construction order, shared-service identity, no leaked workers, and correct safe fallback behavior without downloading a model. |
| **P0.3** | Complete claim-level fallback verification | Replace the remaining lexical-overlap-only grounding heuristic in `AnswerVerifier` with claim-to-evidence checks that reject unsupported claims and record explicit rejection evidence. | A supported multi-claim answer passes, an answer containing one unsupported claim fails, and `AnswerSafeFailure` submits a knowledge-gap observation. |
| **P0.4** | Harden provider failure semantics | Make `PriorityLLMProvider` return bounded, structured timeout, malformed-output, and unavailable-provider outcomes for the canonical fallback path. | Provider failure never returns an unverified draft, never blocks shutdown indefinitely, and leaves memory and learning state valid. |
| **P0.5** | Make the focused validation command reproducible | Add a documented `PYTHONPATH`-safe test command or package installation test path, then run the canonical suite from a clean environment. | A contributor can install the declared project dependencies and execute the focused canonical suite without manual import fixes. |
| **P1.1** | Complete Safe Self-Improvement workflow handoff | Ensure an approved safe-self-improvement proposal becomes an explicitly safety-gated `WorkflowOrchestrator` request, with verification and rollback outcome emitted through shared infrastructure. | No improvement applies outside the workflow/safety path; rejected, applied, verified, and rolled-back outcomes are observable. |
| **P1.2** | Bound and deduplicate autonomy observations | Enforce bounded de-duplication for repeated Watchdog, EventBus, and observability observations before they enter LearningPipeline. | Replayed health or memory events cannot create unbounded learning candidates, autonomous work, or background jobs. |
| **P1.3** | Propagate correlation metadata | Carry one request/workflow identifier through conversation events, router decisions, capability dispatch, tools, execution verification, learning, diagnostics, and observability. | One identifier reconstructs an answer, task result, or safe failure end-to-end. |
| **P1.4** | Verify capability metadata at startup | Add a startup audit for registered actions, required injected collaborators, unsafe discoverability, and ToolManager availability. | Every active capability is callable, has its required collaborators, and either exposes a safe query contract or is deliberately non-discoverable. |
| **P2.1** | Validate future extension ports | Add concise contract tests for capability registration, EventBus observers, BackgroundJobService scheduling, and MemoryCoordinator-only durable writes. | A representative extension uses only the four target extension ports and cannot bypass the registry, shared infrastructure, or memory boundary. |
| **P2.2** | Establish operational readiness checks | Extend readiness to include target-path dependency health, bounded shutdown timing, and recovery from unavailable optional local-model services. | Readiness distinguishes healthy, degraded, and unavailable-but-safe local-model states without breaking local memory and capability behavior. |
| **P2.3** | Trim or isolate obsolete parallel implementations | Mark legacy, experimental, and duplicate route/orchestrator modules as compatibility-only or remove them after migration tests prove no public caller needs them. | Documentation and default imports identify exactly one canonical runtime path. |

## Explicit MVP boundary

Freya is **100% MVP-ready** when its canonical runtime can be started in a clean process and reliably execute the following behavior: it answers grounded questions from local memory; dispatches an available local capability through the registry/router/handler/tool-manager chain; uses the local LLM only when local knowledge and capability are insufficient; verifies or safely discloses fallback answers; blocks unsafe actions before side effects; verifies execution results; safely compensates, reports, and diagnoses terminal failures; and promotes only validated learning through `MemoryCoordinator`.

The focused architecture alignment completed the required structural work. The remaining P0 items are now primarily **runtime hardening, claim verification, clean-environment reproducibility, and legacy-path consolidation**, not redesign.
