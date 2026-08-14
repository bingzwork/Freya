# Freya Remaining-Work Roadmap

**Current Freya Completion: 60%**
**Remaining to 100%: 40%**
**Audit Basis: current codebase and verified runtime/test evidence**

> This is a capability-weighted estimate, not a historical task count. The canonical runtime starts and several focused production paths work, including retrieval integration, execution safety, workflow orchestration, user-control replies, and the canonical integration suite. However, the ordinary conversation lifecycle currently drops internally resolved answers, misroutes ordinary LLM fallbacks, never persists supported-facade exchanges, and can loop through the learning/improvement path. Those defects prevent a claim of end-to-end autonomous personal-AI operation.

| Capability area | Weight | Verified operational credit | Basis |
|---|---:|---:|---|
| Bootstrap and runtime composition | 10% | 7% | Canonical initializer starts, but normal package installation omits a required import dependency. |
| Conversation, local-first routing, and return paths | 25% | 10% | Control and legacy capability replies work; internal answers, capability resolver handling, LLM fallback, and exchange persistence are broken or disconnected. |
| Durable memory and retrieval | 15% | 13% | Focused production retrieval integration passes; the supported facade does not add new user/assistant turns. |
| Task execution, safety, verification, and repair | 15% | 14% | Execution safety state-machine tests pass. |
| Learning, distillation, and safe self-improvement | 15% | 6% | Learning storage works, but real event-driven promotion calls a non-existent safety-gate method and derived memory events can re-enter learning. |
| Autonomy and background work | 10% | 8% | Workflow and autonomy integration tests pass, subject to the learning-loop blocker. |
| Provider readiness and diagnostics | 5% | 4% | Health accurately reports an unavailable Ollama server, but affected fallback routing cannot return a safe answer. |
| Local capabilities, tools, and observability | 5% | 5% | Local capability and focused observability/control tests pass. |

---

## Task 1 — Restore the canonical conversation lifecycle from local resolution to a persisted user-visible answer

**Priority:** P0 — prevents Freya from functioning correctly
**Size:** Medium
**Dependency:** None

### Problem

The supported `AgentFacadeImpl.chat()` path does not preserve the `ResolutionResult` produced by `KnowledgeFirstResolver`. When the resolver finds an internal-memory answer, `UnifiedRouter.route()` creates a `RouteResult` containing only route metadata; `ResolutionResult.answer` is discarded. The facade therefore invokes the LLM instead of returning the locally resolved answer. When resolution requires an LLM, the router marks it as `is_engineering=True`, causing the facade to send an ordinary question to `ExecutionEngine.execute_plan()` rather than using the resolver's prepared LLM prompt, priority, context, and answer-verification path.

The same boundary also fails to persist either the user message or final assistant result. `MemoryCoordinator.record_conversation()` is the canonical durable write API, but no supported production caller invokes it. Consequently, successful conversation-memory retrieval tests do not establish that normal user conversations become future recallable knowledge.

### Evidence

- `app/routing/knowledge_first_resolver.py:108-121` returns `ResolutionResult(action="answer", answer=...)`; `app/routing/unified_router.py:200-206` drops that answer when constructing `RouteResult`.
- `app/routing/unified_router.py:216-224` maps `llm_fallback` to an engineering route; `app/agent/facade_impl.py:58-62,181-183` therefore calls task execution instead of answer fallback.
- `app/agent/facade_impl.py` contains no call to `record_conversation()` or `ConversationMemory.add_message()`; a repository search finds `record_conversation()` only in `app/memory/coordinator.py` and its protocol.
- `app/routing/knowledge_first_resolver.py:135-137` expands `**context` although its default is `None`. A real CLI smoke request, `python3 main.py --no-autonomy --no-orchestrator --no-file-watcher --no-observability 'what capabilities do you have?'`, logged `CapabilityRouter.route() argument after ** must be a mapping, not NoneType` and fell back to legacy routing.

### Required implementation

Create one explicit, typed handoff from `KnowledgeFirstResolver` through `UnifiedRouter` to `AgentFacadeImpl`. `RouteResult` must retain the resolved answer, LLM prompt, priority, context, and any already-executed capability result required by the facade. Return a local answer directly when it is available. For `llm_fallback`, call the prepared LLM fallback through `AnswerVerifier` rather than task execution, preserving the resolver context and priority. Normalize optional context to an empty mapping before capability routing, and make capability execution occur exactly once.

After every supported chat outcome, durably record the user input and the final returned assistant response through `MemoryCoordinator.record_conversation()`. Preserve control semantics and avoid writing a fabricated assistant response when processing raises an exception.

