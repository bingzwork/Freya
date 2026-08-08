# Freya Architecture GAP Analysis

**Generated**: 2026-08-08  
**Scope**: Focused architectural review of \pp/\ and key entry points  
**Method**: Code inspection of core_agent.py, orchestrator.py, intent/, capabilities/, conversational_control.py, memory/, planner/, priority_llm.py, events.py, and CURRENT_ARCHITECTURE.md

---

## Executive Summary

Freya has evolved from a simple agent into a **distributed monolith** with ~35 subsystems wired into two competing God-classes (\FreyaAgent\ and \CentralOrchestrator\). The architecture exhibits:
- **No clear layer boundaries** — everything imports everything
- **Duplicate routing paths** — 3+ intent/control classifiers with overlapping patterns
- **Organic growth without consolidation** — 11 memory modules, 7+ background job sources
- **Circular dependencies** — Agent <-> Orchestrator -> Agent via callbacks

**Critical Finding**: The system works because Ollama is the *de facto* serialization point (PriorityLLM queue), masking contention that would appear under load or with faster models.

---

## 1. MAJOR ARCHITECTURAL PROBLEMS

### GAP-001: Dual God-Classes with Overlapping Responsibilities [P0]
**Files**: \pp/agent/core_agent.py\ (2,868 lines), \pp/orchestrator/orchestrator.py\ (1,239 lines)

| FreyaAgent Owns | CentralOrchestrator Owns |
|-----------------|--------------------------|
| LLM (via PriorityLLM) | CapabilityRegistry |
| ToolManager | WorkflowComposer |
| Planner / Executor / Verifier | TaskExecutor |
| 11 Memory modules | SafetyGate |
| ConversationState / WorkingMemory | SelfObserver |
| AutonomyManager | ActivityReporter / GUI |
| Self-Observation (RA/SA/PD) | FailureRecoveryIntegration |
| DecisionManager | IntentClassifier (re-instantiated) |
| WorldModel / ExternalRegistry / NetworkMonitor | DecisionManager (re-instantiated) |
| ConfigHotReload / FileWatcher | Memory Retrieval (re-instantiated) |

**Evidence**: \FreyaAgent.__init__\ lines 517-1300 instantiates everything. \CentralOrchestrator._initialize_components\ lines 340-500 re-instantiates IntentClassifier, DecisionManager, UnifiedRetrieval, WorldModel.

**Impact**: 
- Two pipeline entry points: \FreyaAgent.run()\ (9 stages) vs \CentralOrchestrator.execute_intent()\ (11 stages)
- AutonomyManager holds ref to FreyaAgent AND gets \set_executor(llm, tools, lessons)\ from Orchestrator
- ConversationControlHandler created by Agent, passed to Orchestrator via \set_conversation_control()\
- No single source of truth for "what is the current plan" or "is execution active"

### GAP-002: Three Competing Intent/Control Routers [P0]
**Files**: \pp/intent/classifier.py\ (768 lines), \pp/capabilities/router.py\ (242 lines), \pp/conversational_control.py\ (1,048 lines)

| Router | Patterns | Actions |
|--------|----------|---------|
| IntentClassifier | 90+ keywords + 50+ regex patterns | Returns IntentType (CHAT, TASK, FILE_OPERATION, SYSTEM_STATUS, CONVERSATIONAL_CONTROL, ...) |
| CapabilityRouter | Patterns + keywords per registered Capability | Executes handler; raises NoCapabilityError |
| ConversationalControlHandler | ControlCommand enum (STOP, CANCEL, PAUSE, RESUME, UNDO, REDO, STATUS, ...) | Direct state manipulation via \_state\ |

**Overlaps**:
- "stop"/"halt"/"cancel" appear in ALL THREE
- "status"/"what are you doing" in IntentClassifier AND ConversationalControlHandler
- SYSTEM_STATUS intent handled by IntentClassifier AND CapabilityRouter AND direct LLM path

**Code Paths**:
1. \FreyaAgent.run()\ line 1043: \classify_intent()\ -> \classification.is_control\ -> \oute_query()\
2. \FreyaAgent.run()\ line 1072: \should_answer_directly()\ -> direct LLM
3. \CentralOrchestrator.execute_intent()\ line 689: \intent_classifier.classify()\ -> decision -> workflow
4. \ConversationControlHandler.handle_*()\ called from executor via \efore_task()\/\check_stop_requested()\

