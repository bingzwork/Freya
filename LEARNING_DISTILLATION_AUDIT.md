# Learning Distillation Reliability Audit

**Project:** Freya  
**Scope:** End-to-end learning distillation reliability and local-first reuse  
**Date:** 2026-08-19  
**Author:** Manus AI  
**Final implementation status:** Working with non-blocking limitations, pending final commit and push

## Executive summary

Freya's learning foundation now supports the complete production-path loop: a verified experience is represented as a structured learning candidate, distilled into an operational lesson, persisted through the existing memory coordinator and local stores, recovered after restart, injected into planning and retrieval context, and consumed locally before unnecessary model fallback. The implementation repairs existing links in place and does not create a public `distillation` capability, replace the architecture, perform neural-network distillation, or disable safety verification.

The last regression was found outside the learning-validation gate. Task-level execution safety was calling `_request_identity()` on `UnifiedExecutor`, but that helper and its request-context handoff existed only on `ExecutionEngine`. The result was a fail-closed safety denial before execution verification. `UnifiedExecutor` now receives the canonical request context and contributes the same trace, correlation, request, session, source, and channel identity fields to task-level SafetyGate checks. The previously failing public integration test passes after this minimal repair.

The learning-distillation acceptance tests pass, the previously failing public verified-task integration test passes, and the affected reliability suite reaches 100% with one expected skip and no failure. The implementation is therefore reliable for the intended MVP behavior. The remaining limitations are honest capability boundaries rather than blockers: engineering-lesson similarity uses token overlap when semantic similarity is unavailable, lessons are marked stale rather than automatically expired, and there is no automatic external knowledge refresh.

## Architecture discovered

The implementation uses the existing learning and memory foundation rather than a parallel subsystem. The eight production stages are as follows.

| Stage | Existing component | Reliability responsibility |
|---|---|---|
| 1 | `LearningPipelineCapability` in [`app/orchestrator/capabilities.py`](app/orchestrator/capabilities.py) | Exposes the existing `store_lesson` action and passes structured lesson fields into the learning pipeline. |
| 2 | `LearningCandidate` and `LearningCandidateType` in [`app/learning/models.py`](app/learning/models.py) | Carries source component, session, raw observation, context, tags, provenance, and candidate type. |
| 3 | `LearningPipeline` in [`app/learning/pipeline.py`](app/learning/pipeline.py) | Extracts structured title/content, filters sensitive or hidden reasoning content, validates verification state, and assigns a final decision. |
| 4 | Existing distillers, including `SkillDistiller` | Converts verified procedural experience into an operational lesson with capability, action, argument schema, validation, and safety requirements. |
| 5 | `MemoryCoordinator` in [`app/memory/coordinator.py`](app/memory/coordinator.py) | Applies promotion policy, conflict handling, user-correction authority, provenance, and writes to the appropriate durable memory store. |
| 6 | Engineering-lesson and semantic memory stores | Persist lessons and knowledge locally, deduplicate equivalent evidence, and retain reinforcement and evidence identifiers. |
| 7 | `UnifiedRetrieval` in [`app/memory/unified_retrieval.py`](app/memory/unified_retrieval.py) | Retrieves lessons and semantic knowledge, exposes operational metadata, and marks temporally stale semantic entries. |
| 8 | `KnowledgeFirstResolver` and `UnifiedPlanner` in [`app/routing/knowledge_first_resolver.py`](app/routing/knowledge_first_resolver.py) and [`app/execution/engine.py`](app/execution/engine.py) | Reuses verified local knowledge before model fallback and supplies learned capability and safety context to future planning. |

Execution verification remains upstream of successful positive learning. `ExecutionVerifier` creates an `EXECUTION_OUTCOME` candidate with `verification_status` and `execution_success`; the learning pipeline allows verified success, retains failed execution only as negative experience, and blocks unverified positive promotion. SafetyGate remains authoritative before task execution and is not bypassed by learned procedures.

## Gaps found and repairs made

