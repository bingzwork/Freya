# Goal‑Driven Learning

## Status
❌ **Not Implemented**

## Overview
Goal‑Driven Learning connects Freya’s Goal Management system with her Knowledge System so that she learns only what is necessary to achieve her active goals. Instead of acquiring knowledge arbitrarily, she analyzes goal requirements, spots knowledge gaps, prioritizes learning tasks, and automatically acquires and validates the needed knowledge before continuing execution.

## Current State
- **Implementation:** No code or functional pipeline exists – only the design specification is present.  
- **Priority:** ⭐⭐⭐⭐⭐ **Critical**  
- **Completion:** 0 %

## Planned Workflow
```
Active Goals → Analyze Goal Requirements → Identify Knowledge Gaps → Prioritize Learning Topics → Knowledge Acquisition → Knowledge Extraction → Knowledge Validation → Store in Knowledge Base → Continue Goal Execution
```

## Core Responsibilities (Planned)
- **Goal Requirement Analysis** – Break down each active goal into its constituent tasks and required knowledge areas.  
- **Knowledge Gap Identification** – Compare existing knowledge against required knowledge; flag missing items.  
- **Learning Prioritization** – Rank missing knowledge by impact on goal completion, dependency depth, and confidence of existing knowledge.  
- **Knowledge Acquisition Trigger** – Automatically launch the Knowledge Acquisition pipeline when gaps are detected.  
- **Learning Progress Tracking** – Record what has been learned, confidence after validation, and remaining gaps.  
- **Goal Execution Improvement** – Feed validated knowledge back into planning and execution to increase success rates.

## Example Scenario
**Goal:** *Build a FastAPI Authentication System*  

- **Current Knowledge:** Python, REST APIs, FastAPI Basics ✔︎  
- **Missing Knowledge:** OAuth, JWT, Refresh Tokens ✘  
- **Decision:** Prioritize acquiring OAuth → JWT → Refresh Tokens knowledge before proceeding.  
- **Outcome:** After validation, the newly stored knowledge enables the planner to select appropriate security tools and generate correct code snippets.

## Learning Triggers
- Creation of a new active goal.  
- Start of a new task or subtask.  
- Planning phase identifies missing dependencies.  
- Decision‑making confidence drops below threshold.  
- Repeated execution failures suggest missing knowledge.  
- Explicit user request for learning or improvement.

## Integration Points
- **Goal Management** – Supplies active goals, priorities, and hierarchy.  
- **Planning & Reasoning** – Requests knowledge when confidence is low.  
- **Knowledge System** – Executes acquisition, extraction, validation, and storage.  
- **Decision Making** – Uses validated knowledge to raise confidence and select actions.  
- **Task Planning** – Adjusts task decomposition based on newly acquired knowledge.

## Success Criteria (Future)
- Freya can automatically detect missing knowledge for any active goal.  
- She can prioritize and acquire only the necessary knowledge.  
- Goal execution success rate improves measurably after learning cycles.  
- Learning progress is tracked and visible in the Learning History.  

## Remaining Implementation Tasks
| Priority | Objective | Description | Why It Matters | Dependencies | Success Criteria |
|----------|-----------|-------------|----------------|--------------|------------------|
| ⭐⭐⭐⭐⭐ **Critical** | Build Goal‑Driven Trigger Pipeline | Wire Goal Management signals to the Knowledge Acquisition workflow so that learning starts automatically when gaps are detected. | Enables truly autonomous, purpose‑driven learning. | Goal Management API, Knowledge Acquisition | Learning initiates without manual intervention. |
| ⭐⭐⭐⭐ **High** | Implement Gap Analysis Engine | Create logic to compare existing knowledge against goal‑required knowledge and output prioritized gap list. | Determines *what* to learn and *why*. | Knowledge Base, Goal Metadata | Gap list is accurate and ordered correctly. |
| ⭐⭐⭐ **Medium** | Add Prioritization Logic | Rank gaps by impact, dependency depth, and confidence of known knowledge. | Ensures the most beneficial learning is tackled first. | Gap Analysis Engine | Ranking aligns with project priorities and reduces goal risk. |
| ⭐⭐ **Low** | Create Learning Progress Dashboard | Simple UI showing active gaps, acquisition status, and confidence after validation. | Provides visibility for users and debugging. | Gap Analysis Engine, Acquisition Status | Dashboard updates in real time and reflects correct state. |
| ⭐ **Future** | Automated Curriculum Generation | Generate multi‑step learning plans that span multiple goals and dependencies. | Supports long‑term, complex objectives. | Prioritization Logic | Generates coherent, ordered curricula that respect dependencies. |

---  
*This document serves as the single source of truth for Goal‑Driven Learning design and roadmap. It will be updated as implementation progresses.*