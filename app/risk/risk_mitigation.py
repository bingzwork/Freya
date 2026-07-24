"""Risk Mitigation module for managing risk mitigation strategies and plans."""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Dict, List, Any, Optional
import uuid

from app.risk.risk_item import RiskItem, RiskSeverity, RiskStatus


class MitigationStrategyType(Enum):
    """Types of mitigation strategies."""
    AVOID = "avoid"              # Change the plan to eliminate the risk
    REDUCE = "reduce"            # Reduce the probability or impact
    TRANSFER = "transfer"        # Transfer the risk (e.g., insurance, outsourcing)
    ACCEPT = "accept"            # Accept the risk without action
    MITIGATE = "mitigate"        # Implement controls to reduce impact
    CONTINGENCY = "contingency"  # Create contingency plans


class MitigationStatus(Enum):
    """Status of mitigation activities."""
    PLANNED = "planned"          # Mitigation is planned but not started
    IN_PROGRESS = "in_progress"  # Mitigation is in progress
    COMPLETED = "completed"      # Mitigation is complete
    VERIFIED = "verified"        # Mitigation has been verified as effective
    FAILED = "failed"            # Mitigation was not successful


@dataclass
class RiskMitigationStrategy:
    """Represents a strategy for mitigating a risk."""
    # Required fields
    risk_id: str
    strategy_type: MitigationStrategyType

    # Optional fields with defaults
    id: str = field(default_factory=lambda: f"mitigation_{uuid.uuid4().hex[:8]}")
    description: str = ""
    implementation_plan: str = ""
    owner: str = ""
    priority: int = 3  # 1 = highest, 5 = lowest
    estimated_cost: float = 0.0
    estimated_effort_hours: float = 0.0
    resources_required: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    status: MitigationStatus = MitigationStatus.PLANNED
    effectiveness: float = 0.0  # 0.0 to 1.0 - estimated effectiveness
    actual_effectiveness: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self):
        if isinstance(self.strategy_type, str):
            self.strategy_type = MitigationStrategyType(self.strategy_type)
        if isinstance(self.status, str):
            self.status = MitigationStatus(self.status)

    @property
    def is_active(self) -> bool:
        """Check if the mitigation is still active."""
        return self.status in [
            MitigationStatus.PLANNED,
            MitigationStatus.IN_PROGRESS,
        ]

    @property
    def is_complete(self) -> bool:
        """Check if the mitigation is complete."""
        return self.status in [
            MitigationStatus.COMPLETED,
            MitigationStatus.VERIFIED,
            MitigationStatus.FAILED,
        ]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "risk_id": self.risk_id,
            "strategy_type": self.strategy_type.value,
            "description": self.description,
            "implementation_plan": self.implementation_plan,
            "owner": self.owner,
            "priority": self.priority,
            "estimated_cost": self.estimated_cost,
            "estimated_effort_hours": self.estimated_effort_hours,
            "resources_required": self.resources_required,
            "dependencies": self.dependencies,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "status": self.status.value,
            "effectiveness": self.effectiveness,
            "actual_effectiveness": self.actual_effectiveness,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RiskMitigationStrategy":
        """Create from dictionary."""
        return cls(
            id=data.get("id", f"mitigation_{uuid.uuid4().hex[:8]}"),
            risk_id=data.get("risk_id", ""),
            strategy_type=data.get("strategy_type", "reduce"),
            description=data.get("description", ""),
            implementation_plan=data.get("implementation_plan", ""),
            owner=data.get("owner", ""),
            priority=data.get("priority", 3),
            estimated_cost=data.get("estimated_cost", 0.0),
            estimated_effort_hours=data.get("estimated_effort_hours", 0.0),
            resources_required=data.get("resources_required", []),
            dependencies=data.get("dependencies", []),
            start_date=data.get("start_date"),
            end_date=data.get("end_date"),
            status=data.get("status", "planned"),
            effectiveness=data.get("effectiveness", 0.0),
            actual_effectiveness=data.get("actual_effectiveness"),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )

    def update_status(self, status: MitigationStatus) -> None:
        """Update the mitigation status."""
        self.status = status
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def mark_completed(self, actual_effectiveness: Optional[float] = None) -> None:
        """Mark the mitigation as completed."""
        self.status = MitigationStatus.COMPLETED
        self.actual_effectiveness = actual_effectiveness
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def mark_verified(self) -> None:
        """Mark the mitigation as verified."""
        self.status = MitigationStatus.VERIFIED
        self.updated_at = datetime.now(timezone.utc).isoformat()


