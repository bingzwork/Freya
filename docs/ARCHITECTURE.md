# Freya Architecture

## Overview

Freya is a modular autonomous AI software engineering agent. The architecture is organized into **28 distinct modules** across multiple layers, each with a clear separation of responsibilities.

---

## Current Structure

```
Freya
│
├── app
│   │
│   ├── agent/              # Agent Core Layer
│   │   ├── agent.py        # Main Agent class
│   │   ├── core_agent.py   # Core Agent logic
│   │   ├── planner.py      # Task planning
│   │   ├── executor.py     # Action execution
│   │   ├── tool_caller.py  # Tool invocation
│   │   ├── brain.py        # Agent brain/state
│   │   └── __init__.py
│   │
│   ├── core/               # Core Utilities Layer
│   │   ├── llm.py          # LLM communication (Provider Abstraction)
│   │   ├── config.py       # Configuration management
│   │   ├── logger.py       # Logging system
│   │   ├── events.py       # Event bus (pub/sub)
│   │   ├── tool_manager.py # Tool execution management
│   │   ├── project_index.py # Project file indexing
│   │   ├── symbol_index.py # Python symbol indexing
│   │   └── models/
│   │
│   ├── intelligence/       # Project Intelligence Layer
│   │   ├── file_locator.py     # Locate source files
│   │   ├── context_builder.py # Build context from files
│   │   ├── dependency_graph.py # Import dependency graph
│   │   ├── lexical_search.py    # Keyword-based search
│   │   └── __init__.py
│   │
│   ├── providers/          # Provider Abstraction Layer (NEW)
│   │   ├── base.py         # Base classes (ProviderError, ProviderConfig, etc.)
│   │   ├── factory.py      # Dynamic provider creation
│   │   ├── health.py       # Health checking
│   │   ├── ollama.py       # Ollama provider implementation
│   │   └── README.md
│   │
│   ├── capabilities/       # Capability Routing System (NEW)
│   │   ├── router.py       # Routes queries to capability handlers
│   │   ├── handlers.py     # 15 capability handlers
│   │   ├── formatter.py    # Response formatting
│   │   └── __init__.py
│   │
│   ├── intent/             # Intent Classification (NEW)
│   │   ├── classifier.py   # 8 intent types
│   │   ├── runtime_context.py # Environment awareness
│   │   ├── json_utils.py   # JSON validation and extraction
│   │   └── __init__.py
│   │
│   ├── memory/             # Memory Layer
│   │   ├── project_memory.py      # Project memory storage
│   │   ├── project_manager.py     # Memory management
│   │   ├── experience_memory.py   # Experience-based lessons (NEW)
│   │   ├── engineering_lessons.py # Development lessons (NEW)
│   │   └── __init__.py
│   │
│   ├── brain/              # Conversation & State
│   │   ├── state.py        # Conversation state with persistence
│   │   └── __init__.py
│   │
│   ├── editing/            # Editing Layer
│   │   ├── patch_engine.py    # Patch application with rollback
│   │   ├── patch_generator.py # LLM-powered patch generation
│   │   └── __init__.py
│   │
│   ├── verification/       # Verification Layer
│   │   ├── runner.py       # Test/py_compile execution
│   │   ├── repair_loop.py   # Iterative fix-and-verify
│   │   └── __init__.py
│   │
│   ├── rag/                # RAG Layer
│   │   └── __init__.py     # SimpleRetriever (lexical + symbol + snippets)
│   │
│   ├── retrieval/          # Retrieval Layer (NEW)
│   │   ├── enhanced_retriever.py # Lexical + semantic combined
│   │   └── __init__.py
│   │
│   ├── semantic/           # Semantic Layer
│   │   ├── search.py       # Sentence-transformers similarity search
│   │   └── __init__.py
│   │
│   ├── vector_db/          # Vector Database (NEW)
│   │   └── __init__.py     # FAISS-based persistent vector storage
│   │
│   ├── monitoring/         # Monitoring System (NEW)
│   │   ├── system_monitor.py      # System health tracking
│   │   ├── process_monitor.py     # Process tracking
│   │   ├── metric_collector.py    # Metrics collection
│   │   ├── alert_manager.py       # Alert management
│   │   ├── monitoring_report.py   # Report generation
│   │   ├── project_metrics.py     # Project-specific metrics
│   │   └── __init__.py
│   │
│   ├── diagnostics/        # Diagnostics System (NEW)
│   │   ├── issue.py               # Issue dataclasses and enums
│   │   ├── code_analyzer.py       # Code quality analysis
│   │   ├── diagnostic_engine.py   # Configurable checks
│   │   ├── diagnostic_report.py   # Report generation
│   │   └── __init__.py
│   │
│   ├── planner/            # Planner System (NEW)
│   │   ├── task.py               # Task dataclasses and enums
│   │   ├── task_graph.py         # Dependency management
│   │   ├── scheduler.py          # Task scheduling
│   │   ├── resource_allocator.py # Resource management
│   │   ├── progress_tracker.py   # Progress monitoring
│   │   ├── plan_visualizer.py    # Plan visualization
│   │   ├── plan_manager.py       # Plan lifecycle management
│   │   └── __init__.py
│   │
│   ├── reviewer/           # Reviewer System (NEW)
│   │   ├── review_request.py     # ReviewRequest dataclass
│   │   ├── review.py             # Review dataclasses and enums
│   │   ├── reviewer_assigner.py  # Assign reviewers
│   │   ├── review_tracker.py     # Track reviews
│   │   ├── review_manager.py     # Manage reviews
│   │   ├── checklist.py          # Review criteria checklists
│   │   └── __init__.py
│   │
│   ├── risk/               # Risk Assessment System (NEW)
│   │   ├── risk_item.py          # RiskItem dataclass
│   │   ├── risk_assessment.py    # Assessment dataclasses
│   │   ├── risk_analyzer.py      # Risk analysis
│   │   ├── risk_register.py      # Risk tracking
│   │   ├── risk_mitigation.py    # Mitigation tracking
│   │   ├── risk_metrics.py       # RiskMetrics dataclass
│   │   └── __init__.py
│   │
│   ├── confidence/         # Confidence Scoring System (NEW)
│   │   ├── confidence_model.py   # ConfidenceModel dataclass
│   │   ├── confidence_scoring.py # Scoring classes and enums
│   │   └── __init__.py
│   │
│   ├── benchmarking/       # Benchmarking System (NEW)
│   │   ├── benchmark.py          # Benchmark dataclasses
│   │   ├── benchmark_runner.py   # Benchmark execution
│   │   ├── benchmark_store.py    # Results storage
│   │   └── __init__.py
│   │
│   ├── documentation/      # Documentation System (NEW)
│   │   ├── doc_generator.py      # Template-based generation
│   │   ├── doc_template.py        # Template management
│   │   ├── doc_store.py          # Documentation storage
│   │   ├── change_log.py         # Changelog management
│   │   └── __init__.py
│   │
│   ├── backlog/            # Backlog System (NEW)
│   │   ├── improvement_backlog.py # Improvement tracking
│   │   └── __init__.py
│   │
│   ├── health/             # Health Dashboard System (NEW)
│   │   ├── health_dashboard.py   # Dashboard visualization
│   │   ├── health_metrics.py     # Health metrics
│   │   ├── health_monitor.py     # Health monitoring
│   │   ├── health_report.py      # Report generation
│   │   └── __init__.py
│   │
│   ├── tools/              # Legacy Tools (partially redundant)
│   │   ├── git_tools.py
│   │   ├── http_tools.py
│   │   └── format_tools.py
│   │
│   └── ui/                 # User Interface
│       ├── permission_menu.py # Permission prompts
│       └── __init__.py
│
├── data/                   # Persistent Data
│   ├── memory/             # Project memory storage
│   ├── vector_db/          # FAISS vector database
│   └── semantic_cache/     # Embedding cache
│
├── tests/                  # Test Suite (26+ test files)
│
├── docs/                   # Documentation
│
└── main.py                 # Entry point
```

