# Freya Capability Roadmap

> **Status:** v0.4.0 - Foundation Complete (Critical Fixes Needed)
> **Last Updated:** 2026-07-26
> **Current State:** All foundation systems implemented, 3 critical bugs identified, release readiness assessment complete

---

## Current State

### COMPLETED Core Implementation

Freya has achieved a **feature-complete core implementation** with all major foundation systems operational (25+ modules, 127+ files):

| # | Feature | Status | Module | Description |
|---|---------|--------|--------|-------------|
| 1 | **Core Utilities** | COMPLETE | app/core/ | Config, logger, events, tool_manager, project/symbol indexing |
| 2 | **Intelligence Layer** | COMPLETE | app/intelligence/ | File locator, context builder, dependency graph, lexical search |
| 3 | **Semantic Search** | COMPLETE | app/semantic/ | Embedding-based search with all-MiniLM-L6-v2 + FAISS |
| 4 | **Retrieval Layer** | COMPLETE | app/rag/ | Enhanced retriever (lexical + semantic hybrid) |
| 5 | **Intent Classification** | COMPLETE | app/intent/ | 8 intent types with pattern + keyword matching |
| 6 | **Capability Routing** | COMPLETE | app/capabilities/ | 15+ direct-answer handlers bypassing LLM |
| 7 | **Agent Core Pipeline** | COMPLETE | app/agent/ | FreyaAgent, Planner, Executor, ToolManager |
| 8 | **Memory Layer** | COMPLETE | app/memory/ | ProjectMemory, ExperienceMemory, EngineeringLessons, VectorDB |
| 9 | **Editing Layer** | COMPLETE | app/editing/ | PatchGenerator, PatchEngine with rollback |
| 10 | **Verification Layer** | COMPLETE | app/verification/ | VerificationRunner (pytest), RepairLoop |
| 11 | **Monitoring Layer** | COMPLETE | app/monitoring/ | SystemMonitor, MetricCollector, AlertManager |
| 12 | **Diagnostics Layer** | COMPLETE | app/diagnostics/ | CodeAnalyzer, DiagnosticEngine, 7 quality checks |
| 13 | **Planner System** | COMPLETE | app/planner/ | Task graph, scheduler, resource allocator, progress tracker, visualizer |
| 14 | **Risk Assessment** | COMPLETE | app/risk/ | RiskAssessor, mitigation tracking |
| 15 | **Confidence Scoring** | COMPLETE | app/confidence/ | Confidence calibration, tracking |
| 16 | **Benchmarking** | COMPLETE | app/benchmarking/ | Timing, accuracy, multi-metric benchmarks |
| 17 | **Documentation Gen** | COMPLETE | app/documentation/ | AST-based, templates, markdown output |
| 18 | **Git Automation** | COMPLETE | app/git/ | Semantic commits, change tracking, branch mgmt |
| 19 | **Provider Abstraction** | PARTIAL | app/providers/ | Base + Ollama only (needs Claude/GPT/Gemini) |
| 20 | **Reviewer System** | COMPLETE | app/reviewer/ | Review workflow, assignments, checklists, metrics |
| 21 | **Improvement Backlog** | COMPLETE | app/backlog/ | Priority scoring, dependency tracking |
| 22 | **Capability Audit** | COMPLETE | app/audit/ | Automated auditing, capability registry, reports |
| 23 | **Health/Observability** | COMPLETE | app/health/ | Health dashboard, metrics, system monitoring |

### 15+ Direct-Answer Capabilities (COMPLETE)
- python_version, os_info, shell_info, working_directory
- memory_usage, disk_usage, internet_connectivity, running_processes
- ollama_status, current_model, provider_info, git_status
- system_health, current_time

---

## CRITICAL BLOCKING ISSUES (Must Fix Before Release)

| # | Issue | Severity | Location | Fix Required |
|---|-------|----------|----------|--------------|
| 1 | **Legacy ToolCaller maps reasoning words to tools** | CRITICAL | `app/agent/tool_caller.py` | DELETE FILE - maps "explain", "analyze", "review", "describe" → list_files |
| 2 | **Duplicate ProjectMemory implementations** | CRITICAL | `app/memory/project_memory.py` + `project_manager.py` | Merge into single source of truth |
| 3 | **Duplicate tool implementations** | HIGH | `app/tools/file_tools.py`, `edit_tools.py` | Delete (duplicates in tool_manager) |
| 4 | **Duplicate TOOL_MAPPING in Executor** | HIGH | `app/agent/executor.py` | Remove duplicated terminal/HTTP/git sections |
| 5 | **Capability registry out of date** | HIGH | `app/audit/capability_registry.py` | 17 foundation systems marked NOT_IMPL but implemented |

