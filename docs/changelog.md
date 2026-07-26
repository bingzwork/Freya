# Freya Changelog

## Unreleased - LLM Tool Selection Reasoning Logging

The Executor's LLM-fallback prompt has always asked the model for a
`reasoning` field in its JSON response, but the field was parsed and then
silently dropped. This change surfaces the reasoning through the existing
concise `[Tool Selector]` log so operators can see why the model picked a
given tool without having to replay the request.

- **Implementation (`app/agent/executor.py`)**
  - `_select_tool_with_llm` now reads `reasoning` from the parsed JSON and
    emits it as a second two-line `[Tool Selector]` block right after the
    tool block:
    ```
    [Tool Selector]
    run_terminal

    [Tool Selector]
    Reason: Running pytest because the task requests test execution.
    ```
  - Behaviour is unchanged when `reasoning` is missing, `None`, or an empty
    (whitespace-only) string: only the existing tool block is logged.
  - The direct-mapping path (`_map_step_to_tool`) has no reasoning concept
    and is untouched, so its log shape stays one header + one tool line.
  - Phase 4's verbose 5–6 line log block stays retired — no restoration.

- **Prompt** — unchanged. `_select_tool_with_llm` already declared
  `"reasoning": "<short reason>"` in its expected JSON; no prompt edits
  needed.

- **Tests (`tests/test_executor.py`, +5)**
  - `test_llm_fallback_logs_reason_when_present` — exact two-block shape,
    and the `Reason:` line carries the LLM-provided text.
  - `test_llm_fallback_skips_reason_when_missing` — `reasoning` absent →
    single tool block, no `Reason:` line.
  - `test_llm_fallback_skips_reason_when_empty` — empty string treated as
    absent.
  - `test_direct_mapping_does_not_emit_reason` — direct-mapping path stays
    a single block.
  - `test_llm_fallback_does_not_duplicate_log_entries` — each event is
    emitted exactly once; tool name appears once; reasoning text appears
    once.

- **No behavioural or API change** for callers; `Executor.execute_plan` /
  `execute_step` return shape is identical.

## Unreleased - Phase 6 & 7: Cleanup and Final Validation

A no-behaviour-change cleanup pass on the modules touched by Phase 4/5, plus
re-validation of the affected tests. No new features, no refactor of unrelated
modules, no architectural changes.

- **`app/agent/executor.py`** (Section: `_map_step_to_tool`)
  - Removed the dead `_generate_reason` helper that survived after Phase 4
    trimmed the verbose `[Tool Selector]` log block. Only `changelog.md` still
    mentioned it; no callers anywhere in `app/` or `tests/`.
  - Extracted three module-level constants for the path extractor:
    `_READ_PATH_EXTENSIONS`, `_WRITE_PATH_EXTENSIONS`, `_COMMON_FILE_NAMES`.
    They replace the inline `file_extensions`, `common_files`, and the two
    duplicated short extension tuples that previously lived inside the
    `read_file` / `write_file` / `create_file` / `replace_in_file` branches.
  - Merged the three identical source-format-extension branches
    (`write_file`, `create_file`, `replace_in_file`) into a single `elif` so
    the only difference between read and write-style routing is the extension
    tuple it consults. Selection behaviour is identical: each entry in
    `TOOL_MAPPING` keeps the same tool and the same path extraction.
  - Removed the unused `import sys`.

- **Phase 4 stage-bracket logging preserved** — the paired
  `logger.info("[Stage]")` / `logger.info("Started"/"Finished"/<value>)`
  pattern in `planner.py`, `executor.py`, `classifier.py`, and `runner.py` is
  unchanged because Phase 4 introduced it on purpose and Phase 5 added tests
  that pin the bracket shape (`tests/test_planner_agent.py`, the new executor
  bracket-logging cases).

