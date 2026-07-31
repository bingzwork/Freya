# Resource Management

## Status
🟢 **Mostly Implemented** (≈ 70 % complete)

## Overview
Resource Management provides the foundation for Freya to monitor, allocate, and schedule system resources (CPU, memory, disk, network, GPU, and external services) used during planning, execution, and learning. Accurate resource awareness enables smarter decision‑making, prevents OOM or rate‑limit failures, and supports future autonomous operation.

## Current Implementation Summary
| Capability | Status | Approx. Completion |
|-----------|--------|--------------------|
| **System Resource Monitoring** | ✅ Complete | 100 % |
| **Process Monitoring** | ✅ Complete | 100 % |
| **Resource Allocator** (Planner) | ✅ Complete | 100 % |
| **Resource‑Aware Scheduling** | ✅ Complete | 100 % |
| **GPU/Hardware Detail** | ❌ Not Implemented | 0 % |
| **Network/API Awareness** | ❌ Not Implemented | 0 % |
| **External Service Detection** | ❌ Not Implemented | 0 % |

## What Works Today (✅ Implemented)

### System Resource Monitoring (`app/monitoring/system_monitor.py`)
Continuous background daemon tracking:

- **CPU** – % usage, core count, frequency, load average (Unix)  
- **Memory** – Total/used/free GB, % usage  
- **Disk** – Total/used/free GB, % usage, read/write MB  
- **Network** – Sent/received MB  
- **Processes** – Count, thread count, status, user, I/O  
- **Temperature** – CPU temp (°C) when available  
- **Health Score** – Composite 0‑100 mapped to EXCELLENT/GOOD/WARNING/CRITICAL  

Features: configurable thresholds, alert callbacks, 100‑sample history, health enum.

### Process Monitoring (`app/monitoring/process_monitor.py`)
Per‑process tracking with filtering and project‑aware detection:

- Process info: PID, name, exe, cmdline, status, user, CPU%, memory%, threads, FDs, I/O  
- Filtering by name pattern, user, thresholds, status  
- Auto‑detects project processes (python, pytest, node, docker)  
- Persistent history (100 samples) and utilities to find/kill high‑usage processes.

### Resource Allocator (`app/planner/resource_allocator.py`)
Integrated into the planning/execution pipeline:

- Declares required resources (e.g., `{"MACHINE":1, "TOOL":1}`)  
- Reserves resources before execution, releases after (success/failure)  
- Supports **MACHINE**, **TOOL**, **GPU** slots.

### Resource‑Aware Scheduling (`app/planner/scheduler.py`)
Scheduler strategies incorporate resource availability when ordering tasks, ensuring feasible execution.

## Missing Capabilities (❌ Not Implemented)

| Capability | Why Needed |
|------------|------------|
| **GPU Detection & Metrics** | Detect GPUs, report VRAM, compute capability, utilization, temperature | Enables model selection and OOM avoidance |
| **Network/API Awareness** | Check internet connectivity, ping endpoints, detect health of Ollama, OpenAI, GitHub, etc. | Prevents hanging tool calls and supports failover |
| **External Service Registry** | Detect/configure databases, message queues, MCP servers | Planning tasks that depend on external services |
| **Unified ResourceManager Facade** | Single `get_snapshot()` aggregating all layers for planning/decision‑making | Simplifies downstream code and ensures consistency |

## Integration Points
- **Executor.execute_plan()** – Queries Resource Allocator for required resources.  
- **Scheduler** – Uses resource‑aware strategies to reorder tasks.  
- **DecisionManager** – Could use risk scores based on resource state (not yet wired).  
- **WorldModel** – Consumes environment snapshots (partially integrated).  

## Remaining Implementation Tasks

### ⭐⭐⭐⭐ High (Major Capabilities)

| Task | Objective | Why It Matters | Dependencies | Success Criteria |
|------|-----------|----------------|--------------|------------------|
| **GPU/Hardware Detail** | Detect GPUs, report VRAM, compute capability, temperature | Enables safe model selection and prevents OOM | System Monitor | `get_gpu_info()` returns model, VRAM, utilization |
| **Network/API Awareness** | Check internet, ping endpoints, detect health of Ollama, OpenAI, etc. | Avoid stalled calls; support automatic failover | System Monitor | `check_connectivity()` returns per‑endpoint status |
| **External Service Registry** | Detect/configure databases, queues, MCP servers | Planning tasks requiring external services | Network/API Awareness | `list_services()` returns configured endpoints |
| **Unified ResourceManager Facade** | Provide single `get_snapshot()` aggregating all layers for planning/decision‑making | Reduces code duplication and ensures consistent state | All above | `ResourceManager.get_snapshot()` completes < 500 ms cold, < 50 ms cached |

### ⭐⭐⭐ Medium (Important Improvements)

| Task | Objective | Why It Matters | Dependencies | Success Criteria |
|------|-----------|----------------|--------------|------------------|
| **Token/Context Management** | Track context usage, trigger summarization before overflow | Prevents context cutoff and preserves important info | LLM provider integration | Auto‑summarize at 80 % of context window |
| **API Quota/Cost Tracking** | Count requests, estimate costs, enforce budgets | Prevent surprise charges or rate‑limit violations | Provider integration | Daily budget alert at 80 % of limit |

### ⭐ Low (Optional Improvements)

| Task | Objective | Why It Matters | Dependencies | Success Criteria |
|------|-----------|----------------|--------------|------------------|
| **Battery/Power Awareness** | Detect laptop battery, adapt workload | Extends autonomous operation to mobile/edge | System Monitor | Pause heavy tasks when < 20 % battery |
| **Thermal Throttling Detection** | Detect sustained high temps, reduce load | Protects hardware longevity | GPU/Hardware Detail | Reduce parallelism at 85 °C |

### ⭐ Future (Long‑Term Ideas)

| Task | Objective |
|------|-----------|
| **Remote Environment Awareness** | Detect SSH/container/K8s resources for distributed execution |
| **Cloud Resource Awareness** | Query AWS/GCP/Azure quotas, limits, and cost data |
| **Collaborative Resource Pool** | Share resource state across multiple agents for coordination |

## Files to Modify (If Extending)

| File | Purpose | Status |
|------|---------|--------|
| `app/monitoring/system_monitor.py` | Add GPU, network, service checks | 🔄 Extend |
| `app/monitoring/__init__.py` | Export new resource APIs | 🔄 Extend |
| `app/planner/resource_allocator.py` | Add GPU resource type, token budget | 🔄 Extend |
| `app/world_model/model.py` | Wire ResourceManager into WorldModel | 🔄 Extend |
| `app/decision/manager.py` | Use resource state in risk assessment | 🔄 Extend |
| `app/resource_manager.py` | **NEW** — Unified facade (if created) | ❌ Create |

## Success Criteria (Definition of Done)

| Criterion | Target | Status |
|-----------|--------|--------|
| `SystemMonitor` reports CPU/Mem/Disk/Net | ✅ | Complete |
| `ProcessMonitor` tracks project processes | ✅ | Complete |
| `ResourceAllocator` integrated in Executor | ✅ | Complete |
| GPU detection + VRAM reporting | ❌ | Not Started |
| Network/API health checks | ❌ | Not Started |
| External service registry | ❌ | Not Started |
| Unified `ResourceManager.get_snapshot()` | ❌ | Not Started |
| Token/context budget tracking | ❌ | Not Started |

---  
*This document serves as the single source of truth for Resource Management design and roadmap. It will be updated as implementation progresses.*