**Impact**: Undefined precedence; clarifying questions sometimes trigger capability routes; stop commands may not interrupt orchestrator workflows.

### GAP-003: Eleven Memory Modules with No Unified Write Path [P1]
**Files**: \pp/memory/\ (11+ modules), \pp/memory/unified_retrieval.py\ (1,196 lines)

| Module | Storage | Primary Use |
|--------|---------|-------------|
| WorkingMemory | In-memory + JSON | Scratchpad for active task |
| TaskMemory | SQLite (data/memory/task_memory.db) | Task execution state |
| LongTermMemory | JSONL (data/memory/long_term/) | User prefs, facts, standards |
| EpisodicMemory | JSONL (data/memory/episodic/) | Append-only event log |
| SemanticMemory | JSONL + Vector (data/memory/semantic/) | Programming knowledge base |
| ProjectMemory | JSON (data/memory/project_memory.json) | Project-specific context |
| ExperienceMemory | JSONL (data/memory/experience/) | Past task outcomes |
| EngineeringLessonStorage | JSONL (data/memory/lessons/) | Learned patterns |
| GoalStorage | JSON (data/memory/goals.json) | Hierarchical goals |
| UnifiedRetrieval | **Read-only aggregation** | Cross-memory search |
| ConsolidationEngine | Background job | Promotes Experience -> Lessons |

**Problems**:
- **Write fragmentation**: Each module has own \dd()\, \save()\, \store()\ — no transaction boundary
- **Read duplication**: \UnifiedRetrieval\ instantiates 11 retriever classes; each re-implements scoring
- **No cache invalidation**: Memory writes don't notify UnifiedRetrieval
- **Cross-references**: \CrossMemoryReferences\ (graph) + \RankingEngine\ (BM25/LLM rerank) + \KnowledgeValidator\ all operate post-hoc

### GAP-004: Background Job Contention with No Isolation [P1]
**Files**: \pp/core/background_jobs.py\, \pp/long_term_autonomy/manager.py\, \pp/core/priority_llm.py\

| Source | Jobs Registered | Priority |
|--------|-----------------|----------|
| AutonomyManager | 7 (persist, learning, maintenance, watchdog, self-initiated, health, decision) | AUTONOMY_THINK (500) |
| ConversationControlHandler | 1 (state persistence) | LOW |
| SystemMonitor | Continuous thread (60s) | — |
| GPUMonitor | Continuous thread (5s) | — |
| RuntimeAwareness | Continuous thread (10s) | — |
| PredictiveDiagnostics | Via Orchestrator job (60s) | BACKGROUND |
| ConsolidationEngine | Scheduled via Autonomy | BACKGROUND |

**Contention Points**:
- All LLM calls go through single \PriorityLLMProvider\ worker thread
- \BackgroundJobService\ uses 10 workers + semaphore; jobs yield via \chat_activity.wait_for_chat_idle()\
- \AutonomyManager._autonomy_loop\ is a daemon thread that ALSO calls \wait_for_chat_idle(60s)\
- System/GPU monitors run independent threads with psutil/subprocess calls

**Race Condition**: If chat starts during \wait_for_chat_idle(60s)\, autonomy wakes <2s later (Condition notify). But if chat starts during a BG job's LLM call, that call completes at AUTO priority before chat gets queue access.

### GAP-005: Self-Observation Triplication [P1]
**Files**: \pp/self_observation/runtime_awareness.py\, \pp/self_observation/self_analysis.py\, \pp/self_observation/predictive_diagnostics.py\

| Component | Interval | Data Sources | Output |
|-----------|----------|--------------|--------|
| RuntimeAwareness | 10s | 20+ component \get_health()\ calls | Health snapshots -> EventBus |
| CentralizedSelfAnalysis | 300s | RuntimeAwareness + DecisionManager + WorldModel + Memory + FailureRecovery | 11-category analysis -> EventBus |
| PredictiveDiagnostics | 60s | RuntimeAwareness + SelfAnalysis | Resource forecasts -> EventBus |

**Problems**:
- All three instantiate and reference \CentralOrchestrator\, \DecisionManager\, \WorldModel\, \UnifiedRetrieval\
- Started by \CentralOrchestrator._initialize_components()\ lines 460-520
- Also instantiated directly in \FreyaAgent.__init__\ lines 850-880
- Each maintains own config, state, and EventBus subscriptions
- No shared base class or interface; duplicated \get_*()\ factory functions

