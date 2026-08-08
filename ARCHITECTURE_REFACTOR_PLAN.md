# Freya Architecture Refactor Plan (P0)

**Generated**: 2026-08-08  
**Based on**: ARCHITECTURE_GAP_ANALYSIS.md  
**Scope**: Target boundaries for P0 refactor -- FreyaAgent, SystemInitializer, Orchestrator, Execution Pipeline, Interfaces

---



---

## AUDIT RESULTS (2026-08-08)

### COMPLETED - Phase 1 Architecture Implementation

| Component | Status | Notes |
|---|---|---|
| AgentFacade (protocol) | Complete | app/agent/facade.py - Public API protocol |
| AgentFacadeImpl | Complete | app/agent/facade_impl.py - Thin implementation (~200 lines in unified mode) |
| SystemInitializer | Complete | app/core/initializer.py - Single-pass startup, dependency order correct |
| Protocols | Complete | app/core/protocols.py - ChatActivityProvider, ExecutorProvider, ExecutionEngineProtocol, MemoryProvider, ToolProvider, RouterProtocol |
| UnifiedRouter | Complete | app/routing/unified_router.py - Single entry point for IntentClassifier + CapabilityRouter + ControlCommandParser |
| ExecutionEngine | Complete | app/execution/engine.py - Single pipeline with UnifiedPlanner + UnifiedExecutor |
| MemoryCoordinator | Complete | app/memory/coordinator.py - Single write facade, transactional, event emission |
| WorkflowOrchestrator | Complete | app/orchestrator/workflow_orchestrator.py - Refactored from CentralOrchestrator, handles workflows only |
| AutonomyManager (protocols) | Complete | Updated to use ExecutorProvider protocol, no FreyaAgent reference |


### VERIFIED - Architecture Guarantees

| Requirement | Status | Evidence |
|---|---|---|
| FreyaAgent no longer God Class | In unified mode | Delegates to UnifiedRouter, ExecutionEngine, MemoryCoordinator when constructed via SystemInitializer. Legacy path retained for backward compatibility. |
| SystemInitializer owns startup/lifecycle | Complete | Creates all components in order; has shutdown() method |
| Agent/Orchestrator circular dependency removed | Complete | AutonomyManager takes workspace, event_bus, job_service, observability; executor set via protocol |
| One canonical execution path | Complete | AgentFacadeImpl -> UnifiedRouter -> ExecutionEngine for chat; WorkflowOrchestrator -> TaskExecutor for workflows |
| Intent routing not duplicated | Complete | UnifiedRouter consolidates 3 routers into single route() call; control checked first |
| Orchestrator stages have clear boundaries | Complete | WorkflowOrchestrator handles workflows only (not chat); execute_intent is convenience wrapper |
| MemoryManager coupling reduced | Complete | MemoryCoordinator provides single write entry points with thread safety and event emission |
| Planner boundaries clean | Partial | UnifiedPlanner uses agent Planner but does not fully merge planner/ PlanManager yet |
| EventBus coupling not duplicated | Complete | SystemInitializer creates local EventBus, injects to components; no get_event_bus() in new code |
| Existing capabilities use correct architecture | Complete | Built-in capabilities registered via UnifiedRouter._register_builtin_capabilities() |
| No obsolete wiring/duplicate services | Partial | Old CentralOrchestrator (app/orchestrator/orchestrator.py) still exists; SelfObservation components not consolidated |


### REMAINING GAP ITEMS