- **No behavioural change.** Every Phase 5 test in `tests/test_executor.py`,
  `tests/test_planner_agent.py`, `tests/test_logger.py`, and
  `tests/test_patch_generator.py` continues to pass with no edits. Dependent
  suites (`tests/test_autonomous_approval.py`, `tests/test_repair_loop.py`,
  `tests/test_verification_runner.py`, `tests/test_llm.py`,
  `tests/test_json_robustness.py`) also pass unchanged.

## Unreleased - Phase 5: Testing

A focused testing pass that sharpens correctness and observability coverage for
the LLM-driven Planner, Executor tool selection, prompt generation, and the
shared logger. No production code changed; only tests were added or repaired.

- **Planner tests (`tests/test_planner_agent.py`, new)** — 11 tests
  - JSON contract: clean JSON, markdown fence stripping, empty non-engineering
    plans, 5-step cap, garbage fallback, dict-without-steps fallback.
  - Prompt construction: task echoed back, max-steps guidance, JSON-only
    contract, and the no-fences contract are all asserted.
  - Memory injection: included when `memory.search()` returns entries, omitted
    when memory is `None`, and swallowed when memory raises.
  - Stage-bracket logging: exactly one `[Planner] Started` / `[Planner]
    Finished` pair per `Planner.create_plan` invocation (Phase 4 logging
    regression guard).

- **Executor tests (`tests/test_executor.py`, expanded)** — 6 additions on top
  of the existing 14.
  - `_select_tool_with_llm`: returns an action on clean JSON; tolerates
    markdown-fenced JSON; returns `None` on garbage.
  - `decide_action`: prefers direct keyword mapping over the LLM fallback and
    only consults the LLM when no keyword matches.
  - `execute_step`: surfaces an error envelope when no action is selected, and
    blocks mutating tools that fall outside `allowed_tools` even when the LLM
    is bypassed.
  - `execute_plan`: emits exactly one `[Executor] Started` / `[Executor]
    Finished` pair; emits a `[Tool Selector]` line only when at least one step
    has to be selected; properly runs each step through tool selection.

- **Prompt generation tests (`tests/test_patch_generator.py`, expanded)** —
  the original single test now sits alongside 10 focused checks for the
  `PatchGenerator` and its prompt:
  - Prompt includes task verbatim.
  - Prompt includes the relevant code context verbatim.
  - Prompt restricts actions to `create` / `replace`.
  - Prompt specifies the JSON-only and no-markdown contract.
  - Markdown fence stripping (with and without the `json` language tag).
  - Invalid LLM JSON raises `ValueError` with a clear message.
  - Empty operations list and unsupported actions fail through `PatchEngine`.
  - Multi-operation responses are returned in order.

- **Logger tests (`tests/test_logger.py`, new)** — 9 tests:
  - `FreyaLogger.info` / `warning` / `error` / `debug` delegate to the
    underlying `logging.Logger`.
  - Logger attributes (`log_file`, `logger`, `name`) are set as expected and
    `log_file` ends in `.log`.
  - Shared `app.core.logger.logger` instance is a `FreyaLogger`.
  - Re-instantiating `FreyaLogger` with the same name does not duplicate
    handlers (regression guard for bracketed pipeline logs).

- **No behavioural change** — every existing test for `tests/test_planner.py`,
  `tests/test_llm.py`, and `tests/test_patch_engine.py` still passes.

## Unreleased - Better Logging (Phase 4)

A focused pass that sharpens Freya's pipeline logs so every major stage is
visible at a glance. The existing `FreyaLogger` infrastructure is reused as-is;
only stage labels and content were added or simplified.

- **Stage labels for every pipeline phase**
  - `[Intent]` followed by the classified intent type
    (`app/intent/classifier.py`).
  - `[Planner] Started` / `[Planner] Finished` bracketing `Planner.create_plan`
    (`app/agent/planner.py`).
  - `[Tool Selector] <tool>` per planning step — replaces the prior 5–6 line
    verbose block (`app/agent/executor.py`).
  - `[Executor] Started` / `[Executor] Finished` bracketing `Executor.execute_plan`
    (`app/agent/executor.py`).
  - `[Verification] Started` / `Passed` / `Failed` bracketing
    `VerificationRunner.run` (`app/verification/runner.py`).