| Gap | Repair | Result |
|---|---|---|
| `store_lesson` supplied mostly generic telemetry, so the real lesson title and operational content could be lost. | Structured title, description/content, category, tags, and metadata are passed through the existing raw-observation contract. | Verified procedures are distilled with usable skill metadata. |
| Learning extraction did not reliably distinguish explicit structured lessons from generic observations. | `_extract_learning` now short-circuits for explicit title/content and retains the generic path for execution telemetry. | Public lessons and verifier outcomes use the correct extraction path. |
| Sensitive values and hidden reasoning could enter promotion. | Added sensitive/hidden-trace rejection for credentials, API keys, passwords, and private chain-of-thought-style fields. | Such candidates receive a negative final decision and are not written to learning stores. |
| Unverified structured lessons could be promoted as skills. | Structured lessons are blocked unless verification metadata is explicitly verified. | Unverified model output cannot become a trusted procedure. |
| Failed verified execution had no useful negative-learning path. | Failed execution is retained only as negative experience and is excluded from engineering lessons. | Failures can inform improvement without becoming successful skills. |
| Weak conflicting knowledge could overwrite stronger knowledge. | `MemoryCoordinator` rejects lower-confidence conflicts and records the rejection. | Stronger verified knowledge is retained. |
| User correction lacked authority over prior learned knowledge. | Explicit user-correction metadata is treated as authoritative. | User correction replaces the prior fact. |
| Temporal metadata was not consistently preserved or surfaced. | Observation, validity, and temporal-scope metadata survive distillation; retrieval marks expired semantic knowledge as stale. | Time-sensitive knowledge is not silently presented as current. |
| Engineering-lesson retrieval depended too heavily on semantic similarity availability. | Added token-overlap fallback for lesson retrieval. | Local lesson reuse remains functional without a vector-search backend. |
| Learned skill metadata was not visible enough to planning and safety-aware reuse. | Retrieval content now exposes capability, action, validation, argument schema, and safety requirement. | Future planning can use the lesson without weakening SafetyGate. |
| A regression caused task-level safety checks to fail before execution verification. | Added request-context storage and `_request_identity()` to `UnifiedExecutor`; `ExecutionEngine` now hands context to and clears it from the executor. | The public verified execution path completes and reaches learning verification again. |

## Twenty acceptance gates

The table below consolidates the twenty required pasted17 acceptance requirements. The permanent regression file contains twelve focused tests, while the remaining gates are exercised by those tests plus the runtime, routing, lifecycle, and autonomous integration tests.

| # | Acceptance requirement | Evidence | Result |
|---:|---|---|---|
| 1 | A verified experience creates a distilled lesson. | `test_public_store_lesson_distills_verified_procedure_with_operational_metadata`; public verifier integration. | **PASS** |
| 2 | The lesson retains operational capability and action metadata. | `capability=file_output`, `action=write`, argument schema, validation, and safety requirement assertions. | **PASS** |
| 3 | The lesson persists across a real memory restart. | Restarted `MemoryCoordinator` retrieves the same lesson identifier. | **PASS** |
| 4 | Persisted knowledge reaches planner context. | Planner context contains `file_output`, `SafetyGate`, and validation text after restart. | **PASS** |
| 5 | Future local retrieval reuses learned knowledge before model fallback. | `KnowledgeFirstResolver` returns `answer`, marks `local_knowledge_reuse`, and suppresses model fallback. | **PASS** |
| 6 | Equivalent lessons deduplicate instead of creating memory spam. | Repeated lesson storage leaves exactly one engineering lesson. | **PASS** |
| 7 | Concurrent equivalent lessons remain deduplicated. | Four concurrent writes leave one lesson with reinforced evidence. | **PASS** |
| 8 | Failed execution is not promoted as a successful skill. | Failed `EXECUTION_OUTCOME` produces experience but no engineering lessons and no positive outcome metadata. | **PASS** |
| 9 | Unverified structured model output is not promoted. | `verified=False` and `verification_status=unknown` produce no engineering lesson. | **PASS** |
| 10 | Sensitive data and hidden reasoning are rejected. | Credential, API-key, and hidden-trace candidate stores nothing in semantic, experience, or engineering-lesson stores. | **PASS** |
| 11 | Explicit user correction overrides weaker or older knowledge. | `user_correction=True` replaces the prior codename. | **PASS** |
| 12 | Weak conflicting evidence cannot overwrite stronger evidence. | Lower-confidence model inference is retained only as a conflict rejection. | **PASS** |
| 13 | Provenance identifies the distiller and evidence lineage. | Lesson context contains `distiller=SkillDistiller` and evidence identifiers. | **PASS** |
| 14 | Confidence remains bounded and evidence-aware. | Distilled lesson confidence is bounded at or below the expected conservative value and reinforcement is tracked separately. | **PASS** |
| 15 | Temporal metadata survives distillation and restart. | `observed_at`, `valid_until`, and `temporal_scope` survive persistence. | **PASS** |
| 16 | Expired temporal knowledge is visibly marked stale. | Retrieval metadata contains `stale=True`, temporal validity, and `STALE` content marker. | **PASS** |
| 17 | Learned skill metadata supports safe procedural reuse. | Retrieval exposes validation, argument schema, capability/action, and the SafetyGate requirement. | **PASS** |
| 18 | Learning influences routing and planning rather than only storage. | Knowledge-first resolver consumes the lesson locally; planner context includes the lesson. | **PASS** |
| 19 | SafetyGate remains authoritative for learned procedures. | Task-level safety call remains before execution; the request-identity regression was repaired without bypassing or weakening the gate; public verified-task integration passes. | **PASS** |
| 20 | Storage growth is stable under repetition and the end-to-end loop reduces unnecessary model dependence. | Deduplication and reinforcement assertions pass; local-first resolver does not call the model on a learned hit. | **PASS** |