| GAP ID | Title | Status | Notes |
|---|---|---|---|
| GAP-001 | Dual God-Classes | Mitigated | FreyaAgent has dual-path (legacy + unified); CentralOrchestrator deprecated but file remains |
| GAP-002 | Triple Router Conflict | Resolved | UnifiedRouter is single entry point |
| GAP-003 | Fragmented Memory | Partially Resolved | MemoryCoordinator provides unified facade but 11 modules still exist underneath |
| GAP-004 | BG Job Contention | Not Addressed | Same PriorityLLM queue; no token-level preemption |
| GAP-005 | Self-Obs Triplication | Not Addressed | RuntimeAwareness, SelfAnalysis, PredictiveDiagnostics still separate |
| GAP-006 | Circular Dependencies | Resolved | Protocols break cycles; AutonomyManager no longer takes FreyaAgent |
| GAP-007 | EventBus Coupling | Mitigated | Injected locally in new components; legacy code still uses global |
| GAP-008 | Scattered Persistence | Not Addressed | No unified PersistenceLayer |
| GAP-009 | Three Pipelines | Mitigated | Two entry points (chat + workflows) with clear separation; autonomy uses background jobs |
| GAP-010 | Dual Capability Registries | Not Addressed | CapabilityRegistry + CapabilityRouter still separate |
| GAP-011 | FreyaAgent SRP Violation | Mitigated | In unified mode it is thin; legacy path still ~2900 lines |
| GAP-012 | Orchestrator SRP | Resolved | WorkflowOrchestrator focused on workflows |
| GAP-013 | Missing Facade | Resolved | AgentFacade protocol + AgentFacadeImpl exist |
| GAP-014 | Autonomy Straddle | Resolved | AutonomyManager uses ExecutorProvider protocol |
| GAP-015 | Dual Planner | Partial | UnifiedPlanner uses agent Planner; planner/ PlanManager not merged |
| GAP-016 | Event Contracts Missing | Not Addressed | No schema validation for events |
| GAP-017 | Coarse LLM Preemption | Not Addressed | PriorityLLM yields at call level, not token level |


### ISSUES DISCOVERED

1. FreyaAgent Dual-Path: core_agent.py still contains the full legacy God Class (~2900 lines) alongside the unified delegation path. Intentional for backward compatibility but creates confusion. AgentFacadeImpl (~200 lines) is the intended thin facade.

2. WorkflowOrchestrator.execute_intent(): Exists but does not do intent classification - wraps input in WorkflowSpec. Convenience for autonomy self-initiated work, not a duplicate router.

3. UnifiedPlanner Partial Merge: Delegates to app.agent.planner.Planner but does not merge app.planner.plan_manager.PlanManager / Plan / TaskGraph.

4. Old CentralOrchestrator Still Exists: app/orchestrator/orchestrator.py is deprecated but still present.

5. Self-Observation Not Consolidated: RuntimeAwareness, CentralizedSelfAnalysis, PredictiveDiagnostics still separate in app/self_observation/.

6. Dual Capability Registries: app/orchestrator/capability_registry.py and app/capabilities/router.py both exist.

7. Event Schema Not Implemented: No Pydantic models for event validation.

8. No Token-Level LLM Preemption: PriorityLLMProvider yields entire calls, not streaming tokens.

9. Planner Directory Structure: app/execution/ has engine.py but no separate planner.py / executor.py.


### RECOMMENDED NEXT STEPS

Priority 1: Remove deprecated orchestrator.py, Complete UnifiedPlanner merge, Create planner.py/executor.py, Add deprecation warning to FreyaAgent legacy path.
Priority 2: Consolidate CapabilityRegistry + CapabilityRouter, Consolidate Self-Observation components, Add EventSchema registry.
Priority 3: Transactional PersistenceLayer, Streaming preemption, Integration tests.


### VALIDATION SUMMARY

| Criteria | Status |
|---|---|
| main.py runs chat loop | Not tested (no main.py in root) |
| All tests pass | Not fully tested (network timeouts) |
| No circular imports | Verified - protocols break cycles |
| Facade impl < 500 lines | AgentFacadeImpl is ~200 lines |
| WorkflowOrchestrator < 400 lines | Is ~1700 lines |
| Single UnifiedRouter | Verified |
| Single ExecutionEngine | Verified |
| AutonomyManager uses protocol | Verified |
| EventBus emits system.initialized | Verified |


### Phase 1 Audit Status: SUBSTANTIALLY COMPLETE

The core architectural refactor (Phase 1) has been successfully implemented:
- New component boundaries established with explicit protocols
- Circular dependencies broken via protocol-based dependency injection
- Single canonical execution path for chat (Facade -> Router -> ExecutionEngine)
- Unified intent/control/capability routing
- SystemInitializer owns all startup/lifecycle
- MemoryCoordinator provides unified write facade

Remaining work is primarily Phase 2+ consolidation (Planners, Capability Registries, Self-Observation) and Phase 3 hardening (PersistenceLayer, Streaming Preemption, Event Schemas).


## Design Principles

