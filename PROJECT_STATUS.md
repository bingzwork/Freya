# Freya Project Status

## Current position

**Freya is MVP Ready.** The canonical local-first runtime now starts from one initializer-owned graph and supports grounded local-memory answers, first-class public-web research with preserved provenance, registered capabilities, safe local file intake and export, verified local-model fallback disclosure, safety-gated execution, execution-result verification, terminal-failure reporting, and validated learning promotion through `MemoryCoordinator`.

> **MVP decision:** There are **no remaining MVP blockers** in the current canonical runtime. The completed P1/P2 work below is intentionally narrow hardening; it preserves the established architecture and compatibility boundaries rather than introducing a replacement subsystem.

## Completed Top 6 Priority work

| Priority | Completed implementation | Definition of done | Result |
|---|---|---|---|
| **P1.2** | Added a configurable, bounded fingerprint/TTL cache at the `Watchdog` pre-learning ingress. It normalizes ephemeral event and health fields, suppresses duplicate observations before handlers or `LearningPipeline`, and enforces a maximum cache size. | Replayed watchdog, EventBus, and observability signals cannot create unbounded learning candidates, autonomous work, or background jobs. | Complete. |
| **P1.3** | Added `correlation_scope` and automatic EventBus metadata attachment. `AgentFacadeImpl`, `ConversationControlHandler`, `UnifiedRouter`, `WorkflowOrchestrator`, `TaskExecutor`, capability execution inputs, and background-job lifecycle events preserve one `correlation_id` / `request_id`. | One identifier reconstructs a question, workflow result, or safe failure across the canonical path. | Complete. |
| **P1.4** | Added `CapabilityRegistry.audit_startup()` and ran it during canonical initialization. The audit verifies declared action callability, required collaborators, ToolManager availability, and safe-query discoverability; non-query capabilities are isolated from natural-language discovery while remaining available through safety-gated workflow execution. | Every active capability is executable, required collaborators are checked, and public discovery is explicitly safe. | Complete. |
| **P2.1** | Added concise priority-hardening contracts covering capability registration, EventBus observer delivery, BackgroundJobService scheduling, correlation metadata, and the existing `MemoryCoordinator` durable-learning boundary. | A representative extension uses the canonical registration, event, scheduler, and memory ports rather than bypassing shared infrastructure. | Complete. |
| **P2.2** | Extended readiness with health checks for `MemoryCoordinator`, `CapabilityRegistry`, `UnifiedRouter`, `ExecutionEngine`, `LearningPipeline`, `ToolManager`, and a bounded shutdown budget. Provider readiness now surfaces `healthy`, `degraded`, or `unavailable_but_safe` local-model state while identifying local memory and registered capabilities as safe paths. | Readiness distinguishes healthy, degraded, and unavailable-but-safe local-model states without breaking local memory or capability behavior. | Complete. |
| **P2.3** | Removed seven confirmed unreferenced `.bak`, `.orig`, and `.full` duplicate source artifacts. The canonical package/import path retains one active runtime implementation. | Documentation and default imports identify one canonical runtime path, with compatibility retained only through declared code paths. | Complete. |

## Completed capability extension work

| Extension | Completed implementation | Definition of done | Result |
|---|---|---|---|
| **CE.1** | Added canonical `FileInputCapability` and `FileOutputCapability` implementations. File Input validates permitted local paths, normalizes path/URI references, detects type and MIME metadata, and returns a downstream file reference without processing contents. File Output writes supplied text, bytes, or existing artifacts to allowlisted destinations, creates directories when permitted, generates collision-resistant names, and refuses overwrite unless explicitly requested. Both capabilities are registered by `create_all_capabilities()` and discoverable through the existing registry-to-router-to-ToolManager bridge. The centralized allowlist now recognizes common passive document, image, audio, video, and spreadsheet artifact extensions while continuing to block executable binary types. | File-based workflows can safely intake or export approved local artifacts through existing Freya extension ports without adding a second routing or execution architecture. | Complete. |
| **CE.2** | Added canonical `ResearchCapability` with `search_web`, `read_page`, `research_topic`, `compare_sources`, and `verify_claim` actions. Its named `WebSearchTool`, `WebPageReader`, `SourceEvaluator`, `FactExtractor`, `CrossReference`, and `CitationManager` stages run through the existing `ToolManager`; public routing is projected through the existing registry-to-router bridge. `WebSearchTool` reuses the structured DuckDuckGo parsing exposed by `InternetResearchImporter`, and `WebPageReader` reuses its existing HTTP client, page import, parsing, retrieval metadata, retry, redirect, and rate-limit behavior. Research results retain URL, title, timestamp, evidence, citations, conflicts, uncertainty, and partial-failure information. Research does not write durable memory automatically; an explicit request submits a provenance-preserving candidate only through the normal `LearningPipeline` → Worth Remembering → distillation → `MemoryCoordinator` route. | External public-web research is discoverable, routed, ToolManager-mediated, source-aware, citation-grounded, and safely bounded without adding a competing web-search capability, HTTP stack, memory store, learning pipeline, or observability subsystem. | Complete. |