---

## 2. DEPENDENCY / COUPLING PROBLEMS

### GAP-006: Circular Dependency Graph [P0]
`
FreyaAgent
  -> creates -> CentralOrchestrator
  -> creates -> AutonomyManager
  -> creates -> ConversationControlHandler
  -> creates -> PriorityLLMProvider

CentralOrchestrator
  -> needs -> ConversationControlHandler (via set_conversation_control)
  -> creates -> RuntimeAwareness / SelfAnalysis / PredictiveDiagnostics
    -> needs -> CentralOrchestrator (passed in constructor)
  -> creates -> FailureRecoveryIntegration
    -> needs -> TaskExecutor / WorkflowComposer / CapabilityRegistry

AutonomyManager
  -> set_executor(llm, tools, lessons) <- FreyaAgent
  -> registers jobs -> BackgroundJobService
  -> uses -> CentralOrchestrator (via orchestrator ref)

PriorityLLMProvider
  <- chat_activity.chat_started/ended <- FreyaChatActivityProvider (in FreyaAgent)
  -> yields to chat via _chat_active flag
`

**Count**: 7+ cycles detected. Breaking any requires interface extraction.

### GAP-007: EventBus as Global Coupling Medium [P1]
- Single \EventBus\ instance used by 20+ components
- Events emitted in hot paths: \intent.classified\, \memory.retrieved\, \decision.made\, \workflow.started\, every health check
- No schema registry; payloads are \Dict[str, Any]\
- \EventHistory\ keeps 10k events in memory with indexes by name/source
- \ObservabilityHub\ also subscribes to events for metrics

**Risk**: EventBus lock contention under load; no backpressure; no dead-letter; silent handler failures.

### GAP-008: Config/State Persistence Scattered [P1]
| System | Storage Location | Format |
|--------|------------------|--------|
| Config | \pp/core/config.py\ + \config_hot_reload.py\ | YAML + env overrides |
| ConversationState | \data/conversation/\ | JSONL |
| WorkingMemory | In-memory only | — |
| TaskMemory | \data/memory/task_memory.db\ | SQLite |
| LongTermMemory | \data/memory/long_term/\ | JSONL per category |
| ProjectMemory | \data/memory/project_memory.json\ | JSON |
| ExperienceMemory | \data/memory/experience/\ | JSONL |
| EngineeringLessons | \data/memory/lessons/\ | JSONL |
| GoalStorage | \data/memory/goals.json\ | JSON |
| ConversationControl | \data/memory/conversation_control.json\ | JSON |
| Service Registry | \data/services/registry.json\ | JSON |
| Autonomy State | \data/autonomy/state.json\ | JSON |

**No**: unified checkpoint, migration strategy, or corruption recovery.

---

## 3. DUPLICATED EXECUTION PATHS

### GAP-009: Three Planning/Execution Pipelines [P0]

| Pipeline | Entry Point | Stages | Output |
|----------|-------------|--------|--------|
| **Agent Pipeline** | \FreyaAgent.run()\ | classify -> clarify? -> direct? -> context_check -> plan -> review -> execute -> verify -> final LLM | LLM response |
| **Orchestrator Pipeline** | \CentralOrchestrator.execute_intent()\ | conv_context -> goals -> intent -> decision -> memory/world -> compose -> capabilities -> execute -> observe -> learning -> improvement | execution_id |
| **Autonomy Pipeline** | \AutonomyManager._autonomy_loop\ | observe -> analyze -> decide -> act -> verify -> learn | background jobs |

**Divergence**: 
- Agent uses \Planner.create_plan()\ -> \Executor.execute_plan()\
- Orchestrator uses \WorkflowComposer.compose()\ -> \TaskExecutor.execute()\
- Different task graphs, different capability sets, different checkpointing

### GAP-010: Two Capability Registries [P1]
- \pp/orchestrator/capability_registry.py\ — \CapabilityRegistry\ with \Capability\ objects (init/activate/deactivate lifecycle)
- \pp/capabilities/router.py\ — \CapabilityRouter\ with \Capability\ dataclasses (handler + patterns)

**Different**: \Capability\ in registry has state machine; in router it's a handler bag. No shared base.

---

## 4. GOD-CLASS RESPONSIBILITIES