1. **Single entry point** -- One AgentFacade for all external callers
2. **Single intent router** -- One UnifiedRouter for all classification/routing
3. **Single execution pipeline** -- One ExecutionEngine for all task execution
4. **Explicit interfaces** -- Protocols define boundaries; no circular deps
5. **Minimal disruption** -- Phase 1 extracts interfaces only; no behavior change

---

## Target Component Boundaries

### 1. AgentFacade (New) -- Public API
**File**: app/agent/facade.py (new)  
**Responsibility**: Sole public interface; orchestrates internal components

`python
class AgentFacade(Protocol):
    def chat(self, user_input: str) -> str: ...
    def execute_task(self, task: str, allow_mutations: bool = True) -> str: ...
    def get_status(self) -> AgentStatus: ...
    def shutdown(self) -> None: ...

@dataclass
class AgentStatus:
    is_executing: bool
    is_paused: bool
    active_plan_id: Optional[str]
    current_task: Optional[str]
    completed_tasks: int
    total_tasks: int
    chat_active: bool
    uptime_seconds: float
`

**Delegates to**:
- UnifiedRouter -- intent/control/capability classification
- ExecutionEngine -- plan + execute
- ConversationControlHandler -- stop/pause/resume/undo/redo/status
- ChatActivityProvider -- chat start/end signaling
- PriorityLLMProvider -- LLM access (via ExecutionEngine)

---

### 2. SystemInitializer (New) -- Startup Composition
**File**: app/core/initializer.py (new)  
**Responsibility**: Single-pass construction of all subsystems; breaks circular deps via protocols

`python
class SystemInitializer:
    def __init__(self, workspace: Path, config: Optional[SystemConfig] = None):
        self.workspace = workspace
        self.config = config or SystemConfig()
    
    def initialize(self) -> InitializedSystem:
        # 1. Infrastructure (no deps)
        event_bus = EventBus()
        job_service = BackgroundJobService(event_bus)
        observability = ObservabilityHub(event_bus)
        config_hot_reload = ConfigHotReload(event_bus)
        file_watcher = FileWatcher(event_bus)
        
        # 2. LLM + Priority (depends on infra)
        base_llm = LLM()
        priority_llm = PriorityLLMProvider(base_llm)
        
        # 3. Chat Activity Provider (depends on priority_llm)
        chat_activity = FreyaChatActivityProvider(priority_llm)
        
        # 4. Memory Coordinator (depends on workspace)
        memory_coordinator = MemoryCoordinator(workspace, event_bus)
        
        # 5. Tool Manager (depends on workspace)
        tool_manager = ToolManager(workspace)
        
        # 6. Unified Router (depends on memory, tools, priority_llm)
        unified_router = UnifiedRouter(
            memory=memory_coordinator,
            tools=tool_manager,
            llm=priority_llm,
            chat_activity=chat_activity,
        )
        
        # 7. Execution Engine (depends on router, tools, memory, priority_llm)
        execution_engine = ExecutionEngine(
            router=unified_router,
            tools=tool_manager,
            memory=memory_coordinator,
            llm=priority_llm,
            chat_activity=chat_activity,
        )
        
        # 8. Conversation Control (depends on execution_engine for callbacks)
        conversation_control = ConversationControlHandler(
            executor=execution_engine,
            plan_manager=execution_engine.plan_manager,
            memory=memory_coordinator.conversation_memory,
        )
        execution_engine.set_conversation_control(conversation_control)
        
        # 9. Agent Facade (composes all above)
        facade = AgentFacadeImpl(
            router=unified_router,
            execution=execution_engine,
            control=conversation_control,
            chat_activity=chat_activity,
            priority_llm=priority_llm,
            memory=memory_coordinator,
        )
        
        # 10. Optional: Autonomy (depends on facade via ExecutorProvider protocol)
        autonomy = None
        if self.config.enable_autonomy:
            autonomy = AutonomyManager(
                executor_provider=execution_engine,  # Protocol, not concrete
                router=unified_router,
                memory=memory_coordinator,
                chat_activity=chat_activity,
                priority_llm=priority_llm,
                event_bus=event_bus,
                job_service=job_service,
            )
        
        # 11. Optional: Orchestrator (depends on facade via protocols)
        orchestrator = None
        if self.config.enable_orchestrator:
            orchestrator = WorkflowOrchestrator(
                capability_registry=CapabilityRegistry(),
                router=unified_router,  # Same router instance
                executor=execution_engine,  # Protocol
                safety_gate=SafetyGate(),
                chat_activity=chat_activity,
                event_bus=event_bus,
                job_service=job_service,
            )
        
        return InitializedSystem(
            facade=facade,
            chat_activity=chat_activity,
            priority_llm=priority_llm,
            memory=memory_coordinator,
            execution=execution_engine,
            control=conversation_control,
            autonomy=autonomy,
            orchestrator=orchestrator,
            infra=InfrastructureBundle(
                event_bus=event_bus,
                job_service=job_service,
                observability=observability,
                config_hot_reload=config_hot_reload,
                file_watcher=file_watcher,
            )
        )
`