---

## v0.4.1 - Critical Bug Fixes (THIS WEEK - Blocking Release)

| Priority | Task | Module | Effort | Owner |
|----------|------|--------|--------|-------|
| P0-CRITICAL | **DELETE `app/agent/tool_caller.py`** | agent | 15 min | - |
| P0-CRITICAL | **Merge ProjectMemory implementations** | memory | 2 hrs | - |
| P0-HIGH | **DELETE `app/tools/file_tools.py` and `edit_tools.py`** | tools | 15 min | - |
| P0-HIGH | **Remove duplicate TOOL_MAPPING sections in executor.py** | agent | 30 min | - |
| P0-HIGH | **Update capability_registry.py: mark 17 foundation systems as IMPLEMENTED** | audit | 30 min | - |
| P1-HIGH | Add timeout handling for LLM calls in Executor | agent | 1 hr | - |
| P1-HIGH | Add JSON Schema validation for Planner output | planner | 2 hrs | - |

### Validation Criteria (v0.4.1)
- [ ] All 5 critical issues resolved
- [ ] All existing tests pass (`pytest tests/ -v`)
- [ ] No duplicate classes in memory module
- [ ] No legacy tool_caller references anywhere
- [ ] Capability audit shows >90% implemented

---

## v0.4.2 - Quality & Completeness (Week 2)

| Priority | Task | Module | Effort |
|----------|------|--------|--------|
| P1 | Multi-provider LLM (Claude, OpenAI, Gemini adapters) | providers | 16 hrs |
| P1 | Structured logging (JSON format) | core/logger | 4 hrs |
| P1 | Health check endpoint / capability | core | 2 hrs |
| P2 | Add delete action to PatchEngine | editing | 2 hrs |
| P2 | ExperienceMemory integration with Agent | memory/agent | 8 hrs |
| P2 | EngineeringLessons integration with Planner | memory/planner | 8 hrs |
| P2 | Streaming LLM responses | core/llm | 8 hrs |
| P3 | API documentation generation | documentation | 4 hrs |
| P3 | README.md with quickstart | docs | 2 hrs |
| P3 | Add tests for: planner, diagnostics, monitoring, risk, confidence, backlog, reviewer, capabilities, benchmarking, documentation, git | tests | 24 hrs |

---

## v0.5.0 - Feature Completion (Month 1)

| Priority | Feature | Module | Effort |
|----------|---------|--------|--------|
| P1 | AST-based Refactoring (rename, extract, inline) | editing | 40 hrs |
| P1 | Cross-file symbol resolution / call graph | intelligence | 24 hrs |
| P1 | Parallel task execution in Executor | agent | 16 hrs |
| P2 | Impact analysis for changes | intelligence | 16 hrs |
| P2 | Test filtering & coverage reporting | verification | 8 hrs |
| P2 | Mutation testing integration | verification | 16 hrs |
| P3 | Plugin system for capabilities | core | 24 hrs |
| P3 | Distributed tracing (OpenTelemetry) | monitoring | 16 hrs |
| P3 | Agent spawning / sub-agent delegation | agent | 24 hrs |

---

## v0.6.0 - Production Hardening (Month 2)

| Feature | Area | Effort |
|---------|------|--------|
| Comprehensive integration tests | testing | 32 hrs |
| Chaos engineering / fault injection | testing | 16 hrs |
| Performance benchmarks & SLAs | benchmarking | 16 hrs |
| Security audit (secrets, injection) | diagnostics | 16 hrs |
| GDPR/compliance data handling | memory | 8 hrs |
| Migration/upgrade tooling | git | 8 hrs |

---

## v1.0.0 - General Availability (Month 3)

| Milestone | Criteria |
|-----------|----------|
| **Stable API** | No breaking changes for 4 weeks |
| **Full test coverage** | >80% unit, >60% integration |
| **Documentation complete** | API ref, architecture, guides, ADR log |
| **Multi-provider GA** | Ollama, Claude, OpenAI, Gemini all tested |
| **Plugin ecosystem** | 3+ community plugins |
| **Production deployments** | 3+ verified production users |

---

## Key Architectural Decisions (ADR Log)

> **Note:** These should be formalized into `docs/adr/`

