 # Freya Current Architecture

 ## 1. High-Level Architecture

 ```mermaid
 graph TB
     subgraph "User Interface"
         CLI[CLI Entry Point\nmain.py]
     end

     subgraph "Orchestrator Layer"
         WO[WorkflowOrchestrator\napp/orchestrator/workflow_orchestrator.py]
         CR[CapabilityRegistry\napp/orchestrator/capability_registry.py]
         WM[WorkflowManager\napp/orchestrator/workflow_manager.py]
     end

     subgraph "Agent Layer"
         CA[CoreAgent\napp/agent/core_agent.py]
         AM[AgentManager\napp/agent/agent_manager.py]
     end

     subgraph "Capability System"
         CB[CapabilityBase\napp/capabilities/base.py]
         CC[Concrete Capabilities\napp/capabilities/*/]
     end

     subgraph "Memory & Context"
         MM[MemoryManager\napp/memory/memory_manager.py]
         CM[ContextManager\napp/context/context_manager.py]
     end

     subgraph "External Integrations"
         LL[LLM Clients\napp/llm/*]
         TP[Tool Providers\napp/tools/*]
     end

     %% Connections
     CLI --> WO
     WO --> CR
     WO --> WM
     WO --> CA
     CA --> AM
     CA --> CB
     CB --> CC
     WO --> MM
     WO --> CM
     CA --> LL
     CA --> TP
     CC --> LL
     CC --> TP

     classDef layer fill:#f5f5f5,stroke:#333,stroke-width:2px;
     class CLI layer;
     class WO,CR,WM layer;
     class CA,AM layer;
     class CB,CC layer;
     class MM,CM layer;
     class LL,TP layer;
 ```

 ## 2. Startup / Initialization Flow

 ```mermaid
 graph LR
     M[main.py\nEntry Point] --> FA[FreyaAgent\nConstructor]
     FA --> SR[ServiceRegistry\nRegistration]
     SR --> SM[ServiceManager\nInitialization]
     SM -->|Async Init| LL[LLM Service]
     SM -->|Async Init| MM[Memory Service]
     SM -->|Async Init| CM[Context Service]
     SM -->|Async Init| TM[Tool Service]
     SM -->|Async Init| AM[Agent Manager]
     AM --> CR[CapabilityRegistry\nDiscovery]
     CR --> CC[Concrete Capabilities\nAuto-registration]
     SM --> RD[Ready State\nEvent: started]
     RD --> CLI[CLI Loop\nAccepting Input]

     classDef init fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px;
     class M,FA,SR,SM,LL,MM,CM,TM,AM,CR,CC,RD,CLI init;
 ```

 ## 3. Chat / Request Flow

 ```mermaid
 sequenceDiagram
     participant U as User
     participant C as CLI\nmain.py
     participant FA as FreyaAgent\nprocess_request()
     participant IR as IntentRouter\napp/routing/intent_router.py
     participant WO as WorkflowOrchestrator\nexecute()
     participant CA as CoreAgent\nrun()
     participant LLM as LLM Client
     participant R as Response

     U->>C: Input message
     C->>FA: process_request(input)
     FA->>IR: route(intent, context)
     IR-->>FA: RouteDecision(workflow/capability)
     FA->>WO: execute(workflow, context)
     WO->>CA: run(capability, context)
     CA->>LLM: generate(prompt, tools)
     LLM-->>CA: Response + ToolCalls
     CA-->>WO: CapabilityResult
     WO-->>FA: ExecutionResult
     FA-->>C: AgentResponse
     C-->>U: Formatted output
 ```

 ## 4. Background / Autonomy Flow

 ```mermaid
 graph TB
     subgraph "Startup"
         ST[ServiceManager.started]
     end

     subgraph "Background Services"
         BS[BackgroundServiceManager\napp/services/background_service_manager.py]
         SC[SchedulerService\napp/services/scheduler_service.py]
         EB[EventBus\napp/events/event_bus.py]
     end

     subgraph "Autonomy Loop"
         AL[AutonomyEngine\napp/autonomy/autonomy_engine.py]
         DG[DiagnosticsCollector\napp/diagnostics/diagnostics_collector.py]
         LN[LearningModule\napp/learning/learning_module.py]
     end

     subgraph "Persistence"
         PM[PersistenceManager\napp/persistence/persistence_manager.py]
         DB[(Database\nSQLite/PostgreSQL)]
         FS[File Store\napp/data/]
     end

     ST --> BS
     BS --> SC
     BS --> EB
     SC -->|Periodic| AL
     EB -->|Events| AL
     AL --> DG
     AL --> LN
     DG --> PM
     LN --> PM
     PM --> DB
     PM --> FS
     AL -.->|Feedback| SC

     classDef bg fill:#fff3e0,stroke:#e65100,stroke-width:2px;
     class BS,SC,EB,AL,DG,LN,PM,DB,FS bg;
 ```

 ## 5. Capability / Tool Flow

 ```mermaid
 sequenceDiagram
     participant RQ as Request\nContext
     participant CR as CapabilityRegistry\napp/orchestrator/capability_registry.py
     participant CP as Capability\napp/capabilities/*/capability.py
     participant TE as ToolExecutor\napp/tools/tool_executor.py
     participant SA as SafetyApproval\napp/safety/approval_manager.py
     participant RS as Result

     RQ->>CR: find_capability(intent)
     CR-->>RQ: CapabilityMatch
     RQ->>CP: execute(params, context)
     CP->>TE: execute_tool(name, args)
     TE->>SA: check_approval(tool, risk_level)
     SA-->>TE: ApprovalDecision
     alt approved
         TE->>TE: Run tool implementation
         TE-->>CP: ToolResult
     else denied
         TE-->>CP: DeniedResult
     end
     CP-->>RQ: CapabilityResult
 ```

 ## 6. Memory / Persistence Flow

 ```mermaid
 graph LR
     subgraph "Input"
         RQ[Request\nContext]
     end

     subgraph "Memory Layer"
         MM[MemoryManager\napp/memory/memory_manager.py]
         WM[WorkingMemory\nShort-term]
         LM[LongTermMemory\nVector Store]
         GM[GoalMemory\nGoals/Tasks]
         KM[KnowledgeMemory\nFacts/Skills]
     end

     subgraph "Storage"
         PM[PersistenceManager\napp/persistence/persistence_manager.py]
         VDB[(Vector DB\nChroma/Pinecone)]
         SQL[(SQL Database\nGoals/Tasks)]
         FS[File System\nKnowledge/Config]
     end

     subgraph "Output"
         RS[Enriched\nResponse]
     end

     RQ --> MM
     MM --> WM
     MM --> LM
     MM --> GM
     MM --> KM
     WM --> PM
     LM --> PM
     GM --> PM
     KM --> PM
     PM --> VDB
     PM --> SQL
     PM --> FS
     MM --> RS

     classDef mem fill:#e3f2fd,stroke:#1565c0,stroke-width:2px;
     class MM,WM,LM,GM,KM,PM,VDB,SQL,FS mem;
 ```

 ## 7. LLM / External Services

 ```mermaid
 graph TB
     subgraph "Freya Core"
         FA[FreyaAgent\napp/agent/core_agent.py]
         PF[ProviderFactory\napp/llm/provider_factory.py]
     end

     subgraph "LLM Providers"
         OL[OllamaProvider\napp/llm/providers/ollama_provider.py]
         OP[OpenAIProvider\napp/llm/providers/openai_provider.py]
         AN[AnthropicProvider\napp/llm/providers/anthropic_provider.py]
         LO[LocalProvider\napp/llm/providers/local_provider.py]
     end

     subgraph "External Services"
         WS[WebSearch\napp/tools/web_search.py]
         FS[FileSystem\napp/tools/filesystem.py]
         CP[CodeExecution\napp/tools/code_executor.py]
         AP[APIConnectors\napp/integrations/*]
     end

     FA --> PF
     PF -->|Select| OL
     PF -->|Select| OP
     PF -->|Select| AN
     PF -->|Select| LO
     OL -->|HTTP| OLH[(Ollama API\nlocalhost:11434)]
     OP -->|HTTP| OAI[(OpenAI API)]
     AN -->|HTTP| ANT[(Anthropic API)]
     LO -->|Local| LLAMA[(llama.cpp\n/ GGUF)]

     FA --> WS
     FA --> FS
     FA --> CP
     FA --> AP

     classDef llm fill:#fce4ec,stroke:#c2185b,stroke-width:2px;
     class FA,PF,OL,OP,AN,LO,OLH,OAI,ANT,LLAMA llm;
     classDef ext fill:#e8eaf6,stroke:#3f51b5,stroke-width:2px;
     class WS,FS,CP,AP ext;
 ```

 # CURRENT STATUS

 ## What Currently Works
 - **CLI ↔ FreyaAgent ↔ Orchestrator**: Basic request routing and response cycle
 - **Capability Registry**: Discovery and auto-registration of capabilities
 - **LLM Provider Factory**: Multi-provider support (Ollama, OpenAI, Anthropic, Local)
 - **MemoryManager**: Working/Long-term/Goal/Knowledge memory with persistence
 - **Tool Execution**: ToolExecutor with safety approval flow
 - **Background Services**: SchedulerService and EventBus running
 - **PersistenceManager**: SQLite + Vector DB + File storage abstraction

 ## What Is Partial
 - **Intent Routing**: Basic keyword matching; no semantic routing yet
 - **Autonomy Engine**: Skeleton exists; loops not fully integrated with scheduler
 - **Learning Module**: Data collection works; model updates not implemented
 - **Diagnostics**: Collection works; alerting/auto-recovery missing
 - **Capability System**: Base class works; dynamic loading inconsistent
 - **Context Manager**: Basic context; no conversation summarization

 ## What Is Broken
 - **Autonomy Loop**: Scheduler → AutonomyEngine not wired; background tasks don't execute
 - **EventBus**: Events published but no subscribers for autonomy/diagnostics
 - **Capability Hot-Reload**: Registry caches on startup; no runtime refresh
 - **LLM Streaming**: Provider interface supports it; CoreAgent doesn't handle streams
 - **Multi-Agent**: AgentManager exists but no multi-agent workflows

 ## What Is Legacy / Duplicated
 - `app/orchestrator/workflow_manager.py` vs `workflow_orchestrator.py` — overlapping responsibility
 - `app/agent/agent_manager.py` vs `core_agent.py` — unclear separation
 - `app/capabilities/base.py` vs `capability_registry.py` — both define capability interface
 - Old `app/services/legacy_*` folders (if present) — unused code paths

 # WHAT NEEDS TO BE FIXED

 | Priority | Problem | Actual Path | Impact | Chat Impact | Background Impact |
 | -------- | ------- | ----------- | ------ | ----------- | ----------------- |
 | P0 | Autonomy loop not wired | `app/services/scheduler_service.py`, `app/autonomy/autonomy_engine.py` | Background tasks never run | None | **Critical** — no autonomous operation |
 | P0 | EventBus has no subscribers | `app/events/event_bus.py` | Events lost; no reactivity | None | **Critical** — diagnostics/learning silent |
 | P0 | Capability hot-reload missing | `app/orchestrator/capability_registry.py` | Restart required for new capabilities | **High** — dev friction | Medium |
 | P1 | LLM streaming not handled | `app/agent/core_agent.py`, `app/llm/providers/*` | No token-by-token output | **High** — poor UX | None |
 | P1 | Intent routing is keyword-only | `app/routing/intent_router.py` | Misroutes complex requests | **High** — wrong capability | Medium |
 | P1 | WorkflowManager vs WorkflowOrchestrator duplication | `app/orchestrator/workflow_manager.py`, `app/orchestrator/workflow_orchestrator.py` | Confusion; double maintenance | Medium | Medium |
 | P2 | No conversation summarization | `app/context/context_manager.py` | Context window exhaustion | Medium | Low |
 | P2 | LearningModule doesn't update models | `app/learning/learning_module.py` | No improvement over time | Low | **High** — autonomy useless |
 | P2 | Diagnostics no alerting/auto-recovery | `app/diagnostics/diagnostics_collector.py` | Issues undetected | Low | **High** |
 | P3 | AgentManager / CoreAgent separation unclear | `app/agent/agent_manager.py`, `app/agent/core_agent.py` | Architectural confusion | Low | Low |
 | P3 | Legacy service folders | `app/services/legacy_*` | Dead code; confusion | None | None |

 ### Chat-Blocking Problems (P0/P1 affecting chat)
 - LLM streaming not handled → poor UX
 - Intent routing keyword-only → wrong capability selection
 - Capability hot-reload missing → dev friction

 ### Background/Autonomy Problems (P0/P1/P2 affecting autonomy)
 - Autonomy loop not wired → **no autonomous operation**
 - EventBus no subscribers → diagnostics/learning silent
 - LearningModule no model updates → autonomy useless
 - Diagnostics no alerting → issues undetected

 ### Technical Debt (P1/P2/P3)
 - WorkflowManager/WorkflowOrchestrator duplication
 - AgentManager/CoreAgent unclear separation
 - Capability interface split across base.py and registry
 - No conversation summarization
 - Legacy service folders

 # NEXT IMPLEMENTATION PRIORITIES

 1. **Wire Autonomy Loop** (P0)
    - Connect SchedulerService → AutonomyEngine in `background_service_manager.py`
    - Register EventBus subscribers for autonomy/diagnostics events

 2. **Fix EventBus Subscriptions** (P0)
    - Add subscribers in `app/autonomy/`, `app/diagnostics/`, `app/learning/`
    - Ensure events flow to autonomy engine

 3. **Implement LLM Streaming** (P1)
    - Update `CoreAgent.run()` to handle async generators
    - Update all provider `generate()` to yield tokens
    - Update CLI to render streaming output

 4. **Upgrade Intent Routing** (P1)
    - Replace keyword matching with embedding-based semantic routing
    - Add fallback to LLM-based classification

 5. **Add Capability Hot-Reload** (P1)
    - Add `refresh()` to `CapabilityRegistry`
    - Watch `app/capabilities/` for changes
    - Expose CLI command for manual reload

 6. **Consolidate Workflow Manager/Orchestrator** (P1)
    - Merge into single `WorkflowOrchestrator`
    - Remove `WorkflowManager` or make it a sub-component

 7. **Implement Learning Module Model Updates** (P2)
    - Add fine-tuning/RLHF pipeline stub
    - Connect to diagnostics feedback loop

 8. **Add Diagnostics Alerting & Auto-Recovery** (P2)
    - Define alert rules in `diagnostics_collector.py`
    - Add notification hooks (log, webhook, CLI)
    - Implement basic auto-recovery (restart service, clear cache)

 9. **Add Conversation Summarization** (P2)
    - Implement in `ContextManager`
    - Trigger on context window threshold

 10. **Clean Up Legacy/Duplicated Code** (P3)
     - Remove `WorkflowManager` or document its role
     - Clarify `AgentManager` vs `CoreAgent`
     - Unify capability interface
     - Remove `legacy_*` folders