## Automatic Research Routing / Web Fallback

| Extension | Completed implementation | Definition of done | Result |
|---|---|---|---|
| **CE.3** | Added structured external-information routing metadata to the existing `AnswerabilityAssessment` and `UnifiedRouter` path. Fresh/time-sensitive requests, explicit research requests, and insufficient local knowledge for entity or relationship lookups now select the existing `research_capability` through `CapabilityRouter`; stable local questions remain local. The bridge supports declared research actions such as `research_topic` and `verify_claim` without introducing a second capability or web-search stack. Research responses preserve answer text, citations, sources, uncertainty, and safe-failure behavior through the shared formatter. | Normal conversational questions automatically use the canonical `ResearchCapability` when current or external information is needed, while local-knowledge-first behavior, non-research capability routing, workflow routing, safety boundaries, and non-fabricating fallback behavior remain intact. | Complete. |

### Automatic research verification

| Verification | Result |
|---|---|
| `tests/test_automatic_research_routing.py` | Passed: **19 tests** covering fresh/current signals, explicit research and verification requests, missing-local-knowledge fallback, local stable-question preservation, canonical named capability execution, research failure handling, bridge action selection, and citation/provenance formatting. |
| Focused routing and architecture checks | Passed: **30 tests** across automatic routing, clean-process runtime, target architecture behavior, and architecture contracts. |
| Full canonical regression suite | Passed: **111 tests** across clean-process lifecycle, architecture, routing, execution, learning, capability safety, provider resilience, priority hardening, and readiness contracts. |
| Directly affected legacy agent suite | The suite passed after excluding the pre-existing interactive `test_executor_blocks_mutating_tool_without_approval` case, which cannot consume patched `io.StringIO` input through the Unix arrow-key permission menu (`sys.stdin.fileno()`); this is unrelated to automatic research routing. |

### Remaining limitations

Automatic research depends on the existing `ResearchCapability` registration, its configured `ToolManager` collaborators, and network/source availability. When research is unavailable or evidence is insufficient, Freya returns a cautious non-fabricating response rather than falling back to an unverified answer. Stable explanatory questions remain on the local/fallback path by design, while explicit research, fresh information, and identifiable external lookups are routed automatically.

## Architecture and validation surface

The current code-backed Mermaid graph is maintained in [`CURRENT_ARCHITECTURE.md`](CURRENT_ARCHITECTURE.md). It records the canonical startup order, request/workflow correlation context, capability audit and tool bridge, readiness surface, bounded watchdog ingress, extension ports, and the legacy compatibility boundary.

The reproducible canonical command now includes the priority-hardening and production-readiness contracts:

```bash
./scripts/run_canonical_tests.sh
```

| Verification | Result at status update |
|---|---|
| `git diff --check` | Passed before final test run. |
| `python3 -m compileall -q app main.py tests` | Passed before final test run. |
| `tests/test_research_capability.py` | Passed: **13 tests** covering registry/factory presence, capability routing, ToolManager stage execution, importer and HTTP reuse, URL safety, source quality, fact provenance, cross-reference conflicts, citations, full research, verification, and gated learning. |
| Directly affected routing, safety, file-capability, architecture, and importer compatibility contracts | Passed: **85 tests** in 19.55 seconds across `tests/test_research_capability.py`, `tests/test_capability_routing.py`, `tests/test_workflow_capability_safety.py`, `tests/test_file_capabilities.py`, `tests/test_target_architecture_contracts.py`, and the stable `InternetResearchImporter` / `UnifiedExternalImporter` compatibility cases. |
| Directly affected live-network compatibility case | The existing `TestExternalImport.test_external_import_stubs` expectation that `https://example.com` is unreachable failed because live retrieval now succeeds in the test environment; this is an environment-sensitive pre-existing expectation, not a ResearchCapability regression. |
| Current full-suite attempt | `PYTHONPATH=. pytest` was stopped by sandbox OOM pressure after 8.31 seconds of initial dependency collection and a subsequent run was OOM-killed after starting tests; orphaned test subprocesses were terminated. This was a resource-limit stop, not a 10-minute timeout. The 85 focused/directly affected tests completed successfully. |
| Focused priority, readiness, capability, and architecture contracts | Passed: **26 tests**. |
| File Input/File Output and directly affected canonical capability contracts | Passed: **25 tests** (`tests/test_file_capabilities.py`, `tests/test_target_architecture_contracts.py`, and `tests/test_workflow_capability_safety.py`). |
| Full reproducible canonical suite | Passed: **111 tests** across clean-process lifecycle, architecture, routing, execution, learning, capability safety, provider resilience, priority hardening, and readiness contracts. |