### Likely files

- `app/routing/unified_router.py`
- `app/routing/knowledge_first_resolver.py`
- `app/agent/facade_impl.py`
- `app/memory/coordinator.py`
- Focused new or revised tests under `tests/`

### Completion criteria

A normal chat request follows this contract: local memory answer → verified return without an LLM call; unavailable local knowledge → local capability once when applicable; otherwise prepared LLM fallback → answer verification → safe user-visible failure if no provider can answer. Both sides of every successful supported exchange survive a fresh process reconstruction and are retrievable by `UnifiedRetrieval`.

### Focused verification

- Add facade-level tests using the real `UnifiedRouter`/`KnowledgeFirstResolver` boundary for internal answer, no-context capability, LLM fallback, and exhausted-provider safe failure.
- Add a restart integration test that calls `FreyaApp.chat()` twice, reconstructs the app, and retrieves both persisted turns through the coordinator's `UnifiedRetrieval`.
- Re-run `python3 -m pytest -q tests/test_production_retrieval_integration.py tests/test_user_communication.py` plus the new route/facade tests.
- Re-run the capability CLI smoke command above with no resolver exception and no unexpected engineering-plan route.

---

## Task 2 — Make learning-to-self-improvement safe, bounded, and compatible with the safety-promotion API

**Priority:** P0 — prevents Freya from functioning correctly
**Size:** Medium
**Dependency:** Task 1 may be implemented independently; both tasks are required before autonomous operation is dependable.

### Problem

Normal startup enables `SafeSelfImprovementEngine`. Its real promotion path invokes `SafetyPromotionGates.evaluate(candidate, execution_result)`, but that class exposes `evaluate_promotion(PromotionContext)`, not `evaluate`. A learning candidate that reaches the event-driven improvement path therefore emits repeated `PatchPromotionManager` errors rather than receiving a sound safety decision.

The autonomy watchdog subscribes to `memory.*` and only excludes `memory.experience_stored`. Canonical durable learning writes also emit derived `memory.cross_reference_added` and `memory.node_added` events. Those events are turned back into watchdog observations and queued as new learning candidates, creating a feedback path that can continually re-enter learning and improvement. The real durable-learning test did not complete within two focused 120–180 second runs and continuously logged the promotion interface error.

### Evidence

- `app/safe_self_improvement/promotion.py:274-280` calls the absent `SafetyPromotionGates.evaluate()` method.
- `app/core/safety_gates.py:407-454` defines the actual public entry point, `evaluate_promotion(context)`.
- `app/safe_self_improvement/self_improvement.py:541-563` synchronously converts every `learning.improvement_candidate` event into an auto-executed improvement candidate.
- `app/autonomy/models.py:72-74` subscribes the watchdog to `memory.*`; `app/autonomy/watchdog.py:121-130` filters only `memory.experience_stored`.
- `app/memory/cross_references.py:470-507` emits `memory.cross_reference_added` and `memory.node_added` during canonical memory writes.
- Running `python3 -m pytest -vv -s tests/test_task11_autonomous_learning.py::test_background_learning_handoff_reaches_durable_memory` timed out after 120 seconds while repeatedly logging `Promotion error: 'SafetyPromotionGates' object has no attribute 'evaluate'`.

### Required implementation

Adapt the promotion manager to construct the documented `PromotionContext`, call `SafetyPromotionGates.evaluate_promotion()`, and translate its result into the promotion manager's own decision/result contract without conflating similarly named models. Treat unavailable or malformed safety evidence as a rejection or human-review state; never silently promote.

Restrict watchdog ingestion to operational events that represent new observations, or explicitly exclude every memory-persistence and self-generated learning/improvement event. Add deduplication and bounded back-pressure for observation-to-learning submission so an internal event cycle cannot grow the queue indefinitely. The real learning-event handler must be tested without replacing `submit_improvement()` with a recording stub.

### Likely files

- `app/safe_self_improvement/promotion.py`
- `app/safe_self_improvement/self_improvement.py`
- `app/core/safety_gates.py`
- `app/autonomy/watchdog.py`
- `app/autonomy/models.py`
- `tests/test_task11_autonomous_learning.py`
- `tests/test_shared_event_improvement_flow.py`

### Completion criteria

A durable learning item may create an improvement proposal, but it cannot create an unbounded sequence of new learning candidates or promotion attempts. The proposal receives a real safety decision and remains rejected/deferred/review-required unless all documented safety stages pass. Shutdown completes promptly after the background-learning handoff.

