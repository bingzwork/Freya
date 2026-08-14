# Freya MVP Project Status

*Rebased on `470fd7a` and updated on 2026-08-14.*

## Scope and architecture commitment

This redo preserves `TARGET_ARCHITECTURE.md` as the source of truth. The work does not replace the target graph, add a parallel router, add a new memory system, or move ownership between `SystemInitializer`, `UnifiedRouter`, `CapabilityRegistry`, `WorkflowOrchestrator`, `ExecutionEngine`, `AnswerVerifier`, or `LearningPipeline`.

The MVP objective is to make the existing target path behave as specified:

```text
Knowledge request
  -> ConversationControl
  -> UnifiedRouter
  -> KnowledgeFirstResolver
  -> UnifiedRetrieval
  -> Can Freya Answer?
  -> Freya Answer OR CapabilityRouter / Capability Handlers / ToolManager
  -> PriorityLLMProvider fallback
  -> AnswerVerifier / AnswerRepairLoop / AnswerSafeFailure

Action request
  -> WorkflowOrchestrator
  -> SafetyGate
  -> ExecutionEngine
  -> UnifiedPlanner
  -> UnifiedExecutor
  -> ExecutionVerifier
  -> RepairLoop or Task Complete

Observation
  -> LearningPipeline
  -> Observe
  -> Evaluate
  -> Extract Learning
  -> Validate Learning
  -> Worth Remembering?
  -> Classify / Distill
  -> MemoryCoordinator
```

## Implemented in this redo

The existing `KnowledgeFirstResolver` now carries the retrieval evidence it already obtained through the existing fallback route context. `AgentFacadeImpl` passes that context into the existing `AnswerVerifier`; no component or ownership boundary was changed.

On the target fallback path, `AnswerVerifier` now requires meaningful grounding against the local retrieval evidence before accepting a draft. An empty evidence bundle cannot authorize a fallback response. Invalid drafts continue to use the existing `AnswerRepairLoop` and `AnswerSafeFailure` path. The verifier timestamp now uses an explicit UTC timestamp rather than depending on an internal logger formatter.

The fallback prompt now instructs the existing local model to use supplied evidence only and disclose when the evidence is insufficient. The change is a behavior guard inside the target’s existing `PriorityLLMProvider` → `AnswerVerifier` path, not a replacement LLM architecture.

Added regression tests in `tests/test_target_architecture_behavior.py` cover empty-evidence rejection, evidence-supported fallback acceptance, and evidence preservation by the existing resolver.

`CURRENT_ARCHITECTURE.md` was rewritten using the exact component names, edges, initialization order, and learning rule from `TARGET_ARCHITECTURE.md`.

## Priority list

| Priority | Existing target component or edge | Remaining issue | Minimal fix within the target architecture | MVP acceptance criterion |
|---|---|---|---|---|
| **P0** | `ConversationControl` → `UnifiedRouter` → `KnowledgeFirstResolver` | The supported chat path needs deterministic end-to-end acceptance coverage across local answer, capability, fallback, repair, and safe failure | Add fixture-based integration tests using injected existing collaborators; do not add a new facade or router | A clean-process test proves every target question branch and persists the final exchange through the existing memory path |
| **P0** | `UnifiedRetrieval` → `Can Freya Answer?` → `AnswerVerifier` | Lexical overlap is only a basic grounding guard and can miss contradiction or unsupported claims | Improve the existing verifier’s claim/evidence checks, retaining `AnswerVerifier` as the gate | Every returned fallback claim is supported by retrieved evidence, otherwise `AnswerSafeFailure` is used |
| **P0** | `CapabilityRegistry` → `CapabilityRouter` → `Capability Handlers` → `ToolManager` | Registration and query matching need one consistent, tested contract across the existing components | Add an adapter or shared registration contract without introducing another registry or moving ownership | Every MVP capability has a declared callable action, validated inputs, safety metadata, and a normalized result |
| **P0** | `SystemInitializer` and shared infrastructure | Module-level state and legacy test cleanup can make behavior depend on import or test order | Isolate test fixtures and remove only accidental legacy imports from the supported path; retain the target initialization order | Supported-path tests pass in isolation and as a suite without changing target component ownership |
| **P1** | `ExecutionVerifier` → `RepairLoop` → `ExecutionSafeFailure` | Multi-step partial failures need explicit compensation and reporting | Add checkpoint-aware compensation results to the existing execution failure path | A failed workflow reports completed, failed, compensated, and unrecoverable steps without claiming success |
| **P1** | `ExecutionVerifier` → `LearningPipeline` | Execution learning needs complete evidence and verification provenance | Require existing learning candidates to carry source event/task IDs, verification state, and evidence references | Every stored experience or skill is traceable to a verified execution outcome |
| **P1** | `Watchdog` → `LearningPipeline` and `EventBus` | Repeated observation events can create feedback loops when autonomy is enabled | Add origin IDs, bounded propagation depth, and deduplication to the existing events | Replaying one health or memory event does not create unbounded learning submissions |
| **P1** | `Diagnostics` → `Safe Self-Improvement` → `WorkflowOrchestrator` | Optional improvement proposals need one verified safety and rollback path | Make the existing improvement proposal call the target workflow and safety interfaces consistently | No improvement is promoted without an approval record, post-change verification, and rollback outcome |
| **P2** | `LLMStack` → `PriorityLLMProvider` → local model | Provider timeouts and malformed output need deterministic handling | Add bounded timeout, retry, health, and structured-error behavior to the existing provider | Local-model failure produces safe disclosure and does not corrupt conversation or learning state |
| **P2** | `Infrastructure` → `ObservabilityHub` | A full request cannot always be reconstructed across routing, execution, and learning | Propagate the existing correlation metadata through events and component logs | One request ID reconstructs the target path from ingress to result or safe failure |
| **P2** | Future extension ports | New features need to register through the target’s declared extension edges | Document and test capability, event, background, and memory-aware extension contracts | An extension uses only the existing registry, event bus, background service, or stable memory API |

