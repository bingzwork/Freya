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
