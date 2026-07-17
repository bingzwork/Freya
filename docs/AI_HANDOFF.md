# Freya AI Agent Handoff

## Purpose

Freya is a local Python software-engineering agent. It uses Ollama through
`app/core/llm.py`; the configured default is `qwen2.5-coder:14b`.

## Current working capabilities

- Indexes supported project files and Python symbols.
- Locates classes/functions/files and builds compact symbol-level context.
- Ranks relevant source locally from task terms, identifiers, filenames, and
source/docstring words.
- **Semantic search via sentence-transformers (all-MiniLM-L6-v2) for conceptual matching.**
- **Enhanced retrieval combining lexical (60%) and semantic (40%) scores.**
- Follows direct local Python imports for dependency context.
- Plans and executes at most eight tool actions per request.
- Defaults to read-only tools; file changes and terminal actions require
`allow_mutations=True` in the API.
- Proposes structured `create`/exact `replace` patches.
- Applies approved patches as transactions, runs pytest, and rolls back every
changed file when verification fails.
- Retries approved repairs with concise test-failure feedback.
- Persists bounded local task/decision/verification memory in
`data/memory/freya_memory.json`.

## Important entry points

| Need | Location / API |
| --- | --- |
| CLI | `main.py` |
| Main orchestrator | `app/agent/core_agent.py` / `FreyaAgent` |
| Workspace-safe files | `app/core/tool_manager.py` |
| Patch validation/transaction | `app/editing/patch_engine.py` |
| Patch LLM JSON proposal | `app/editing/patch_generator.py` |
| Test verification | `app/verification/runner.py` |
| Retry loop | `app/verification/repair_loop.py` |
| Durable local memory | `app/memory/project_memory.py` |
| Local ranked retrieval | `app/intelligence/lexical_search.py` |
| Semantic search | `app/semantic/search.py` |
| Enhanced retrieval | `app/retrieval/enhanced_retriever.py` |

## Safety invariants

1. `ToolManager.safe_path()` must keep all file operations in the workspace.
2. Replacements require the old text to occur exactly once.
3. Creating a file must never overwrite an existing file.
4. Autonomous mutation APIs must continue to require explicit approval.
5. Failed verification must restore every touched file, including deleting
files that were created by the failed patch.
6. Do not add arbitrary model-generated shell execution to verification.

## Validation

Run from the workspace:

```powershell
.\.venv\Scripts\python.exe -m pytest --basetemp .pytest-tmp -p no:cacheprovider
.\.venv\Scripts\python.exe -m compileall -q app main.py
```

The custom pytest options are necessary in restricted Windows environments.

## Known limitations

- Retrieval combines lexical and semantic, but semantic depends on sentence-transformers being installed
- Dependency graph only follows direct local Python imports.
- Patch transaction rollback does not yet preserve metadata or binary files.
- Patch proposals depend on valid LLM JSON; malformed proposals are rejected.
- No GUI, voice, internet search, or background task manager yet.

## Implementation Status

### Completed and Working
- [x] Semantic search module (`app/semantic/search.py`)
- [x] Enhanced retriever combining lexical + semantic (`app/retrieval/enhanced_retriever.py`)
- [x] Integration in `app/agent/core_agent.py` with fallback
- [x] Package exports for `app.semantic` and `app.retrieval`
- [x] All 24 tests passing
- [x] Dependency: sentence-transformers>=2.2,<3.0

### Documentation

After each completed increment, update this file with the new capabilities,
test result, limitations, and the single next priority. Also add a concise
entry to `docs/changelog.md` and update `docs/DEVELOPMENT.md` if API or setup
behavior changed.

## Next implementation priority

1. Add comprehensive tests for semantic search and enhanced retriever
2. Add formal patch review object
3. Add command-line workflow for the full `propose -> preview -> approve -> apply -> verify` lifecycle
4. Keep mutation approval explicit
5. Add end-to-end tests with a stub LLM