**Key**: No component holds ref to FreyaAgent; all cross-component deps are **protocols**.

---

### 3. FreyaAgent (Refactored) -- Thin Facade Impl
**File**: app/agent/facade_impl.py (new), app/agent/core_agent.py (deprecated)  
**Responsibility**: Implements AgentFacade; **< 500 lines**; zero subsystem instantiation

`python
class AgentFacadeImpl:
    def __init__(
        self,
        router: UnifiedRouter,
        execution: ExecutionEngine,
        control: ConversationControlHandler,
        chat_activity: ChatActivityProvider,
        priority_llm: PriorityLLMProvider,
        memory: MemoryCoordinator,
    ):
        self._router = router
        self._execution = execution
        self._control = control
        self._chat_activity = chat_activity
        self._priority_llm = priority_llm
        self._memory = memory
    
    def chat(self, user_input: str) -> str:
        self._chat_activity.chat_started()
        try:
            # Route through unified router
            route_result = self._router.route(user_input)
            if route_result.is_direct_answer:
                return self._answer_directly(user_input, route_result)
            elif route_result.is_clarification:
                return self._ask_clarification(user_input, route_result)
            elif route_result.is_control:
                return self._control.handle(route_result.control_command)
            else:
                return self._execute_engineering_task(user_input, route_result)
        finally:
            self._chat_activity.chat_ended()
    
    def execute_task(self, task: str, allow_mutations: bool = True) -> str:
        # Explicit engineering task entry (bypasses router)
        self._chat_activity.chat_started()
        try:
            return self._execution.execute_plan(task, allow_mutations)
        finally:
            self._chat_activity.chat_ended()
    
    def get_status(self) -> AgentStatus:
        return AgentStatus(
            is_executing=self._execution.is_executing,
            is_paused=self._control.is_paused,
            active_plan_id=self._execution.active_plan_id,
            current_task=self._execution.current_task_title,
            completed_tasks=len(self._execution.completed_tasks),
            total_tasks=len(self._execution.plan_tasks),
            chat_active=self._chat_activity.is_chat_active(),
            uptime_seconds=time.time() - self._start_time,
        )
    
    def shutdown(self) -> None:
        self._execution.shutdown()
        self._priority_llm.shutdown()
        # ... infra shutdown via event bus
`

**Removed from old FreyaAgent**:
- All 20+ subsystem instantiations
- build_context, _build_run_lessons_block, _build_run_experience_block
- start_autonomy, stop_autonomy, autonomy health checks
- Self-observation components (RA/SA/PD)
- WorldModel, ExternalRegistry, NetworkMonitor
- ConfigHotReload, FileWatcher
- ProjectIndex, SymbolIndex, DependencyGraph, FileLocator, LexicalSearch
- ReflectionEngine, DecisionManager, FailureRecovery, EvaluationManager

---

### 4. UnifiedRouter (New) -- Single Intent/Control/Capability Router
**File**: app/routing/unified_router.py (new)  
**Consolidates**: IntentClassifier, CapabilityRouter, ConversationalControlHandler (routing part)