@dataclass
class RiskMitigationPlan:
    """Represents a comprehensive plan for mitigating multiple risks."""
    id: str = field(default_factory=lambda: f"mitigation_plan_{uuid.uuid4().hex[:8]}")
    name: str = ""
    description: str = ""
    scope: str = ""
    objectives: List[str] = field(default_factory=list)
    strategies: List[RiskMitigationStrategy] = field(default_factory=list)
    owner: str = ""
    stakeholders: List[str] = field(default_factory=list)
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    budget: float = 0.0
    status: str = "draft"  # draft, approved, active, completed, cancelled
    priority: int = 3  # 1 = highest, 5 = lowest
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def completion_percentage(self) -> float:
        """Calculate the completion percentage."""
        if not self.strategies:
            return 0.0
        completed = len([s for s in self.strategies if s.is_complete])
        return (completed / len(self.strategies)) * 100

    @property
    def total_estimated_effort(self) -> float:
        """Get the total estimated effort in hours."""
        return sum(s.estimated_effort_hours for s in self.strategies)

    @property
    def total_estimated_cost(self) -> float:
        """Get the total estimated cost."""
        return sum(s.estimated_cost for s in self.strategies)

    @property
    def average_effectiveness(self) -> float:
        """Get the average effectiveness of all strategies."""
        if not self.strategies:
            return 0.0
        return sum(s.effectiveness for s in self.strategies) / len(self.strategies)

    @property
    def is_active(self) -> bool:
        """Check if the plan is active."""
        return self.status == "active"

    @property
    def is_complete(self) -> bool:
        """Check if the plan is complete."""
        return self.status == "completed"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "scope": self.scope,
            "objectives": self.objectives,
            "strategies": [s.to_dict() for s in self.strategies],
            "owner": self.owner,
            "stakeholders": self.stakeholders,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "budget": self.budget,
            "status": self.status,
            "priority": self.priority,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completion_percentage": self.completion_percentage,
            "total_estimated_effort": self.total_estimated_effort,
            "total_estimated_cost": self.total_estimated_cost,
            "average_effectiveness": self.average_effectiveness,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RiskMitigationPlan":
        """Create from dictionary."""
        plan = cls(
            id=data.get("id", f"mitigation_plan_{uuid.uuid4().hex[:8]}"),
            name=data.get("name", ""),
            description=data.get("description", ""),
            scope=data.get("scope", ""),
            objectives=data.get("objectives", []),
            owner=data.get("owner", ""),
            stakeholders=data.get("stakeholders", []),
            start_date=data.get("start_date"),
            end_date=data.get("end_date"),
            budget=data.get("budget", 0.0),
            status=data.get("status", "draft"),
            priority=data.get("priority", 3),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )
        plan.strategies = [
            RiskMitigationStrategy.from_dict(s) for s in data.get("strategies", [])
        ]
        return plan

    def add_strategy(self, strategy: RiskMitigationStrategy) -> None:
        """Add a mitigation strategy to the plan."""
        self.strategies.append(strategy)
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def remove_strategy(self, strategy_id: str) -> bool:
        """Remove a strategy from the plan."""
        for i, strategy in enumerate(self.strategies):
            if strategy.id == strategy_id:
                self.strategies.pop(i)
                self.updated_at = datetime.now(timezone.utc).isoformat()
                return True
        return False

    def get_strategy(self, strategy_id: str) -> Optional[RiskMitigationStrategy]:
        """Get a strategy by ID."""
        for strategy in self.strategies:
            if strategy.id == strategy_id:
                return strategy
        return None

    def update_strategy_status(
        self,
        strategy_id: str,
        status: MitigationStatus,
    ) -> bool:
        """Update the status of a strategy."""
        strategy = self.get_strategy(strategy_id)
        if strategy:
            strategy.update_status(status)
            self.updated_at = datetime.now(timezone.utc).isoformat()
            return True
        return False

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the mitigation plan."""
        return {
            "total_strategies": len(self.strategies),
            "completed_strategies": len([s for s in self.strategies if s.is_complete]),
            "active_strategies": len([s for s in self.strategies if s.is_active]),
            "completion_percentage": self.completion_percentage,
            "total_estimated_effort": self.total_estimated_effort,
            "total_estimated_cost": self.total_estimated_cost,
            "average_effectiveness": self.average_effectiveness,
        }

    def get_strategies_by_status(self, status: MitigationStatus) -> List[RiskMitigationStrategy]:
        """Get strategies by status."""
        return [s for s in self.strategies if s.status == status]

    def get_strategies_by_risk(self, risk_id: str) -> List[RiskMitigationStrategy]:
        """Get strategies for a specific risk."""
        return [s for s in self.strategies if s.risk_id == risk_id]

    def get_high_priority_strategies(self) -> List[RiskMitigationStrategy]:
        """Get high priority strategies (priority 1 or 2)."""
        return [s for s in self.strategies if s.priority <= 2]
