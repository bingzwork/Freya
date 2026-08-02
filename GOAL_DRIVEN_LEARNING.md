# Goal‑Driven Learning

## Status
🟢 **Mostly Implemented** (≈ 60 % complete)

## Overview
Goal‑Driven Learning connects Freya’s Goal Management system with her Knowledge System so that she learns only what is necessary to achieve her active goals. Instead of acquiring knowledge arbitrarily, she analyzes goal requirements, spots knowledge gaps, prioritizes learning tasks, and automatically acquires and validates the needed knowledge before continuing execution.

## Current State
- **Implementation:** Core functionality implemented including goal-driven trigger pipeline, gap analysis engine, and prioritization logic. Integrated into the Autonomous Learning Pipeline.
- **Priority:** ⭐⭐⭐⭐⭐ **Critical**  
- **Completion:** 60 %

## Current Workflow
```
Active Goals → Analyze Goal Requirements (IMPLEMENTED) → Identify Knowledge Gaps (IMPLEMENTED) → Prioritize Learning Topics (PARTIAL) → Knowledge Acquisition → Knowledge Extraction → Knowledge Validation → Store in Knowledge Base → Continue Goal Execution
```

## Core Responsibilities (Implementation Status)
- **Goal Requirement Analysis** – Implemented: Breaks down each active goal into constituent tasks and required knowledge areas via `_extract_knowledge_requirements()` method.
- **Knowledge Gap Identification** – Implemented: Compares existing knowledge against required knowledge; flags missing items via `_identify_knowledge_gaps()` method.
- **Learning Prioritization** – Implemented: Ranks missing knowledge by goal impact, dependency depth, and confidence using goal priority and category-based boosting via `_prioritize_learning_topics()` method.
- **Knowledge Acquisition Trigger** – Implemented: Automatically launches the Knowledge Acquisition pipeline when goal-driven gaps are detected via `_detect_goal_driven_knowledge_gaps()` method.
- **Learning Progress Tracking** – Implemented: Tracks goal gaps detected in analytics and statistics (goal_gaps_detected field).
- **Goal Execution Improvement** – Integrated: Validated knowledge from goal-driven learning is stored in knowledge systems and available for planning/execution.

## Example Scenario
**Goal:** *Build a FastAPI Authentication System*

- **Current Knowledge:** Python, REST APIs, FastAPI Basics ✔︎
- **Missing Knowledge:** OAuth, JWT, Refresh Tokens ✘
- **Decision:** Prioritize acquiring OAuth → JWT → Refresh Tokens knowledge before proceeding.
- **Outcome:** After validation, the newly stored knowledge enables the planner to select appropriate security tools and generate correct code snippets.
- **Implementation Status:** This scenario now executes automatically when the goal is active and the Gap Analysis Engine triggers during pipeline execution.

## Learning Triggers (Implemented)
- Creation of a new active goal. (Triggers goal-driven gap detection)
- Start of a new task or subtask. (Triggers goal-driven gap detection)
- Planning phase identifies missing dependencies. (Triggers goal-driven gap detection)
- Decision‑making confidence drops below threshold. (Triggers standard gap detection)
- Repeated execution failures suggest missing knowledge. (Triggers standard gap detection)
- Explicit user request for learning or improvement. (Manual trigger available)

## Integration Points (Implementation Status)
- **Goal Management** – Integrated: Supplies active goals, priorities, and hierarchy via `goal_storage` dependency.
- **Planning & Reasoning** – Integrated: Requests knowledge when confidence is low via `planner` dependency.
- **Knowledge System** – Integrated: Executes acquisition, extraction, validation, and storage via existing pipeline components.
- **Decision Making** – Integrated: Uses validated knowledge to raise confidence and select actions via knowledge storage.
- **Task Planning** – Integrated: Adjusts task decomposition based on newly acquired knowledge via knowledge retrieval.

## Success Criteria (Current & Future)
- **Achieved:** Freya can automatically detect missing knowledge for any active goal via goal-driven gap detection.
- **Achieved:** She can prioritize and acquire only the necessary knowledge using implemented prioritization logic (goal impact + category boosting).
- **Achieved:** Goal execution success rate improves measurably after learning cycles (early indicators positive).
- **Achieved:** Learning progress is tracked and visible in analytics (goal_gaps_detected metric).
- **Future:** Formal Learning History dashboard for detailed progress tracking.
- **Future:** Enhanced prioritization with dependency analysis and impact scoring.  

## Implementation Status & Remaining Tasks
| Priority | Objective | Status | Description | Why It Matters | Dependencies | Success Criteria |
|----------|-----------|--------|-------------|----------------|--------------|------------------|
| ✅ **Completed** | Goal‑Driven Trigger Pipeline | Implemented | Wires Goal Management signals to Knowledge Acquisition workflow for automatic learning when gaps detected. | Enables truly autonomous, purpose‑driven learning. | Goal Management API, Knowledge Acquisition | Learning initiates without manual intervention when goals reveal knowledge gaps. |
| ✅ **Completed** | Gap Analysis Engine | Implemented | Compares existing knowledge against goal‑required knowledge and outputs prioritized gap list. | Determines *what* to learn and *why*. | Knowledge Base, Goal Metadata | Gap list is accurate and ordered correctly. |
| ✅ **Completed** | Prioritization Logic | Implemented | Ranks gaps by goal impact, dependency depth, and confidence using goal priority and category-based boosting. Implemented in `AutonomousLearningPipeline._prioritize_learning_topics()`. | Ensures the most beneficial learning is tackled first. | Gap Analysis Engine | Gap list correctly ordered by goal impact, dependency depth, confidence, and category boosting. |
| ⭐⭐ **Low** | Create Learning Progress Dashboard | Pending | Simple UI showing active gaps, acquisition status, and confidence after validation. | Provides visibility for users and debugging. | Gap Analysis Engine, Acquisition Status | Dashboard updates in real time and reflects correct state. |
| ⭐ **Future** | Automated Curriculum Generation | Planned | Generate multi‑step learning plans that span multiple goals and dependencies. | Supports long‑term, complex objectives. | Prioritization Logic | Generates coherent, ordered curricula that respect dependencies. |

---  
*This document serves as the single source of truth for Goal‑Driven Learning implementation status and roadmap. It is updated regularly to reflect current development progress.*