### GAP-011: FreyaAgent Violates SRP [P0]
**Responsibilities** (from \__init__\):
1. LLM client wrapper (PriorityLLM)
2. Chat activity coordination (FreyaChatActivityProvider)
3. Tool management
4. Project/Experience/Engineering memory
5. Goal/Plan management
6. Execution (Executor, PatchEngine, PatchGenerator)
7. Verification/Repair
8. Planner
9. Conversation memory (ConversationState)
10. Working/Task/LongTerm/Episodic/Semantic memory
11. UnifiedRetrieval + Consolidation + Forgetting + CrossRef + Ranking + Validation
12. ConversationalControlHandler
13. CentralOrchestrator
14. DecisionManager + FailureRecovery + Evaluation
15. AutonomyManager + AutonomousLearningPipeline + SafeSelfImprovement
16. WorldModel + ExternalServiceRegistry + NetworkMonitor
17. ConfigHotReload + FileWatcher
18. EventBus + BackgroundJobService + ObservabilityHub
19. RuntimeAwareness + CentralizedSelfAnalysis + PredictiveDiagnostics
20. GitManager + SymbolIndex + ProjectIndex + ContextBuilder + DependencyGraph + FileLocator + LexicalSearch + EnhancedRetriever + ReflectionEngine

**Total**: 20+ distinct subsystem categories in one class.

### GAP-012: CentralOrchestrator Violates SRP [P1]
**Responsibilities**:
1. Capability lifecycle (registry, health checks)
2. Workflow composition (strategy, intent, memory, decision)
3. Task execution (checkpointing, parallelism, retries)
4. Safety gating (risk analysis, human approval)
5. Self-observation (snapshots, metrics)
6. Activity reporting (plain English)
7. GUI/Streaming interfaces
8. Failure recovery integration
9. Conversation control coordination
10. RuntimeAwareness / SelfAnalysis / PredictiveDiagnostics lifecycle
11. Background job scheduling
12. Event publishing
13. Global state (\_active_workflows\, \_shared_context\)

---

## 5. ORCHESTRATOR / AGENT BOUNDARIES

### GAP-013: No Clear Facade / API Boundary [P0]
- \main.py\ -> \FreyaAgent.run()\ 
- \FreyaAgent\ -> creates \CentralOrchestrator\ but **doesn't delegate** routing
- \CentralOrchestrator\ -> has \execute_intent()\ but Agent calls it **only implicitly** via AutonomyManager
- External callers (tests, GUI) don't know which entry point to use

**Missing**: Single \AgentFacade\ with \chat(user_input)\, \execute_task(task)\, \get_status()\ that encapsulates routing.

### GAP-014: AutonomyManager Straddles Both [P1]
`python
# In FreyaAgent.__init__:
self.autonomy_manager = AutonomyManager(
    agent=self,  # Circular!
    orchestrator=self.orchestrator,  # Dual reference
    ...
)

# In AutonomyManager:
def set_executor(self, llm, tools, lessons):  # Called by Agent after Orchestrator starts
`
AutonomyManager holds both \gent\ and \orchestrator\ refs, uses Agent for LLM/tools, uses Orchestrator for capability execution.

---

## 6. MEMORY / PLANNER / AUTONOMY / EVENT ARCHITECTURE ISSUES

### GAP-015: Planner Has Two Implementations [P1]
- \pp/agent/planner.py\ — \Planner.create_plan()\ used by Agent pipeline
- \pp/planner/plan_manager.py\ — \PlanManager\ + \Plan\ + \TaskGraph\ used by Orchestrator/CAP registry
- Different \Task\ models, different dependency graphs, different serialization

### GAP-016: Event Architecture Lacks Contracts [P1]
- \Event\ dataclass: \
ame, data, source, timestamp, event_id, priority, tags, metadata\
- No: schema validation, versioning, required fields per event type
- Handlers subscribe with string patterns (\"task.*"\) — typos silently ignored
- \EventHistory\ stores everything; no TTL by event type

### GAP-017: PriorityLLM Yields Are Coarse-Grained [P1]
- \PriorityLLMProvider._should_yield_for_chat()\ checks \_chat_active\ boolean
- Autonomy/Background jobs yield entire LLM calls, not tokens
- If autonomy starts a 30s LLM stream, chat waits until completion
- No: streaming preemption, partial result return, or cancellation

---

## 7. SEVERITY MATRIX

