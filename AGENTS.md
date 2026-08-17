# Freya Agent Instructions

1. Inspect production code before implementing architectural changes.
2. `CURRENT_ARCHITECTURE.md` describes implemented runtime reality; `TARGET_ARCHITECTURE.md` describes intended direction.
3. Do not refactor production code solely because documentation differs from code.
4. Preserve initializer-owned canonical services and do not create parallel registries, memory systems, schedulers, routers, executors, or promotion paths.
5. Preserve fail-closed runtime and promotion safety behavior, typed evidence, provenance, verification, and rollback.
6. Run focused tests and documentation checks before broader validation.
7. Preserve unrelated user changes and confirm the final diff contains only intended work.


## Verified implementation completion

For implementation tasks, successful completion requires inspecting `git status` and the complete diff, committing only intended verified changes, preserving unrelated user changes, pushing successfully to the configured Freya remote, verifying the push, and reporting the active branch and commit hash. Do not hardcode a branch name. A local commit without a successful push does not count as completed implementation work.