| ADR | Decision | Date | Status |
|-----|----------|------|--------|
| 001 | Patch-based editing (not direct file writes) | 2026-01 | ACCEPTED |
| 002 | Ollama-only LLM provider for v0.x | 2026-01 | ACCEPTED |
| 003 | Intent classification with 8 types | 2026-01 | ACCEPTED |
| 004 | Executor uses keyword mapping + LLM fallback | 2026-01 | ACCEPTED |
| 005 | FAISS for vector storage (not cloud) | 2026-01 | ACCEPTED |
| 006 | ExperienceMemory is READ-ONLY (no writes) | 2026-07 | ACCEPTED |
| 007 | Capability router for direct answers | 2026-07 | ACCEPTED |
| 008 | New Planner: TaskGraph + Scheduler + ResourceAllocator | 2026-07 | ACCEPTED |
| 009 | Remove ToolCaller (legacy, buggy) | 2026-07-26 | PROPOSED |

---

## Testing Status

| Test Suite | Status | Coverage | Notes |
|------------|--------|----------|-------|
| test_executor.py | ✅ PASS | ~85% | Tool selection mappings |
| test_tool_manager.py | ✅ PASS | ~80% | Tool execution safety |
| test_events.py | ✅ PASS | ~70% | Event bus |
| test_verification_runner.py | ✅ PASS | ~75% | pytest, py_compile |
| test_patch_engine.py | ✅ PASS | ~80% | Patch apply/verify/rollback |
| test_project_memory.py | ✅ PASS | ~70% | Memory CRUD |
| test_project_intelligence.py | ✅ PASS | ~70% | Intelligence layer |
| test_patch_generator.py | ✅ PASS | ~65% | LLM patch generation |
| test_rag.py | ✅ PASS | ~60% | Retrieval (requires sentence-transformers) |
| **MISSING: planner** | ❌ | 0% | High priority |
| **MISSING: diagnostics** | ❌ | 0% | High priority |
| **MISSING: monitoring** | ❌ | 0% | High priority |
| **MISSING: risk, confidence, backlog** | ❌ | 0% | Medium priority |
| **MISSING: reviewer, capabilities** | ❌ | 0% | Medium priority |
| **MISSING: benchmarking, docs, git** | ❌ | 0% | Medium priority |
| **MISSING: full integration** | ❌ | 0% | Critical for v0.5.0 |

---

## Documentation Status

| Document | Status | Location | Priority |
|----------|--------|----------|----------|
| README.md | ❌ MISSING | root | **P0** |
| PROJECT_OVERVIEW.md | ✅ EXISTS | docs/ | - |
| ARCHITECTURE.md | ❌ MISSING | docs/ | P1 |
| API Reference | ❌ MISSING | docs/api/ | P1 |
| ADR Log | ❌ MISSING | docs/adr/ | P1 |
| Contribution Guide | ❌ MISSING | CONTRIBUTING.md | P2 |
| Changelog | ✅ EXISTS | docs/changelog.md | - |
| Quickstart Guide | ❌ MISSING | docs/quickstart.md | P1 |

---

## Release Readiness Checklist

| Criterion | v0.4.1 | v0.5.0 | v1.0.0 |
|-----------|--------|--------|--------|
| Critical bugs fixed | ☐ | ✅ | ✅ |
| All tests pass | ☐ | ✅ | ✅ |
| Test coverage >70% | ☐ | ☐ | ✅ |
| API stable | ☐ | ☐ | ✅ |
| Multi-provider | ☐ | ☐ | ✅ |
| Documentation complete | ☐ | ☐ | ✅ |
| ADR log exists | ☐ | ☐ | ✅ |
| No TODO/FIXME in core | ☐ | ☐ | ✅ |

---

*Roadmap updated per Comprehensive Engineering Audit (2026-07-26)*

---

## Phase 2: Better Tool Selection - COMPLETED
### Improved Tool Selection Quality (2026-07-25)
| # | Enhancement | Status | Module | Description |
|---|-------------|--------|--------|-------------|
| 1 | **Enhanced Tool Mapping** | COMPLETE | app/agent/executor.py | Added comprehensive keyword-to-tool mappings for common software engineering tasks |
| 2 | **Direct Tool Selection** | COMPLETE | app/agent/executor.py | Direct keyword mapping bypasses LLM for common patterns, improving speed and consistency |
| 3 | **Improved Logging** | COMPLETE | app/agent/executor.py | Detailed logging of every tool-selection decision with reasoning |
| 4 | **Least Powerful Tool** | COMPLETE | app/agent/executor.py | Preference for simplest tool capable of completing the task |
| 5 | **Avoid Unnecessary Terminal** | COMPLETE | app/agent/executor.py | run_terminal only used when actually required (build, test, install) |
| 6 | **Unit Tests** | COMPLETE | tests/test_executor.py | Comprehensive test suite for tool selection validation |

---
## Next Priority Features (v0.9.0)

