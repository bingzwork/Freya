# Freya Reliability Audit — pasted_content_16

## Scope and conclusion

This audit covers Freya’s local production installation after the capability, routing, vision, planning, research, and observability repairs. The existing foundation and autonomy hardening from pasted_content_15 was preserved. The audit did not add a second router, memory system, learning system, provider, or capability implementation.

The current local result is **reliability maturity Level 4 for locally supportable day-to-day operation**, with explicit provider and environment limitations. It is not Level 5 because the complete repository suite is disproportionately slow in this Windows environment and was stopped during the final bounded run at approximately 2% after more than five minutes; the focused suites are green, but the full-suite requirement therefore remains an evidence limitation rather than an unexplained test failure. Autonomy remains disabled by default.

## Evidence summary

| Area | Result |
|---|---|
| Foundation | Prior pasted15 foundation audit and focused regression suite remain valid. |
| Capability registration | All 42 expected capabilities are registered, callable, and reachable through the canonical registry-to-router bridge. |
| Natural-language routing | Baseline `42/42` and expanded `210/210` matrix pass. The expanded matrix contains five realistic variants per capability. |
| Capability/provider suites | Focused capability, provider, HTTP, research, vision, planning, database, browser, simulation, and safety groups pass. |
| Failure injection | Safety denial, approval-required behavior, unavailable provider, verification timeout, and malformed/invalid input tests pass in the pasted15 and pasted16 focused groups. |
| Learning/distillation | Internal knowledge, experience, and skill distillation tests pass; the public adapter remains `reflect`, `consolidate`, and `store_lesson`, with no separate `distillation` capability. |
| Observability | Trace propagation remains intact; zero-duration disk/network metric collection is now guarded. |
| Full repository suite | A final complete run was started, reached approximately 2%, remained CPU-active for more than five minutes, and was stopped as a bounded-resource action. No result from the incomplete run is represented as green. |
| Autonomy | Provenance, deduplication, action budget, bounded retry, verified completion, and shutdown hardening from pasted15 remain in place; autonomy is disabled by default. |

## All 42 capability status table

The following table records the current local status. `FULL` means the implementation and representative local path are verified. `LIMITED` means the Freya code and provider boundary are controlled, but the environment lacks a required account, executable, device, provider, or representative media fixture.