## Real learn–restart–reuse proof

The real `FreyaApp` restart probe completed successfully in two separate processes. The write process returned `WRITE_EXIT=0`, produced a positive decision, stored lesson identifier `lesson_d7391e538404`, and reported one engineering lesson. The read process returned `READ_EXIT=0`, recovered one lesson after restart, and produced planner context containing `=== Engineering Lessons ===` with the `file_output`, `SafetyGate`, and verification content. This proves durable local persistence and post-restart retrieval rather than an in-memory-only mock.

The focused acceptance test independently verifies the same durability contract using a fresh `MemoryCoordinator` after the first coordinator is discarded. The recovered lesson identifier matches the original identifier, and the planner context includes its operational safety metadata.

## Skill reuse proof

The verified procedure is stored as an engineering lesson through the existing `SkillDistiller`. The lesson includes the capability `file_output`, action `write`, an argument schema for `path` and `content`, validation instructions to read and compare the file, and the requirement that SafetyGate approval remains required. A subsequent knowledge-first request returns the learned procedure locally, marks `local_knowledge_reuse=True`, marks `model_fallback_suppressed=True`, and does not call the LLM stack.

## Rejection proof

Failed execution is not silently converted into success. A failed execution candidate is allowed only as negative experience; it does not create an engineering lesson and no stored experience is marked positive. Unverified structured lessons are not promoted. Sensitive values and hidden reasoning fields are filtered before any memory write, and the focused test confirms all three relevant stores remain empty for the rejected candidate.

## Persistence and safety proof

Positive learning still requires verified execution evidence. The pipeline's validation gate accepts `verification_status=verified` and `execution_success=True`, while rejecting unknown, unverified, failed, rejected, and false verification states for positive structured lessons. Failed execution has an explicit negative-experience exception and does not enter the successful skill store.

SafetyGate remains in the execution path before task execution. The final regression repair only restores the request identity expected by that existing gate. It does not turn off the gate, auto-approve a task, or treat a learned procedure as an authorization. The verified public task integration now returns `The requested read completed and verification passed.` and records successful learning after verification.

## Verification performed

| Verification scope | Result |
|---|---|
| `test_pasted17_learning_distillation.py` | 12 passed, including three previously confirmed stable runs. |
| `test_learning_distillation_runtime.py` | Passed. |
| `test_shared_event_improvement_flow.py` | Passed. |
| `test_knowledge_first_routing_regressions.py` | Passed. |
| `test_target_architecture_behavior.py` | Passed. |
| `test_integration_autonomous.py::test_public_task_success_is_safety_checked_verified_learned_and_persisted` | Passed after the `UnifiedExecutor` request-identity repair. |
| Combined affected foundation, autonomy, learning, routing, communication, lifecycle, and autonomous integration suite | Reached 100% with one expected skip and no failures. An expected test log reports a deliberately failing background job; the test itself passed. |
| Python compilation of `app/execution/engine.py` | Passed. |
| Real two-process `FreyaApp` restart proof | `WRITE_EXIT=0`; `READ_EXIT=0`. |

