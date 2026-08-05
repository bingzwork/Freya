"""Context-Aware Retrieval for World Model.

This module provides filtering of environment snapshots based on task context,
returning only the information relevant to specific task types.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from app.world_model.model import (
    EnvironmentSnapshot,
    ProjectInfo,
    RuntimeInfo,
    GitInfo,
    ResourceInfo,
    ToolInfo,
    HealthInfo,
)

# Import static relevance mappings from learned_relevance to avoid duplication
from app.world_model.learned_relevance import (
    TASK_TYPES,
    TASK_RELEVANCE,
    FIELD_RELEVANCE,
)

# Learned relevance integration
try:
    from app.world_model.learned_relevance import (
        LearnedRelevanceEngine,
        RetrievalOutcome,
        create_learned_relevance_engine,
    )
    _LEARNED_RELEVANCE_AVAILABLE = True
except ImportError:
    _LEARNED_RELEVANCE_AVAILABLE = False
    LearnedRelevanceEngine = None  # type: ignore
    RetrievalOutcome = None  # type: ignore
    create_learned_relevance_engine = None  # type: ignore

# Global learned relevance engine instance
_learned_relevance_engine: Optional["LearnedRelevanceEngine"] = None


@dataclass
class TaskContext:
    """Represents a task context for relevance filtering."""
    task_type: str = "unknown"
    # Additional context that can influence relevance
    keywords: List[str] = field(default_factory=list)
    files: List[str] = field(default_factory=list)
    # Whether to include all layers even if not directly relevant
    include_all_layers: bool = False

    @classmethod
    def from_string(cls, task_type: str) -> "TaskContext":
        """Create TaskContext from a simple task type string."""
        return cls(task_type=task_type)

    @classmethod
    def from_task(cls, task: str) -> "TaskContext":
        """Create TaskContext by inferring type from task description."""
        task_lower = task.lower()

        # Simple keyword-based inference
        if any(k in task_lower for k in ["build", "compile", "package", "bundle"]):
            return cls(task_type="build", keywords=["build"])
        elif any(k in task_lower for k in ["test", "pytest", "unittest", "spec"]):
            return cls(task_type="test", keywords=["test"])
        elif any(k in task_lower for k in ["deploy", "release", "publish", "push prod"]):
            return cls(task_type="deploy", keywords=["deploy"])
        elif any(k in task_lower for k in ["debug", "fix", "error", "bug", "traceback", "crash"]):
            return cls(task_type="debug", keywords=["debug"])
        elif any(k in task_lower for k in ["refactor", "restructure", "reorganize", "cleanup"]):
            return cls(task_type="refactor", keywords=["refactor"])
        elif any(k in task_lower for k in ["analyze", "review", "inspect", "understand", "explain"]):
            return cls(task_type="analyze", keywords=["analyze"])
        elif any(k in task_lower for k in ["install", "dependency", "requirement", "package"]):
            return cls(task_type="install", keywords=["install"])
        elif any(k in task_lower for k in ["lint", "format", "style", "prettier", "black", "ruff"]):
            return cls(task_type="lint", keywords=["lint"])
        else:
            return cls(task_type="develop", keywords=[])


# Learned Relevance Engine Management

def get_learned_relevance_engine() -> Optional["LearnedRelevanceEngine"]:
    """Get the global learned relevance engine instance."""
    global _learned_relevance_engine
    if _learned_relevance_engine is None and _LEARNED_RELEVANCE_AVAILABLE:
        _learned_relevance_engine = create_learned_relevance_engine()
    return _learned_relevance_engine


def set_learned_relevance_engine(engine: "LearnedRelevanceEngine") -> None:
    """Set the global learned relevance engine instance."""
    global _learned_relevance_engine
    _learned_relevance_engine = engine


def init_learned_relevance(storage_path: Optional[Path] = None, **kwargs) -> "LearnedRelevanceEngine":
    """Initialize and set the global learned relevance engine."""
    global _learned_relevance_engine
    if not _LEARNED_RELEVANCE_AVAILABLE:
        raise RuntimeError("Learned relevance engine not available")
    _learned_relevance_engine = create_learned_relevance_engine(storage_path=storage_path, **kwargs)
    return _learned_relevance_engine


def filter_snapshot_for_task(
    snapshot: EnvironmentSnapshot,
    task_type: str,
    include_irrelevant: bool = False,
    use_learned: bool = True,
    relevance_threshold: float = 0.3,
) -> EnvironmentSnapshot:
    """Filter an environment snapshot to only include information relevant to a task type.

    This creates a new snapshot with only the relevant fields populated,
    keeping the original snapshot unchanged.

    Args:
        snapshot: The full environment snapshot to filter.
        task_type: The type of task (e.g., "build", "test", "deploy", "debug").
        include_irrelevant: If True, include fields marked as irrelevant (but empty).
        use_learned: If True, use learned relevance weights (when available).
        relevance_threshold: Minimum relevance score to include a layer/field.

    Returns:
        A filtered EnvironmentSnapshot with only relevant data.
    """
    if task_type not in TASK_RELEVANCE:
        task_type = "unknown"

    # Get relevant layers - use learned if available and requested
    engine = get_learned_relevance_engine() if use_learned else None
    if engine is not None:
        relevant_layers = engine.get_relevant_layers(task_type, threshold=relevance_threshold)
    else:
        relevant_layers = TASK_RELEVANCE.get(task_type, TASK_RELEVANCE["unknown"])

    def get_relevant_fields(layer: str) -> List[str]:
        if engine is not None:
            return engine.get_relevant_fields(task_type, layer, threshold=relevance_threshold)
        return FIELD_RELEVANCE.get(layer, {}).get(task_type, [])

    # Create a new snapshot with filtered data
    filtered = EnvironmentSnapshot(
        snapshot_id=snapshot.snapshot_id + f"_filtered_{task_type}",
        timestamp=snapshot.timestamp,
        elapsed_ms=snapshot.elapsed_ms,
    )

    # Filter each layer
    if "project" in relevant_layers:
        filtered.project = _filter_project(snapshot.project, get_relevant_fields("project"), include_irrelevant)
    if "runtime" in relevant_layers:
        filtered.runtime = _filter_runtime(snapshot.runtime, get_relevant_fields("runtime"), include_irrelevant)
    if "git" in relevant_layers:
        filtered.git = _filter_git(snapshot.git, get_relevant_fields("git"), include_irrelevant)
    if "resources" in relevant_layers:
        filtered.resources = _filter_resources(snapshot.resources, get_relevant_fields("resources"), include_irrelevant)
    if "tools" in relevant_layers:
        filtered.tools = _filter_tools(snapshot.tools, get_relevant_fields("tools"), include_irrelevant)
    if "health" in relevant_layers:
        filtered.health = _filter_health(snapshot.health, get_relevant_fields("health"), include_irrelevant)

    return filtered


def _filter_project(project, relevant_fields: List[str], include_irrelevant: bool) -> Any:
    """Filter project info to relevant fields."""
    from app.world_model.model import ProjectInfo
    if include_irrelevant:
        return project  # Return full object

    data = project.to_dict()
    filtered_data = {k: v for k, v in data.items() if k in relevant_fields}
    return ProjectInfo(**filtered_data)


def _filter_runtime(runtime, relevant_fields: List[str], include_irrelevant: bool) -> Any:
    """Filter runtime info to relevant fields."""
    from app.world_model.model import RuntimeInfo
    if include_irrelevant:
        return runtime

    data = runtime.to_dict()
    # Runtime has nested structure
    filtered_data = _filter_nested_dict(data, relevant_fields)
    return RuntimeInfo(
        os_name=filtered_data.get("os", {}).get("name", ""),
        os_version=filtered_data.get("os", {}).get("version", ""),
        os_family=filtered_data.get("os", {}).get("family", ""),
        shell_name=filtered_data.get("shell", {}).get("name", ""),
        shell_path=filtered_data.get("shell", {}).get("path", ""),
        python_version=filtered_data.get("python", {}).get("version", ""),
        python_major=filtered_data.get("python", {}).get("major", 0),
        python_minor=filtered_data.get("python", {}).get("minor", 0),
        python_patch=filtered_data.get("python", {}).get("patch", 0),
        python_executable=filtered_data.get("python", {}).get("executable", ""),
        working_directory=filtered_data.get("working_directory", ""),
        environment=filtered_data.get("environment", {}),
    )


def _filter_git(git, relevant_fields: List[str], include_irrelevant: bool) -> Any:
    """Filter git info to relevant fields."""
    from app.world_model.model import GitInfo
    if include_irrelevant:
        return git

    data = git.to_dict()
    filtered_data = {k: v for k, v in data.items() if k in relevant_fields}
    return GitInfo(**filtered_data)


def _filter_resources(resources, relevant_fields: List[str], include_irrelevant: bool) -> Any:
    """Filter resource info to relevant fields."""
    from app.world_model.model import ResourceInfo
    if include_irrelevant:
        return resources

    data = resources.to_dict()
    # Flatten for filtering
    flat = {}
    for section, values in data.items():
        if isinstance(values, dict):
            for k, v in values.items():
                flat[f"{section}.{k}"] = v
        else:
            flat[section] = values

    filtered_flat = {k: v for k, v in flat.items() if any(k.startswith(f + ".") or k == f for f in relevant_fields)}

    return ResourceInfo(
        cpu_percent=filtered_flat.get("cpu.percent", 0.0),
        cpu_count=filtered_flat.get("cpu.count", 0),
        cpu_freq_mhz=filtered_flat.get("cpu.freq_mhz", 0.0),
        memory_total_gb=filtered_flat.get("memory.total_gb", 0.0),
        memory_used_gb=filtered_flat.get("memory.used_gb", 0.0),
        memory_free_gb=filtered_flat.get("memory.free_gb", 0.0),
        memory_percent=filtered_flat.get("memory.percent", 0.0),
        disk_total_gb=filtered_flat.get("disk.total_gb", 0.0),
        disk_used_gb=filtered_flat.get("disk.used_gb", 0.0),
        disk_free_gb=filtered_flat.get("disk.free_gb", 0.0),
        disk_percent=filtered_flat.get("disk.percent", 0.0),
        disk_read_mb=filtered_flat.get("disk.read_mb", 0.0),
        disk_write_mb=filtered_flat.get("disk.write_mb", 0.0),
        net_sent_mb=filtered_flat.get("network.sent_mb", 0.0),
        net_recv_mb=filtered_flat.get("network.recv_mb", 0.0),
        process_count=filtered_flat.get("processes.count", 0),
        thread_count=filtered_flat.get("processes.threads", 0),
        temperature_celsius=filtered_flat.get("temperature"),
        load_avg_1min=filtered_flat.get("load_avg.1min"),
        load_avg_5min=filtered_flat.get("load_avg.5min"),
        load_avg_15min=filtered_flat.get("load_avg.15min"),
        health_score=filtered_flat.get("health_score", 0.0),
        health_status=filtered_flat.get("health_status", "unknown"),
    )


def _filter_tools(tools, relevant_fields: List[str], include_irrelevant: bool) -> Any:
    """Filter tool info to relevant fields."""
    from app.world_model.model import ToolInfo
    if include_irrelevant:
        return tools

    data = tools.to_dict()
    filtered_data = {k: v for k, v in data.items() if k in relevant_fields}
    return ToolInfo(**filtered_data)


def _filter_health(health, relevant_fields: List[str], include_irrelevant: bool) -> Any:
    """Filter health info to relevant fields."""
    from app.world_model.model import HealthInfo
    if include_irrelevant:
        return health

    data = health.to_dict()
    filtered_data = {k: v for k, v in data.items() if k in relevant_fields}
    return HealthInfo(**filtered_data)


def _filter_nested_dict(data: Dict[str, Any], relevant_fields: List[str]) -> Dict[str, Any]:
    """Filter a nested dictionary by relevant field names."""
    result = {}
    for key, value in data.items():
        if key in relevant_fields:
            result[key] = value
        elif isinstance(value, dict):
            # Check if any nested fields match
            nested = _filter_nested_dict(value, relevant_fields)
            if nested:
                result[key] = nested
    return result


def get_relevant_context(
    snapshot: EnvironmentSnapshot,
    task_context: TaskContext,
    use_learned: bool = True,
    relevance_threshold: float = 0.3,
) -> Dict[str, Any]:
    """Get relevant context from a snapshot for a given task context.

    Returns a dictionary with only the relevant information, suitable for
    inclusion in LLM prompts or decision-making.

    Args:
        snapshot: The full environment snapshot.
        task_context: The task context specifying what's relevant.
        use_learned: If True, use learned relevance weights (when available).
        relevance_threshold: Minimum relevance score to include a layer/field.

    Returns:
        Dictionary with relevant environment information.
    """
    filtered = filter_snapshot_for_task(
        snapshot,
        task_context.task_type,
        use_learned=use_learned,
        relevance_threshold=relevance_threshold,
    )

    context = {
        "task_type": task_context.task_type,
        "snapshot_id": filtered.snapshot_id,
        "timestamp": filtered.timestamp,
    }

    # Add only non-empty layers
    if filtered.project.name or filtered.project.file_count:
        context["project"] = filtered.project.to_dict()
    if filtered.runtime.os_name:
        context["runtime"] = filtered.runtime.to_dict()
    if filtered.git.is_repo:
        context["git"] = filtered.git.to_dict()
    if filtered.resources.cpu_count > 0:
        context["resources"] = filtered.resources.to_dict()
    if filtered.tools.available_tools:
        context["tools"] = filtered.tools.to_dict()
    if filtered.health.overall_status != "unknown":
        context["health"] = filtered.health.to_dict()

    return context


def get_relevant_summary(
    snapshot: EnvironmentSnapshot,
    task_type: str,
    use_learned: bool = True,
    relevance_threshold: float = 0.3,
) -> str:
    """Get a concise text summary of relevant environment info for a task type.

    Useful for quick context injection into LLM prompts.

    Args:
        snapshot: The full environment snapshot.
        task_type: The type of task.
        use_learned: If True, use learned relevance weights (when available).
        relevance_threshold: Minimum relevance score to include a layer/field.

    Returns:
        Text summary of relevant environment information.
    """
    filtered = filter_snapshot_for_task(
        snapshot,
        task_type,
        use_learned=use_learned,
        relevance_threshold=relevance_threshold,
    )

    lines = [f"=== Environment ({task_type}) ==="]

    if filtered.project.name:
        lines.append(f"Project: {filtered.project.name} ({filtered.project.main_language})")
        if filtered.project.build_system != "unknown":
            lines.append(f"  Build: {filtered.project.build_system}")
        if filtered.project.framework != "none detected":
            lines.append(f"  Framework: {filtered.project.framework}")

    if filtered.runtime.os_family:
        lines.append(f"OS: {filtered.runtime.os_family} (Python {filtered.runtime.python_version})")

    if filtered.git.is_repo:
        lines.append(f"Git: {filtered.git.current_branch} ({'clean' if filtered.git.is_clean else 'dirty'})")
        if filtered.git.ahead or filtered.git.behind:
            lines.append(f"  Sync: ↑{filtered.git.ahead} ↓{filtered.git.behind}")

    if filtered.resources.cpu_count:
        lines.append(
            f"Resources: CPU {filtered.resources.cpu_percent:.0f}% / "
            f"Mem {filtered.resources.memory_percent:.0f}% / "
            f"Disk {filtered.resources.disk_percent:.0f}%"
        )
        lines.append(f"  Health: {filtered.resources.health_status}")

    if filtered.tools.available_tools:
        key_tools = []
        if filtered.tools.git_available: key_tools.append("git")
        if filtered.tools.python_available: key_tools.append("python")
        if filtered.tools.node_available: key_tools.append("node")
        if filtered.tools.docker_available: key_tools.append("docker")
        lines.append(f"Key tools: {', '.join(key_tools) if key_tools else 'basic'}")

    if filtered.health.overall_status != "unknown":
        lines.append(f"Project Health: {filtered.health.overall_status} ({filtered.health.health_score:.0f}/100)")

    return "\n".join(lines)


def list_supported_task_types() -> List[str]:
    """Get list of supported task types for context filtering."""
    return list(TASK_TYPES.keys())


def get_task_type_description(task_type: str) -> str:
    """Get description for a task type."""
    return TASK_TYPES.get(task_type, "Unknown task type")


# Learned Relevance Outcome Recording

def record_retrieval_outcome(
    task_type: str,
    query: str,
    retrieved_layers: List[str],
    retrieved_fields: Dict[str, List[str]],
    success: bool,
    user_feedback: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Record a retrieval outcome for learning relevance weights.

    This function feeds back the result of a retrieval operation so the
    learned relevance engine can adapt its weights based on what worked.

    Args:
        task_type: The type of task
        query: The query that was executed
        retrieved_layers: List of layers that were retrieved
        retrieved_fields: Dict mapping layer to list of fields retrieved
        success: Whether the retrieval led to a successful task outcome
        user_feedback: Optional user feedback ("positive", "negative")
        metadata: Additional metadata about the retrieval
    """
    engine = get_learned_relevance_engine()
    if engine is None:
        return

    outcome = RetrievalOutcome(
        task_type=task_type,
        query=query,
        retrieved_layers=retrieved_layers,
        retrieved_fields=retrieved_fields,
        success=success,
        user_feedback=user_feedback,
        metadata=metadata or {},
    )
    engine.record_outcome(outcome)


def get_learned_relevance_summary(task_type: str) -> Dict[str, Any]:
    """Get a summary of learned relevance weights for a task type.

    Args:
        task_type: The type of task

    Returns:
        Dictionary with learned weights and metadata, or empty dict if not available
    """
    engine = get_learned_relevance_engine()
    if engine is None:
        return {}
    return engine.get_weight_summary(task_type)


def get_all_learned_relevance() -> Dict[str, Dict[str, Any]]:
    """Get all learned relevance weights for all task types."""
    engine = get_learned_relevance_engine()
    if engine is None:
        return {}
    return engine.get_all_weights()


def reset_learned_relevance(task_type: str) -> None:
    """Reset learned relevance weights for a task type to static defaults.

    Args:
        task_type: The type of task to reset
    """
    engine = get_learned_relevance_engine()
    if engine is not None:
        engine.reset_task_weights(task_type)