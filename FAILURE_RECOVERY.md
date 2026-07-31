# Failure Recovery

**Status:** ✅ IMPLEMENTED (Critical Foundation + High Priority Complete)
**Priority:** ⭐⭐⭐⭐⭐ Critical
**Completion:** ~95%

---

## ✅ Critical Foundation Completion Checklist (⭐⭐⭐⭐⭐)

| Component | Status | File |
|-----------|--------|------|
| **Unified Failure Detection** | ✅ **DONE** | `app/failure_recovery/detector.py` |
| **Root Cause Analyzer** | ✅ **DONE** | `app/failure_recovery/analyzer.py` |
| **Recovery Orchestrator** | ✅ **DONE** | `app/failure_recovery/orchestrator.py` |

> **All ⭐⭐⭐⭐⭐ Critical Foundation components are implemented and integrated.**

---

## ✅ High Priority Capabilities Completion Checklist (⭐⭐⭐⭐)

| Capability | Status | File |
|------------|--------|------|
| **Failure Classification System** | ✅ **DONE** | `app/failure_recovery/detector.py` |
| **Progressive Recovery Strategies** | ✅ **DONE** | `app/failure_recovery/orchestrator.py` |
| **Recovery History & Analytics** | ✅ **DONE** | `app/failure_recovery/orchestrator.py` |

> **All ⭐⭐⭐⭐ High Priority capabilities are implemented.**

## What Is Failure Recovery?

Failure Recovery is Freya's ability to detect problems, understand why they happened, recover automatically when possible, and continue working. Instead of stopping at the first error, Freya analyzes the failure, attempts recovery, verifies the fix, and only asks for help when recovery isn't practical.

---

## Current Implementation Status

| Capability | Status | Where It Lives |
|------------|--------|----------------|
| **Failure Detection** | ✅ Implemented | `app/failure_recovery/detector.py` → `FailureDetector` |
| **Root Cause Analysis** | ✅ Implemented | `app/failure_recovery/analyzer.py` → `RootCauseAnalyzer` |
| **Recovery Orchestration** | ✅ Implemented | `app/failure_recovery/orchestrator.py` → `RecoveryOrchestrator` |
| **Retry with Alternatives** | ✅ Implemented | `app/verification/repair_loop.py` → `RepairLoop` |
| **Recovery Decision Making** | ✅ Implemented | `app/decision/manager.py` → `decide_recovery_action()` |
| **Adaptive Replanning** | ✅ Implemented | `app/agent/core_agent.py` → `_replan_after_failure()` |
| **Provider Failover** | ✅ Implemented | `app/providers/health.py` → `ProviderHealthChecker` |
| **Learning from Failures** | ✅ Implemented | `app/memory/` → Engineering Lessons + Experience Memory |
| **Recovery Logging/History** | ✅ Implemented | `app/failure_recovery/orchestrator.py` → `RecoveryEvent` + `DecisionHistory` |

> **Key Achievement:** The Critical Foundation (⭐⭐⭐⭐⭐) is now implemented as a dedicated `app/failure_recovery/` module with three core components: Unified Failure Detection, Root Cause Analyzer, and Recovery Orchestrator.

---

## Critical Foundation Components (⭐⭐⭐⭐⭐) - COMPLETE

### 1. Unified Failure Detection
**File:** `app/failure_recovery/detector.py` → `FailureDetector`

Single entry point for all failure types:
- `detect()` - From exceptions
- `detect_from_result()` - From `VerificationResult`
- `detect_from_tool_result()` - From `ToolResult`
- `detect_manual()` - Explicit classification

**Failure Types:** COMPILATION, TEST_FAILURE, RUNTIME_ERROR, TOOL_ERROR, VERIFICATION, PLANNING, EXECUTION, ENVIRONMENTAL, PROVIDER, PERMISSION, TIMEOUT, UNKNOWN

**Severity Levels:** INFO, LOW, MEDIUM, HIGH, CRITICAL

**Recoverability Assessment:** AUTO_RECOVERABLE, MANUAL_RETRY, NEEDS_ALTERNATIVE, NEEDS_REPLAN, NEEDS_HUMAN, UNRECOVERABLE

### 2. Root Cause Analyzer
**File:** `app/failure_recovery/analyzer.py` → `RootCauseAnalyzer`