## Files changed for pasted17

| File | Purpose |
|---|---|
| [`app/orchestrator/capabilities.py`](app/orchestrator/capabilities.py) | Structured `store_lesson` metadata propagation and the previously repaired planning capability context link. |
| [`app/learning/pipeline.py`](app/learning/pipeline.py) | Structured extraction, sensitive/hidden-trace filtering, verification gate, and negative execution experience handling. |
| [`app/memory/coordinator.py`](app/memory/coordinator.py) | Weak-conflict rejection and user-correction authority. |
| [`app/memory/unified_retrieval.py`](app/memory/unified_retrieval.py) | Engineering-lesson token-overlap fallback, operational metadata exposure, and temporal stale marking. |
| [`app/routing/knowledge_first_resolver.py`](app/routing/knowledge_first_resolver.py) | Local learned-knowledge hit before LLM fallback for stable explanations. |
| [`app/execution/engine.py`](app/execution/engine.py) | Minimal regression repair: request-context handoff and identity helper for `UnifiedExecutor` task-level safety checks. |
| [`tests/test_pasted17_learning_distillation.py`](tests/test_pasted17_learning_distillation.py) | Permanent pasted17 learning-distillation acceptance tests. |
| [`LEARNING_DISTILLATION_AUDIT.md`](LEARNING_DISTILLATION_AUDIT.md) | This audit. |

The temporary probe and failure-log files were removed before final review. No separate public distillation capability was added, and no neural-network training or model fine-tuning was performed.

## Remaining limitations

| Limitation | Plain-English meaning | Impact classification | MVP blocker? |
|---|---|---|---|
| No vector similarity backend for engineering lessons | Lesson retrieval does not currently use a dedicated embedding index. It uses the implemented token-overlap fallback when semantic similarity is unavailable. | Future development and retrieval quality; normal operation remains functional for clear lexical matches. | **No** |
| Lessons are marked stale but not automatically expired or deleted | Freya visibly labels time-sensitive knowledge as stale, but it does not run a background expiry job that removes or quarantines it automatically. | Memory and temporal-safety enhancement; callers can see the stale marker and should reverify before acting. | **No** |
| No automatic external knowledge refresh | A stored lesson does not independently revisit the public web or external systems to determine whether its procedure changed. | Future development and knowledge freshness. | **No** |
| Local-first reuse depends on a sufficiently matching request | The current fallback is strongest when the future request shares meaningful terms with the stored lesson. | Retrieval quality and future development, not core storage or safety. | **No** |
| Runtime/provider capabilities remain environment-dependent | External browser, image-search, or provider-specific actions can still depend on credentials, network access, or an available local provider. | Capabilities and environment integration; unrelated to the correctness of local learning distillation. | **No** |

These limitations are intentionally not hidden. None prevents verified learning, durable persistence, restart recovery, safe reuse, rejection of unsafe evidence, or SafetyGate authority in the intended MVP path.

## Final verdict

> **LEARNING DISTILLATION FULLY RELIABLE for the intended MVP production path, with non-blocking limitations documented above.**

The answer to the central question is **YES**: Freya's existing learning foundation is now wired end-to-end for verified experience, structured lesson distillation, durable local knowledge, restart recovery, local-first retrieval, safe planning influence, deduplication, conflict handling, temporal marking, and rejection of failed, unverified, sensitive, or hidden-trace content.

## References

[1]: app/learning/pipeline.py "LearningPipeline implementation"
[2]: app/memory/coordinator.py "MemoryCoordinator implementation"
[3]: app/memory/unified_retrieval.py "Unified retrieval implementation"
[4]: app/routing/knowledge_first_resolver.py "Knowledge-first resolver implementation"
[5]: app/execution/engine.py "Canonical execution engine and UnifiedExecutor"
[6]: app/orchestrator/capabilities.py "Public capability adapters"
[7]: tests/test_pasted17_learning_distillation.py "Pasted17 permanent acceptance tests"
[8]: tests/test_integration_autonomous.py "Autonomous execution integration tests"