| Capability | Registration | Implementation | Routing | Execution | SafetyGate | Verification | Failure recovery | Provider status | `/api/chat` | UI path | Restart | Final status | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `api_connector` | yes | yes | 210/210 | boundary | fail-closed | structured | controlled | allowlist/provider not configured | normal handler | chat/bridge | safe | LIMITED | SSRF and domain controls pass |
| `audio` | yes | yes | 210/210 | boundary | fail-closed | structured | controlled | no representative audio fixture/provider | normal handler | chat/bridge | safe | LIMITED | media boundary is explicit |
| `automation` | yes | yes | 210/210 | verified | fail-closed | structured | bounded | local scheduler available | normal handler | chat/events | safe | FULL | pause/resume/cancel remain governed |
| `browser_capability` | yes | yes | 210/210 | boundary | fail-closed | structured | controlled | supported browser executable unavailable | normal handler | chat/browser events | safe | LIMITED | public discovery and safe failure pass |
| `calendar` | yes | yes | 210/210 | boundary | fail-closed | structured | controlled | no calendar account/provider | normal handler | chat/events | safe | LIMITED | absence is explicit |
| `capability_introspection` | yes | yes | 210/210 | verified | fail-closed | structured | controlled | local | normal handler | chat | safe | FULL | registry-backed |
| `code_execution` | yes | yes | 210/210 | verified | fail-closed | structured | controlled | local | normal handler | chat/events | safe | FULL | commands and patch verification covered |
| `communication_hub` | yes | yes | 210/210 | verified | fail-closed | structured | controlled | local event bus | normal handler | avatar/events | safe | FULL | publish/history pass |
| `computer` | yes | yes | 210/210 | verified | fail-closed | structured | controlled | local boundary | normal handler | chat/UI | safe | FULL | mutation remains guarded |
| `contacts` | yes | yes | 210/210 | boundary | fail-closed | structured | controlled | no contacts account/provider | normal handler | chat | safe | LIMITED | provider absence controlled |
| `data_analysis` | yes | yes | 210/210 | verified | fail-closed | structured | controlled | local | normal handler | chat/results | safe | FULL | analysis group passes |
| `database` | yes | yes | 210/210 | boundary | fail-closed | structured | controlled | no normal user database configured | normal handler | chat/results | safe | LIMITED | SQLite boundary covered |
| `debugging` | yes | yes | 210/210 | verified | fail-closed | structured | controlled | local | normal handler | chat/events | safe | FULL | inspect/diagnostics pass |
| `decision_engine` | yes | yes | 210/210 | verified | fail-closed | structured | controlled | local | normal handler | chat/results | safe | FULL | option validation and result normalization pass |
| `dependency_management` | yes | yes | 210/210 | verified | fail-closed | structured | controlled | local | normal handler | chat/results | safe | FULL | inspect/validate/check pass |
| `document_editing` | yes | yes | 210/210 | verified | fail-closed | structured | controlled | local filesystem | normal handler | chat/results | safe | FULL | file mutation governed |
| `email` | yes | yes | 210/210 | boundary | fail-closed | structured | controlled | no email account/provider | normal handler | chat/events | safe | LIMITED | provider absence controlled |
| `file_input` | yes | yes | 210/210 | verified | fail-closed | structured | controlled | local filesystem | normal handler | chat/results | safe | FULL | local intake passes |
| `file_output` | yes | yes | 210/210 | verified | fail-closed | structured | controlled | local filesystem | normal handler | chat/results | safe | FULL | write path passes |
| `image` | yes | yes | 210/210 | boundary | fail-closed | structured | controlled | no representative normal-runtime image provider | normal handler | chat/results | safe | LIMITED | media failure explicit |
| `iot` | yes | yes | 210/210 | boundary | fail-closed | structured | controlled | no physical devices required | normal handler | chat/events | safe | LIMITED | no virtual devices invented |
| `knowledge_base` | yes | yes | 210/210 | verified | fail-closed | structured | controlled | local stores | normal handler | chat/results | safe | FULL | canonical knowledge path |
| `learning_pipeline` | yes | yes | 210/210 | verified | fail-closed | structured | controlled | local pipeline and memory | normal handler | chat/events | safe | FULL | internal distillers pass; no standalone distillation action |
| `memory_management` | yes | yes | 210/210 | verified | fail-closed | structured | controlled | local stores | normal handler | chat/results | safe | FULL | memory integrity tests pass |
| `orchestration_core` | yes | yes | 210/210 | verified | fail-closed | structured | bounded | local workflow engine | normal handler | chat/events | safe | FULL | workflow status/execute pass |
| `planning_engine` | yes | yes | 210/210 | verified | fail-closed | structured | controlled | local planner | normal handler | chat/results | safe | FULL | undefined context repaired |
| `reasoning_engine` | yes | yes | 210/210 | verified | fail-closed | structured | controlled | local LLM boundary | normal handler | chat/results | safe | FULL | deterministic route and fallback pass |
| `research_capability` | yes | yes | 210/210 | boundary | fail-closed | structured | bounded fallback | local importer plus bounded public fallbacks | normal handler | chat/results | safe | FULL | importer result over-filter repaired |
| `safety_guard` | yes | yes | 210/210 | verified | fail-closed | structured | controlled | local policy | normal handler | chat/events | safe | FULL | denial/approval tests pass |
| `show_capabilities` | yes | yes | 210/210 | verified | fail-closed | structured | controlled | local | normal handler | chat | safe | FULL | alias collisions repaired |
| `show_goals` | yes | yes | 210/210 | verified | fail-closed | structured | controlled | local | normal handler | chat | safe | FULL | route matrix pass |
| `show_identity` | yes | yes | 210/210 | verified | fail-closed | structured | controlled | local | normal handler | chat/avatar | safe | FULL | built-in aliases repaired |
| `show_memory` | yes | yes | 210/210 | verified | fail-closed | structured | controlled | local stores | normal handler | chat/results | safe | FULL | local-first route pass |
| `show_tasks` | yes | yes | 210/210 | verified | fail-closed | structured | controlled | local | normal handler | chat/results | safe | FULL | task aliases repaired |
| `simulation_capability` | yes | yes | 210/210 | verified | fail-closed | structured | controlled | local | normal handler | chat/results | safe | FULL | simulation group passes |
| `system_monitoring` | yes | yes | 210/210 | verified | fail-closed | structured | controlled | local metrics | normal handler | chat/results | safe | FULL | zero-duration metric guard added |
| `system_status` | yes | yes | 210/210 | verified | fail-closed | structured | controlled | local | normal handler | chat/avatar | safe | FULL | control/status precedence repaired |
| `tool_dispatch` | yes | yes | 210/210 | verified | fail-closed | structured | bounded | local ToolManager | normal handler | chat/events | safe | FULL | approved dispatch boundary pass |
| `tool_registry` | yes | yes | 210/210 | verified | fail-closed | structured | controlled | local | normal handler | chat/results | safe | FULL | registry aliases repaired |
| `video` | yes | yes | 210/210 | boundary | fail-closed | structured | controlled | no representative video fixture/provider | normal handler | chat/results | safe | LIMITED | ffprobe/media absence explicit |
| `vision` | yes | yes | 210/210 | boundary | fail-closed | structured | controlled | local provider/fixture limited | normal handler | chat/results | safe | LIMITED | `image_path`, evidence, filename, and unavailable-provider contracts repaired |
| `voice` | yes | yes | 210/210 | boundary | fail-closed | structured | controlled | local speech boundary | normal handler | avatar/audio | safe | FULL | voice/audio routing collision repaired |