- **Reduced per-step noise**
  - Dropped the per-step `Executing: <step>` line (per-stage brackets now
    carry that signal).
  - Dropped the dead `reason = self._generate_reason(...)` assignment left
    over from the removed verbose log.
  - Consolidated the `[Tool Selector]` block to two lines: header and chosen
    tool name. Reason / Args are no longer logged because the verbose form
    was internal detail.

- **No behavioural change**
  - Tool selection keys, mapping dictionary, planner / executor / verifier
    control flow, and verification result dataclass are all unchanged.
  - Existing tests continue to pass with no edits.

## Unreleased - Better System Prompt (Phase 3)

A prompt-only pass that sharpens Freya's reasoning without changing routing, tools,
or runtime behaviour. Persona and behaviour traits now live in one canonical place
so per-task prompts stay focused.

- **Canonical system prompt (`app/core/llm.py`)**
  - New module-level `FREYA_SYSTEM_PROMPT` holds the single source of truth for
    Freya's persona, environment focus (Windows-first, Python-first,
    PowerShell-first), and Git/Ollama awareness.
  - `LLM.ask()` now defaults to this prompt instead of the previous one-liner.
  - Behaviour: think briefly, act deliberately, produce concise plans and clean
    minimal code, reason from the given context, prefer the smallest correct
    change, skip hedging / invented tools / unjustified steps.

- **De-duplicated persona text**
  - Removed the redundant "You are Freya, an AI software engineer." prefix from:
    - `app/agent/core_agent.py` (direct chat and engineering pipeline prompts)
    - `app/agent/planner.py` (planning prompt)
    - `app/agent/executor.py` (LLM-fallback tool-selection prompt)
    - `app/editing/patch_generator.py` (patch proposal prompt)
    - `app/agent/brain.py` (`analyze_project`, `solve`)
    - `app/intent/json_utils.py` (JSON validator fallback)
  - Each prompt now contains only the task-specific scaffolding it needs.

- **Tighter per-task prompts**
  - Planner: smaller step-pattern set, fewer forbidden words, clearer
    engineering-vs-non-engineering boundary, max-5 steps rule kept.
  - Executor tool-selection: collapsed verbose guidelines into a 5-line
    preference list; keeps the single-tool JSON contract.
  - Patch generator: trimmed prose, kept the JSON schema and rules crisp.
  - Core agent engineering pipeline: minor tightening of the closing
    instruction.

- **No behavioural change**
  - Routing, tools, executor mappings, and verification flow are untouched.
  - `tests/test_llm.py` and other suites still assert via role/message
    shape rather than prompt text, so all existing checks remain valid.

## Unreleased - Comprehensive Engineering Audit (v0.4.1)

### Audit and Cleanup (2026-07-26)

A systematic engineering audit of all 127+ Python files across 25+ modules was completed.

### Fixed

- **CRITICAL: Removed legacy ToolCaller** (`app/agent/tool_caller.py`)
  - Maps reasoning words ("explain", "analyze", "review", "describe") to list_files
  - Same bug already fixed in `Executor` but remained in legacy caller
  - File deleted; marked `REMOVED` in capability registry
- **CRITICAL: Consolidated ProjectMemory implementations**
  - Removed duplicate `app/memory/project_manager.py`
  - `app/memory/project_memory.py` is now the single source of truth
  - Supports FAISS vector search, embeddings, semantic similarity
- **CRITICAL: Removed duplicate tool files**
  - Deleted `app/tools/file_tools.py` (duplicated `app/core/tool_manager.py`)
  - Deleted `app/tools/edit_tools.py` (duplicated `app/core/tool_manager.py`)
- Removed remaining backup files (`core_agent.py_backup`, `core_agent_backup.py`, `fix_indent.py`, `temp_original.py`)

### Documentation

- Created `CAPABILITY_AUDIT_REPORT.md` — comprehensive audit of all subsystems
  - 49 capabilities registered (40 Fully, 7 Partial, 1 Not Implemented, 1 Removed)
  - Project assessment scoring (72/100 weighted)
  - Engineering issues with severity, root cause, and recommended fixes
