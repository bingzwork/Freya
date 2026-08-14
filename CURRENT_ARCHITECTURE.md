flowchart TD
%% Freya current canonical runtime — generated from the codebase on 2026-08-14.
%% The graph documents current ownership and runtime data flow only.

subgraph BOOT["1. BOOTSTRAP"]
  direction TB
  A["main.py / FreyaApp"] --> B["SystemInitializer"]
  B --> CA["Capability startup audit"]
  B --> RDY["Readiness registration"]
end

subgraph INTERFACE["2. FREYA INTERFACE"]
  direction TB
  K["AgentFacadeImpl"] --> J["ConversationControlHandler"]
  J --> CORR["correlation_scope\nrequest_id / correlation_id"]
end

subgraph MEMORY["3. FREYA KNOWLEDGE + MEMORY"]
  direction TB
  E["MemoryCoordinator"]
  E3["UnifiedRetrieval"]
  E2["Goal Storage"]
  E1["Working · Task · Long-Term\nSemantic · Episodic · Project Memory"]
  E4["ExperienceMemory"]
  E5["ConversationMemory"]
  E6["EngineeringLessons"]
  E --> E3
  E --> E2
  E --> E1
  E --> E4
  E --> E5
  E --> E6
  E3 --> E1
  E3 --> E4
  E3 --> E5
  E3 --> E6
end

subgraph INTELLIGENCE["4. FREYA INTELLIGENCE"]
  direction TB
  G["Intelligence"] --> G1["Reasoning + Decision"]
  G --> G2["Confidence / Answerability"]
  G --> G3["Context + Goal Awareness"]
end

subgraph ROUTING["5. KNOWLEDGE-FIRST ROUTING"]
  direction TB
  H["UnifiedRouter"] --> H0["KnowledgeFirstResolver"]
  H0 --> H5{"Grounded local answer?"}
  H5 -->|"Yes"| RESULT["Freya Answer"]
  H5 -->|"No"| H6{"Safe local capability?"}
  H6 -->|"Yes"| H1
  H6 -->|"No"| D2
end

subgraph CAPABILITY["6. MODULAR CAPABILITY SYSTEM"]
  direction TB
  M2["CapabilityRegistry"] --> H1["CapabilityRouter"] --> H2["Capability Handlers"] --> F["ToolManager"]
  CA -->|"callability · collaborators\nsafe query discoverability"| M2
  TD["tool_dispatch\nnon-discoverable"] --> F
end

subgraph LLM["7. LOCAL LLM FALLBACK ONLY"]
  direction TB
  D["LLMStack"] --> D2["PriorityLLMProvider"]
  D --> D3["ChatActivityProvider"]
  D2 --> D1["Ollama / Local Model"]
  D2 --> V1
end

subgraph LEARNING["8. SELF-LEARNING PIPELINE"]
  direction TB
  LP["LearningPipeline"] --> LP1["Observe"] --> LP2["Evaluate"] --> LP3["Extract"] --> LP4["Validate"] --> LP5{"Worth remembering?"}
  LP5 -->|"No"| TEMP["Discard / temporary"]
  LP5 -->|"Yes"| LP6["Classify\nknowledge · experience · skill"]
  LP6 --> LP7["KnowledgeDistiller"]
  LP6 --> LP8["ExperienceDistiller"]
  LP6 --> LP9["SkillDistiller"]
  LP8 -->|"reusable evidence"| LP9
  LP7 --> LP10["Validated DistilledLearning"]
  LP8 --> LP10
  LP9 --> LP10
  LP10 -->|"Validated learning only"| E
end

subgraph EXECUTION["9. WORKFLOW + EXECUTION"]
  direction TB
  M["WorkflowOrchestrator"] --> M1["SafetyGate"]
  I["ExecutionEngine"] --> I1["UnifiedPlanner"] --> I2["UnifiedExecutor"] --> I3["ExecutionVerifier"]
  I3 -->|"passed"| DONE["Task Complete"]
  I3 -->|"failed / partial"| I4["RepairLoop"]
  I4 -->|"bounded retry"| I1
  I4 -->|"exhausted"| SF2["ExecutionSafeFailure"]
  V1["AnswerVerifier"] -->|"valid"| RESULT
  V1 -->|"invalid / low confidence"| AR["AnswerRepairLoop"]
  AR -->|"bounded retry"| D2
  AR -->|"exhausted"| SF1["AnswerSafeFailure"]
  M --> TX["TaskExecutor\nworkflow correlation context"]
  TX --> M1
  TX --> H1
end

subgraph LEGACY["10. LEGACY COMPATIBILITY"]
  direction TB
  LC["Legacy FreyaAgent"] --> LC1["Legacy local memory bundle"]
  LC --> LC2["ConversationState"]
end

subgraph AUTONOMY["11. AUTONOMY + OBSERVATION"]
  direction TB
  L["AutonomyManager"] --> L1["Watchdog"]
  L --> L3["SelfInitiatedWorkManager"]
  L --> L4["MaintenanceManager"]
  L1 --> DD["Bounded dedup cache\nfingerprint + TTL + capacity"]
  DD -->|"unique observations only"| LP
end

subgraph IMPROVEMENT["12. DIAGNOSTICS + SAFE SELF-IMPROVEMENT"]
  direction TB
  Q1["DiagnosticEngine"] --> Q2["Safe Self-Improvement"]
  Q2 -->|"approved change request"| M
