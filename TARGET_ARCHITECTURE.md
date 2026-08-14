Freya Migration Target Architecture

This file is the authoritative architecture contract for the migration from the OLD Freya architecture to the NEW Freya architecture.

All future implementation work must conform to this exact diagram.

The existing OLD implementation may be redesigned and refactored as necessary to reach this target.

The target architecture itself must not be redesigned, simplified, reinterpreted, renamed, replaced, or extended unless explicitly instructed by the user.

```mermaid
flowchart TD


%% =========================================================
%% 1. BOOTSTRAP
%% =========================================================
subgraph BOOT["1. BOOTSTRAP"]
direction TB


A["main.py"]
B["SystemInitializer"]


A --> B
end



%% =========================================================
%% 2. PUBLIC INTERFACE
%% =========================================================
subgraph INTERFACE["2. FREYA INTERFACE"]
direction TB


K["AgentFacadeImpl"]
J["ConversationControl"]


K --> J
end



%% =========================================================
%% 3. KNOWLEDGE + MEMORY
%% =========================================================
subgraph MEMORY["3. FREYA KNOWLEDGE + MEMORY"]
direction TB


E["MemoryCoordinator"]
E3["UnifiedRetrieval"]
E2["GoalManager"]


E1["Core Memory Modules<br/>
Working · Task · Long-Term<br/>
Semantic · Episodic · Project"]


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



%% =========================================================
%% 4. FREYA INTELLIGENCE
%% =========================================================
subgraph INTELLIGENCE["4. FREYA INTELLIGENCE"]
direction TB


G["IntelligenceEngine"]
G1["Reasoning + Decision Logic"]
G2["Confidence / Answerability"]
G3["Context + Goal Awareness"]


G --> G1
G --> G2
G --> G3
end



%% =========================================================
%% 5. KNOWLEDGE-FIRST RESOLUTION
%% =========================================================
subgraph ROUTING["5. KNOWLEDGE-FIRST ROUTING"]
direction TB


H["UnifiedRouter"]
H0["KnowledgeFirstResolver"]


H5{"Can Freya Answer?"}
H6{"Local Capability Available?"}


RESULT["Freya Answer"]


H --> H0


H5 -->|"Yes"| RESULT


H5 -->|"No / Insufficient"| H6
end



%% =========================================================
%% 6. MODULAR CAPABILITY SYSTEM
%% =========================================================
subgraph CAPABILITY["6. MODULAR CAPABILITY SYSTEM"]
direction TB


M2["CapabilityRegistry"]
H1["CapabilityRouter"]
H2["Capability Handlers"]
F["ToolManager"]


M2 --> H1
H1 --> H2
H2 --> F
end



%% =========================================================
%% 7. LOCAL LLM FALLBACK ONLY
%% =========================================================
subgraph LLM["7. LOCAL LLM FALLBACK ONLY"]
direction TB


D["LLMStack"]
D2["PriorityLLMProvider"]
D1["Ollama / Local Model"]
D3["ChatActivityProvider"]


D --> D2
D --> D3


D2 --> D1
end



%% =========================================================
%% 8. LLM LEARNING PATH
%% =========================================================
subgraph LEARNING["8. SELF-LEARNING PIPELINE"]
direction TB


LP["LearningPipeline"]


LP1["Observe"]
LP2["Evaluate"]
LP3["Extract Learning"]
LP4["Validate Learning"]
LP5{"Worth Remembering?"}
LP6["Classify\nKNOWLEDGE · EXPERIENCE · SKILL"]
LP7["KnowledgeDistiller"]
LP8["ExperienceDistiller"]
LP9["SkillDistiller"]
LP10["Better Knowledge & Skills\nnormalized DistilledLearning"]


TEMP["Discard / Keep Temporary"]


LP --> LP1
LP1 --> LP2
LP2 --> LP3
LP3 --> LP4
LP4 --> LP5


LP5 -->|"No"| TEMP
LP5 -->|"Yes"| LP6
LP6 -->|"KNOWLEDGE"| LP7
LP6 -->|"EXPERIENCE"| LP8
LP6 -->|"SKILL"| LP9
LP8 -->|"Reusable experience evidence"| LP9
LP7 --> LP10
LP8 --> LP10
LP9 --> LP10
end



%% =========================================================
%% 9. WORKFLOW + EXECUTION
%% =========================================================
subgraph EXECUTION["9. WORKFLOW + EXECUTION"]
direction TB


M["WorkflowOrchestrator"]
M1["SafetyGate"]


I["ExecutionEngine"]
I1["UnifiedPlanner"]
I2["UnifiedExecutor"]
I3["ExecutionVerifier"]
I4["RepairLoop"]


V1["AnswerVerifier"]
DONE["Task Complete"]


AR["AnswerRepairLoop"]
SF1["AnswerSafeFailure"]
SF2["ExecutionSafeFailure"]


M --> M1


I --> I1
I1 --> I2
I2 --> I3


I3 -->|"Passed"| DONE


I3 -->|"Failed"| I4
I4 -->|"Repair / Replan (Attempt < Max)"| I1
I4 -->|"Retries Exhausted"| SF2
SF2 -->|"Request Compensation"| M1


V1 -->|"Invalid / Low Confidence"| AR
AR -->|"Retry w/ Corrective Context (Attempt < Max)"| D2
SF1 -->|"Low-Confidence Disclosure"| RESULT
SF1 -->|"Log Knowledge Gap"| LP


%% Approved learning is classified and distilled before its canonical coordinator write.


%% Planner asks Freya knowledge first
I1 --> H


%% Approved actions use capability system
I2 -->|"Proposed Action"| M1
M1 -->|"Approved Action"| H1


%% Tool results return to executor
F -->|"Tool Result"| I2


%% Execution experience feeds learning
I3 -->|"Outcome / Experience"| LP


DONE --> J


%% Execution verification failure handling
SF2 -->|"Partial Failure Report"| J
SF2 -->|"Log Failure Pattern"| Q1



%% =========================================================
%% 10. CONVERSATION FLOW
%% =========================================================



%% =========================================================
%% 11. AUTONOMY + OBSERVATION
%% =========================================================
subgraph AUTONOMY["11. AUTONOMY + OBSERVATION"]
direction TB


L["AutonomyManager"]


L1["Watchdog"]
L3["SelfInitiatedWorkManager"]
L4["MaintenanceManager"]


L --> L1
L --> L3
L --> L4
end



%% =========================================================
%% 12. SAFE SELF-IMPROVEMENT
%% =========================================================
subgraph IMPROVEMENT["12. DIAGNOSTICS + SAFE SELF-IMPROVEMENT"]
direction TB


Q1["Diagnostics"]
Q2["Safe Self-Improvement"]


Q1 --> Q2
end



%% =========================================================
%% 13. SHARED INFRASTRUCTURE
%% =========================================================
subgraph INFRA["13. SHARED INFRASTRUCTURE"]
direction TB


C["Infrastructure"]


C1["EventBus"]
C2["BackgroundJobService"]
C3["ObservabilityHub"]


C --> C1
C --> C2
C --> C3
end



%% =========================================================
%% 14. FUTURE EXTENSION PORTS
%% =========================================================
subgraph EXTENSIONS["14. FUTURE EXTENSION PORTS"]
direction TB


X["Future Capability / Feature"]


X1["Callable Capability"]
X2["Event / Observer"]
X3["Background / Autonomous"]
X4["Memory-Aware Feature"]


X --> X1
X --> X2
X --> X3
X --> X4
end



%% =========================================================
%% CROSS-GROUP WIRING (COMPLETE & VALIDATED)
%% =========================================================


%% --- Goal & Context wiring ---
E2 -->|"Active Goals"| G3
E2 -->|"Goal Context"| I1

E3 -->|"Retrieved Knowledge"| G
E3 -->|"Knowledge / Experience"| H5

G -->|"Intent / Plan Hints"| I1
G1 -->|"Reasoned Decisions"| I1
G2 -->|"Confidence Score"| H5
G3 -->|"Context Snapshot"| I1


%% --- Knowledge-First Routing ---
H0 -->|"1. Search Freya First"| E3
H5 -->|"Yes, High Confidence"| RESULT
H5 -->|"No / Insufficient"| H6

H6 -->|"Yes"| H1
H6 -->|"No"| D2


%% --- LLM Fallback & Learning ---
D2 -->|"Fallback Answer"| V1

V1 -->|"Valid Answer"| RESULT
V1 -->|"Learning Candidate"| LP

%% Answer verification failure handling
AR -->|"Retry w/ Corrective Context (Attempt < Max)"| D2
SF1 -->|"Low-Confidence Disclosure"| RESULT
SF1 -->|"Log Knowledge Gap"| LP


%% --- Learning to Memory ---
LP10 -->|"Canonical coordinated write"| E
LP -->|"Learning Events"| C1


%% --- Planner asks Freya knowledge first ---
I1 -->|"Knowledge/Capability Query"| H


%% --- Execution uses Capability System ---
I2 -->|"Proposed Action"| M1
M1 -->|"Approved Action"| H1
H1 -->|"Dispatch"| H2
H2 -->|"Execute Tool"| F
F -->|"Tool Result"| I2


%% --- Execution Verification & Repair ---
I3 -->|"Passed"| DONE
I3 -->|"Failed / Partial"| I4
I4 -->|"Repair / Replan (Attempt < Max)"| I1
I4 -->|"Retries Exhausted"| SF2
SF2 -->|"Request Compensation"| M1
SF2 -->|"Partial Failure Report"| J
SF2 -->|"Log Failure Pattern"| Q1


%% --- Conversation Flow Wiring ---
J -->|"Question / Knowledge Request"| H
J -->|"Task / Action Request"| M
J -->|"Context / Memory Read"| E
J -->|"Intelligence Context"| G
J -->|"Chat Activity"| D3
J -->|"Goal Updates"| E2

RESULT -->|"Final Answer"| J
DONE -->|"Task Result"| J


%% --- Autonomy + Observation Wiring ---
L3 -->|"Read Goals"| E2
L3 -->|"Autonomous Work Request"| M
L4 -->|"Maintenance Work Request"| M

L1 -->|"Observations / Anomalies"| LP
L1 -->|"Health Events"| C1


%% --- Safe Self-Improvement Wiring ---
LP -->|"Improvement Candidate"| Q2
Q2 -->|"Approved Improvement Proposal"| M
Q1 -->|"Failure Patterns"| Q2
Q1 -->|"Diagnostics Data"| Q2


%% --- Shared Infrastructure Wiring ---
M -->|"Events / Commands"| C1
M -->|"Schedule Background"| C2
I -->|"Metrics / Traces"| C3

C1 -->|"System Events"| L1
C1 -->|"Learning Events"| LP
C1 -->|"Autonomy Triggers"| L3
C1 -->|"Maintenance Triggers"| L4

C3 -->|"Metrics / Health"| L1
C3 -->|"Diagnostics Data"| Q1
C3 -->|"Execution Metrics"| M

L -->|"Background Jobs"| C2


%% --- Future Extension Ports Wiring ---
X1 -.->|"Register Capability"| M2
X2 -.->|"Publish / Subscribe"| C1
X3 -.->|"Schedule Background"| C2
X4 -.->|"Stable Memory API"| E


%% =========================================================
%% 15. INITIALIZATION (COMPLETE DEPENDENCY GRAPH)
%% =========================================================


B -->|"1. Init Infrastructure"| C
B -->|"2. Init LLM Stack"| D
B -->|"3. Init Memory"| E
B -->|"4. Init Intelligence"| G
B -->|"5. Init Capability Registry"| M2
B -->|"6. Init Router"| H
B -->|"7. Init Execution Engine"| I
B -->|"8. Init Orchestrator"| M
B -->|"9. Init Interface"| J
B -->|"10. Init Facade"| K
B -->|"11. Init Autonomy"| L
B -->|"12. Init Learning Pipeline"| LP
B -->|"13. Init Diagnostics"| Q1
B -->|"14. Init Self-Improvement"| Q2


%% =========================================================
%% STYLING
%% =========================================================


classDef bootstrap fill:#263238,color:#ffffff,stroke:#546e7a,stroke-width:2px;


classDef interface fill:#6a1b9a,color:#ffffff,stroke:#ab47bc;


classDef memory fill:#00695c,color:#ffffff,stroke:#26a69a,stroke-width:2px;


classDef intelligence fill:#1565c0,color:#ffffff,stroke:#42a5f5;


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



class A,B bootstrap;


class K,J interface;


class E,E1,E2,E3,E4,E5,E6 memory;


class G,G1,G2,G3 intelligence;


class H,H0,H5,H6,RESULT routing;


class M2,H1,H2,F capability;


class D,D1,D2,D3 llm;


class LP,LP1,LP2,LP3,LP4,LP5,LP6,LP7,LP8,LP9,LP10,TEMP learning;


class I,I1,I2,I3,I4,V1,DONE,AR execution;


class M,L,L1,L3,L4 workflow;


class M1,SF1,SF2 safety;


class C,C1,C2,C3 infrastructure;


class Q1,Q2 improvement;


class X,X1,X2,X3,X4 extension;
<<<END_EXTERNAL_UNTRUSTED_CONTENT id="fixed-architecture">
>