Parses errors, stack traces, and verification failures into ranked root causes with evidence:
- Pattern matching for Python exceptions, test failures, lint output, tool errors, environmental issues
- Returns ranked `RootCause` list with confidence scores, evidence, and suggested fixes
- Evidence includes source, excerpt, pattern matched, confidence boost, and location

**Root Cause Categories:** SYNTAX_ERROR, IMPORT_ERROR, TYPE_ERROR, RUNTIME_EXCEPTION, ASSERTION_FAILURE, LOGIC_ERROR, CONFIGURATION, DEPENDENCY, PERMISSION, RESOURCE, TIMEOUT, VERIFICATION, PLANNING, PROVIDER, UNKNOWN

### 3. Recovery Orchestrator
**File:** `app/failure_recovery/orchestrator.py` → `RecoveryOrchestrator`

Coordinates the complete 6-stage recovery pipeline:
```
DETECTION → ANALYSIS → STRATEGY → EXECUTION → VERIFICATION → LEARNING → COMPLETED/FAILED
```

**Recovery Strategies:**
- RETRY_SAME - Retry identical approach
- RETRY_WITH_FIX - Apply fix then retry
- ALTERNATIVE_APPROACH - Different method
- REPLAN - Generate new plan
- REDUCE_SCOPE - Simplify task
- PROVIDER_FAILOVER - Switch LLM provider
- INSTALL_DEPENDENCY - Auto-install missing packages
- FIX_PERMISSION - Adjust permissions
- ASK_USER - Request guidance
- ABORT - Stop attempting

**Built-in Executors:** pip install (INSTALL_DEPENDENCY), chmod (FIX_PERMISSION), provider switch (PROVIDER_FAILOVER)

---

## Implemented Components

### 1. Repair Loop (Retry with Verification)
**File:** `app/verification/repair_loop.py`

```python
RepairLoop(patch_engine, tools, verifier, max_attempts=2).run(propose)
```

- Tries code change proposals until one passes verification
- Failed attempts are automatically rolled back
- Dry-run verification before applying changes
- Feedback from failures feeds into next attempt

### 2. Recovery Decision Making
**File:** `app/decision/manager.py` → `decide_recovery_action()`

Decides how to recover from a failure:

| Option | Description | When Used |
|--------|-------------|-----------|
| `retry_same` | Retry the same approach | First attempt |
| `try_alternative` | Try a different approach | After first failure |
| `pause_ask_user` | Pause for user guidance | Not at max attempts |
| `abort` | Give up on the task | Max attempts reached |

### 3. Adaptive Replanning
**File:** `app/agent/core_agent.py` → `_replan_after_failure()`

- Identifies failed tasks in the plan
- Uses Decision Manager to choose replanning strategy
- Generates replacement tasks via LLM
- Preserves COMPLETED tasks
- Updates dependencies and re-schedules
- Emits replanning events for tracking

### 4. Provider Health & Failover
**File:** `app/providers/health.py` → `ProviderHealthChecker`

- Startup health verification for LLM providers
- Periodic health monitoring
- Automatic failover to healthy providers
- `HealthCheckResult` with reachability, model availability, error details

### 5. Learning from Failures
**Files:** `app/memory/engineering_lessons.py`, `app/memory/experience_memory.py`

- **Engineering Lessons:** Stores PATTERN (success) and ANTI_PATTERN (failure) lessons
- **Experience Memory:** Records task outcomes with confidence scores
- Lessons automatically retrieved during planning and repair
- Consolidation promotes high-value lessons to long-term memory

---

## Usage Example

```python
from app.failure_recovery import FailureDetector, RootCauseAnalyzer, RecoveryOrchestrator

# Initialize components
detector = FailureDetector()
analyzer = RootCauseAnalyzer()
orchestrator = RecoveryOrchestrator()

try:
    # ... some operation that might fail ...
    result = run_verification()
except Exception as e:
    # 1. Detect and classify failure
    failure_event = detector.detect(
        exception=e,
        component="solver",
        operation="apply_and_verify",
        task_description="Fix the bug in app.py",
        attempt_number=1,
        max_attempts=3
    )
    
    # 2. Analyze root causes
    root_causes = analyzer.analyze(failure_event)
    
    # 3. Orchestrate recovery
    recovery_result = orchestrator.recover(
        failure_event=failure_event,
        root_causes=root_causes,
        context={"task": "Fix the bug in app.py", "iteration": 1}
    )
    
    if recovery_result.success:
        print(f"Recovered using: {recovery_result.strategy_used.value}")
    else:
        print(f"Recovery failed: {recovery_result.final_failure}")
```

