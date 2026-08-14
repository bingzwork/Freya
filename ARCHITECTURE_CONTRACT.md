# Freya Core Architecture v1

**Status: FROZEN**

This document freezes Freya’s currently implemented core architecture as **Freya Core Architecture v1**. It is a compatibility contract for future work. It records the stable ownership boundaries and extension points that are present in the codebase today; it does not claim that every implementation detail is complete or correct.

The contract is grounded in the current runtime composition in [`main.py`](./main.py), [`app/core/initializer.py`](./app/core/initializer.py), [`app/core/protocols.py`](./app/core/protocols.py), and the current architecture map in [`CURRENT_ARCHITECTURE.md`](./CURRENT_ARCHITECTURE.md). The implementation remains the source of truth if this document and code ever disagree.

## 1. Freeze rules

Freya’s current core architectural structure and stable component boundaries are frozen at version 1. Future capabilities must plug into the existing extension points described below. They must not create parallel routers, orchestrators, memory systems, learning systems, event systems, or background-job systems.

This freeze applies to **architecture and ownership**, not to implementation quality. Internal code, tests, configuration, performance work, and bug fixes may continue to change as long as they do not unnecessarily redesign the frozen architecture. Bugs, broken implementations, missing edge cases, and unsafe behavior are **not frozen** and may still be fixed.

New capabilities may be added freely through the supported architecture. If a future task genuinely requires a change to the core architecture, the coding agent must report the reason, affected boundary, and compatibility impact instead of changing the architecture automatically.

The architecture may be explicitly **unfrozen** or versioned to **Freya Core Architecture v2** later by direct user instruction.

## 2. Frozen core structure

### 2.1 Bootstrap and composition root

[`main.py`](./main.py) owns the thin `FreyaApp` process wrapper. It delegates construction to [`SystemInitializer`](./app/core/initializer.py). `SystemInitializer` is the single composition root: it constructs the runtime graph, binds shared infrastructure, wires late-bound dependencies, registers readiness checks, and returns the [`InitializedSystem`](./app/core/protocols.py) aggregate.

The initializer’s current construction boundary is:

1. Shared infrastructure: `EventBus`, `BackgroundJobService`, `ObservabilityHub`, and optional config/file watchers.
2. `LLMStack`, including the priority LLM and chat-activity provider.
3. `MemoryCoordinator` and its unified retrieval surface.
4. `ToolManager` and the intelligence components.
5. The canonical `CapabilityRegistry` and its startup audit.
6. `SafetyGate` and the `UnifiedRouter`.
7. `ExecutionEngine` and answer verification.
8. Optional `WorkflowOrchestrator`.
9. `ConversationControlHandler`.
10. `AgentFacadeImpl`.
11. Optional `AutonomyManager`.
12. `LearningPipeline`, including late-bound learning collaborators.
13. Optional diagnostics and safe self-improvement.

The order may be repaired or extended internally when required by a bug fix, but another composition root must not be introduced for the same runtime.

### 2.2 Public agent boundary

[`AgentFacadeImpl`](./app/agent/facade_impl.py) is the thin public agent facade. It exposes the user-facing `chat`, direct `execute_task`, status, and shutdown operations while delegating to composed services. It does not instantiate subsystems.

[`ConversationControlHandler`](./app/conversational_control.py) owns conversational control commands, question routing coordination, exchange recording, and pause/cancel/stop-style control behavior. Correlation metadata is carried through the existing correlation scope rather than through an additional request-routing system.

### 2.3 Memory and retrieval boundary

[`MemoryCoordinator`](./app/memory/coordinator.py) is Freya’s unified memory facade and **single durable write path**. It owns the implemented working, task, long-term, episodic, semantic, project, experience, engineering-lesson, goal, and conversation stores, as well as cross-memory references and memory maintenance helpers.

[`UnifiedRetrieval`](./app/memory/unified_retrieval.py) is the shared read aggregation surface created by the coordinator. Durable conversation, task, fact, learned-item, experience, lesson, and goal writes must continue through the coordinator’s existing APIs or an extension of those APIs. A new feature must not create a competing durable memory owner or bypass coordinator invariants.

### 2.4 Routing and intelligence boundary

[`UnifiedRouter`](./app/routing/unified_router.py) is the **single production routing boundary**. It handles conversational control first, then delegates authoritative knowledge-first resolution to [`KnowledgeFirstResolver`](./app/routing/knowledge_first_resolver.py). The implemented route outcomes are a grounded answer, a registered capability result, or a verified local-LLM fallback path.

`Intelligence` supplies reasoning, confidence/answerability, and context/goal awareness to the knowledge-first resolver. `UnifiedRetrieval` is consulted before fallback. Resolver failures must remain visible to the canonical caller rather than silently selecting a competing legacy route.

### 2.5 Capabilities and tool execution

[`CapabilityRegistry`](./app/orchestrator/capability_registry.py) is the single source of capability registrations and startup audits. Its metadata contract controls actions, discoverability, safe query exposure, dependencies, collaborators, and capability health.

Query-facing capability registrations are projected through the existing [`CapabilityRegistrationBridge`](./app/capabilities/registration_bridge.py) into the query-time capability router. The runtime ownership chain is:

> `CapabilityRegistry → CapabilityRouter → capability handlers → ToolManager`

Approved internal tool dispatch remains non-discoverable where required and delegates to [`ToolManager`](./app/core/tool_manager.py). Future capabilities must register through this surface rather than adding another registry, router, or ad hoc natural-language dispatch path.

### 2.6 LLM boundary

[`LLMStack`](./app/core/llm_stack.py) is the current LLM composition boundary. It owns the priority provider and chat-activity coordination used by routing, execution, autonomy, and background work. The canonical fallback path is local-model-first through `PriorityLLMProvider`, with answer verification and bounded answer repair handled by the existing verification boundary.

