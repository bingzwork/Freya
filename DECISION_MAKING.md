# Decision Making

**Status:** ✅ IMPLEMENTED (Phase 1 & Phase 2 Complete - Full Decision Framework + Enhancements)

**Priority:** ⭐⭐⭐⭐⭐ Critical

---

## Overview

Decision Making is Freya's judgment layer — the system that evaluates whether an action should be taken.

| Component | Status | Description |
|-----------|--------|-------------|
| **Confidence Scoring** | ✅ Complete | Multi-factor confidence models for decisions, actions, recommendations |
| **Risk Assessment** | ✅ Complete | Code/system risk analysis with severity, probability, mitigation |
| **Goal Scheduling** | ✅ Complete | Priority-based goal queue with dependency blocking |
| **Adaptive Replanning** | ✅ Complete | Plan modification on failure, preserving completed work |
| **Intent Classification** | ✅ Complete | Routes requests with confidence thresholds |
| **Memory Retrieval** | ✅ Complete | Context gathering from multiple memory systems |
| **Decision Engine** | ✅ Complete | Unified decision workflow orchestrator |
| **Decision History** | ✅ Complete | Structured decision log with outcomes |
| **Explainable Decisions** | ✅ Complete | Plain-English decision explanations |
| **Human Oversight Integration** | ✅ Complete | Approval gates based on risk/confidence |
| **Adaptive Decision Revision** | ✅ Complete | Monitor outcomes during execution, re-evaluate when context changes |
| **Learning From Decisions** | ✅ Complete | Analyze outcomes, update confidence models, detect patterns |
| **Decision Visualization** | ✅ Complete | Decision tree/graph export, timeline view in multiple formats |
| **Meta-Decision Learning** | ✅ Complete | Learn when to trust/subvert confidence estimates |
| **Human Oversight Enhancement** | ✅ Complete | Interactive approval UI, review/override APIs, audit trail |

---

## What Exists Today

### ✅ Confidence Scoring (`app/confidence/`)
Multi-dimensional confidence evaluation:
- **DecisionConfidence** — complexity, alternatives, context quality, best-practice alignment, impact
- **ActionConfidence** — reversibility, side effects, historical success rate, system state, action type
- **RecommendationConfidence** — evidence, benefit, risk, source reliability, applicability
- **ConfidenceCalculator** — weighted event aggregation with risk adjustment
- **ConfidenceTracker** — persistent history with summaries

### ✅ Risk Assessment (`app/risk/`)
Code and system risk analysis:
- **RiskItem** — severity (critical→info), probability (certain→rare), category (security, performance, reliability, etc.)
- **RiskAnalyzer** — pattern-based detection (hardcoded secrets, SQL injection, error swallowing, TODO comments)
- **RiskAssessment** — complete assessment sessions with findings and recommendations

### ✅ Goal Scheduling (`app/memory/goals.py`)
- Priority queue (`queue()`) sorted by critical→high→medium→low→optional
- Dependency blocking (`is_blocked()`) — unmet deps = blocked
- Next goal selection (`select_next()`) with auto-resume of paused goals

### ✅ Adaptive Replanning (`app/agent/core_agent.py`)
- `_replan_after_failure()` — replaces failed tasks, preserves COMPLETED work
- ProgressTracker emits replanning events
- Works for both `solve()` and `run_active_goal()`

### ✅ Intent Classification (`app/intent/classifier.py`)
- 8 intent types with routing priority (CONVERSATIONAL_CONTROL → SYSTEM_STATUS → engineering → chat)
- Confidence thresholds: ACCEPT=0.70, LOW=0.40, mid-band triggers clarification
- Engineering intents include runtime context

### ✅ Memory Retrieval (`app/memory/`)
- Unified retrieval across working, episodic, semantic, long-term, task, project memory
- Engineering lessons (patterns + anti-patterns) surfaced during planning/repair
- Experience memory with outcomes for similar tasks

