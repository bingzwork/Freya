"""World Model Package.

This package provides Freya's unified view of its operating environment,
integrating all environment layers into a single facade.
"""

from app.world_model.model import (
    EnvironmentSnapshot,
    ProjectInfo,
    RuntimeInfo,
    GitInfo,
    ResourceInfo,
    ToolInfo,
    HealthInfo,
    WorldModel,
    create_world_model,
)
from app.world_model.retrieval import (
    TaskContext,
    get_relevant_context,
    filter_snapshot_for_task,
    get_relevant_summary,
    list_supported_task_types,
    get_task_type_description,
)

__all__ = [
    "EnvironmentSnapshot",
    "ProjectInfo",
    "RuntimeInfo",
    "GitInfo",
    "ResourceInfo",
    "ToolInfo",
    "HealthInfo",
    "WorldModel",
    "create_world_model",
    "TaskContext",
    "get_relevant_context",
    "filter_snapshot_for_task",
    "get_relevant_summary",
    "list_supported_task_types",
    "get_task_type_description",
]