| ID | Title | Severity | Effort | Risk if Unfixed |
|----|-------|----------|--------|-----------------|
| GAP-001 | Dual God-Classes | **P0** | High | Unmaintainable; duplicate bugs; unclear ownership |
| GAP-002 | Triple Router Conflict | **P0** | Medium | Silent misroutes; stop commands fail intermittently |
| GAP-009 | Three Pipelines | **P0** | High | Different behavior for same task; testing burden |
| GAP-006 | Circular Dependencies | **P0** | Medium | Startup fragility; testing isolation impossible |
| GAP-011 | FreyaAgent SRP Violation | **P0** | High | 2,800-line class; any change risks regression |
| GAP-013 | Missing Facade | **P0** | Low | External API undefined |
| GAP-003 | Fragmented Memory | **P1** | High | Data inconsistency; no transaction semantics |
| GAP-004 | BG Job Contention | **P1** | Medium | Latency spikes under load |
| GAP-005 | Self-Obs Triplication | **P1** | Medium | 3x resource polling; divergent configs |
| GAP-007 | EventBus Coupling | **P1** | Medium | Cascade failures; no observability of event flow |
| GAP-008 | Scattered Persistence | **P1** | Medium | No backup/restore strategy |
| GAP-010 | Dual Capability Registries | **P1** | Low | Capability defined twice |
| GAP-012 | Orchestrator SRP | **P1** | High | 1,200-line class |
| GAP-014 | Autonomy Straddle | **P1** | Medium | Dual ownership confusion |
| GAP-015 | Dual Planner | **P1** | Medium | Plan format incompatibility |
| GAP-016 | Event Contracts Missing | **P1** | Low | Runtime errors from schema drift |
| GAP-017 | Coarse LLM Preemption | **P1** | Medium | Chat latency under autonomy load |

---

## 8. DEPENDENCIES / BLOCKERS

`mermaid
graph TD
    FIX_001[Extract AgentFacade] --> FIX_002[Unify Router]
    FIX_001 --> FIX_003[Consolidate Pipelines]
    FIX_002 --> FIX_003
    FIX_003 --> FIX_004[Merge Planner Implementations]
    FIX_003 --> FIX_005[Unify Capability Registries]
    FIX_006[Break Cycles via Interfaces] --> FIX_001
    FIX_006 --> FIX_004
    FIX_007[Event Schema Registry] -.-> FIX_002
    FIX_007 -.-> FIX_003
    FIX_008[Unified Persistence Layer] -.-> FIX_003
    FIX_009[Consolidate Self-Observation] -.-> FIX_003
    FIX_010[PriorityLLM Streaming Preemption] -.-> FIX_003
`

**Hard Blockers**:
1. **GAP-006 (Cycles)** must be broken before extracting facades — interfaces needed first
2. **GAP-002 (Routers)** must be unified before consolidating pipelines — single intent source required
3. **GAP-015 (Dual Planner)** blocks **GAP-009 (Pipeline Consolidation)** — one \Task\ model needed

---

## 9. RECOMMENDED IMPLEMENTATION ORDER

### Phase 1: Foundation (Weeks 1-2) — *No Behavioral Changes*
| Step | Action | Files |
|------|--------|-------|
| 1.1 | Define \IntentClassification\ protocol + single \IntentRouter\ facade | \pp/intent/\, \pp/capabilities/router.py\, \pp/conversational_control.py\ |
| 1.2 | Extract \AgentFacade\ interface with \chat()\, \execute()\, \status()\ | \pp/agent/core_agent.py\, \main.py\ |
| 1.3 | Introduce \EventSchema\ registry (pydantic models per event type) | \pp/core/events.py\ |
| 1.4 | Break cycles: \AutonomyManager\ -> \ExecutorProvider\ protocol; \Orchestrator\ -> \ChatActivityProvider\ protocol | \pp/long_term_autonomy/\, \pp/orchestrator/\, \pp/agent/core_agent.py\ |

### Phase 2: Consolidation (Weeks 3-5)
| Step | Action | Files |
|------|--------|-------|
| 2.1 | Merge \IntentClassifier\ + \CapabilityRouter\ + \ConversationalControlHandler\ -> single \UnifiedRouter\ | \pp/intent/\, \pp/capabilities/\, \pp/conversational_control.py\ |
| 2.2 | Consolidate \Planner\ (agent) + \PlanManager/Plan/TaskGraph\ (planner/) -> single \PlanningEngine\ | \pp/agent/planner.py\, \pp/planner/\ |
| 2.3 | Unify \CapabilityRegistry\ + \CapabilityRouter\ -> single \CapabilityRegistry\ with handler attachment | \pp/orchestrator/capability_registry.py\, \pp/capabilities/router.py\ |
| 2.4 | Merge \RuntimeAwareness\ + \CentralizedSelfAnalysis\ + \PredictiveDiagnostics\ -> single \SelfObservationEngine\ | \pp/self_observation/\ |

