# Freya Changelog

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
