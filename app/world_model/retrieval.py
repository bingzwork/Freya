"""Context-Aware Retrieval for World Model.

This module provides filtering of environment snapshots based on task context,
returning only the information relevant to specific task types.
"""

from dataclasses import dataclass, field
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

# Task type definitions for context-aware retrieval
TASK_TYPES = {
    "build": "Building/compiling the project",
    "test": "Running tests",
    "deploy": "Deploying the application",
    "debug": "Debugging issues",
    "refactor": "Refactoring code",
    "develop": "General development",
    "analyze": "Code analysis",
    "install": "Installing dependencies",
    "lint": "Linting/formatting",
    "unknown": "Unknown task type",
}

# Relevance mapping: task_type -> relevant snapshot fields
TASK_RELEVANCE = {
    "build": ["project", "runtime", "git", "tools", "resources", "health"],
    "test": ["project", "runtime", "git", "tools", "resources", "health"],
    "deploy": ["project", "runtime", "git", "tools", "resources", "health"],
    "debug": ["project", "runtime", "git", "tools", "resources", "health"],
    "refactor": ["project", "runtime", "git", "tools", "resources", "health"],
    "develop": ["project", "runtime", "git", "tools", "resources", "health"],
    "analyze": ["project", "runtime", "git", "tools", "resources", "health"],
    "install": ["project", "runtime", "git", "tools", "resources", "health"],
    "lint": ["project", "runtime", "git", "tools", "resources", "health"],
    "unknown": ["project", "runtime", "git", "tools", "resources", "health"],
}

# Field-specific relevance within a snapshot layer
FIELD_RELEVANCE = {
    "project": {
        "build": ["name", "main_language", "build_system", "config_files", "entry_points"],
        "test": ["name", "main_language", "config_files", "framework"],
        "deploy": ["name", "main_language", "build_system", "framework", "entry_points", "config_files"],
        "debug": ["name", "main_language", "entry_points", "config_files", "file_count"],
        "refactor": ["name", "main_language", "file_count", "total_lines", "config_files"],
        "develop": ["name", "main_language", "build_system", "framework", "entry_points"],
        "analyze": ["name", "main_language", "file_count", "total_lines"],
        "install": ["name", "main_language", "config_files", "build_system"],
        "lint": ["name", "main_language", "config_files"],
        "unknown": ["name", "main_language", "build_system", "framework", "entry_points", "config_files", "file_count", "total_lines"],
    },
    "runtime": {
        "build": ["family", "version", "name"],
        "test": ["family", "version", "name"],
        "deploy": ["family", "version", "name", "working_directory"],
        "debug": ["family", "version", "name", "working_directory", "environment"],
        "refactor": ["family", "version"],
        "develop": ["family", "version", "name", "working_directory"],
        "analyze": ["family", "version"],
        "install": ["family", "version", "working_directory"],
        "lint": ["family", "version"],
        "unknown": ["family", "version", "name", "working_directory", "environment"],
    },
    "git": {
        "build": ["is_repo", "current_branch", "is_clean", "ahead", "behind"],
        "test": ["is_repo", "current_branch", "is_clean"],
        "deploy": ["is_repo", "current_branch", "is_clean", "ahead", "behind", "remotes"],
        "debug": ["is_repo", "current_branch", "has_changes", "status"],
        "refactor": ["is_repo", "current_branch", "is_clean", "has_changes"],
        "develop": ["is_repo", "current_branch", "has_changes"],
        "analyze": ["is_repo", "current_branch"],
        "install": ["is_repo"],
        "lint": ["is_repo", "has_changes"],
        "unknown": ["is_repo", "current_branch", "is_clean", "ahead", "behind", "remotes", "has_changes", "status"],
    },
    "resources": {
        "build": ["cpu.percent", "memory.percent", "disk.percent", "health_status"],
        "test": ["cpu.percent", "memory.percent", "health_status"],
        "deploy": ["cpu.percent", "memory.percent", "disk.percent", "health_status", "health_score"],
        "debug": ["cpu.percent", "memory.percent", "disk.percent", "temperature", "health_status"],
        "refactor": ["cpu.percent", "memory.percent", "health_status"],
        "develop": ["cpu.percent", "memory.percent", "health_status"],
        "analyze": ["cpu.percent", "memory.percent", "health_score"],
        "install": ["cpu.percent", "memory.percent", "disk.percent"],
        "lint": ["cpu.percent", "memory.percent"],
        "unknown": ["cpu.percent", "memory.percent", "disk.percent", "health_status", "health_score", "temperature", "cpu.count", "memory.total_gb", "disk.total_gb", "processes.count", "processes.threads", "load_avg.1min", "load_avg.5min", "load_avg.15min"],
    },
    "tools": {
        "build": ["available_tools", "tool_versions", "git_available"],
        "test": ["available_tools", "tool_versions", "python_available", "git_available"],
        "deploy": ["available_tools", "tool_versions", "git_available", "docker_available"],
        "debug": ["available_tools", "tool_versions", "python_available", "node_available"],
        "refactor": ["available_tools", "tool_versions", "python_available"],
        "develop": ["available_tools", "tool_versions", "python_available", "git_available"],
        "analyze": ["available_tools", "tool_versions"],
        "install": ["available_tools", "tool_versions", "python_available", "npm_available", "docker_available"],
        "lint": ["available_tools", "tool_versions", "python_available"],
        "unknown": ["available_tools", "tool_versions", "git_available", "python_available", "node_available", "docker_available", "npm_available"],
    },
    "health": {
        "build": ["overall_status", "health_score", "code_quality"],
        "test": ["overall_status", "health_score", "test_metrics", "code_quality"],
        "deploy": ["overall_status", "health_score", "code_quality", "test_metrics", "performance_metrics"],
        "debug": ["overall_status", "health_score", "code_quality", "test_metrics", "performance_metrics"],
        "refactor": ["overall_status", "health_score", "code_quality", "performance_metrics"],
        "develop": ["overall_status", "health_score", "code_quality"],
        "analyze": ["overall_status", "health_score", "code_quality", "performance_metrics"],
        "install": ["overall_status", "health_score"],
        "lint": ["overall_status", "health_score", "code_quality"],
        # Unknown type - include all fields
        "unknown": ["overall_status", "health_score", "metrics_count", "alerts_count", "code_quality", "test_metrics", "performance_metrics"],
    },
}


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