### ✅ Decision Management (`app/decision/`)
**Phase 1 - Decision Management Foundation Complete:**
- **Decision Manager** (`app/decision/manager.py`) — Central orchestrator running the Observe→Gather→Identify→Evaluate→Estimate Risk/Benefit→Choose→Execute→Observe loop
- **Decision Workflow** (`app/decision/workflow.py`) — Structured 6-step pipeline replacing ad-hoc decision points
- **Decision History** (`app/decision/history.py`) — Persistent searchable log with decision, reason, outcome, timestamp, confidence, result
- **Decision Models** (`app/decision/models.py`) — Core data models: DecisionCategory, DecisionType, DecisionContext, DecisionOption, DecisionResult, DecisionRecord
- **Category-Specific Handlers** — Execution, Information, Planning, Recovery, Learning decision types with tailored logic
- **Convenience Functions** — `decide_context_sufficiency()`, `decide_tool_selection()`, `decide_recovery_action()`, `decide_plan_approach()`, `decide_replanning_strategy()`, `decide_planning_strategy()`
- **Explainable Decisions** — `DecisionResult.explain()` and `DecisionManager.explain_decision()` in plain English
- **Human Oversight Gates** — Automatic approval requirements based on risk level and confidence thresholds

---

## What's Missing (Phase 3+ Future Enhancements)

| Missing Piece | Purpose | Dependencies |
|---------------|---------|--------------|
| **Advanced Decision Visualization** | Interactive web-based dashboard, real-time updates | Decision Visualization (basic complete) |
| **Cross-Project Decision Transfer** | Transfer decision patterns across projects | Meta-Decision Learning |
| **Collaborative Decision Making** | Multi-human approval workflows | Human Oversight Enhancement |
| **Decision Market/Trading** | Internal prediction markets for decision outcomes | All Phase 2 components |

---

## Decision Categories (Implemented)

| Category | Examples | Handler |
|----------|----------|---------|
| **Execution** | Edit file? Execute tool? Continue task? Stop? | `_handle_execution_decision` |
| **Information** | Read another file? Search docs? Retrieve memory? Enough context? | `_handle_information_decision` |
| **Planning** | Break into subtasks? Simplify? Change strategy? | `_handle_planning_decision` |
| **Recovery** | Retry? Alternative? Pause? Ask user? | `_handle_recovery_decision` |
| **Learning** | Store lesson? Long-term memory? Knowledge base? | `_handle_learning_decision` |

**Decision Types by Category:**
- **Execution**: TOOL_SELECTION, FILE_OPERATION, COMMAND_EXECUTION, AGENT_ACTION, TASK_CONTINUATION
- **Information**: CONTEXT_SUFFICIENCY, MEMORY_RETRIEVAL, USER_QUERY, EXTERNAL_SEARCH
- **Planning**: TASK_DECOMPOSITION, STRATEGY_SELECTION, PRIORITY_ORDERING, RESOURCE_ALLOCATION
- **Recovery**: RETRY_WITH_ALTERNATIVE, ESCALATE, PAUSE_AND_ASK, ABORT_TASK
- **Learning**: STORE_LESSON, CONSOLIDATE_EXPERIENCE, UPDATE_KNOWLEDGE_BASE

---

## Remaining Implementation Tasks

### ⭐⭐⭐⭐⭐ Critical (Phase 1 - COMPLETE ✅)
1. **Decision Manager Module** (`app/decision/manager.py`)
   - Orchestrate the full decision workflow
   - Integrate Confidence, Risk, Goals, Planning, Memory
   - Expose `decide(context, options) -> DecisionResult`

2. **Decision Workflow Pipeline**
   - Observe Situation → Gather Context → Identify Actions → Evaluate Options → Estimate Risk/Benefit → Choose Best → Execute → Observe Outcome → Next Decision
   - Replace implicit decision points in agent with explicit calls

3. **Decision History Store** (`app/decision/history.py`)
   - Persistent log with decision, rationale, confidence, risk, outcome, timestamp
   - Searchable by type, component, time range, outcome

### ⭐⭐⭐⭐ High (Phase 2+ - COMPLETE ✅)
4. **Adaptive Decision Revision** (`app/decision/adaptive_revision.py`)
   - Monitor outcomes during execution
   - Re-evaluate decisions when context changes significantly
   - Dynamic action selection based on new information
   - Background monitoring thread with configurable interval
   - 5 built-in change detectors (system state, failures, goals, resources, time)

