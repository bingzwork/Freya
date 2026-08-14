# Current Freya Production Architecture

*Verified against the current codebase on 2026-08-14.*

This diagram documents the runtime assembled by `main.py` → `FreyaApp` → `SystemInitializer`. **Solid lines** are implemented production wiring. **Dashed red lines** mark active defects in otherwise instantiated paths; they are deliberately shown so the document does not present the target architecture as working.

```mermaid
flowchart TB
    CLI["main.py / FreyaApp"] --> INIT["SystemInitializer"]

    subgraph BOOT["Bootstrap and shared services"]
        INIT --> INFRA["EventBus + BackgroundJobService + ObservabilityHub"]
        INIT --> LLM["LLMStack: PriorityLLMProvider + ChatActivity"]
        LLM --> OLLAMA["Configured Ollama provider"]
        INIT --> MEM["MemoryCoordinator"]
        MEM --> RETRIEVE["UnifiedRetrieval"]
        MEM --> DURABLE["Conversation, goals, long-term, episodic, semantic, project, experience, lessons"]
        MEM --> XREF["CrossMemoryReferences"]
    end

    subgraph CHAT["Supported conversation route"]
        INIT --> FACADE["AgentFacadeImpl"]
        FACADE --> ROUTER["UnifiedRouter"]
        ROUTER --> CONTROL["ConversationControlHandler"]
        ROUTER --> RESOLVE["KnowledgeFirstResolver"]
        RESOLVE --> RETRIEVE
        RESOLVE --> INTEL["Intelligence: answerability + goal context"]
        INTEL --> LOCAL["Local-memory answer"]
        LOCAL -. "answer payload is dropped before facade" .-> FACADE
        RESOLVE --> CAP["Router-owned CapabilityRouter"]
        CAP -. "context=None raises; router falls back" .-> LEGACY["Legacy intent/capability routing"]
        RESOLVE --> FALLBACK["Prepared LLM fallback"]
        FALLBACK -. "misclassified as engineering" .-> EXEC
        FACADE --> VERIFY_ANSWER["AnswerVerifier / repair"]
        VERIFY_ANSWER --> REPLY["User-visible answer"]
        FACADE -. "no record_conversation() write" .-> DURABLE
    end

    subgraph EXECUTION["Task execution and workflow"]
        INIT --> EXEC["ExecutionEngine"]
        INIT --> SAFETY["SafetyGate"]
        INIT --> ORCH["WorkflowOrchestrator (optional)"]
        ORCH --> EXEC
        EXEC --> PLAN["Plan → execute tools"]
        PLAN --> SAFETY
        SAFETY --> VERIFY_EXEC["VerificationRunner / ExecutionVerifier"]
        VERIFY_EXEC -->|"failure"| REPAIR["RepairLoop"]
        REPAIR --> PLAN
        VERIFY_EXEC -->|"terminal outcome"| LEARN["LearningPipeline"]
        EXEC --> REPLY
    end

    subgraph AUTONOMY["Autonomy and background work"]
        INIT --> AUTO["AutonomyManager (optional)"]
        AUTO -->|"starts queue drain"| LEARN
        AUTO --> WD["Watchdog"]
        AUTO --> ORCH
        INFRA --> AUTO
        INFRA --> WD
        WD -->|"observation candidate"| LEARN
        XREF -. "derived memory.* events are still observed" .-> WD
    end

    subgraph IMPROVEMENT["Diagnostics and self-improvement"]
        INIT --> DIAG["DiagnosticEngine (optional)"]
        INIT --> SSI["SafeSelfImprovementEngine (optional)"]
        LEARN -->|"learning.improvement_candidate"| INFRA
        DIAG -->|"diagnostics.completed"| INFRA
        INFRA --> SSI
        SSI --> RISK["RiskBasedExecutor"]
        RISK --> PROMOTE["PatchPromotionManager"]
        PROMOTE -. "calls absent evaluate()" .-> GATES["SafetyPromotionGates"]
    end

    classDef issue fill:#ffebee,stroke:#c62828,color:#7f0000,stroke-width:2px;
    classDef optional fill:#e3f2fd,stroke:#1565c0,color:#0d47a1,stroke-dasharray: 5 5;
    class LOCAL,FALLBACK,PROMOTE,GATES issue;
    class ORCH,AUTO,DIAG,SSI optional;
```

## Runtime composition and actual return paths

| Area | Current production relationship |
|---|---|
| **Bootstrap** | `SystemInitializer` binds the shared event bus, job service, observability hub, LLM stack, memory coordinator, learning pipeline, answer verifier, tools, intelligence, router, execution engine, conversation control, facade, and enabled optional subsystems. The workflow orchestrator is started before the autonomy manager. |
| **Local-first resolution** | `KnowledgeFirstResolver` retrieves memory and asks `Intelligence` for answerability. It can construct an internal `ResolutionResult.answer`, a capability result, or an LLM fallback prompt. The router currently discards the answer/prompt payload when converting to `RouteResult`; this is an active production defect, not an omitted diagram edge. |
| **Conversation output** | The facade sends direct answers through the priority provider and answer verifier, handles controls through `ConversationControlHandler`, and sends engineering routes to `ExecutionEngine`. The facade currently does not write supported user/assistant exchanges through `MemoryCoordinator.record_conversation()`. |
| **Execution** | `ExecutionEngine` plans, safety-checks, executes, verifies, attempts repair on verification failure, records a terminal plan state, and hands terminal outcomes to `LearningPipeline` through `ExecutionVerifier`. `WorkflowOrchestrator` uses the same execution engine and safety gate. |
| **Memory and learning** | `MemoryCoordinator` owns durable stores, unified retrieval, conversation memory, and cross-memory references. `LearningPipeline` persists accepted items through the coordinator. When autonomy is enabled, the autonomy manager starts the pipeline's background queue drain. |
| **Autonomy** | `AutonomyManager` starts watchdog, self-initiated-work, and maintenance components and uses the shared job service and orchestrator. The watchdog observes `memory.*`; derived cross-reference writes are currently not all excluded, leaving a real feedback risk into learning. |
| **Self-improvement** | `LearningPipeline` and diagnostics publish shared events. `SafeSelfImprovementEngine` receives them and auto-executes learning-origin candidates with its own risk executor and promotion manager; it does **not** route those candidates through `WorkflowOrchestrator`. The promotion manager's safety-gate call is currently incompatible with the instantiated gate API. |

## Deliberately omitted from the active diagram

The legacy `FreyaAgent`, `long_term_autonomy`, and experimental/legacy retrieval subsystems exist in the repository but are not created by `SystemInitializer` or reached by the supported `FreyaApp` path. They are therefore not represented as current production architecture.

## Verified initialization order

1. Shared infrastructure: event bus, job service, observability, optional hot reload, and optional file watcher.
2. `LLMStack`, followed by memory coordinator, learning pipeline, and answer verifier.
3. Tool manager, intelligence, separate orchestrator capability registry, and safety gate.
4. Router, execution engine, conversation control, and facade.
5. Optional workflow orchestrator, optional autonomy manager, diagnostics, and safe self-improvement engine.
6. Readiness checks are registered and immediately evaluated before the initialized system is returned.

> **Current limitations shown above are implementation defects, not future design proposals.** Their required remediation and verification are defined in [`PROJECT_STATUS.md`](PROJECT_STATUS.md).