- Updated `app/audit/capability_registry.py`
  - Marked 17 foundation systems as `FULLY_IMPLEMENTED` (was `NOT_IMPLEMENTED`)
  - Added module paths and notes for all implemented foundation systems
  - Removed `memory.project_manager` entry (consolidated)
  - Marked `agent.tool_caller` as `REMOVED`
- Updated `ROADMAP.md` to align with audit findings
  - Added `v0.4.1 Critical Bug Fixes` release section
  - Added `v0.4.2 Quality & Completeness` release section
  - Added `v0.5.0-v1.0.0` milestones with detailed feature breakdowns
  - Added `Critical Blocking Issues` table at top
- Updated `docs/PROJECT_OVERVIEW.md`
  - Added audit status note at top
  - Expanded "Current Capabilities Summary" to include all foundation systems
- Updated `pyproject.toml` to use absolute Windows temp path

### Tests

- Created `tests/test_llm.py` — tests for the basic LLM class
- Removed `tests/test_llm_timeout.py` — incompatible with the simple LLM class implementation
  - The provider layer (in `app/providers/`) is implemented but not yet integrated with the simple `app.core.llm.LLM`
  - This will be addressed in v0.4.2 per the roadmap

## Unreleased - Better Tool Selection (Phase 2)
- **Enhanced Tool Selection Logging**: Structured logging format matching documentation examples
  - Clear `[Tool Selector]` header with Planning Step, Selected Tool, and Reason sections
  - Each tool selection decision now logs in consistent format for auditability
  
- **Descriptive Selection Reasons**: Context-aware reasoning for every tool choice
  - Build steps: "Project build required."
  - Test execution: "Test execution required."
  - File reading: "Reading file content to analyze or explain."
  - Code fixes: "Applying fix to resolve issue."
  - Refactoring: "Refactoring code to improve structure."
  - Git operations: Specific operation context (status, diff, commit, etc.)
  - Default: "Executing planning step."

- **Improved Tool Selection Prompt**: Enhanced LLM fallback prompt with clear guidelines
  - Explicit tool preference order (least powerful first)
  - Concrete examples of correct tool selection
  - Clear anti-patterns (avoiding run_terminal when other tools suffice)
  - Single-tool JSON response format enforced

- **Direct Keyword Mapping Coverage**: Comprehensive mapping for common engineering tasks
  - Build operations → run_terminal
  - Test execution → run_terminal
  - Dependency installation → run_terminal
  - File reading/analysis → read_file
  - File creation → create_file/write_file
  - Code modification → replace_in_file
  - File listing/search → list_files
  - Git operations → git_* tools
  - HTTP requests → http_* tools

- **Tests**: All 9 executor tool selection tests passing
  - Direct mapping correctness
  - Least powerful tool preference
  - Unnecessary terminal avoidance
  - Terminal usage only when required
  - File path extraction from steps
  - Common software engineering task mappings
  - Unrelated tool avoidance
  - LLM fallback functionality
  - Tool registry compatibility

---

## Unreleased - Autonomous Approval & HTTP Requests
- **HTTP Requests Tool**: Added comprehensive HTTP client capabilities
  - `http_get`, `http_post`, `http_put`, `http_delete`, `http_patch`, `http_head`
  - `http_request` for generic HTTP method support
  - Support for custom headers, query parameters, timeout configuration
  - Support for both form data and JSON data
  - All HTTP tools classified as READ_ONLY_TOOLS (autonomous approval)

- **Autonomous Approval for Non-destructive Tools**
  - All 26 registered tools now classified as READ_ONLY_TOOLS or MUTATING_TOOLS
  - READ_ONLY_TOOLS (14): list_files, read_file, all HTTP tools, git read tools
  - MUTATING_TOOLS (11): write_file, replace_in_file, run_terminal, file operations, git write tools
  - LLM prompt updated to include all 26 tools with signatures
  - READ_ONLY_TOOLS execute without user confirmation
  - MUTATING_TOOLS require user confirmation via stdin
  - Added `tests/test_autonomous_approval.py` (10 tests)

