"""Resource Allocator for managing task resources.

This module provides resource allocation and management for tasks,
including tracking available resources and assigning them to tasks.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Any, Optional, Set
from collections import defaultdict


class ResourceType(Enum):
    """Types of resources."""
    DEVELOPER = "developer"
    MACHINE = "machine"
    GPU = "gpu"
    MEMORY = "memory"
    STORAGE = "storage"
    LICENSE = "license"
    TOOL = "tool"
    CUSTOM = "custom"


@dataclass
class Resource:
    """Represents a resource that can be allocated to tasks."""
    id: str
    name: str
    resource_type: ResourceType
    capacity: float = 1.0  # Total available capacity
    available: float = None  # Currently available capacity
    unit: str = "unit"
    description: str = ""
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if isinstance(self.resource_type, str):
            self.resource_type = ResourceType(self.resource_type)
        # If available is not set, default to capacity
        if self.available is None:
            self.available = self.capacity

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Resource":
        """Create resource from dictionary."""
        return cls(
            id=data["id"],
            name=data["name"],
            resource_type=data.get("resource_type", ResourceType.CUSTOM.value),
            capacity=data.get("capacity", 1.0),
            available=data.get("available", None),
            unit=data.get("unit", "unit"),
            description=data.get("description", ""),
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "resource_type": self.resource_type.value,
            "capacity": self.capacity,
            "available": self.available,
            "unit": self.unit,
            "description": self.description,
            "tags": self.tags,
            "metadata": self.metadata,
        }

    @property
    def utilization(self) -> float:
        """Get the current utilization percentage."""
        if self.capacity <= 0:
            return 0.0
        return ((self.capacity - self.available) / self.capacity) * 100

    def allocate(self, amount: float) -> bool:
        """Allocate a portion of this resource.

        Args:
            amount: Amount to allocate

        Returns:
            True if allocation was successful
        """
        if amount > self.available:
            return False
        self.available -= amount
        return True

    def release(self, amount: float) -> None:
        """Release a portion of this resource.

        Args:
            amount: Amount to release
        """
        self.available = min(self.capacity, self.available + amount)

    def reset(self) -> None:
        """Reset the resource to full availability."""
        self.available = self.capacity


@dataclass
class Allocation:
    """Represents an allocation of a resource to a task."""
    task_id: str
    resource_id: str
    amount: float
    allocated_at: str
    released_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Allocation":
        """Create allocation from dictionary."""
        return cls(
            task_id=data["task_id"],
            resource_id=data["resource_id"],
            amount=data["amount"],
            allocated_at=data["allocated_at"],
            released_at=data.get("released_at"),
            metadata=data.get("metadata", {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "task_id": self.task_id,
            "resource_id": self.resource_id,
            "amount": self.amount,
            "allocated_at": self.allocated_at,
            "released_at": self.released_at,
            "metadata": self.metadata,
        }


class ResourceAllocator:
    """Manages allocation of resources to tasks.

    This class tracks available resources and assigns them to tasks
    based on requirements and availability.
    """

    def __init__(self):
        """Initialize the resource allocator."""
        # Resource ID -> Resource
        self._resources: Dict[str, Resource] = {}

        # Task ID -> List of Allocation
        self._allocations: Dict[str, List[Allocation]] = defaultdict(list)

        # Resource ID -> List of Allocation
        self._resource_allocations: Dict[str, List[Allocation]] = defaultdict(list)

        # History of all allocations
        self._history: List[Allocation] = []

    def add_resource(self, resource: Resource) -> None:
        """Add a resource to the allocator."""
        self._resources[resource.id] = resource

    def remove_resource(self, resource_id: str) -> bool:
        """Remove a resource from the allocator."""
        if resource_id in self._resources:
            del self._resources[resource_id]
            return True
        return False

    def get_resource(self, resource_id: str) -> Optional[Resource]:
        """Get a resource by ID."""
        return self._resources.get(resource_id)

    def list_resources(self, resource_type: Optional[ResourceType] = None) -> List[Resource]:
        """List all resources, optionally filtered by type."""
        resources = list(self._resources.values())
        if resource_type:
            return [r for r in resources if r.resource_type == resource_type]
        return resources

    def allocate(self, task_id: str, resource_id: str, amount: float = 1.0) -> Optional[Allocation]:
        """Allocate a resource to a task.

        Args:
            task_id: ID of the task
            resource_id: ID of the resource to allocate
            amount: Amount to allocate

        Returns:
            Allocation if successful, None otherwise
        """
        resource = self._resources.get(resource_id)
        if resource is None:
            return None

        if not resource.allocate(amount):
            return None

        allocation = Allocation(
            task_id=task_id,
            resource_id=resource_id,
            amount=amount,
            allocated_at=datetime.now().isoformat(),
        )

        self._allocations[task_id].append(allocation)
        self._resource_allocations[resource_id].append(allocation)
        self._history.append(allocation)

        return allocation

    def allocate_for_task(self, task_id: str, required_resources: List[str]) -> List[Allocation]:
        """Allocate all required resources for a task.

        Args:
            task_id: ID of the task
            required_resources: List of resource IDs required

        Returns:
            List of successful allocations
        """
        allocations = []
        for resource_id in required_resources:
            allocation = self.allocate(task_id, resource_id)
            if allocation:
                allocations.append(allocation)
            else:
                # Rollback any successful allocations
                for a in allocations:
                    self.release(a.task_id, a.resource_id, a.amount)
                return []
        return allocations

    def release(self, task_id: str, resource_id: str, amount: float = 1.0) -> None:
        """Release a resource allocation.

        Args:
            task_id: ID of the task
            resource_id: ID of the resource
            amount: Amount to release
        """
        resource = self._resources.get(resource_id)
        if resource:
            resource.release(amount)

        # Update allocation
        for allocation in self._allocations.get(task_id, []):
            if allocation.resource_id == resource_id and allocation.released_at is None:
                allocation.released_at = datetime.now().isoformat()
                break

    def release_for_task(self, task_id: str) -> None:
        """Release all resources allocated to a task.

        Args:
            task_id: ID of the task
        """
        for allocation in self._allocations.get(task_id, []):
            self.release(task_id, allocation.resource_id, allocation.amount)

    def get_allocations_for_task(self, task_id: str) -> List[Allocation]:
        """Get all allocations for a task."""
        return self._allocations.get(task_id, [])

    def get_allocations_for_resource(self, resource_id: str) -> List[Allocation]:
        """Get all allocations for a resource."""
        return self._resource_allocations.get(resource_id, [])

    def is_available(self, resource_id: str, amount: float = 1.0) -> bool:
        """Check if a resource has enough capacity available.

        Args:
            resource_id: ID of the resource
            amount: Amount needed

        Returns:
            True if available
        """
        resource = self._resources.get(resource_id)
        if resource is None:
            return False
        return resource.available >= amount

    def get_available_resources(
        self,
        resource_type: Optional[ResourceType] = None,
        min_amount: float = 0.01,
    ) -> List[Resource]:
        """Get all resources with available capacity.

        Args:
            resource_type: Filter by resource type
            min_amount: Minimum available amount

        Returns:
            List of available resources
        """
        resources = []
        for resource in self._resources.values():
            if resource.available >= min_amount:
                if resource_type is None or resource.resource_type == resource_type:
                    resources.append(resource)
        return resources

    def get_utilization(self) -> Dict[str, float]:
        """Get utilization percentage for all resources."""
        return {rid: r.utilization for rid, r in self._resources.items()}

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of resource allocation."""
        return {
            "total_resources": len(self._resources),
            "allocated_tasks": len(self._allocations),
            "total_allocations": len(self._history),
            "utilization": self.get_utilization(),
        }

    def reset(self) -> None:
        """Reset all resources to full availability."""
        for resource in self._resources.values():
            resource.reset()
        self._allocations.clear()
        self._resource_allocations.clear()
        self._history.clear()

    @classmethod
    def discover_gpu_resources(cls) -> List[Resource]:
        """Discover and create GPU resources from system GPUs.

        Returns:
            List of GPU Resource objects
        """
        try:
            from app.monitoring.gpu_monitor import GPUMonitor, GPUVendor
        except ImportError:
            return []

        gpu_monitor = GPUMonitor()
        gpu_info_list = gpu_monitor.get_gpu_info()
        gpu_metrics_list = gpu_monitor.collect_metrics()

        # Build metrics lookup
        metrics_by_index = {m.index: m for m in gpu_metrics_list}

        resources = []
        for gpu_info in gpu_info_list:
            # Create resource for this GPU
            gpu_metrics = metrics_by_index.get(gpu_info.index)

            # Calculate available VRAM (in GB)
            vram_total_gb = gpu_info.vram_total_mb / 1024.0 if gpu_info.vram_total_mb > 0 else 0
            vram_used_gb = gpu_info.vram_used_mb / 1024.0 if gpu_info.vram_used_mb > 0 else 0
            vram_free_gb = vram_total_gb - vram_used_gb if vram_total_gb > 0 else 0

            # Use GPU utilization for GPU capacity (if available)
            gpu_util = gpu_metrics.gpu_utilization_percent if gpu_metrics else 0
            # Available GPU compute = 100% - utilization
            available_compute = max(0.0, 100.0 - gpu_util) / 100.0

            # Tags for GPU
            tags = ["gpu", gpu_info.vendor.value.lower()]
            if gpu_info.compute_capability:
                tags.append(f"cc_{gpu_info.compute_capability}")
            if gpu_info.cuda_version:
                tags.append(f"cuda_{gpu_info.cuda_version.replace('.', '_')}")

            resource = Resource(
                id=f"gpu_{gpu_info.index}",
                name=f"GPU {gpu_info.index}: {gpu_info.name}",
                resource_type=ResourceType.GPU,
                capacity=1.0,  # 1 GPU unit
                available=available_compute,  # Available compute percentage
                unit="gpu",
                description=f"{gpu_info.vendor.value.upper()} {gpu_info.name} - {vram_total_gb:.1f}GB VRAM",
                tags=tags,
                metadata={
                    "vendor": gpu_info.vendor.value,
                    "name": gpu_info.name,
                    "driver_version": gpu_info.driver_version,
                    "vram_total_gb": vram_total_gb,
                    "vram_free_gb": vram_free_gb,
                    "compute_capability": gpu_info.compute_capability,
                    "cuda_version": gpu_info.cuda_version,
                    "rocm_version": gpu_info.rocm_version,
                    "opencl_version": gpu_info.opencl_version,
                    "device_id": gpu_info.device_id,
                    "architecture": gpu_info.architecture,
                },
            )
            resources.append(resource)

        return resources

    def sync_gpu_resources(self) -> int:
        """Sync GPU resources with current system state.

        Discovers GPU hardware and updates resource availability based on current metrics.

        Returns:
            Number of GPU resources synced/updated
        """
        gpu_resources = self.discover_gpu_resources()
        count = 0

        for resource in gpu_resources:
            existing = self._resources.get(resource.id)
            if existing:
                # Update availability based on current metrics
                existing.available = resource.available
                existing.metadata = resource.metadata
                count += 1
            else:
                self.add_resource(resource)
                count += 1

        return count
