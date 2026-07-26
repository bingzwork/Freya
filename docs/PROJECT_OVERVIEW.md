# Freya Project Overview

> **Audit Status (2026-07-26):** All critical issues fixed. Production code clean. 49 capabilities registered; 40 fully implemented, 7 partially implemented, 1 not yet implemented (AST refactoring), 1 removed (legacy ToolCaller). See `CAPABILITY_AUDIT_REPORT.md` for full details.

## Vision

Freya is an autonomous AI software engineer capable of understanding, navigating, modifying, testing, and improving software projects with minimal human guidance.

Unlike a traditional chatbot, Freya is designed to operate as an intelligent coding agent that reasons over source code instead of relying solely on large language model prompts.

The long-term objective is for Freya to:

- Understand entire software projects
- Build internal representations of code
- Locate relevant files automatically
- Read only necessary code
- Generate precise code modifications
- Execute tools safely
- Verify its own changes
- Improve itself over time

---

# Current Architecture

Freya currently consists of several independent subsystems.

## LLM

Responsible for communicating with Ollama.

Current model:

- qwen2.5-coder:14b

Responsibilities:

- Answer prompts
- Generate plans
- Explain code
- Assist tool selection

---

## Tool Manager

Responsible for executing tools safely.

### Tool Classification

All tools are classified as either **READ_ONLY_TOOLS** (autonomous approval) or **MUTATING_TOOLS** (requires user confirmation).

**READ_ONLY_TOOLS (14) - Autonomous Approval:**
- `list_files()` - List workspace files
- `read_file(path)` - Read file contents
- `http_get(url, ...)` - HTTP GET request
- `http_post(url, ...)` - HTTP POST request
- `http_put(url, ...)` - HTTP PUT request
- `http_delete(url, ...)` - HTTP DELETE request
- `http_patch(url, ...)` - HTTP PATCH request
- `http_head(url, ...)` - HTTP HEAD request
- `http_request(method, url, ...)` - Generic HTTP request
- `git_status(path)` - Get git status
- `git_diff(path, staged)` - Get git diff
- `git_log(path, limit)` - Get git history
- `git_branch_list()` - List git branches
- `git_is_repo(path)` - Check if git repository

**MUTATING_TOOLS (11) - Requires User Approval:**
- `write_file(path, content)` - Write file
- `replace_in_file(path, old, new)` - Replace text
- `run_terminal(command)` - Run shell command
- `create_file(path, content)` - Create new file
- `delete_file(path)` - Delete file
- `format_file(path)` - Format file
- `git_add(path)` - Stage file for commit
- `git_commit(message, all)` - Commit changes
- `git_push(branch)` - Push to remote
- `git_pull(branch)` - Pull from remote
- `git_checkout(branch)` - Switch branch

Safety features:

- Workspace restriction
- Safe path validation
- Structured ToolResult responses

---

## Project Index

Indexes the project contents.

Current behavior:

- Scans supported files
- Ignores unnecessary folders

Ignored folders:

- .git
- .venv
- __pycache__
- node_modules
- .pytest_cache
- .mypy_cache
- .idea
- .vscode

Purpose:

Allows Freya to understand the structure of an entire project.

---

## Symbol Index

Indexes Python symbols.

Current capabilities:

- Detect classes
- Detect functions
- Detect async functions
- Store line numbers
- Store file contents

The Symbol Index currently serves as Freya's code map.

---

## File Locator

Uses the Symbol Index to locate source files.

Capabilities:

- Search by class name
- Search by function name
- Search by filename
- Rank results
- Return best match

Example:

User:

Explain ToolManager

↓

File Locator

↓

app/core/tool_manager.py

---

## Context Builder (Version 1)

Current implementation:

- Extracts keywords from the user's request
- Uses File Locator
- Reads relevant source files
- Sends only matching files to the LLM

This replaces sending the entire project.

---

## Lexical Search

Dependency-free relevance ranking over source code.

Capabilities:

- Ranks by task terms, identifiers, filenames, source text, docstrings
- No external dependencies required
- Fast local execution

---

## Semantic Search

Embedding-based similarity search using sentence-transformers.

Capabilities:

- Uses all-MiniLM-L6-v2 model
- Finds conceptually similar code
- Understands natural language queries
- Caches embeddings to disk for performance
- Graceful fallback if dependencies unavailable
- **Persistent Vector Database (FAISS) for efficient similarity search across sessions**

---

## Enhanced Retriever

Combines lexical and semantic search for better relevance.

Scoring:

- 60% lexical (keyword matching)
- 40% semantic (embedding similarity)

---

## Vector Database

Persistent vector storage using FAISS for efficient similarity search.

Current implementation:

- **Auto-installation**: Automatically detects and installs FAISS if missing via pip
- **FAISS Flat index** for exact similarity search on small datasets
- **Adaptive Index Selection**: Automatically switches between index types based on dataset size:
  - Flat: <= 10,000 vectors (exact search)
  - IVF_Small (nlist=100): <= 100,000 vectors
  - IVF_Medium (nlist=400): <= 500,000 vectors
  - IVF_Large (nlist=800): > 500,000 vectors
- **Lazy Deletion**: Tombstone-based efficient deletion without full index rebuild
  - Tombstone tracking for deleted vectors
  - Automatic compaction at 10% deletion ratio with 60s minimum interval
  - Force compaction via `force_compact()` method
- Normalized vectors for cosine similarity
- Metadata storage alongside vectors
- Persistence to `data/vector_db/` directory
- Graceful fallback to in-memory if FAISS unavailable
- **Built-in Benchmarking**: `benchmark_build()`, `benchmark_search()`, `benchmark_delete()`, `run_benchmarks()`

Used by:

- `ProjectMemory` for persistent semantic memory
- `SemanticSearch` for persistent symbol embeddings