`python
@dataclass
class RouteResult:
    # Classification
    intent: IntentType
    confidence: float
    reason: str
    
    # Routing decision
    is_direct_answer: bool
    is_clarification: bool
    is_control: bool
    is_engineering: bool
    control_command: Optional[ControlCommand]
    
    # Capability match (if any)
    capability_name: Optional[str] = None
    capability_confidence: float = 0.0

class UnifiedRouter:
    def __init__(
        self,
        memory: MemoryCoordinator,
        tools: ToolManager,
        llm: PriorityLLMProvider,
        chat_activity: ChatActivityProvider,
    ):
        self._intent_classifier = IntentClassifier()  # Reuse existing logic
        self._capability_router = CapabilityRouter()  # Reuse existing handlers
        self._control_parser = ControlCommandParser()  # Extract from ConversationalControlHandler
        self._memory = memory
        self._tools = tools
        self._llm = llm
        self._chat_activity = chat_activity
        
        # Register built-in capabilities
        self._register_builtin_capabilities()
    
    def route(self, user_input: str, context: Optional[Dict] = None) -> RouteResult:
        # 1. Check conversational control FIRST (short-circuits everything)
        control_cmd = self._control_parser.parse(user_input)
        if control_cmd:
            return RouteResult(
                intent=IntentType.CONVERSATIONAL_CONTROL,
                confidence=1.0,
                reason=Control command,
                is_control=True,
                control_command=control_cmd,
            )
        
        # 2. Classify intent
        classification = self._intent_classifier.classify(user_input, context)
        
        # 3. Check capability match for SYSTEM_STATUS and other direct routes
        if classification.intent in (IntentType.SYSTEM_STATUS, IntentType.CHAT, IntentType.QUESTION):
            cap_match = self._capability_router.find_matching(user_input, classification.intent.value)
            if cap_match:
                return RouteResult(
                    intent=classification.intent,
                    confidence=max(classification.confidence, cap_match[0][1]),
                    reason=fCapability: {cap_match[0][0]},
                    is_direct_answer=True,
                    capability_name=cap_match[0][0],
                    capability_confidence=cap_match[0][1],
                )
        
        # 4. Check clarification thresholds
        if classification.is_ambiguous or classification.should_clarify_engineering:
            return RouteResult(
                intent=classification.intent,
                confidence=classification.confidence,
                reason=classification.reason,
                is_clarification=True,
            )
        
        # 5. Direct answer for non-engineering
        if classification.should_answer_directly:
            return RouteResult(
                intent=classification.intent,
                confidence=classification.confidence,
                reason=classification.reason,
                is_direct_answer=True,
            )
        
        # 6. Engineering task
        return RouteResult(
            intent=classification.intent,
            confidence=classification.confidence,
            reason=classification.reason,
            is_engineering=True,
        )
    
    def execute_capability(self, capability_name: str, query: str, **context) -> CapabilityResult:
        return self._capability_router.route(query, capability_name=capability_name, **context)
`

**Key**: Single route() call returns complete routing decision; no multi-stage classification in callers.

---

### 5. ExecutionEngine (New) -- Single Execution Pipeline
**File**: app/execution/engine.py (new)  
**Consolidates**: Planner (agent), Executor (agent), PlanManager (planner/), VerificationRunner, RepairLoop

`python
class ExecutionEngine:
    def __init__(
        self,
        router: UnifiedRouter,
        tools: ToolManager,
        memory: MemoryCoordinator,
        llm: PriorityLLMProvider,
        chat_activity: ChatActivityProvider,
    ):
        self._router = router
        self._tools = tools
        self._memory = memory
        self._llm = llm
        self._chat_activity = chat_activity
        
        # Unified planning (merges agent Planner + planner/ PlanManager)
        self._planner = UnifiedPlanner(
            llm=llm,
            memory=memory,
            router=router,
            tools=tools,
        )
        
        # Unified execution (merges agent Executor + planner/ TaskExecutor)
        self._executor = UnifiedExecutor(
            planner=self._planner,
            tools=tools,
            memory=memory,
            llm=llm,
            verification=VerificationRunner(tools.workspace),
            repair=RepairLoop(),
        )
        
        # Conversation control callback
        self._conversation_control: Optional[ConversationControlHandler] = None
    
    def set_conversation_control(self, control: ConversationControlHandler):
        self._conversation_control = control
        self._executor.set_conversation_control(control)
    
    def execute_plan(self, task: str, allow_mutations: bool = True) -> str:
        # 1. Build context (unified retrieval)
        context = self._memory.retrieve_for_planning(task)
        
        # 2. Create plan (single planner)
        plan = self._planner.create_plan(task, context, allow_mutations)
        
        # 3. Human review (via conversation control)
        reviewed_plan = self._conversation_control.review_plan(plan, task)
        if reviewed_plan is None:
            return Plan cancelled.
        
        # 4. Execute with verification/repair
        results = self._executor.execute(reviewed_plan, allow_mutations)
        
        # 5. Final LLM summary
        return self._summarize_results(task, plan, results)
    
    def _summarize_results(self, task: str, plan, results) -> str:
        prompt = fTask: {task}\nPlan: {plan.summary()}\nResults: {results}\nSummarize for the user.
        return self._llm.ask(prompt, priority=LLMPriority.CHAT)
    
    # Properties for status
    @property
    def is_executing(self) -> bool: ...
    @property
    def is_paused(self) -> bool: ...
    @property
    def active_plan_id(self) -> Optional[str]: ...
    @property
    def current_task_title(self) -> Optional[str]: ...
    @property
    def completed_tasks(self) -> List[str]: ...
    @property
    def plan_tasks(self) -> List[Task]: ...
    
    def shutdown(self):
        self._executor.shutdown()
`