---

# Architecture Layers

## Layer 1: Provider Abstraction (`app/providers/`)

The foundation layer for LLM communication. Provides a unified interface for multiple LLM providers with automatic health checking and timeout support.

**Key Features:**
- Abstract base class (BaseLLMProvider)
- Dynamic provider creation (ProviderFactory)
- Health monitoring (ProviderHealthChecker)
- Timeout configuration
- Ollama implementation (full HTTP client, streaming, model listing)
- Extensible for Claude, GPT, Gemini, DeepSeek

**Data Flow:**
```
ProviderFactory
    ↓
BaseLLMProvider (interface)
    ↓
OllamaProvider (concrete)
    ↓
LLM responses
```

---

## Layer 2: Core Utilities (`app/core/`)

The foundational utilities that all other layers depend on.

**Key Features:**
- Environment-based configuration
- Structured logging (file + console)
- Event bus (pub/sub pattern)
- Tool execution with safety restrictions
- Project indexing (file discovery)
- Symbol indexing (AST-based Python parsing)

---

## Layer 3: Intelligence (`app/intelligence/` + `app/semantic/` + `app/retrieval/`)

Project awareness and code understanding systems.

**Data Flow:**
```
User Query
    ↓
Keyword Extraction
    ↓
FileLocator (symbol-based lookup)
    ↓
LexicalSearch (TF-like scoring)
    ↓
SemanticSearch (embedding similarity)
    ↓
EnhancedRetriever (60% lexical + 40% semantic)
    ↓
DependencyGraph (import relationship expansion)
    ↓
Relevant Context → LLM
```