## Current readiness by target section

| Target section | Status | Assessment |
|---|---|---|
| Bootstrap | **Implemented** | `main.py` initializes `SystemInitializer`. |
| Freya interface | **Implemented** | `AgentFacadeImpl` and `ConversationControl` are wired through the existing runtime. |
| Knowledge and memory | **Implemented with hardening needed** | `MemoryCoordinator` and `UnifiedRetrieval` provide the target memory boundary; integration coverage remains necessary. |
| Intelligence | **Implemented** | Existing intelligence modules provide reasoning, answerability, confidence, context, and goal awareness. |
| Knowledge-first routing | **Implemented with P0 test and grounding work** | Resolver searches local knowledge before capability and local-model fallback. |
| Modular capability system | **Implemented with P0 contract work** | Registry, router, handlers, and tool manager exist; registration consistency requires acceptance coverage. |
| Local LLM fallback | **Implemented with verifier guard** | Fallback drafts pass through the existing verifier and repair/safe-failure path. |
| Self-learning pipeline | **Implemented** | Validated learning is classified, distilled, and written through `MemoryCoordinator`. |
| Workflow and execution | **Implemented with P1 hardening** | Safety, planning, execution, verification, repair, and safe failure are present. |
| Autonomy and observation | **Implemented but not default-MVP ready** | Existing autonomy and watchdog paths need event deduplication and shutdown coverage. |
| Diagnostics and safe self-improvement | **Present but not default-MVP ready** | Requires end-to-end proposal, safety, verification, and rollback tests. |
| Shared infrastructure | **Implemented** | Existing `EventBus`, `BackgroundJobService`, and `ObservabilityHub` support the target edges. |
| Future extension ports | **Available** | Extension contracts require focused documentation and tests. |

## Validation performed

The following checks were run against the architecture-preserving changes:

| Check | Result |
|---|---|
| Target-focused regression tests | Passed after dependency setup |
| Existing routing, retrieval, learning, safety, repair, and workflow tests | Passed in the focused run |
| `python3 -m compileall -q main.py app` | Passed |
| `git diff --check` | Passed |

The broad repository suite contains legacy, optional-subsystem, and environment-sensitive tests. Any failures from that suite must be triaged without changing `TARGET_ARCHITECTURE.md`: supported-path regressions should be fixed in the existing target components, while legacy test isolation and optional-service requirements should be documented separately.

## MVP definition of done

Freya is MVP-ready when the target architecture can be exercised in a clean process without external model downloads: a known question is answered from local memory without an LLM call; an available local capability is routed through the existing registry, handlers, and tool manager; an unavailable capability invokes the local model only as a constrained fallback; unsupported output is repaired or safely disclosed; dangerous actions are blocked before side effects; execution failures are verified and bounded; and only validated learning reaches `MemoryCoordinator`.

No redesign is required to reach that definition. The recommended order is **P0 acceptance and grounding**, followed by **capability and execution contract coverage**, then **learning provenance and autonomy hardening**, and finally optional self-improvement and observability improvements.