**UnifiedPlanner** merges:
- app/agent/planner.py Planner.create_plan()
- app/planner/plan_manager.py PlanManager + Plan + TaskGraph
- Single Task model, single dependency graph

**UnifiedExecutor** merges:
- app/agent/executor.py Executor.execute_plan()
- app/orchestrator/task_executor.py TaskExecutor.execute()
- Single checkpointing, single failure recovery path

---

### 6. MemoryCoordinator (New) -- Unified Memory Facade
**File**: app/memory/coordinator.py (new)  
**Responsibility**: Single write path; transactional; cache invalidation for UnifiedRetrieval

`python
class MemoryCoordinator:
    def __init__(self, workspace: Path, event_bus: EventBus):
        self._workspace = workspace
        self._event_bus = event_bus
        
        # Initialize all memory modules
        self._working = WorkingMemory()
        self._task = TaskMemory(workspace)
        self._long_term = LongTermMemory(workspace)
        self._episodic = EpisodicMemory(workspace)
        self._semantic = SemanticMemory(workspace)
        self._project = ProjectMemory(workspace)
        self._experience = ExperienceMemory(workspace)
        self._lessons = EngineeringLessonStorage(workspace)
        self._goals = GoalStorage(workspace)
        self._conversation = ConversationMemory(workspace)
        
        # Unified retrieval (read-only aggregation)
        self._retrieval = UnifiedRetrieval(
            working_memory=self._working,
            task_memory=self._task,
            long_term_memory=self._long_term,
            episodic_memory=self._episodic,
            semantic_memory=self._semantic,
            project_memory=self._project,
            experience_memory=self._experience,
            engineering_lessons=self._lessons,
            goal_memory=self._goals,
            conversation_memory=self._conversation,
        )
        
        # Consolidation/Forgetting engines (background)
        self._consolidation = ConsolidationEngine(self)
        self._forgetting = ForgettingEngine(self)
    
    # Single write entry points (transactional)
    def record_conversation(self, turn: ConversationTurn):
        self._conversation.add_turn(turn)
        self._event_bus.emit(memory.conversation.updated, {turn_id: turn.id})
    
    def record_task_execution(self, task_id: str, result: TaskResult):
        self._task.record_result(task_id, result)
        self._episodic.append(Event(type=task_execution, task_id=task_id, data=result))
        if result.lesson:
            self._lessons.add(result.lesson)
        self._event_bus.emit(memory.task.completed, {task_id: task_id})
    
    def add_fact(self, category: str, key: str, value: str, **meta):
        self._long_term.add(category, key, value, **meta)
        self._event_bus.emit(memory.long_term.added, {category: category, key: key})
    
    # Read delegation
    def retrieve_for_planning(self, query: str) -> str:
        return self._retrieval.retrieve_for_planner(query)
    
    def retrieve_for_execution(self, query: str) -> str:
        return self._retrieval.retrieve_for_execution(query)
    
    def retrieve(self, query: RetrievalQuery) -> List[RetrievalResult]:
        return self._retrieval.retrieve(query)
    
    # Properties for sub-module access (when needed)
    @property
    def conversation_memory(self): return self._conversation
    @property
    def working_memory(self): return self._working
    @property
    def goal_storage(self): return self._goals
    # ...
`

