# Freya Architecture

## Current Structure

```
Freya
│
├── app
│
├── agent
│   ├── core_agent.py
│   ├── planner.py
│   ├── executor.py
│   ├── tool_caller.py
│   ├── brain.py
│
├── core
│   ├── llm.py
│   ├── logger.py
│   ├── config.py
│   ├── tool_manager.py
│   ├── project_index.py
│   ├── symbol_index.py
│
├── intelligence
│   └── file_locator.py
│
├── tools
│
├── memory
│
├── rag
│
├── ui
│
└── tests
```

---

# Agent Pipeline

User

↓

Core Agent

↓

Tool Caller

↓

Tool Manager

↓

Project Intelligence

↓

Context Builder

↓

LLM

↓

Response

---

# Project Intelligence Layer

Current modules:

ProjectIndex

↓

SymbolIndex

↓

FileLocator

Responsibilities:

ProjectIndex

- scans project
- stores files

SymbolIndex

- parses Python AST
- indexes classes
- indexes functions
- stores line numbers

FileLocator

- resolves symbols
- resolves filenames
- ranks matches

Future additions:

- ContextBuilder
- DependencyGraph
- SemanticSearch

---

# Tool Layer

Current tools:

- read_file
- write_file
- list_files
- run_terminal

All tools execute through ToolManager.

Future:

- git
- search
- patch
- rename
- refactor
- diagnostics

---

# LLM Layer

Current implementation:

Ollama

↓

Qwen2.5-Coder 14B

Future support:

- GPT
- Claude
- Gemini
- DeepSeek
- Local models

---

# Future Execution Pipeline

User Request

↓

Planner

↓

Task Graph

↓

Context Builder

↓

Dependency Graph

↓

LLM

↓

Patch Generator

↓

Patch Applier

↓

Verification

↓

Finished

This architecture minimizes token usage while maximizing code accuracy.