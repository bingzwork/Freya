# Freya

Freya is a personal, local-first AI agent project focused on a canonical runtime with explicit routing, capability, execution, learning, safety, and operational ownership boundaries.

## Development validation

Install the declared development dependencies and run the focused canonical suite with the following command from the repository root:

```bash
./scripts/run_canonical_tests.sh
```

The command installs the project with its `dev` extra and runs the clean-process lifecycle, fallback verification, provider-resilience, workflow-safety, execution, learning, routing, and architecture-contract tests without requiring a manual `PYTHONPATH` adjustment.

For the current implementation state and remaining hardening priorities, see [`PROJECT_STATUS.md`](PROJECT_STATUS.md).
