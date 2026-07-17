# Freya Project Overview

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

Current tools:

- read_file
- write_file
- list_files
- run_terminal

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

---

## Enhanced Retriever

Combines lexical and semantic search for better relevance.

Scoring:

- 60% lexical (keyword matching)
- 40% semantic (embedding similarity)

---

## Tool Selection

Freya no longer relies entirely on the LLM for tool selection.

Current strategy:

Deterministic rules first.

Examples:

Explain X
→ list_files

Read file
→ read_file

Run command
→ run_terminal

Unknown requests
→ fallback to LLM

This greatly improves consistency.

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

Freya now possesses:

- [x] Project awareness
- [x] Code awareness
- [x] Symbol awareness
- [x] File awareness
- [x] Lexical search
- [x] Semantic search
- [x] Enhanced retrieval
- [x] Patch generation
- [x] Patch verification
- [x] Autonomous repair loop
- [x] Persistent memory

---

# Current Limitations

Freya still:

- Cannot build full dependency graphs (only follows direct imports)
- Cannot preserve metadata or binary files during rollback
- Dependencies on external vector databases (uses local caching instead)
- No GUI, voice, or internet search

These are planned for future milestones.

---

# Next Milestones

1. **v0.6.0** - Dependency Graph and Context Builder v2
   - Full dependency graph
   - Improved context building
   - Better symbol-level context extraction

2. **v0.7.0** - Enhanced Patch System
   - Formal patch review object
   - CLI workflow for propose/preview/approve/apply/verify
   - End-to-end tests with stub LLM

3. **v0.8.0** - Self-Improvement
   - Learning from past decisions
   - Autonomous goal detection
   - Online learning capabilities
