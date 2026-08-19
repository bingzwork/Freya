# Pasted21 Agent Console Audit

## Scope

Pasted21 replaces placeholder Agent Console data with safe, backend-connected operational metadata while preserving Freya’s existing canonical architecture. The implementation does not create a second task registry, memory system, scheduler, router, browser stack, or autonomy manager. It reads the existing `BackgroundJobService`, `WorkflowOrchestrator`, `AutonomyManager`, `MemoryCoordinator`, `ObservabilityHub`, local provider, and canonical SafetyGate.

## Implemented backend integration

The existing UI server now exposes read-only aggregation routes:

| Route | Purpose |
|---|---|
| `/api/agent-console` | Bounded combined snapshot for Tasks, Memory, System Status, and Autonomy |
| `/api/tasks` | Current background jobs, bounded job history, active autonomous work, and active workflows |
| `/api/memory/status` | Safe counts and readiness metadata only; no conversation text, prompts, embeddings, or private records |
| `/api/system/status` | Readiness/component state plus real CPU, RAM, disk, process-memory, GPU-if-available, and backend uptime values |
| `/api/autonomy/status` | Authoritative lifecycle state and worker counts |
| `POST /api/autonomy/start` | Explicitly starts the canonical AutonomyManager after UI confirmation |
| `POST /api/autonomy/stop` | Stops the canonical autonomy workers and learning pipeline |

Task records are normalized from the existing job and workflow owners. They preserve real identifiers, origin, status, timestamps, duration when known, goal/workflow/trace identifiers when present, waiting reasons, approval flags, and failure summaries. Unknown progress is returned as `null`; no progress percentage is fabricated. Job summaries expose only sanitized provenance fields and never return raw metadata payloads.

Memory status is intentionally metadata-only. The surface reports working-memory activity, bounded conversation-context count, store/retrieval readiness, and learning-pipeline availability/counts where the canonical service exposes them. It does not expose message content, hidden reasoning, embeddings, raw records, or private summaries.

System Status now consumes the existing ObservabilityHub flat `system.*` metrics. The live service reports measured CPU, RAM, disk, current process memory, and backend-process uptime. GPU and VRAM remain explicitly `Unavailable` on this host because no GPU measurement was available. The canonical orchestrator SafetyGate is surfaced as `Ready`, including its balanced policy mode and assessment/pending-approval counts.

## Autonomy lifecycle and safety

Normal UI startup constructs the real autonomy manager in `OFF` and does not start autonomous workers. The initializer now supports an explicit `start_autonomy_on_boot` flag, defaulting to `False`. The Agent Console’s Enable control requires a confirmation dialog that explains autonomous initiation and states that SafetyGate still controls authorization. The backend then performs the real start/stop operation through the existing AutonomyManager.

The AutonomyManager now exposes authoritative `OFF`, `STARTING`, `ON`, `STOPPING`, and `ERROR` state metadata, along with `started_at`, `last_error`, learning-pipeline state, watchdog state, self-initiated work count, and maintenance state. Start failures roll back already-started components and return an error state. Stop remains idempotent and clears worker state. Existing SafetyGate enforcement and approval boundaries are unchanged.

## Frontend integration

The existing Agent Console now uses `/api/agent-console` polling every eight seconds and continues to consume the existing `/api/avatar-events` stream for operational activity events. The Activity tab preserves the existing timeline and trace display. The Tasks tab renders active and recent backend task records, origin labels, status, durations, waiting-for-approval markers, and bounded failure summaries. The Memory tab renders safe metadata and unavailable states with retry behavior. The System Status section renders real component readiness, hardware metrics, autonomy state, and lifecycle controls. The existing chat, attachment, microphone, scrolling, image-result, and backend event behavior remains intact.

## Verification

| Check | Result |
|---|---|
| Modified Python syntax checks | Passed |
| Frontend production build (`pnpm --dir client run build`) | Passed |
| Permanent `tests/test_pasted21_agent_console.py` | **6 passed** |
| Focused combined suite: Pasted21, pasted18 live paths, research, routing, browser, and SafetyGate tests | **100% passed; no failures** |
| Normal startup autonomy state | `OFF`, `running: false` |
| Explicit autonomy start API | `200`, authoritative state `ON`, learning/watchdog/self-initiated/maintenance workers running |
| Explicit autonomy stop API | `200`, authoritative state `OFF`, workers stopped |
| Live Agent Console Tasks tab | Real recurring background jobs displayed; placeholder-unavailable copy absent |
| Live Agent Console Memory tab | Real metadata displayed; placeholder-unavailable copy absent |
| Live Agent Console confirmation | Confirmation dialog and SafetyGate explanation displayed |
| Live autonomy transition | `OFF → ON → OFF` passed |
| Live chat after console interaction | Assistant response displayed and composer remained present |
| Browser console errors during live UI probe | None observed |
| Final live SafetyGate status | `Ready`, `balanced` mode |
| Final live hardware status | CPU, RAM, disk, process memory, and uptime populated; GPU/VRAM explicitly unavailable |

## Honest limitations

The host did not expose a GPU device to the existing monitoring stack, so GPU and VRAM are shown as `Unavailable`. Browser and Research do not currently register dedicated readiness components in the existing health surface, so the console reports those component-specific states as `Unavailable` rather than claiming they are ready. This does not replace or disable the existing browser/research capabilities; it is a limitation of the currently exposed readiness metadata. No new provider or fake health result was added.

## Repository state

Pasted21 source changes are intended for commit and push only from the following files:

- `app/ui/agent_console.py`
- `app/autonomy/manager.py`
- `app/core/background_jobs.py`
- `app/core/initializer.py`
- `app/core/protocols.py`
- `app/memory/coordinator.py`
- `ui_server.py`
- `client/src/pages/Home.tsx`
- `client/src/index.css`
- `tests/test_pasted21_agent_console.py`
- `P21_AGENT_CONSOLE_AUDIT.md`

Temporary Pasted21 probes and patch scripts were removed. Unrelated/pre-existing working-tree files remain untouched.
