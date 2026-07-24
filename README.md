# Freya - Autonomous AI Software Engineer

Freya is a local Python-based AI software engineering agent that understands, navigates, modifies, tests, and improves software projects with minimal human guidance.

## Features

- **Project Intelligence**: Indexes project files and Python symbols (classes, functions, async functions) with line numbers
- **Local Retrieval**: Dependency-free lexical ranking over source code, symbols, docstrings, and filenames
- **Semantic Search**: Embedding-based search using sentence-transformers (all-MiniLM-L6-v2) for conceptual matching
- **Enhanced Context**: Combines lexical and semantic search for better relevance
- **Safe Execution**: Workspace-restricted tool execution with explicit mutation approval
- **Patch Management**: Structured patch proposals with explicit apply approval
- **Verification**: Automatic pytest verification with rollback on failure
- **Autonomous Repair**: Bounded retry loop with verification feedback
- **Persistent Memory**: Local task/decision/verification memory in data/memory/freya_memory.json
- **Multi-turn Conversation**: Full conversation state management with persistence
- **Provider Abstraction**: Support for multiple LLM providers (Ollama, extensible for Claude, GPT, etc.)
- **Intent Classification**: 8 intent types for optimal request routing
- **Capability Routing**: 15+ direct-answer capabilities bypassing LLM for common queries
- **Health Monitoring**: Comprehensive system resource tracking and alerting
- **Vector Database**: FAISS-based persistent embedding storage with adaptive indexing

## Quick Start

```bash
# Install dependencies
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt

# Run Freya
.venv\Scripts\python main.py
```

## Usage

```python
from app.agent.core_agent import FreyaAgent

agent = FreyaAgent("./my_project")

# Run a task (read-only by default)
result = agent.run("Explain the authentication system")

# With mutations allowed
result = agent.run("Add a new API endpoint", allow_mutations=True)

# Propose a patch without applying
proposal = agent.propose_patch("Fix the bug in user_login")

# Apply and verify
result = agent.apply_patch_and_verify(proposal, allow_mutations=True)

# Autonomous solving
result = agent.solve(
    "Add rate limiting", 
    max_iterations=5, 
    allow_mutations=True
)

# Multi-turn conversation
result1 = agent.run("What does this project do?")
result2 = agent.run("Now add a new feature")  # Remembers context

# With conversation persistence
agent = FreyaAgent(
    "./my_project",
    max_conversation_history=50,
    conversation_persistence_path="data/conversation.json"
)
```

## Architecture

- **Provider Layer**: LLM provider abstraction (Ollama, extensible for others)
- **Core Layer**: LLM, ProjectIndex, SymbolIndex, ToolManager, Logger, Events
- **Intelligence Layer**: FileLocator, ContextBuilder, DependencyGraph, LexicalSearch, SemanticSearch, EnhancedRetriever
- **Capability Layer**: IntentClassifier, CapabilityRouter, 15+ direct-answer handlers
- **Agent Layer**: CoreAgent, Planner, Executor, ToolCaller, Brain
- **Memory Layer**: ProjectMemory, ConversationState, VectorDB
- **Editing Layer**: PatchGenerator, PatchEngine with atomic apply and rollback
- **Verification Layer**: VerificationRunner, RepairLoop
- **Monitoring Layer**: SystemMonitor, ProcessMonitor, MetricCollector, AlertManager
- **Diagnostics Layer**: CodeAnalyzer, DiagnosticEngine

## Architecture Components

- **LLM**: Communicates with Ollama (default: qwen2.5-coder:14b)
- **ProjectIndex**: Scans and stores project files
- **SymbolIndex**: Parses Python AST and indexes symbols
- **LexicalSearch**: Keyword-based relevance ranking
- **SemanticSearch**: Embedding-based similarity search
- **EnhancedRetriever**: Combines lexical and semantic results
- **ContextBuilder**: Extracts relevant symbols and dependencies
- **IntentClassifier**: Classifies requests into 8 intent types
- **CapabilityRouter**: Routes queries to 15+ direct-answer capabilities
- **ToolManager**: Executes tools safely within workspace
- **PatchEngine**: Validates and applies patches atomically
- **VerificationRunner**: Runs pytest suite
- **RepairLoop**: Retries with verification feedback
- **ProjectMemory**: Persists task and decision history
- **ConversationState**: Manages multi-turn conversation history
- **SystemMonitor**: Tracks system resources (CPU, memory, disk, network)
- **AlertManager**: Manages alerts with configurable thresholds

## Requirements

- Python 3.11+
- Ollama with qwen2.5-coder:14b (or configure another model in .env)
- Dependencies in requirements.txt

## Configuration

Create a .env file:

```
MODEL=qwen2.5-coder:14b
PROJECT_NAME=Freya
WORKSPACE=.
MEMORY_PATH=data/memory
VECTOR_PATH=data/vector_db
```

## Testing

```bash
# Run all tests
.venv\Scripts\python -m pytest tests/ -v

# Run with custom basetemp (Windows)
.venv\Scripts\python -m pytest tests/ --basetemp=C:/temp/pytest -v

# Validate code compiles
.venv\Scripts\python -m compileall -q app
```

## Documentation

- docs/PROJECT_OVERVIEW.md - High-level project vision
- docs/ARCHITECTURE.md - Detailed module structure and data flows
- docs/DEVELOPMENT.md - Development setup and workflow
- docs/AI_HANDOFF.md - Current capabilities and next priorities
- docs/changelog.md - Release history
- docs/ROADMAP.md - Future plans
- PROJECT_STATUS.md - Current implementation status and metrics