Files:

- `app/vector_db/__init__.py` - VectorDB class with IndexConfig dataclass
- Tests in `tests/test_vector_db.py` (41 tests)

---

## Tool Selection

Freya uses a hybrid approach for tool selection: deterministic rule-based mapping first, then LLM fallback for complex steps.

### Strategy

1. **Direct Keyword Mapping** (fast, consistent):
   - Comprehensive keyword-to-tool mappings for common software engineering tasks
   - Build operations → `run_terminal`
   - Test execution → `run_terminal`
   - Dependency installation → `run_terminal`
   - File reading/analysis → `read_file`
   - File creation → `create_file` / `write_file`
   - Code modification → `replace_in_file`
   - File listing/search → `list_files`
   - Git operations → `git_*` tools
   - HTTP requests → `http_*` tools

2. **LLM Fallback** (for unmatched steps):
   - Enhanced prompt with tool preference order (least powerful first)
   - Concrete examples of correct tool selection
   - Anti-patterns explicitly documented (avoid unnecessary terminal use)
   - Structured JSON response format

### Logging Format

Every tool selection decision is logged in a structured format for auditability:

```
[Tool Selector]
Planning Step:
Build the project

Selected Tool:
run_terminal

Reason:
Project build required.
```

### Tool Preference Order (Least Powerful → Most Powerful)

1. **Read operations**: `list_files`, `read_file`
2. **File operations**: `create_file`, `write_file`, `delete_file`, `replace_in_file`
3. **Git operations**: `git_*` tools
4. **HTTP operations**: `http_*` tools
5. **Terminal operations**: `run_terminal` (last resort)

### Guiding Principles

- Match tool to planning step precisely
- Never choose unrelated tools
- Avoid `run_terminal` when another tool can accomplish the task
- Prefer the least powerful tool capable of completing the step

---

# Current Workflow

User Request

↓

Tool Selection

↓

Project Intelligence

↓

File Locator + Lexical Search + Semantic Search

↓

Relevant Context

↓

LLM

↓

Response

---

# Current Capabilities Summary

## Core Agent Pipeline

- [x] Project awareness (project_index)
- [x] Code awareness (symbol_index)
- [x] Symbol awareness
- [x] File awareness
- [x] Lexical search
- [x] Semantic search (sentence-transformers + FAISS)
- [x] Enhanced retrieval (60% lexical + 40% semantic)
- [x] Patch generation
- [x] Patch verification
- [x] Autonomous repair loop
- [x] Persistent memory (ProjectMemory, ExperienceMemory, EngineeringLessons)
- [x] Persistent Vector Database (FAISS) with auto-install, adaptive indexing, lazy deletion, and benchmarking

## Foundation Systems (Phase 1 - all implemented)

- [x] **Capability Audit System** — Automated auditing with registry and reports
- [x] **Diagnostics Engine** — Static code analysis (unused imports, complexity, security, etc.)
- [x] **System Monitoring** — Real-time CPU, memory, disk, network metrics with alerts
- [x] **Advanced Planner** — Task graph, scheduler, resource allocator, progress tracker, visualizer
- [x] **Reviewer System** — Code review workflow with assignments, checklists, metrics
- [x] **Risk Assessment** — Risk identification, assessment, mitigation tracking
- [x] **Confidence Scoring** — Confidence calibration and tracking
- [x] **Improvement Backlog** — Priority-scored backlog with weighted scoring
- [x] **Benchmarking Framework** — Timing, accuracy, multi-metric benchmarks
- [x] **Documentation Automation** — AST-based documentation generation
- [x] **Git Automation** — Semantic commits, change tracking, branch management
- [x] **Project Health** — Health dashboard with metrics and monitoring
- [x] **LLM Provider Abstraction** — Multi-provider framework (Ollama implementation)

## Subsystems

- [x] Multi-turn conversation state with persistence
- [x] Intent classification (8 types with confidence scoring)
- [x] Capability routing (15+ direct answers bypassing LLM)
- [x] Patch-based editing with rollback
- [x] Verification runner (pytest, py_compile)
- [x] Permission menu for mutating tools

## Architectural Quality

- [x] Clean modular structure (25+ modules, 127+ files)
- [x] Event system (pub/sub) for inter-component communication
- [x] Provider factory pattern for LLM extensibility
- [x] Capability registry (49 capabilities tracked)
- [x] All foundation systems integrated
- [x] Comprehensive test suite (500+ tests across 40 test files)
- [x] No duplicate implementations (all duplicates removed in v0.4.1)

---

# Current Limitations

Freya still:

- Cannot build full dependency graphs (only follows direct imports)
- Cannot preserve metadata or binary files during rollback
- No GUI, voice, or internet search

These are planned for future milestones.

---

# Next Milestones

> See `ROADMAP.md` for the full actionable roadmap aligned with the 2026-07-26 audit.

## Upcoming (v0.4.2 - v0.5.0)

1. **Multi-provider LLM** — Claude, OpenAI, Gemini provider implementations
2. **Structured Logging** — JSON format for production observability
3. **Streaming LLM** — Token-by-token responses for better UX
4. **Delete Patch Action** — PatchEngine support for file deletion
5. **ExperienceMemory Integration** — Connect experience lessons to agent decisions
6. **EngineeringLessons Integration** — Auto-retrieve lessons during planning
7. **AST-based Refactoring** — Safe code transformations (rename, extract, inline)
8. **Cross-file Symbol Resolution** — Navigate imports/references across files

## Future (v0.6.0 - v1.0.0)

- Plugin system for extensibility
- Distributed tracing (OpenTelemetry)
- Agent spawning / sub-agent delegation
- Multi-version LLM caching
- Production hardening (integration tests, fault injection)