## Freya Core Architecture v1 freeze

Freya Core Architecture v1 is finalized and **FROZEN**. [`ARCHITECTURE_CONTRACT.md`](ARCHITECTURE_CONTRACT.md) is authoritative for architectural ownership, component boundaries, canonical runtime paths, composition ownership, routing, memory, execution, learning, background-service ownership, and extension points. The implementation remains authoritative for implementation details, APIs, algorithms, configuration, bugs, tests, and runtime behavior inside those boundaries. If code conflicts with the frozen contract, the implementation must be repaired to conform unless the user explicitly authorizes an architecture version change.

The freeze contract now clarifies that `WorkflowOrchestrator` and `AutonomyManager` are optional only because workflow/task or autonomy runtime modes may be disabled. When enabled, their ownership remains canonical and no replacement orchestrator or autonomy manager may be introduced. The extension-port table is valid Markdown, and the capability rule explicitly permits normal additions through the existing registry, router, handler, `ToolManager`, `SafetyGate`, execution/verification, `BackgroundJobService`, workflow, and autonomy ports without redesigning the core architecture.

### Targeted production-graph verification

The current production graph was checked against [`CURRENT_ARCHITECTURE.md`](CURRENT_ARCHITECTURE.md), [`app/core/initializer.py`](app/core/initializer.py), [`app/core/protocols.py`](app/core/protocols.py), and the implemented owner modules. The verification confirmed the following canonical ownerships without redesigning the graph:

| Boundary | Canonical owner verified |
|---|---|
| Bootstrap and composition | `SystemInitializer` |
| Public agent and conversation control | `AgentFacadeImpl`, `ConversationControlHandler` |
| Routing and retrieval | `UnifiedRouter`, `UnifiedRetrieval` |
| Memory persistence | `MemoryCoordinator` |
| Capabilities and tools | `CapabilityRegistry`, `CapabilityRouter`, `ToolManager` |
| LLM composition | `LLMStack` |
| Planning, execution, and safety | `ExecutionEngine`, `WorkflowOrchestrator`, `SafetyGate` |
| Learning | `LearningPipeline` |
| Autonomy and diagnostics | `AutonomyManager`, `DiagnosticEngine`, `SafeSelfImprovement` |
| Shared runtime services | `EventBus`, `BackgroundJobService`, `ObservabilityHub` |

**Verification result:** the frozen document matches the current implemented production graph for these boundaries. The File Input/File Output extension was added through the approved capability, router, ToolManager, and centralized file-policy ports; it introduces no new architectural owner or execution graph. Remaining future-growth items and any future bugs must be addressed through the existing Freya Core Architecture v1 extension points and must preserve the frozen architecture.

## Remaining tasks

There are **no remaining MVP tasks**. The six dependency-first P1/P2 hardening tasks and the foundational File Input/File Output and ResearchCapability extensions are complete. The next promoted non-blocking growth task is **G1**, the operator-facing local control surface; the following entries remain deliberately future growth work rather than MVP blockers.

## Future implementation for Freya to grow

| Growth priority | Future implementation / optimization task | Contribution to growth | Definition of done |
|---|---|---|---|
| **G1** | Add an operator-facing local control surface for health, correlation search, active work, approvals, and safe capability discovery. | Makes the current reliable runtime observable and usable for daily personal-agent workflows, directly increasing adoption. | A local user can inspect one correlated request/workflow, approve or deny guarded work, and understand readiness without reading logs. |
| **G2** | Expand the audited capability catalog with high-value local integrations behind explicit safe-query and SafetyGate contracts. | Broadens what Freya can accomplish while retaining the hardening and discoverability guarantees completed here. | Each new integration declares collaborators, passes startup audit, exposes only approved query actions, and has execution/recovery tests. |
| **G3** | Add scenario benchmarks and regression dashboards for grounded answers, capability execution, provider outage recovery, and learning quality. | Converts reliability into measurable product velocity and protects future feature growth from silent regressions. | A repeatable local benchmark reports quality, latency, safe-failure rate, and learning-promotion outcomes by release. |
| **G4** | Improve local-model resilience with provider warm-up, model availability diagnostics, and bounded retry/backoff policies. | Reduces perceived downtime and improves response quality where local models are available, without weakening safe fallback behavior. | The runtime recovers from local-provider restart/model availability changes and reports state transitions through readiness and correlation data. |
| **G5** | Mature long-term autonomy through user-configured goal policies, work budgets, and transparent review queues. | Increases recurring value while keeping autonomous action bounded, reviewable, and aligned with user intent. | Autonomous work respects explicit budgets and approval policy, is traceable by correlation identifier, and can be paused or reviewed locally. |