5. **Learning From Decisions** (`app/decision/learning.py`)
   - Analyze successful vs failed decisions
   - Update confidence models from outcomes
   - Pattern recognition for recurring decision contexts
   - Confidence calibration with context-aware adjustments
   - Actionable insights generation (bias, anomaly, pattern detection)

6. **Human Oversight Enhancement** (`app/decision/human_oversight.py`)
   - Interactive terminal-based approval UI with arrow-key navigation
   - Approval request queue with priority handling
   - Rule-based auto-approval/routing/escalation
   - Decision review and override APIs
   - Full audit trail for human interventions

### ⭐⭐⭐ Medium (Phase 2+ - COMPLETE ✅)
7. **Decision Visualization** (`app/decision/visualization.py`)
   - Decision tree/graph export for debugging
   - Timeline view of decision → outcome chains
   - Multiple output formats: DOT/GraphViz, Mermaid, JSON, HTML (interactive)
   - Causal and revision edge tracking

### ⭐⭐ High (Phase 2+ - COMPLETE ✅)
8. **Meta-Decision Learning** (`app/decision/meta_learning.py`)
   - Learn when to trust/subvert own confidence estimates
   - Context-dependent reliability rules
   - Systematic bias detection (overconfidence, risk aversion, anchoring, recency)
   - Dynamic threshold adjustment based on learned biases
   - Meta-confidence: confidence in confidence estimates

---

## Phase 3+ Future Enhancements

### ⭐⭐⭐ Medium (Phase 3 - Optional Improvements)
9. **Advanced Decision Visualization**
   - Interactive web-based dashboard with real-time updates
   - Drill-down into decision contexts and outcomes
   - Comparative analysis across projects

10. **Cross-Project Decision Transfer**
    - Transfer decision patterns across projects
    - Shared meta-learning models
    - Federated decision learning

### ⭐⭐ Low (Phase 4 - Future Ideas)
11. **Collaborative Decision Making**
    - Multi-human approval workflows
    - Consensus-based decision routing
    - Stakeholder notification and escalation

12. **Decision Market/Trading**
    - Internal prediction markets for decision outcomes
    - Calibration through betting mechanisms
    - Incentivized accuracy in confidence estimation

---

## Integration Points

The Decision Manager connects these existing systems:

```
┌─────────────────────────────────────────────────────────────┐
│                    DECISION MANAGER                         │
├─────────────────────────────────────────────────────────────┤
│  Observe → Gather Context → Identify Actions → Evaluate    │
│         → Estimate Risk/Benefit → Choose → Execute → Learn │
└─────────────────────────────────────────────────────────────┘
        │              │              │            │
        ▼              ▼              ▼            ▼
   ┌────────┐    ┌──────────┐   ┌─────────┐ ┌──────────┐
   │Intent  │    │ Memory   │   │Planning  Risk    Confidence   │
   │ Class. │◄──►│ Systems  │◄─►││ Manager ││ Assess.  │ │ Scoring  │
   └────────┘    └──────────┘   └─────────┘ └──────────┘
                                               │
                                               ▼
                                        ┌────────────┐
                                        │ Goal       │
                                        │ Scheduling │
                                        └────────────┘
```

---

## Completion Estimate

**Current: ~100%** — Phase 1 & Phase 2 complete with full unified orchestration layer + all enhancements.

| Phase | Status |
|-------|--------|
| Phase 1 — Decision Framework | ✅ Complete |
| Phase 2 — Context & Information Decisions | ✅ Complete (integrated) |
| Phase 3 — Risk & Confidence Evaluation | ✅ Complete (integrated) |
| Phase 4 — Execution Decisions | ✅ Complete (integrated) |
| Phase 5 — Adaptive Decision Making | ✅ Complete (integrated) |
| Phase 6 — Decision History | ✅ Complete |
| Phase 7 — Learning From Decisions | ✅ Complete |
| Phase 8 — Autonomous Judgment System | ✅ Complete (Phase 2+) |

---

## Next Steps (Phase 3+)

1. **Phase 3**: Advanced Decision Visualization - interactive web dashboard with real-time updates
2. **Phase 3**: Cross-Project Decision Transfer - share patterns across projects
3. **Phase 4**: Collaborative Decision Making - multi-human approval workflows
4. **Phase 4**: Decision Market/Trading - internal prediction markets for decision outcomes