---

### 7. WorkflowOrchestrator (Refactored CentralOrchestrator)
**File**: app/orchestrator/workflow_orchestrator.py (renamed)  
**Responsibility**: Long-running workflows, capability lifecycle, background autonomy support -- NOT chat routing

`python
class WorkflowOrchestrator:
    def __init__(
        self,
        capability_registry: CapabilityRegistry,
        router: UnifiedRouter,           # Shared instance
        executor: ExecutionEngineProtocol,  # Protocol, not concrete
        safety_gate: SafetyGate,
        chat_activity: ChatActivityProvider,
        event_bus: EventBus,
        job_service: BackgroundJobService,
    ):
        self._capability_registry = capability_registry
        self._router = router            # For capability matching
        self._executor = executor        # For executing workflow steps
        self._safety_gate = safety_gate
        self._chat_activity = chat_activity
        self._event_bus = event_bus
        self._job_service = job_service
        
        # Workflow composer (uses router for capability resolution)
        self._workflow_composer = WorkflowComposer(
            registry=capability_registry,
            router=router,
        )
        
        # Self-observation (consolidated)
        self._self_observation = SelfObservationEngine(
            orchestrator=self,
            capability_registry=capability_registry,
            executor=executor,
            safety_gate=safety_gate,
        )
    
    def execute_workflow(self, spec: WorkflowSpec) -> str:
        Execute a pre-defined workflow (not user chat).
        workflow = self._workflow_composer.compose(spec)
        return self._executor.execute_workflow(workflow)
    
    def register_capability(self, capability: Capability) -> bool:
        return self._capability_registry.register(capability)
    
    def get_capability(self, name: str) -> Optional[Capability]:
        return self._capability_registry.get_capability(name)
    
    def start(self):
        self._capability_registry.start()
        self._self_observation.start()
        self._register_background_jobs()
    
    def stop(self):
        self._self_observation.stop()
        self._capability_registry.stop()
`

**Removed from old CentralOrchestrator**:
- Intent classification (delegates to UnifiedRouter)
- Memory retrieval (delegates to MemoryCoordinator via executor)
- Decision making (delegates to UnifiedRouter/ExecutionEngine)
- Conversation control (delegates to ConversationControlHandler)
- Chat pipeline (FreyaAgent handles chat)

---

## Interface Protocols (Break Circular Dependencies)

### File: app/core/protocols.py (new)

`python
from typing import Protocol, Optional, List, Dict, Any
from app.planner.task import Task

class ExecutorProvider(Protocol):
    Protocol for AutonomyManager to execute capabilities without FreyaAgent ref.
    def execute_capability(self, name: str, inputs: Dict[str, Any]) -> CapabilityResult: ...
    def get_available_capabilities(self) -> List[str]: ...
    def is_chat_active(self) -> bool: ...

class ChatActivityProvider(Protocol):
    Protocol for PriorityLLM, Autonomy, BG Jobs to yield to chat.
    def chat_started(self) -> None: ...
    def chat_ended(self) -> None: ...
    def is_chat_active(self) -> bool: ...
    def wait_for_chat_idle(self, timeout: float) -> bool: ...

class ExecutionEngineProtocol(Protocol):
    Protocol for Orchestrator to execute workflows.
    def execute_workflow(self, workflow: ComposedWorkflow) -> str: ...
    def execute_plan(self, task: str, allow_mutations: bool) -> str: ...

class MemoryProvider(Protocol):
    Protocol for read-only memory access.
    def retrieve_for_planning(self, query: str) -> str: ...
    def retrieve_for_execution(self, query: str) -> str: ...
    def get_active_goal(self) -> Optional[Goal]: ...
    def get_working_memory_snapshot(self) -> Dict[str, Any]: ...

class ToolProvider(Protocol):
    Protocol for tool execution.
    def execute(self, tool_name: str, args: Dict[str, Any]) -> ToolResult: ...
    def list_available(self, allow_mutations: bool) -> List[str]: ...
`

---

## Dependency Graph (Post-Refactor)