### Focused verification

- Add an integration test using the real learning pipeline, event bus, watchdog, and self-improvement engine; assert a bounded number of candidates/events and no repeated promotion exceptions.
- Add unit tests for approved, rejected, and malformed safety-promotion inputs through the corrected adapter.
- Run `python3 -m pytest -q tests/test_task11_autonomous_learning.py tests/test_shared_event_improvement_flow.py tests/test_learning_pipeline.py` and enforce a short test timeout appropriate to the test duration.

---

## Task 3 — Declare every unconditional bootstrap dependency in the installable package

**Priority:** P1 — required for dependable end-to-end autonomous operation
**Size:** Small
**Dependency:** None

### Problem

A clean installation from the project metadata cannot import the canonical initializer. `app.core.__init__` eagerly imports `app.core.file_watcher`, which imports `watchdog`, but `watchdog` is absent from `pyproject.toml` dependencies. The audit environment had to install it separately after `pip install -e '.[dev]'` before current-production tests could collect.

### Evidence

- `pyproject.toml:6-17` lists runtime dependencies but omits `watchdog`.
- `app/core/__init__.py` eagerly exposes the file watcher, and `app/core/file_watcher.py` imports `watchdog.events`.
- Before manual installation, focused test collection failed with `ModuleNotFoundError: No module named 'watchdog'` while importing `main` → `app.core.initializer`.

### Required implementation

Add the compatible `watchdog` version range to the project runtime dependencies. Review only other imports required by the canonical `main.py` → `SystemInitializer` path and declare any similarly unconditional dependency that is missing; do not add dependencies solely for disconnected legacy modules. Keep `requirements.txt` and install metadata consistent if both remain supported installation interfaces.

### Likely files

- `pyproject.toml`
- `requirements.txt` only if required for consistency
- A focused packaging/import test or CI command

### Completion criteria

A clean environment can install the documented runtime plus development extras and collect/import the canonical bootstrap without manually installing an undeclared package.

### Focused verification

- Create a clean virtual environment or equivalent isolated install of `.[dev]`.
- Run `python -c 'import main; from app.core.initializer import SystemInitializer'` and `python -m pytest -q tests/test_production_health_readiness.py` in that environment.

---

## Dependency order

| Order | Task | Why it comes next |
|---:|---|---|
| 1 | Task 1 | Restores the user-facing local-memory-first conversation lifecycle and persistent recall. |
| 2 | Task 2 | Prevents autonomous learning/improvement feedback loops and makes safety-promotion decisions real. |
| 3 | Task 3 | Makes the repaired canonical runtime reproducibly installable. |

> No historical completion summaries, optional enhancements, or disconnected legacy cleanup are included. The items above are the verified work still required for a dependable autonomous Freya under the current architecture.

## Verification record from this audit

| Check | Result |
|---|---|
| `python3 -m pytest -q tests/test_production_health_readiness.py tests/test_llm_stack.py` | Passed: 19 tests. |
| `python3 -m pytest -q tests/test_production_retrieval_integration.py` | Passed: 3 tests. |
| `python3 -m pytest -q tests/test_execution_safety_state_machine.py` | Passed: 8 tests. |
| `python3 -m pytest -q tests/test_workflow_orchestrator.py` | Passed: 2 tests. |
| `python3 -m pytest -q tests/test_user_communication.py` | Passed: 20 tests. |
| `python3 -m pytest -q tests/test_integration_autonomous.py` | Passed: 10 tests. |
| `python3 -m pytest -q tests/test_shared_event_improvement_flow.py` | Passed: 6 tests, but the suite stubs the real `submit_improvement()` call at lines 40–44 and therefore does not exercise promotion. |
| Focused batch of seven production modules | Stopped after 580 seconds; this was not a full-suite result and was isolated rather than treated as a product failure by itself. |
| `tests/test_task11_autonomous_learning.py::test_background_learning_handoff_reaches_durable_memory` | Stopped after 120 seconds; repeated live `SafetyPromotionGates.evaluate` attribute errors identified Task 2. |
| CLI capability smoke test | Bootstrap succeeded after manual dependency installation; logged the null-context resolver exception identified in Task 1. |

## Full-suite status

No new full-suite run was started. The prior documentation records a full-suite timeout, and the audit used targeted tests as required. The combined focused run was stopped after 580 seconds to isolate the durable-learning hang; it must not be read as a passing aggregate suite.

---

**Status document purpose:** this file is the execution roadmap from the current codebase to a functionally complete Freya. It contains only unresolved, mandatory work.
