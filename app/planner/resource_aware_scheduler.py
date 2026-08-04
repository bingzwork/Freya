"""Resource-Aware Scheduling for Freya AI.

This module provides scheduling that considers:
- CPU/GPU/RAM availability from system monitoring
- Background job service integration
- Concurrency limits
- Execution cost estimation
- Blocking operation handling
- Execution windows (time-based constraints)
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Dict, List, Any, Optional, Set, Callable
from collections import defaultdict
from pathlib import Path

from app.planner.task import Task, TaskStatus, TaskPriority
from app.planner.task_graph import TaskGraph
from app.planner.resource_allocator import ResourceAllocator, Resource, ResourceType
from app.planner.duration_estimation import DurationEstimator

# Try to import monitoring
try:
    from app.monitoring.gpu_monitor import GPUMonitor
    from app.monitoring.system_monitor import SystemMonitor
    MONITORING_AVAILABLE = True
except ImportError:
    MONITORING_AVAILABLE = False


class ExecutionWindow:
    """Time window when a task can execute."""
    def __init__(
        self,
        start_hour: int = 0,
        end_hour: int = 24,
        days: Optional[List[int]] = None,  # 0=Monday, 6=Sunday
        timezone_str: str = "UTC",
    ):
        self.start_hour = start_hour
        self.end_hour = end_hour
        self.days = days or list(range(7))  # All days by default
        self.timezone_str = timezone_str

    def is_active(self, dt: Optional[datetime] = None) -> bool:
        """Check if the window is active at the given time."""
        check_time = dt or datetime.now(timezone.utc)
        if check_time.tzinfo is None:
            check_time = check_time.replace(tzinfo=timezone.utc)

        hour = check_time.hour
        day = check_time.weekday()

        if day not in self.days:
            return False
        if self.start_hour <= self.end_hour:
            return self.start_hour <= hour < self.end_hour
        else:
            # Overnight window
            return hour >= self.start_hour or hour < self.end_hour

    def next_window_start(self, from_time: Optional[datetime] = None) -> datetime:
        """Get the next window start time."""
        check = from_time or datetime.now(timezone.utc)
        if check.tzinfo is None:
            check = check.replace(tzinfo=timezone.utc)

        for offset in range(7):  # Check next 7 days
            target_day = (check.weekday() + offset) % 7
            if target_day in self.days:
                target = check.replace(hour=self.start_hour, minute=0, second=0, microsecond=0)
                if offset > 0:
                    target += timedelta(days=offset)
                if offset == 0 and check.hour >= self.end_hour:
                    continue
                if target > check or offset > 0:
                    return target
        # Fallback
        return check + timedelta(days=1)


@dataclass
class ResourceConstraint:
    """Constraint on resource usage for a task."""
    resource_type: ResourceType
    min_required: float = 1.0
    preferred: float = 1.0
    max_allowed: Optional[float] = None
    blocking: bool = False  # If true, task waits for resource


@dataclass
class TaskResourceProfile:
    """Resource requirements for a task."""
    task_id: str
    cpu_cores: float = 1.0
    memory_gb: float = 1.0
    gpu_count: int = 0
    gpu_memory_gb: float = 0.0
    storage_gb: float = 0.1
    network_mbps: float = 0.0
    custom_resources: Dict[str, float] = field(default_factory=dict)
    constraints: List[ResourceConstraint] = field(default_factory=list)
    execution_window: Optional[ExecutionWindow] = None
    can_preempt: bool = False
    estimated_cost: float = 0.0  # Cost in arbitrary units

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "cpu_cores": self.cpu_cores,
            "memory_gb": self.memory_gb,
            "gpu_count": self.gpu_count,
            "gpu_memory_gb": self.gpu_memory_gb,
            "storage_gb": self.storage_gb,
            "network_mbps": self.network_mbps,
            "custom_resources": self.custom_resources,
            "constraints": [
                {
                    "resource_type": c.resource_type.value,
                    "min_required": c.min_required,
                    "preferred": c.preferred,
                    "max_allowed": c.max_allowed,
                    "blocking": c.blocking,
                }
                for c in self.constraints
            ],
            "execution_window": {
                "start_hour": self.execution_window.start_hour if self.execution_window else 0,
                "end_hour": self.execution_window.end_hour if self.execution_window else 24,
                "days": self.execution_window.days if self.execution_window else list(range(7)),
            } if self.execution_window else None,
            "can_preempt": self.can_preempt,
            "estimated_cost": self.estimated_cost,
        }


class SystemResourceMonitor:
    """Monitors system resources for scheduling decisions."""

    def __init__(self):
        self._cpu_monitor = None
        self._gpu_monitor = None
        self._memory_monitor = None

        if MONITORING_AVAILABLE:
            try:
                self._cpu_monitor = SystemMonitor()
                self._gpu_monitor = GPUMonitor()
            except Exception:
                pass

    def get_cpu_availability(self) -> float:
        """Get available CPU cores as fraction of total (0-1)."""
        try:
            import psutil
            cpu_percent = psutil.cpu_percent(interval=0.1)
            return max(0.0, 1.0 - (cpu_percent / 100.0))
        except Exception:
            return 0.5  # Default assumption

    def get_memory_availability(self) -> float:
        """Get available memory as fraction of total (0-1)."""
        try:
            import psutil
            mem = psutil.virtual_memory()
            return max(0.0, mem.available / mem.total)
        except Exception:
            return 0.5

    def get_gpu_availability(self) -> List[Dict[str, Any]]:
        """Get GPU availability information."""
        if not self._gpu_monitor:
            return []

        try:
            gpu_metrics = self._gpu_monitor.collect_metrics()
            gpu_info = self._gpu_monitor.get_gpu_info()

            gpu_info_by_index = {g.index: g for g in gpu_info}
            metrics_by_index = {m.index: m for m in gpu_metrics}

            result = []
            for info in gpu_info:
                metrics = metrics_by_index.get(info.index)
                vram_total = info.vram_total_mb / 1024.0 if info.vram_total_mb > 0 else 0
                vram_used = info.vram_used_mb / 1024.0 if info.vram_used_mb > 0 else 0
                vram_free = vram_total - vram_used if vram_total > 0 else 0

                gpu_util = metrics.gpu_utilization_percent if metrics else 0
                available_compute = max(0.0, 100.0 - gpu_util) / 100.0

                result.append({
                    "index": info.index,
                    "name": info.name,
                    "vendor": info.vendor.value,
                    "vram_total_gb": vram_total,
                    "vram_free_gb": vram_free,
                    "compute_available": available_compute,
                    "temperature": metrics.temperature_c if metrics else 0,
                    "power_watts": metrics.power_draw_w if metrics else 0,
                })
            return result
        except Exception:
            return []

    def get_resource_summary(self) -> Dict[str, Any]:
        """Get overall resource availability summary."""
        cpu_avail = self.get_cpu_availability()
        mem_avail = self.get_memory_availability()
        gpus = self.get_gpu_availability()

        return {
            "cpu": {
                "available_fraction": cpu_avail,
                "total_cores": self._get_cpu_count(),
            },
            "memory": {
                "available_fraction": mem_avail,
                "total_gb": self._get_total_memory_gb(),
            },
            "gpu": {
                "count": len(gpus),
                "devices": gpus,
                "avg_compute_available": sum(g["compute_available"] for g in gpus) / len(gpus) if gpus else 0,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _get_cpu_count(self) -> int:
        try:
            import psutil
            return psutil.cpu_count(logical=True) or 1
        except Exception:
            return 1

    def _get_total_memory_gb(self) -> float:
        try:
            import psutil
            return psutil.virtual_memory().total / (1024**3)
        except Exception:
            return 8.0


class ResourceAwareScheduler:
    """Scheduler that considers system resources and constraints."""

    def __init__(
        self,
        graph: Optional[TaskGraph] = None,
        strategy: str = "resource_aware",
        resource_monitor: Optional[SystemResourceMonitor] = None,
        max_concurrent_tasks: int = 4,
        cost_budget: Optional[float] = None,
    ):
        self.graph = graph or TaskGraph()
        self.strategy = strategy
        self.resource_monitor = resource_monitor or SystemResourceMonitor()
        self.max_concurrent_tasks = max_concurrent_tasks
        self.cost_budget = cost_budget

        # Task resource profiles
        self._task_profiles: Dict[str, TaskResourceProfile] = {}

        # Running tasks tracking
        self._running_tasks: Dict[str, Dict[str, Any]] = {}

        # History
        self._schedule_history: List[Dict[str, Any]] = []

        # Duration estimator for cost estimation
        self._duration_estimator = DurationEstimator()

    def register_task_profile(self, profile: TaskResourceProfile) -> None:
        """Register a resource profile for a task."""
        self._task_profiles[profile.task_id] = profile

    def infer_task_profile(self, task: Task) -> TaskResourceProfile:
        """Infer resource profile from task properties."""
        profile = TaskResourceProfile(task_id=task.id)

        # Infer from category
        if task.category.value in ("implementation", "feature", "refactoring"):
            profile.cpu_cores = 2.0
            profile.memory_gb = 4.0
        elif task.category.value in ("testing", "bug_fix"):
            profile.cpu_cores = 1.0
            profile.memory_gb = 2.0
        elif task.category.value in ("deployment",):
            profile.cpu_cores = 1.0
            profile.memory_gb = 1.0
            profile.network_mbps = 100.0
        elif task.category.value in ("research",):
            profile.cpu_cores = 1.0
            profile.memory_gb = 2.0
            profile.network_mbps = 50.0

        # Check for GPU requirements in tags/description
        text = f"{task.title} {task.description}".lower()
        if any(kw in text for kw in ["gpu", "cuda", "ml", "training", "inference", "pytorch", "tensorflow"]):
            profile.gpu_count = 1
            profile.gpu_memory_gb = 8.0

        # Priority affects cost
        priority_cost = {
            TaskPriority.CRITICAL: 10.0,
            TaskPriority.HIGH: 5.0,
            TaskPriority.MEDIUM: 2.0,
            TaskPriority.LOW: 1.0,
        }
        profile.estimated_cost = priority_cost.get(task.priority, 2.0)

        # Duration affects cost
        if task.estimated_hours > 0:
            profile.estimated_cost *= max(1.0, task.estimated_hours / 2.0)

        return profile

    def can_schedule_task(
        self,
        task: Task,
        resource_constraints: Optional[Dict[ResourceType, float]] = None,
    ) -> Tuple[bool, str]:
        """Check if a task can be scheduled given current resources."""
        profile = self._task_profiles.get(task.id) or self.infer_task_profile(task)
        system = self.resource_monitor.get_resource_summary()

        # Check CPU
        cpu_needed = profile.cpu_cores / system["cpu"]["total_cores"]
        if cpu_needed > system["cpu"]["available_fraction"]:
            return False, f"Insufficient CPU: need {cpu_needed:.1%}, available {system['cpu']['available_fraction']:.1%}"

        # Check memory
        mem_needed_gb = profile.memory_gb
        mem_total_gb = system["memory"]["total_gb"]
        mem_needed_frac = mem_needed_gb / mem_total_gb if mem_total_gb > 0 else 1.0
        if mem_needed_frac > system["memory"]["available_fraction"]:
            return False, f"Insufficient memory: need {mem_needed_gb:.1f}GB, available {system['memory']['available_fraction']*mem_total_gb:.1f}GB"

        # Check GPU
        if profile.gpu_count > 0:
            if system["gpu"]["count"] == 0:
                return False, "No GPU available"
            # Check if any GPU has enough memory and compute
            gpu_ok = False
            for gpu in system["gpu"]["devices"]:
                if gpu["vram_free_gb"] >= profile.gpu_memory_gb and gpu["compute_available"] > 0.2:
                    gpu_ok = True
                    break
            if not gpu_ok:
                return False, f"Insufficient GPU: need {profile.gpu_memory_gb}GB VRAM with available compute"

        # Check custom constraints
        if resource_constraints:
            for rtype, available in resource_constraints.items():
                if available < 0.5:
                    return False, f"Resource {rtype.value} constrained ({available:.1%} available)"

        # Check concurrent task limit
        if len(self._running_tasks) >= self.max_concurrent_tasks:
            return False, f"Max concurrent tasks ({self.max_concurrent_tasks}) reached"

        # Check cost budget
        if self.cost_budget is not None:
            current_cost = sum(t.get("profile", {}).get("estimated_cost", 0) for t in self._running_tasks.values())
            if current_cost + profile.estimated_cost > self.cost_budget:
                return False, f"Cost budget exceeded: {current_cost + profile.estimated_cost} > {self.cost_budget}"

        return True, "OK"

    def schedule_tasks(
        self,
        tasks: List[Task],
        start_time: Optional[str] = None,
        resource_constraints: Optional[Dict[ResourceType, float]] = None,
    ) -> Dict[str, Any]:
        """Schedule tasks with resource awareness."""
        if start_time is None:
            start_time = datetime.now(timezone.utc).isoformat()

        start_dt = datetime.fromisoformat(start_time)

        # Build profiles for all tasks
        for task in tasks:
            if task.id not in self._task_profiles:
                self._task_profiles[task.id] = self.infer_task_profile(task)

        # Topological sort for dependencies
        try:
            topo_order = self.graph.topological_sort()
        except Exception:
            topo_order = [t.id for t in tasks]

        # Filter to only our tasks
        task_ids = {t.id for t in tasks}
        topo_order = [tid for tid in topo_order if tid in task_ids]

        # Schedule using resource-aware algorithm
        schedule_items = []
        task_start_times: Dict[str, datetime] = {}
        task_end_times: Dict[str, datetime] = {}
        resource_timeline: Dict[str, List[Tuple[datetime, datetime, str]]] = defaultdict(list)  # resource -> [(start, end, task_id)]

        current_time = start_dt

        for task_id in topo_order:
            task = self.graph.get_task(task_id)
            if not task:
                continue

            profile = self._task_profiles.get(task_id)

            # Calculate earliest start based on dependencies
            dep_end_times = [
                task_end_times.get(dep_id, start_dt)
                for dep_id in task.dependencies
            ]
            dep_start = max(dep_end_times) if dep_end_times else start_dt

            # Find earliest slot considering resource constraints
            scheduled_start = self._find_earliest_slot(
                task, profile, dep_start, resource_timeline, resource_constraints
            )

            # Duration
            duration = profile.estimated_cost  # Use cost as time proxy, or get from estimate
            if hasattr(task, 'duration_estimate') and task.duration_estimate:
                if hasattr(task.duration_estimate, 'estimated_seconds'):
                    duration = task.duration_estimate.estimated_seconds / 3600
                else:
                    duration = task.duration_estimate.get("estimated_seconds", 0) / 3600
            elif task.estimated_hours:
                duration = task.estimated_hours
            else:
                duration = 1.0

            scheduled_end = scheduled_start + timedelta(hours=duration)

            # Record
            task_start_times[task_id] = scheduled_start
            task_end_times[task_id] = scheduled_end

            # Update resource timeline
            if profile:
                if profile.cpu_cores > 0:
                    resource_timeline["cpu"].append((scheduled_start, scheduled_end, task_id))
                if profile.memory_gb > 0:
                    resource_timeline["memory"].append((scheduled_start, scheduled_end, task_id))
                if profile.gpu_count > 0:
                    resource_timeline["gpu"].append((scheduled_start, scheduled_end, task_id))

            schedule_items.append({
                "task_id": task_id,
                "task_title": task.title,
                "start_time": scheduled_start.isoformat(),
                "end_time": scheduled_end.isoformat(),
                "duration_hours": duration,
                "resources": {
                    "cpu_cores": profile.cpu_cores if profile else 1.0,
                    "memory_gb": profile.memory_gb if profile else 1.0,
                    "gpu_count": profile.gpu_count if profile else 0,
                }
            })

        # Calculate totals
        if schedule_items:
            total_end = max(datetime.fromisoformat(item["end_time"]) for item in schedule_items)
            total_duration = total_end - start_dt
        else:
            total_duration = timedelta(0)

        result = {
            "start_time": start_time,
            "end_time": (start_dt + total_duration).isoformat(),
            "total_duration_hours": round(total_duration.total_seconds() / 3600, 2),
            "items": schedule_items,
            "max_concurrent": self._calculate_max_concurrent(schedule_items),
        }

        self._schedule_history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "schedule": result,
        })

        return result

    def _find_earliest_slot(
        self,
        task: Task,
        profile: Optional[TaskResourceProfile],
        earliest_start: datetime,
        resource_timeline: Dict[str, List[Tuple[datetime, datetime, str]]],
        resource_constraints: Optional[Dict[ResourceType, float]] = None,
    ) -> datetime:
        """Find the earliest time slot that satisfies all resource constraints."""
        # Simple implementation: check current time forward in 30-min increments
        # A full implementation would use a more sophisticated algorithm
        check_time = earliest_start
        max_lookahead = timedelta(days=7)

        while check_time < earliest_start + max_lookahead:
            # Check execution window
            if profile and profile.execution_window:
                if not profile.execution_window.is_active(check_time):
                    check_time = profile.execution_window.next_window_start(check_time)
                    continue

            # Check resources
            can_schedule = True

            # CPU check
            if profile and profile.cpu_cores > 0:
                cpu_busy = sum(
                    1 for start, end, _ in resource_timeline.get("cpu", [])
                    if start <= check_time < end
                )
                if cpu_busy >= self.max_concurrent_tasks:
                    can_schedule = False

            # GPU check
            if profile and profile.gpu_count > 0:
                gpu_busy = sum(
                    1 for start, end, _ in resource_timeline.get("gpu", [])
                    if start <= check_time < end
                )
                if gpu_busy >= 1:  # Single GPU for now
                    can_schedule = False

            if can_schedule:
                # Also check system availability
                system = self.resource_monitor.get_resource_summary()
                if profile:
                    cpu_needed = profile.cpu_cores / system["cpu"]["total_cores"]
                    if cpu_needed > system["cpu"]["available_fraction"]:
                        can_schedule = False

            if can_schedule:
                return check_time

            check_time += timedelta(minutes=30)

        return earliest_start  # Fallback

    def _calculate_max_concurrent(self, items: List[Dict[str, Any]]) -> int:
        """Calculate maximum concurrent tasks in schedule."""
        events = []
        for item in items:
            start = datetime.fromisoformat(item["start_time"])
            end = datetime.fromisoformat(item["end_time"])
            events.append((start, 1))
            events.append((end, -1))

        events.sort(key=lambda x: (x[0], x[1]))

        max_concurrent = 0
        current = 0
        for _, delta in events:
            current += delta
            max_concurrent = max(max_concurrent, current)

        return max_concurrent

    def start_task(self, task_id: str) -> bool:
        """Mark a task as running."""
        if task_id in self._running_tasks:
            return False

        task = self.graph.get_task(task_id)
        if not task:
            return False

        profile = self._task_profiles.get(task_id) or self.infer_task_profile(task)

        can_schedule, reason = self.can_schedule_task(task)
        if not can_schedule:
            return False

        self._running_tasks[task_id] = {
            "task": task,
            "profile": profile.to_dict() if hasattr(profile, 'to_dict') else profile.__dict__,
            "start_time": datetime.now(timezone.utc).isoformat(),
        }
        return True

    def complete_task(self, task_id: str, actual_duration_hours: Optional[float] = None) -> bool:
        """Mark a task as completed."""
        if task_id not in self._running_tasks:
            return False

        info = self._running_tasks.pop(task_id)
        if actual_duration_hours is not None:
            info["actual_duration_hours"] = actual_duration_hours
        info["end_time"] = datetime.now(timezone.utc).isoformat()

        # Record actual for learning
        task = info["task"]
        if hasattr(task, 'duration_estimate') and actual_duration_hours:
            # Could update duration estimator here
            pass

        return True

    def get_running_tasks(self) -> List[Dict[str, Any]]:
        """Get list of currently running tasks."""
        return list(self._running_tasks.values())

    def get_resource_utilization(self) -> Dict[str, Any]:
        """Get current resource utilization from running tasks."""
        cpu_total = sum(t.get("profile", {}).get("cpu_cores", 0) for t in self._running_tasks.values())
        mem_total = sum(t.get("profile", {}).get("memory_gb", 0) for t in self._running_tasks.values())
        gpu_total = sum(t.get("profile", {}).get("gpu_count", 0) for t in self._running_tasks.values())

        system = self.resource_monitor.get_resource_summary()

        return {
            "allocated": {
                "cpu_cores": cpu_total,
                "memory_gb": mem_total,
                "gpu_count": gpu_total,
            },
            "system": system,
            "running_task_count": len(self._running_tasks),
            "max_concurrent": self.max_concurrent_tasks,
        }


class CostOptimizedScheduler(ResourceAwareScheduler):
    """Scheduler that optimizes for execution cost."""

    def __init__(self, *args, cost_per_hour: Dict[str, float] = None, **kwargs):
        super().__init__(*args, **kwargs)
        # Cost per hour by resource type
        self.cost_per_hour = cost_per_hour or {
            "cpu_core_hour": 0.05,
            "memory_gb_hour": 0.01,
            "gpu_hour": 1.0,
            "storage_gb_hour": 0.001,
        }

    def estimate_task_cost(self, profile: TaskResourceProfile, duration_hours: float) -> float:
        """Estimate cost for a task."""
        cost = 0.0
        cost += profile.cpu_cores * duration_hours * self.cost_per_hour["cpu_core_hour"]
        cost += profile.memory_gb * duration_hours * self.cost_per_hour["memory_gb_hour"]
        cost += profile.gpu_count * duration_hours * self.cost_per_hour["gpu_hour"]
        cost += profile.storage_gb * duration_hours * self.cost_per_hour["storage_gb_hour"]
        return cost

    def schedule_minimizing_cost(
        self,
        tasks: List[Task],
        start_time: Optional[str] = None,
        max_cost: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Schedule tasks to minimize cost while respecting constraints."""
        # Use base scheduling but consider cost in ordering
        # Tasks with lower cost/priority ratio go first if budget is tight
        # This is a simplified version - full implementation would use ILP or heuristics

        if max_cost is not None:
            self.cost_budget = max_cost

        return self.schedule_tasks(tasks, start_time)


# Convenience function
def create_resource_aware_scheduler(
    graph: TaskGraph,
    strategy: str = "resource_aware",
    max_concurrent: int = 4,
    monitor: Optional[SystemResourceMonitor] = None,
) -> ResourceAwareScheduler:
    """Factory function to create a resource-aware scheduler."""
    return ResourceAwareScheduler(
        graph=graph,
        strategy=strategy,
        resource_monitor=monitor,
        max_concurrent_tasks=max_concurrent,
    )