**Key Features:**
- Lexical search: task terms, identifiers, filenames, source text, docstrings
- Semantic search: all-MiniLM-L6-v2 (384 dimensions)
- Enhanced retrieval: weighted combination with deduplication
- Dependency graph: AST-based import parsing
- Embedding cache: `.semantic_cache/` for performance
- Vector DB: FAISS with adaptive indexing

---

## Layer 4: Capability Routing (`app/capabilities/` + `app/intent/`)

Direct answer system that bypasses the LLM for known queries.

**Data Flow:**
```
User Query
    ↓
RuntimeContext (environment detection)
    ↓
IntentClassifier (8 intent types)
    ↓
CapabilityRouter (pattern + keyword matching)
    ↓
[if match] → Execute Capability → Return Result
    ↓
[no match] → Continue to LLM pipeline
```

**Key Features:**
- 8 intent types: CHAT, QUESTION, TASK, FILE_OPERATION, CODE_TASK, SYSTEM_STATUS, TOOL_REQUEST, GIT_OPERATION
- 15 direct-answer capabilities (system info, git status, memory, etc.)
- JSON robustness utilities (validation, extraction, retry)
- Environment awareness (OS, shell, Python version, working directory)
- **Conditional Runtime Context Injection**: Runtime context is only included for engineering-related intents (TASK, FILE_OPERATION, CODE_TASK, TOOL_REQUEST, GIT_OPERATION) to help generate appropriate environment-specific commands. Non-engineering intents (CHAT, QUESTION, SYSTEM_STATUS) do not receive runtime context.

---

## Layer 5: Agent Core (`app/agent/`)

The main agent logic and orchestration layer.

**Data Flow (Current):**
```
User Request
    ↓
Intent Classification (Layer 4)
    ↓
Capability Router (Layer 4) --(match)--> Direct Answer
    ↓
[no capability match]
    ↓
Tool Selection
    ↓
Project Intelligence (Layer 3)
    ↓
Context Building (relevant files only)
    ↓
LLM (with Conditional Runtime Context)
    ↓
Response or Action Execution
    ↓
Verification (if applicable)
```

**Components:**
- CoreAgent: Main request processing
- Planner: Task planning and scheduling
- Executor: Action execution with tool calls
- ToolCaller: Tool invocation management
- Brain: Agent state and memory management

---

## Layer 6: Memory (`app/memory/` + `app/brain/`)

Persistent and session-based memory systems.

**Systems:**
- ProjectMemory: Bounded (200 entries) task/decision/verification storage
- ConversationState: Multi-turn conversation with persistence
- ExperienceMemory: Read-only lessons learned
- EngineeringLessons: Development experience documentation
- Vector DB: Persistent embeddings for semantic memory

**Key Features:**
- Keyword search
- Semantic similarity search
- Context generation for LLM prompts
- Auto-save/load with persistence
- FAISS-based vector storage with adaptive indexing

---

## Layer 7: Editing (`app/editing/`)

Code modification with safety and verification.

**Data Flow:**
```
LLM Request for Code Change
    ↓
PatchGenerator (LLM-powered)
    ↓
PatchEngine validation
    ↓
Dry run verification
    ↓
User approval (if mutation)
    ↓
Atomic patch application
    ↓
Snapshot saved for rollback
    ↓
Verification (pytest, py_compile)
    ↓
[success] Commit
    ↓
[failure] Automatic rollback
```