### Priority 1: Enhanced Patch System
- **Status:** PENDING
- **Description:** Formal patch review object with CLI workflow
- **Deliverables:**
  - PatchReview dataclass
  - CLI commands: propose, preview, approve, apply, verify
  - Delete operation support
  - Line-based editing
  - End-to-end tests with stub LLM
- **Estimated Complexity:** Medium
- **Dependencies:** None

### Priority 2: AST-based Refactoring
- **Status:** PENDING
- **Description:** Safe code transformations using Abstract Syntax Trees
- **Deliverables:**
  - AST-based refactoring module
  - Integration with FreyaAgent
  - Support for common refactoring operations
  - Preservation of code semantics and formatting
  - Edge case handling (comments, whitespace, encoding)
  - libcst integration for safer modifications
- **Estimated Complexity:** Medium-High
- **Dependencies:** None

### Priority 3: Watch Mode
- **Status:** PENDING
- **Description:** Monitor file changes and provide real-time feedback
- **Deliverables:**
  - File system watcher
  - Real-time code analysis
  - Instant feedback on changes
  - Configurable triggers
- **Estimated Complexity:** Medium
- **Dependencies:** None

---

## Future Enhancements (v1.0.0+)

### v0.9.0 - QA & Polish
- [ ] Enhanced Patch System (Priority 1)
- [ ] AST-based Refactoring (Priority 2)
- [ ] Watch Mode (Priority 3)
- [ ] Build System Integration (CMake, Bazel, Makefile)
- [ ] Self-learning from Decisions
- [ ] Test Generation Framework

### v1.0.0 - Production Ready
- [ ] Token Counting for LLM requests
- [ ] Rate Limiting for LLM providers
- [ ] Streaming Responses from LLM
- [ ] Background Task Processing
- [ ] Git Authentication Support
- [ ] Additional LLM Providers (Claude, GPT, Gemini, DeepSeek)
- [ ] Web Search Capability
- [ ] GUI Interface (Optional)
- [ ] Voice Interface (Optional)

---

## Architecture Evolution Checklist

### Context Builder v2
- [ ] Full transitive dependency graph
- [ ] Improved symbol-level context extraction
- [ ] Better relevance scoring
- [ ] Context caching for performance

### Enhanced Patch System
- [ ] Formal patch review object
- [ ] CLI workflow integration
- [ ] Delete operation support
- [ ] Line-based editing
- [ ] End-to-end test coverage

### Self-Improvement
- [ ] Learning from past decisions
- [ ] Pattern recognition in solutions
- [ ] Autonomous goal detection
- [ ] Online learning capabilities

### Provider Expansions
- [ ] Claude provider implementation
- [ ] OpenAI GPT provider implementation
- [ ] Gemini provider implementation
- [ ] DeepSeek provider implementation
- [ ] Streaming support for all providers

---

## Current Metrics

- **Total Modules:** 28+ distinct modules
- **Total Python Files:** 100+ source files
- **Test Files:** 26+ test files
- **Test Results:** 104+ tests passing
- **Lines of Code:** 10000+ estimated
- **Documentation:** 10+ documentation files
- **Coverage:** Comprehensive

---

## Development Guidelines

### For Continuing Work

1. **Review Current State**
   ```bash
   git log --oneline -10
   git status
   pytest tests/ --basetemp=C:/temp/pytest -v
   ```

2. **Follow Existing Patterns**
   - Use type hints
   - Add docstrings
   - Follow naming conventions
   - Add comprehensive tests

3. **Maintain Backward Compatibility**
   - New features should be optional
   - Default parameters maintain existing behavior
   - All existing tests must continue to pass

4. **Update Documentation**
   - Update docs/PROJECT_OVERVIEW.md for major changes
   - Update docs/ARCHITECTURE.md for architectural changes
   - Add usage examples in docs/
   - Update ROADMAP.md after completion

5. **Commit Conventions**
   - Use semantic commit messages
   - Reference related issues
   - Include co-authorship where applicable

---

## How to Proceed

### 1. Pick Next Roadmap Item
The next priority items are:
1. **Enhanced Patch System** (v0.9.0 Priority 1)
2. **AST-based Refactoring** (v0.9.0 Priority 2)
3. **Watch Mode** (v0.9.0 Priority 3)

### 2. During Implementation
- Follow patterns established in existing code
- Maintain backward compatibility
- Add tests for all new functionality
- Update documentation as you go

### 3. After Completion
- Update this ROADMAP.md
- Update commit history
- Verify all tests pass
- Document any limitations

---

*Current status: All core systems operational. Ready for v0.9.0 feature development.*