## Root causes and actual repairs

The capability audit found and repaired five locally reproducible defects. First, `VisionCapability` accepted `path` and `file_reference` but not the established `image_path` field, and its result omitted the structured evidence object expected by callers; input normalization and evidence/provenance output were repaired without fabricating provider content. Second, `PlanningEngineCapability.action_create_plan` referenced an undefined `external_context`; it now derives that value from the supplied context and uses the existing planner. Third, `WebSearchTool` discarded valid importer-ranked public results when query terms were absent from the result title or snippet; the provider boundary now trusts validated provider-ranked results and keeps bounded fallback behavior. Fourth, generic semantic aliases and control precedence caused ordinary language to fall through or collide with unrelated capabilities; the canonical bridge vocabulary and control-aware precedence were repaired. Fifth, observability divided by a zero collection interval during rapid startup/teardown; disk and network rate calculations now return zero for a zero-duration interval.

No SafetyGate bypass, verification weakening, model-training path, external download, test-only production backdoor, or broad exception-based success fabrication was introduced.

## Remaining limits

The ten environment-limited rows remain honest limitations: API allowlist/provider configuration, representative audio, a supported browser executable, calendar account, contacts account, normal database path, email account, representative image and video fixtures/providers, and physical IoT devices. These limits affect optional external execution, not normal conversation, local routing, local memory, or fail-closed behavior. The internal distillation foundation is verified, but `learning_pipeline` intentionally does not expose a separate public action named `distillation`; distillation remains inside the existing learning foundation.

Autonomy remains disabled by default. The incomplete full-suite run is recorded as an evidence limitation: focused suites passed, but the complete suite must be revisited in a bounded environment before claiming Level 5 maturity.

## Supporting evidence

- `tests/test_pasted16_routing_matrix.py` — 210 natural-language variants, 210/210 pass.
- `tests/test_pasted16_reliability.py` — all-42 registration/reachability and zero-duration observability regression.
- `tests/test_capability_next_task.py` — production planning/communication/debugging/dependency actions.
- `tests/test_research_capability.py` — importer delegation and public result handling.
- `tests/test_new_capabilities.py` and `tests/test_structured_vision_capability.py` — vision and API boundaries.
- `tests/test_learning_distillation_runtime.py` — knowledge, experience, and skill distillation/storage behavior.
- `FOUNDATION_RELIABILITY_AUDIT.md` and `AUTONOMY_RELIABILITY_AUDIT.md` — prior foundation/autonomy evidence preserved.