`
main.py
    |
    v
SystemInitializer.initialize()  -->  InitializedSystem
    |                                    |
    |                                    +--> AgentFacade (FreyaAgentImpl)
    |                                    |       |
    |                                    |       +--> UnifiedRouter
    |                                    |       +--> ExecutionEngine
    |                                    |       +--> ConversationControlHandler
    |                                    |       +--> ChatActivityProvider
    |                                    |       +--> PriorityLLMProvider
    |                                    |       +--> MemoryCoordinator
    |                                    |
    |                                    +--> AutonomyManager (optional)
    |                                    |       |
    |                                    |       +--> ExecutorProvider (protocol -> ExecutionEngine)
    |                                    |       +--> ChatActivityProvider (protocol)
    |                                    |       +--> UnifiedRouter (protocol)
    |                                    |       +--> MemoryProvider (protocol)
    |                                    |
    |                                    +--> WorkflowOrchestrator (optional)
    |                                            |
    |                                            +--> CapabilityRegistry
    |                                            +--> UnifiedRouter (shared instance)
    |                                            +--> ExecutionEngineProtocol (protocol)
    |                                            +--> SafetyGate
    |                                            +--> ChatActivityProvider (protocol)
    |                                            +--> SelfObservationEngine
`

**No cycles**: All cross-component edges point **down** or are **protocols**.

---

## Migration Strategy (Phase 1 -- No Behavior Change)

| Step | Action | Files Created | Files Modified |
|------|--------|---------------|----------------|
| 1.1 | Create protocols.py | app/core/protocols.py | -- |
| 1.2 | Create SystemInitializer | app/core/initializer.py | -- |
| 1.3 | Create AgentFacade protocol + AgentFacadeImpl | app/agent/facade.py, app/agent/facade_impl.py | main.py (use Facade) |
| 1.4 | Create UnifiedRouter | app/routing/unified_router.py | app/agent/core_agent.py (delegate) |
| 1.5 | Create MemoryCoordinator | app/memory/coordinator.py | app/agent/core_agent.py (delegate) |
| 1.6 | Create ExecutionEngine | app/execution/engine.py | app/agent/core_agent.py (delegate) |
| 1.7 | Refactor CentralOrchestrator -> WorkflowOrchestrator | app/orchestrator/workflow_orchestrator.py | app/orchestrator/orchestrator.py (deprecate) |
| 1.8 | Update AutonomyManager to use protocols | -- | app/long_term_autonomy/manager.py |
| 1.9 | Update main.py to use SystemInitializer | -- | main.py |

**Validation**: All existing tests pass; main.py chat loop works identically.

---

## File Map (Target State)

| Concern | File |
|---------|------|
| Public API | app/agent/facade.py (protocol), app/agent/facade_impl.py |
| Startup | app/core/initializer.py |
| Protocols | app/core/protocols.py |
| Routing | app/routing/unified_router.py |
| Execution | app/execution/engine.py, app/execution/planner.py, app/execution/executor.py |
| Memory | app/memory/coordinator.py |
| Orchestration | app/orchestrator/workflow_orchestrator.py, app/orchestrator/capability_registry.py |
| Autonomy | app/long_term_autonomy/manager.py (updated for protocols) |
| Self-Observation | app/self_observation/engine.py (consolidated) |
| Conversation Control | app/conversational_control.py (simplified to handler only) |
| Priority LLM | app/core/priority_llm.py (unchanged) |
| Infrastructure | app/core/events.py, app/core/background_jobs.py, app/core/observability.py |

---

## What Changes in Phase 2+ (Not in This Plan)

- Consolidate Planner implementations -> app/execution/planner.py
- Consolidate CapabilityRegistry + CapabilityRouter -> single registry with handlers
- Consolidate RuntimeAwareness + CentralizedSelfAnalysis + PredictiveDiagnostics -> SelfObservationEngine
- Add streaming preemption to PriorityLLMProvider
- Implement transactional PersistenceLayer for memory

---

## Acceptance Criteria for Phase 1

1. main.py starts and runs chat loop identically
2. All existing tests pass (no behavior changes)
3. No circular imports in dependency graph
4. FreyaAgent (facade impl) < 500 lines
5. WorkflowOrchestrator < 400 lines
6. Single UnifiedRouter handles all intent/control/capability routes
7. Single ExecutionEngine used by both Facade and Orchestrator
8. AutonomyManager uses ExecutorProvider protocol (no FreyaAgent ref)
9. EventBus emits system.initialized with component list