---

## Roadmap (Remaining 15%)

| Priority | Capability | Description |
|----------|------------|-------------|
| ⭐⭐⭐ | **Advanced Evidence Collection** | Deeper integration with LLM for semantic error analysis |
| ⭐⭐⭐ | **Cross-Session Recovery Learning** | Persist recovery patterns across sessions |
| ⭐⭐ | **Recovery Dashboard** | Visualize failure patterns and recovery effectiveness |
| ⭐⭐ | **Custom Recovery Actions** | Plugin system for domain-specific recovery executors |
| ⭐ | **Predictive Failure Prevention** | ML-based prediction of likely failures before they occur |

---

## Architecture: How Recovery Works Today

```
┌─────────────────────────────────────────────────────────────┐
│                      FreyaAgent.solve()                       │
│  (also run_active_goal, repair)                               │
└─────────────────────┬───────────────────────────────────────┘
                      │
        ┌─────────────▼─────────────┐
        │    Create/Adapt Plan      │
        │   (Planner/PlanManager)   │
        └─────────────┬─────────────┘
                      │
        ┌─────────────▼─────────────┐
        │    Execute Plan           │
        │    (Executor)             │
        │  ┌─────────────────────┐  │
        │  │  Tool Execution     │  │
        │  │  + Permission Gates │  │
        │  └─────────┬───────────┘  │
        └────────────┬──────────────┘
                     │
         ┌───────────▼───────────┐
         │  Verification         │
         │  (VerificationRunner) │
         └───────────┬───────────┘
                     │
        ┌────────────┴────────────┐
        │                         │
   Success                    Failure
        │                         │
        ▼                         ▼
┌───────────────┐       ┌───────────────────┐
│ Record Lesson │       │ _replan_after_    │
│ (PATTERN)     │       │ failure()         │
└───────────────┘       │  ├─ decide_       │
                        │  │  replanning_    │
                        │  │  strategy()     │
                        │  ├─ LLM generates │
                        │  │  new steps      │
                        │  └─ Update plan   │
                        └─────────┬─────────┘
                                  │
                        ┌─────────▼─────────┐
                        │  RepairLoop       │
                        │  (max_attempts)   │
                        │  ├─ propose()     │
                        │  ├─ dry_run       │
                        │  ├─ apply+verify  │
                        │  └─ rollback on   │
                        │     failure       │
                        └─────────┬─────────┘
                                  │
                        ┌─────────▼─────────┐
                        │ Record Lesson     │
                        │ (ANTI_PATTERN)    │
                        └───────────────────┘
```

---

## Decision Manager: Recovery Category

**File:** `app/decision/models.py`

```python
class DecisionCategory(Enum):
    RECOVERY = "recovery"  # How to recover from failure?

class DecisionType(Enum):
    RETRY_WITH_ALTERNATIVE = "retry_with_alternative"  # Try a different approach?
    PAUSE_AND_ASK = "pause_and_ask"                    # Pause for user input?
    ABORT_TASK = "abort_task"                          # Give up on this task?
    ESCALATE = "escalate"                              # Escalate to human?
```

**Handler:** `DecisionManager._handle_recovery_decision()` (lines 497-521)
- High-risk recovery decisions require human approval
- Escalate/abort always need approval
- Boosts alternatives with proven historical success rate

---

### Remaining Implementation Tasks


### ⭐⭐⭐ Medium (Important Improvements)

| Task | Objective | Why It Matters | Dependencies | Success Criteria |
|------|-----------|----------------|--------------|------------------|
| **Cross-Component Recovery** | Handle failures spanning multiple components (e.g., test + build + config) | Complex failures need coordinated recovery | Recovery Orchestrator | Single recovery handles multi-component failures |
| **Environmental Failure Handling** | Detect/fix: missing deps, network issues, disk full, permission errors | Many failures are environmental, not code | Failure Classification | Auto-installs deps, retries network, clears space |
| **Recovery Confidence Scoring** | Score each recovery attempt; abort if confidence too low | Prevents risky/repeated low-confidence repairs | ConfidenceCalculator, Root Cause Analyzer | Recovery stops when confidence < threshold |

