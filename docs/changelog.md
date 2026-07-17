# Freya Changelog

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