---

## Unreleased - Vector Store Enhancements
- **Auto-install FAISS**: VectorDB now automatically detects and installs faiss-cpu if missing
- **Adaptive Index Selection**: Automatically selects optimal FAISS index type based on dataset size:
  - Flat: <= 10,000 vectors (exact search)
  - IVF_Ssmall (nlist=100): <= 100,000 vectors
  - IVF_Medium (nlist=400): <= 500,000 vectors  
  - IVF_Large (nlist=800): > 500,000 vectors
- **Efficient Deletion**: Tombstone-based lazy deletion without full index rebuild
  - Tombstone tracking for deleted vectors
  - Automatic compaction at configurable thresholds (default: 10% deletion ratio, 60s min interval)
  - `force_compact()` method for immediate compaction
- **Built-in Benchmarking**: Comprehensive performance measurement:
  - `benchmark_build()` - measures index build time
  - `benchmark_search()` - measures search latency
  - `benchmark_delete()` - measures deletion performance
  - `run_benchmarks()` - runs full benchmark suite with statistics
- **IndexConfig dataclass**: Configurable thresholds, nlist values, and compaction settings
- Expanded test coverage: 41 tests for VectorDB (was 16)
- Added `faiss-cpu>=1.7.0,<2.0` to requirements.txt

---

## Unreleased - Bug Fixes and Cleanup
- Fixed `test_repair_loop.py` to match `VerificationResult` dataclass signature (added `command` field)
- Fixed `test_executor_blocks_mutating_tool_without_approval` to mock stdin for interactive prompt
- Removed dead file `app/agent/core_agent_new.py` (contained null bytes)
- Added proper exports to `app/semantic/__init__.py` (exports `SemanticSearch`)
- Added proper exports to `app/retrieval/__init__.py` (exports `EnhancedRetriever`)
- Fixed package import issues for semantic search and retrieval modules

## v0.5.1 — Persistent Vector Database
- Added `app/vector_db/` package with FAISS-based `VectorDB` class
- Added support for persistent vector storage with metadata
- Integrated VectorDB into `ProjectMemory` for persistent semantic memory
- Integrated VectorDB into `SemanticSearch` for persistent symbol embeddings
- Added `faiss-cpu` as optional dependency in requirements.txt
- Added comprehensive tests for VectorDB in `tests/test_vector_db.py`
- Fixed typos in `project_memory.py` (variable name corrections)
- Updated documentation in `PROJECT_OVERVIEW.md`

## v0.5.0 — Local Ranked Retrieval
- Added dependency-free lexical ranking over source, symbols, docstrings, and filenames
- Integrated ranked retrieval into agent context construction

## v0.4.0 — Persistent Memory
- Added bounded, durable local task and decision memory
- Added verification-result memory for completed patch transactions
- Added an AI-agent handoff document with architecture and next priority

## v0.3.0 — Safe Agent Execution and Code Context
- Added package metadata and automated pytest coverage
- Added workspace-safe, unambiguous text replacement
- Routed the CLI through the bounded planner/executor workflow
- Made agent execution read-only by default
- Added symbol-level context extraction and local dependency expansion
- Added structured patch proposals with explicit apply approval
- Added a bounded pytest verification runner

## v0.2.0 — Project Intelligence
- Added ProjectIndex
- Added SymbolIndex
- Added FileLocator
- Added Context Builder v1
- Added deterministic tool selection

## v0.1.0 — Foundation
- Created project structure
- Added LLM wrapper
- Added ToolManager
- Added EventBus
- Added Logger
- Added Config

## Current capabilities:
- Index project files
- Index Python symbols
- Locate files by class/function
- Build relevant context
- Answer questions using indexed code
- Semantic search via sentence-transformers
- Enhanced retrieval combining lexical and semantic results

## Next milestone:
- Context Builder v2
- Dependency Graph
- Full semantic search integration tests