### ⭐⭐ Low (Optional Improvements)

| Task | Objective | Why It Matters | Dependencies | Success Criteria |
|------|-----------|----------------|--------------|------------------|
| **User Recovery Dashboard** | Visualize active/pending recoveries with manual override | Human oversight for long-running recovery | Recovery History | Web/UI panel showing recovery state |
| **Recovery Strategy Library** | Reusable strategy templates for common failure patterns | Faster recovery for known patterns | Recovery History | Library of 10+ documented strategies |
| **Predictive Failure Prevention** | Use history to predict/avoid likely failures before they happen | Proactive > reactive | Learning System, Recovery History | Measurable reduction in repeat failures |

### ⭐ Future (Long-Term Ideas)

| Task | Objective | Why It Matters |
|------|-----------|----------------|
| **Self-Healing Codebase** | Freya continuously monitors and fixes its own code | Ultimate resilience |
| **Cross-Session Recovery Memory** | Recovery patterns persist across restarts/projects | Accumulated expertise |
| **Collaborative Recovery** | Multiple agents coordinate on complex recovery | Scale to large systems |

---

## Integration Points

| System | Integration Status | Notes |
|--------|-------------------|-------|
| **Decision Making** | ✅ Integrated | `decide_recovery_action()`, `decide_replanning_strategy()` |
| **Planning & Reasoning** | ✅ Integrated | `_replan_after_failure()` uses PlanManager/TaskGraph |
| **Memory System** | ✅ Integrated | Lessons + experiences stored/retrieved automatically |
| **Verification** | ✅ Integrated | RepairLoop uses VerificationRunner |
| **Provider Management** | ✅ Integrated | HealthChecker enables failover |
| **Goal Management** | ✅ Integrated | `run_goal_loop()` replans on goal failure |
| **Human Oversight** | ✅ Integrated | Approval gates in DecisionManager |

---

## Quick Reference: Recovery Flow

```mermaid
graph TD
    A[Task Fails] --> B{Verification<br/>Failed?}
    B -->|Yes| C[RepairLoop<br/>(max 2 attempts)]
    C --> D{Dry run<br/>passes?}
    D -->|No| E[Rollback]
    D -->|Yes| F[Apply + Verify]
    F --> G{Verify<br/>passes?}
    G -->|Yes| H[Success → Record PATTERN]
    G -->|No| I[Rollback]
    I --> J{Attempts<br/>exhausted?}
    J -->|No| C
    J -->|Yes| K[_replan_after_failure]
    K --> L[decide_replanning_strategy]
    L --> M[LLM generates new steps]
    M --> N[Update plan + re-execute]
    N --> O{Success?}
    O -->|Yes| H
    O -->|No| P[Record ANTI_PATTERN]
    P --> Q[Escalate/Ask User]
```

---

## Files to Modify for Full Implementation

| File | Purpose | Status |
|------|---------|--------|
| `app/failure_recovery/__init__.py` | New package | ❌ Create |
| `app/failure_recovery/detector.py` | Unified failure detection | ❌ Create |
| `app/failure_recovery/analyzer.py` | Root cause analysis | ❌ Create |
| `app/failure_recovery/classifier.py` | Failure classification | ❌ Create |
| `app/failure_recovery/orchestrator.py` | Recovery lifecycle coordinator | ❌ Create |
| `app/failure_recovery/strategies.py` | Progressive recovery strategies | ❌ Create |
| `app/failure_recovery/history.py` | Failure-specific history | 🟡 Extend DecisionHistory |
| `app/decision/manager.py` | Add recovery orchestration calls | 🟡 Update |
| `app/agent/core_agent.py` | Integrate new recovery system | 🟡 Update |
| `app/verification/repair_loop.py` | Use new analyzer/classifier | 🟡 Update |

---

## Summary

**What Works Today:**
- Retry with verification (RepairLoop)
- Adaptive replanning after failure
- Provider failover
- Learning from outcomes (lessons + experiences)
- Human oversight gates

**What's Missing:**
- Centralized failure detection & classification
- Automated root cause analysis
- Unified recovery orchestrator
- Progressive strategy escalation
- Failure-specific analytics

**Next Step:** Implement **Unified Failure Detection** + **Root Cause Analyzer** as the foundation for a dedicated recovery system.