def filter_snapshot_for_task(
    snapshot: EnvironmentSnapshot,
    task_type: str,
    include_irrelevant: bool = False,
) -> EnvironmentSnapshot:
    """Filter an environment snapshot to only include information relevant to a task type.

    This creates a new snapshot with only the relevant fields populated,
    keeping the original snapshot unchanged.

    Args:
        snapshot: The full environment snapshot to filter.
        task_type: The type of task (e.g., "build", "test", "deploy", "debug").
        include_irrelevant: If True, include fields marked as irrelevant (but empty).

    Returns:
        A filtered EnvironmentSnapshot with only relevant data.
    """
    if task_type not in TASK_RELEVANCE:
        task_type = "unknown"

    relevant_layers = TASK_RELEVANCE.get(task_type, TASK_RELEVANCE["unknown"])

    # FIELD_RELEVANCE is structured as {layer_name: {task_type: [fields]}}
    # We need to get the relevant fields for each layer
    def get_relevant_fields(layer: str) -> List[str]:
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
) -> Dict[str, Any]:
    """Get relevant context from a snapshot for a given task context.

    Returns a dictionary with only the relevant information, suitable for
    inclusion in LLM prompts or decision-making.

    Args:
        snapshot: The full environment snapshot.
        task_context: The task context specifying what's relevant.

    Returns:
        Dictionary with relevant environment information.
    """
    filtered = filter_snapshot_for_task(snapshot, task_context.task_type)

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


def get_relevant_summary(snapshot: EnvironmentSnapshot, task_type: str) -> str:
    """Get a concise text summary of relevant environment info for a task type.

    Useful for quick context injection into LLM prompts.
    """
    filtered = filter_snapshot_for_task(snapshot, task_type)

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