**Key Features:**
- Create and replace actions (no delete yet)
- JSON-based patch format
- Transactional apply_and_verify
- Snapshot-based rollback
- Repair loop with max attempts

---

## Layer 8: Verification (`app/verification/`)

Automated testing and quality assurance.

**Components:**
- VerificationRunner: pytest and py_compile execution
- RepairLoop: Iterative fix-and-verify with rollback

**Key Features:**
- No shell exposure to LLM
- Timeout handling (120 seconds default)
- Dry run before mutation
- Feedback incorporation between attempts

---

## Layer 9: Quality Systems

### Monitoring (`app/monitoring/`)
System health and performance tracking.

**Components:**
- SystemMonitor: Health checks and metrics
- ProcessMonitor: Process tracking
- MetricCollector: Various system metrics
- AlertManager: Severity levels and deduplication
- MonitoringReport: Report generation
- ProjectMetricsCollector: Project-specific metrics

### Diagnostics (`app/diagnostics/`)
Code quality and issue detection.

**Components:**
- CodeAnalyzer: Configurable code quality checks
- DiagnosticEngine: Orchestrates analysis
- DiagnosticReport: Results presentation

**Checks:**
- Unused imports
- Unreachable code
- Empty blocks
- Long functions (>100 lines)
- Complex functions (cyclomatic complexity >10)
- Missing docstrings
- Missing type hints
- Bare except clauses
- Hardcoded secrets

---

## Layer 10: Planning & Review

### Planner (`app/planner/`)
Task planning and scheduling infrastructure.

**Components:**
- Task: TaskStatus, TaskPriority, TaskCategory enums
- TaskGraph: Dependency management
- Scheduler: Task scheduling
- ResourceAllocator: Resource management
- ProgressTracker: Progress monitoring
- PlanVisualizer: Plan visualization
- PlanManager: Plan lifecycle management

### Reviewer (`app/reviewer/`)
Code review management.

**Components:**
- ReviewRequest: Request dataclass
- Review: ReviewDecision enum, ReviewComment, Review dataclass
- ReviewerAssigner: Assign reviewers
- ReviewTracker: Track reviews
- ReviewManager: Manage reviews
- Checklist: Review criteria

---

## Layer 11: Risk & Confidence

### Risk Assessment (`app/risk/`)
Risk identification and mitigation.

**Components:**
- RiskItem: Risk dataclass
- RiskAssessment: Assessment dataclasses
- RiskAnalyzer: Risk analysis
- RiskRegister: Risk tracking
- RiskMitigation: Mitigation tracking
- RiskMetrics: Metrics dataclass

### Confidence Scoring (`app/confidence/`)
Confidence tracking for LLM responses.

**Components:**
- ConfidenceModel: Confidence dataclass
- ConfidenceLevel: LOW, MEDIUM, HIGH, VERY_HIGH
- ConfidenceEventType: Event classification
- ConfidenceEvent: Event tracking
- ConfidenceScore: Scoring dataclass
- ConfidenceCalculator: Scoring logic
- ConfidenceTracker: Historical tracking

---

## Layer 12: Benchmarking & Documentation

### Benchmarking (`app/benchmarking/`)
Performance measurement framework.

**Components:**
- Benchmark: BenchmarkStatus, BenchmarkMetric enums
- BenchmarkResult, Benchmark, BenchmarkSuite dataclasses
- TimingBenchmark: Time-based benchmarks
- AccuracyBenchmark: Accuracy-based benchmarks
- MultiMetricBenchmark: Multiple metrics
- BenchmarkRunner: Execution engine
- BenchmarkStore: Results storage

### Documentation (`app/documentation/`)
Documentation generation and management.

**Components:**
- DocumentationGenerator: Template-based generation
- DocTemplate: Template management
- DocStore: Documentation storage
- ChangeLog: Changelog management

---

## Layer 13: Backlog & Health

### Backlog (`app/backlog/`)
Improvement tracking.

**Components:**
- ImprovementItem: Priority, status, type tracking
- ImprovementBacklog: Backlog management

### Health Dashboard (`app/health/`)
Project health monitoring and reporting.

