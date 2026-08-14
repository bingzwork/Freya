# Production Health and Readiness

Freya exposes a **read-only** production health surface through its supported command-line runtime. Use `python3 main.py --health` to emit the complete JSON liveness and readiness snapshot. Use `python3 main.py --readiness` to emit only readiness; it exits with status `0` when ready and `1` when not ready. Neither command initializes Freya, starts background work, probes providers, changes configuration, or repairs dependencies.

> **Liveness** means the CLI process can answer the query. It is deliberately independent of application initialization and is reported as `{"status": "alive", "alive": true}`.

> **Readiness** means the initialized agent has a usable runtime graph according to the latest observations held by the shared `ObservabilityHub`. A live process is therefore not automatically ready.

| Readiness status | Meaning | Exit behavior of `--readiness` |
|---|---|---:|
| `not_ready` | Initialization is incomplete or a required runtime dependency is `unknown` or `unhealthy`. | `1` |
| `ready` | Initialization is complete and every required dependency is healthy. | `0` |
| `degraded` | Initialization is complete, all required dependencies remain usable, and one or more dependencies are degraded. | `0` |

The readiness payload exposes the completion of initialization and each registered required dependency. Normal `SystemInitializer` startup registers the agent facade, the active configured LLM providers, the shared background-job service, and any enabled workflow-orchestration or autonomy services. Provider checks report each configured provider’s health, reachability, model availability, state, check time, and non-sensitive error detail. Background services report their existing runtime liveness state. Optional dependencies are still visible but do not make the agent unready merely because they fail.

The CLI query reports only already-known runtime state. During normal startup, the initializer registers and evaluates the same checks through `ObservabilityHub`; the health surface merely reads that state. Operators requiring a long-lived remotely queryable endpoint should run Freya behind an application host that exposes this existing JSON payload rather than treating the one-shot CLI command as an HTTP server.