end

subgraph INFRA["13. SHARED INFRASTRUCTURE"]
  direction TB
  C["Infrastructure"] --> C1["EventBus\ncorrelation metadata"]
  C --> C2["BackgroundJobService\ncorrelation-preserving lifecycle events"]
  C --> C3["ObservabilityHub"]
  C3 --> RH["Readiness\ntarget-path checks + local-model state"]
  C2 --> SB["Bounded shutdown budget"]
end

subgraph EXTENSIONS["14. FUTURE EXTENSION PORTS"]
  direction TB
  X["Future capability / feature"] --> X1["Callable capability"]
  X --> X2["Event observer"]
  X --> X3["Background / autonomous work"]
  X --> X4["Memory-aware feature"]
end

%% Canonical contract chain forms retained for compatibility validation.
M2 --> H1 --> H2 --> F
I --> I1 --> I2 --> I3
LP10 -->|"Validated learning only"| E

%% Canonical answer flow.
CORR -->|"context carries same identifier"| H
J -->|"memory reads / writes"| E
J -->|"intelligence context"| G
J -->|"chat activity"| D3
H0 -->|"local retrieval first"| E3
E3 --> G
G2 --> H5
D2 -->|"fallback draft"| V1
SF1 -->|"safe disclosure"| RESULT
SF1 -->|"knowledge gap"| LP
V1 -->|"learning candidate"| LP
RESULT -->|"final response"| J

%% Canonical task and learning flow.
J -->|"task request"| M
I1 -->|"planning context"| H
I2 -->|"proposed action"| M1
M1 -->|"approved action"| H1
F -->|"tool result"| I2
I3 -->|"verified outcome"| LP
SF2 -->|"partial failure report"| J
SF2 -->|"failure pattern"| Q1
LP -->|"improvement candidate"| Q2

%% Shared-event, autonomous, and extension flow.
M -->|"events / commands"| C1
M -->|"scheduled work"| C2
I -->|"metrics / traces"| C3
C1 -->|"system events"| L1
C1 -->|"learning events"| LP
C1 -->|"autonomy triggers"| L3
C1 -->|"maintenance triggers"| L4
C3 -->|"health / alerts"| L1
C3 -->|"diagnostic data"| Q1
L3 -->|"read goals"| E2
L3 -->|"autonomous request"| M
L4 -->|"maintenance request"| M
L -->|"background jobs"| C2
X1 -.->|"register capability"| M2
X2 -.->|"publish / subscribe"| C1
X3 -.->|"schedule work"| C2
X4 -.->|"MemoryCoordinator-only durable write path"| E

%% Initialization ownership and compatibility boundary.
B -->|"1. Infrastructure"| C
B -->|"2. LLM stack"| D
B -->|"3. Memory"| E
B -->|"4. Intelligence"| G
B -->|"5. Capability registry"| M2
B -->|"6. Router"| H
B -->|"7. Execution engine"| I
B -->|"8. Orchestrator"| M
B -->|"9. Conversation control"| J
B -->|"10. Facade"| K
B -->|"11. Autonomy"| L
B -->|"12. Learning pipeline"| LP
B -->|"13. Diagnostics"| Q1
B -->|"14. Init Self-Improvement"| Q2
LC -.->|"Injected canonical components"| K
LC2 -.->|"compatibility conversation history"| J

classDef bootstrap fill:#263238,color:#ffffff,stroke:#546e7a,stroke-width:2px;
classDef interface fill:#6a1b9a,color:#ffffff,stroke:#ab47bc;
classDef memory fill:#00695c,color:#ffffff,stroke:#26a69a,stroke-width:2px;
classDef routing fill:#00838f,color:#ffffff,stroke:#26c6da;
classDef capability fill:#0277bd,color:#ffffff,stroke:#29b6f6;
classDef llm fill:#4527a0,color:#ffffff,stroke:#7e57c2;
classDef learning fill:#558b2f,color:#ffffff,stroke:#9ccc65;
classDef execution fill:#2e7d32,color:#ffffff,stroke:#66bb6a;
classDef workflow fill:#ef6c00,color:#ffffff,stroke:#ffa726;
classDef safety fill:#c62828,color:#ffffff,stroke:#ef5350,stroke-width:3px;
classDef infrastructure fill:#37474f,color:#ffffff,stroke:#78909c;
classDef improvement fill:#ad1457,color:#ffffff,stroke:#ec407a;
classDef extension fill:#455a64,color:#ffffff,stroke:#90a4ae,stroke-dasharray:5 5;
classDef legacy fill:#5d4037,color:#ffffff,stroke:#8d6e63,stroke-dasharray:4 3;
class A,B,CA,RDY bootstrap;
class K,J,CORR interface;
class E,E1,E2,E3,E4,E5,E6 memory;
class H,H0,H5,H6,RESULT routing;
class M2,H1,H2,F,TD capability;
class D,D1,D2,D3 llm;
class LP,LP1,LP2,LP3,LP4,LP5,LP6,LP7,LP8,LP9,LP10,TEMP learning;
class I,I1,I2,I3,I4,V1,DONE,AR,TX execution;
class M,L,L1,L3,L4 workflow;
class M1,SF1,SF2 safety;
class C,C1,C2,C3,RH,SB infrastructure;
class Q1,Q2 improvement;
class X,X1,X2,X3,X4 extension;
class LC,LC1,LC2 legacy;