**Components:**
- HealthDashboard: Visualization
- HealthMetrics: Metrics collection
- HealthMonitor: Monitoring
- HealthReport: Report generation

---

# Data Flow Summary

The complete Freya request processing pipeline:

```
┌─────────────────────────────────────────────────────────────┐
│                        USER REQUEST                            │
└─────────────────────────────────────────────────────────────┘
                                    │
                                    ↓
┌─────────────────────────────────────────────────────────────┐
│                    RUNTIME CONTEXT                            │
│  (OS, Shell, Python Version, Working Directory, Dependencies) │
└─────────────────────────────────────────────────────────────┘
                                    │
                                    ↓
┌─────────────────────────────────────────────────────────────┐
│                    INTENT CLASSIFICATION                       │
│  (CHAT, QUESTION, TASK, FILE_OP, CODE_TASK, SYSTEM_STATUS,   │
│   TOOL_REQUEST, GIT_OPERATION)                                 │
└─────────────────────────────────────────────────────────────┘
                                    │
                                    ↓
┌─────────────────────────────────────────────────────────────┐
│                    CAPABILITY ROUTER                          │
│  (15 direct-answer capabilities: system info, git status,   │
│   memory usage, ollama status, etc.)                          │
└─────────────────────────────────────────────────────────────┘
                                    │
               ┌────────────────────┴────────────────────┐
               │                                         │
               ↓                                         ↓
┌─────────────────────┐           ┌────────────────────────────┐
│   DIRECT ANSWER     │           │       LLM PIPELINE          │
│   (bypass LLM)      │           │                            │
└─────────────────────┘           │  ┌─────────────────────┐   │
                                     │  │ TOOL SELECTION     │   │
                                     │  │ (rule-based +     │   │
                                     │  │  LLM fallback)     │   │
                                     │  └─────────┬─────────┘   │
                                     │            ↓             │
                                     │  ┌─────────────────────┐   │
                                     │  │ PROJECT INTELLIGENCE│   │
                                     │  │ (FileLocator +     │   │
                                     │  │  LexicalSearch +    │   │
                                     │  │  SemanticSearch +   │   │
                                     │  │  EnhancedRetriever) │   │
                                     │  └─────────┬─────────┘   │
                                     │            ↓             │
                                     │  ┌─────────────────────┐   │
                                     │  │  RELEVANT CONTEXT   │   │
                                     │  │  (filtered files    │   │
                                     │  │   only)            │   │
                                     │  └─────────┬─────────┘   │
                                     │            ↓             │
                                     │  ┌─────────────────────┐   │
                                     │  │      LLM            │   │
                                     │  │  (with context +    │   │
                                     │  │   runtime context)  │   │
                                     │  └─────────┬─────────┘   │
                                     │            ↓             │
                                     │  ┌─────────────────────┐   │
                                     │  │   RESPONSE /        │   │
                                     │  │   ACTION EXECUTION  │   │
                                     │  └─────────┬─────────┘   │
                                     │            ↓             │
                                     │  ┌─────────────────────┐   │
                                     │  │   VERIFICATION      │   │
мите                                 │  │   (if applicable)   │   │
                                     │  └─────────────────────┘   │
                                     └────────────────────────────┘
```

---

# Key Architectural Principles

1. **Modularity**: Each system is self-contained with clear interfaces
2. **Separation of Concerns**: Distinct layers handle different responsibilities
3. **Extensibility**: New providers, capabilities, and checks can be added without modifying core code
4. **Safety**: Mutations require explicit user approval; workspace restrictions prevent escape
5. **Persistence**: Memory, vectors, and metrics are persisted to disk
6. **Code-First**: The codebase is the source of truth; documentation follows implementation

---

# Future Architecture Evolution

1. **Context Builder v2**: Symbol-level context extraction
2. **Enhanced Patch System**: CLI workflow, delete operation, line-based editing
3. **Self-Improvement**: Learning from past decisions, online learning
4. **Additional Providers**: Claude, GPT, Gemini, DeepSeek implementations
5. **Web Search**: Internet search capability
6. **Token Counting**: LLM token usage tracking
7. **Rate Limiting**: Request rate management
8. **Git Authentication**: Secure git operations
9. **Streaming Responses**: Real-time LLM output
10. **Background Tasks**: Asynchronous task processing