### Phase 3: Architecture Cleanup (Weeks 6-8)
| Step | Action | Files |
|------|--------|-------|
| 3.1 | Decompose \FreyaAgent\ into: \AgentCore\, \MemoryCoordinator\, \ExecutionEngine\, \AutonomyCoordinator\ | \pp/agent/core_agent.py\ |
| 3.2 | Decompose \CentralOrchestrator\ into: \WorkflowEngine\, \CapabilityManager\, \SafetyManager\, \ObservabilityReporter\ | \pp/orchestrator/orchestrator.py\ |
| 3.3 | Implement unified \PersistenceLayer\ with transaction support for all memory modules | \pp/memory/\, \pp/core/atomic_store.py\ |
| 3.4 | Add streaming preemption to \PriorityLLMProvider\ (token-level yield) | \pp/core/priority_llm.py\ |

### Phase 4: Hardening (Weeks 9-10)
| Step | Action |
|------|--------|
| 4.1 | Integration tests for unified router + facade |
| 4.2 | Load testing with concurrent chat + autonomy |
| 4.3 | Documentation: Architecture Decision Records for each consolidation |

---

## 10. WHAT MUST NOT BE CHANGED YET

| Component | Reason |
|-----------|--------|
| **Ollama integration** (\pp/core/llm.py\) | Stable; no architectural role |
| **ToolManager** (\pp/core/tool_manager.py\) | Well-encapsulated; FileAllowlist works |
| **PatchEngine / PatchGenerator** (\pp/editing/\) | Mature; low coupling |
| **VerificationRunner / RepairLoop** (\pp/verification/\) | Self-contained; clear interface |
| **ProjectIndex / SymbolIndex** (\pp/core/\) | Build-time only; no runtime deps |
| **ExternalServiceRegistry / NetworkMonitor** (\pp/services/\, \pp/monitoring/\) | Optional; clean boundaries |
| **GitManager** (\pp/git/\) | Independent utility |
| **Config system** (\pp/core/config.py\) | Works; hot-reload decoupled via EventBus |
| **atomic_store.py** | Low-level primitive; used correctly |

**Frozen**: Any change to the above requires full regression suite. Do not refactor as part of architectural consolidation.

---

## 11. VALIDATION CRITERIA FOR EACH PHASE

| Phase | Must Pass |
|-------|-----------|
| 1 | \main.py\ works unchanged; all existing tests pass; EventBus emits validated events |
| 2 | Single \UnifiedRouter\ handles all intent/control/capability routes; single \PlanningEngine\ used by Agent and Orchestrator; single \CapabilityRegistry\ |
| 3 | \FreyaAgent\ < 500 lines; \CentralOrchestrator\ < 400 lines; no circular imports; memory writes transactional |
| 4 | Chat latency P99 < 2s under concurrent autonomy load; zero event schema violations in 1hr soak test |

---

## Appendix: File Reference Map

| Concern | Primary Files |
|---------|---------------|
| Agent Entry | \main.py\, \pp/agent/core_agent.py\, \pp/agent/agent.py\ |
| Orchestrator | \pp/orchestrator/orchestrator.py\, \pp/orchestrator/*.py\ |
| Intent/Control | \pp/intent/classifier.py\, \pp/capabilities/router.py\, \pp/conversational_control.py\ |
| Memory | \pp/memory/*.py\, \pp/memory/unified_retrieval.py\ |
| Planning | \pp/agent/planner.py\, \pp/planner/plan_manager.py\, \pp/planner/task*.py\ |
| Autonomy | \pp/long_term_autonomy/manager.py\, \pp/autonomous_learning/\ |
| Self-Observation | \pp/self_observation/*.py\ |
| LLM Priority | \pp/core/priority_llm.py\, \pp/core/llm.py\ |
| Events/Infra | \pp/core/events.py\, \pp/core/background_jobs.py\, \pp/core/observability.py\ |
| Config | \pp/core/config.py\, \pp/core/config_hot_reload.py\, \pp/core/file_watcher.py\ |