Provider health and readiness belong to the existing observability/readiness surface. A new feature must not create a second provider priority system or a separate chat-activity lifecycle.

### 2.7 Workflow and execution boundary

[`ExecutionEngine`](./app/execution/engine.py) owns the canonical engineering execution path: planning, execution, verification, bounded repair, safe failure, and execution-memory/learning handoff. The stable planning/execution contract is represented by the existing `ExecutionEngineProtocol` in [`app/core/protocols.py`].

[`WorkflowOrchestrator`](./app/orchestrator/workflow_orchestrator.py) is the coordinating workflow boundary. It composes the shared capability registry, router, execution engine, safety gate, task executor, chat activity, event bus, and background-job service. It may coordinate workflows and approved self-improvement actions, but it must not become a second router, memory owner, capability registry, or execution engine.

[`SafetyGate`](./app/orchestrator/safety_gate.py) remains the safety boundary for approved actions. Tool results return to the existing execution path for verification rather than bypassing execution ownership.

### 2.8 Learning boundary

[`LearningPipeline`](./app/learning/pipeline.py) is the canonical learning path. Its implemented flow is observe, evaluate, extract, validate, decide whether the item is worth remembering, classify the learning, distill it, and persist only validated learning through `MemoryCoordinator`.

Learning may observe events and execution outcomes through the shared infrastructure, but a new feature must not add a parallel learning pipeline or a second durable learning store. Validated learning must return through the coordinator-owned memory path.

### 2.9 Autonomy, diagnostics, and safe improvement

[`AutonomyManager`](./app/autonomy/manager.py) owns the current autonomy/watchdog/self-initiated/maintenance coordination boundary and uses the existing goal storage, workflow orchestration, learning, observability, and background-job services.

[`DiagnosticEngine`](./app/diagnostics/diagnostic_engine.py) owns diagnostic analysis. [`SafeSelfImprovement`](./app/safe_self_improvement/self_improvement.py) owns the approved-change boundary and routes approved changes through the existing workflow orchestration path. These components may be improved internally, but new autonomous or diagnostic graphs must not be created beside them.

### 2.10 Shared infrastructure boundary

[`EventBus`](./app/core/events.py) is the shared event publication/subscription backbone and correlation-metadata carrier. [`BackgroundJobService`](./app/core/background_jobs.py) is the unified background scheduling and execution service, including lifecycle, retry, chat-aware yielding, event emission, and bounded shutdown behavior. [`ObservabilityHub`](./app/core/observability.py) owns component registration, health checks, readiness, metrics, and alert-oriented runtime visibility.

Future event observers must subscribe to the existing `EventBus`. Future scheduled, delayed, recurring, or autonomous work must use the existing `BackgroundJobService` and the appropriate autonomy/workflow owner. A new event bus, scheduler, worker pool, or background-job registry must not be introduced for a feature that fits these contracts.

### 2.11 Legacy compatibility boundary

The legacy `FreyaAgent`, legacy local-memory bundle, and `ConversationState` remain compatibility surfaces where identified in [`CURRENT_ARCHITECTURE.md`](./CURRENT_ARCHITECTURE.md). They are not permission to create a second canonical runtime graph. New production behavior belongs on the current initializer/facade/router/memory/execution paths unless a future architecture version explicitly changes that rule.

## 3. Supported extension ports

New capabilities should use the following existing ports:

| Need | Existing extension point | Ownership rule |
| --- | --- | --- |
| Add a callable or query-facing capability | `CapabilityMetadata`, `Capability`, `CapabilityRegistry`, `CapabilityRegistrationBridge` | Register once in the canonical registry; expose natural-language discovery only through the existing safe-query contract. |
| Add a tool-backed action | Capability handler plus `ToolManager` | Approved actions stay behind `SafetyGate` and return through the existing execution/verification flow. |
| Add durable memory | `MemoryCoordinator` write API and `UnifiedRetrieval` | The coordinator remains the single durable write owner and retrieval aggregation surface. |
| Observe system activity | Shared `EventBus` | Publish and subscribe through the existing bus with correlation metadata. |
| Add scheduled or background work | `BackgroundJobService`, `WorkflowOrchestrator`, or `AutonomyManager` | Use the existing lifecycle, retry, chat-aware yielding, and shutdown contract. |
| Add a user-facing chat behavior | `AgentFacadeImpl`, `ConversationControlHandler`, `UnifiedRouter`, and registered capability paths | Do not add another request router or facade. |
| Add learning from an outcome | `LearningPipeline` and `MemoryCoordinator` | Reuse the existing observe-to-validated-learning pipeline and canonical persistence path. |
| Add diagnostics or safe repair | `DiagnosticEngine`, `SafeSelfImprovement`, `WorkflowOrchestrator` | Approved changes remain inside the existing safety and workflow boundaries. |

## 4. What this freeze does not mean

This contract does not freeze bugs, tests, performance characteristics, provider availability, prompt wording, UI implementation, data contents, internal algorithms, or configuration values. It does not prevent additive capabilities, new handlers, new event observers, new job definitions, new memory records, or new diagnostics when they use the supported ports.

It also does not silently authorize a large refactor. If a task cannot be completed through the extension ports and genuinely requires changing a frozen ownership boundary, the agent must stop before that architectural change and report why a new architecture version is needed.

## 5. Versioning

This document defines **Freya Core Architecture v1**. The v1 contract remains active until the user explicitly instructs Freya to unfreeze it or to adopt a versioned successor such as **Freya Core Architecture v2**. A future version must state the changed boundaries, migration impact, compatibility strategy, and reason for the change.
