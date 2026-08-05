"""Learned Relevance Ranking for World Model Retrieval.

This module provides a learning layer that adapts relevance scores based on
successful task outcomes and user interactions while preserving the existing
static mapping as the fallback.
"""

import json
import logging
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from collections import defaultdict

# Avoid circular import by importing constants locally when needed
# from app.world_model.retrieval import TASK_TYPES, TASK_RELEVANCE, FIELD_RELEVANCE, TaskContext

logger = logging.getLogger(__name__)


# Default static mappings (copied from retrieval.py to avoid circular import)
# These are used as fallbacks when the retrieval module isn't available
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
        "unknown": ["overall_status", "health_score", "metrics_count", "alerts_count", "code_quality", "test_metrics", "performance_metrics"],
    },
}


@dataclass
class TaskRelevanceWeights:
    """Learned relevance weights for a specific task type.

    Stores layer weights and field weights that have been learned
    from successful retrieval outcomes.
    """
    task_type: str
    # Layer weights: layer_name -> weight (0.0 to 1.0)
    layer_weights: Dict[str, float] = field(default_factory=dict)
    # Field weights: layer_name -> {field_name -> weight}
    field_weights: Dict[str, Dict[str, float]] = field(default_factory=dict)
    # Statistics
    sample_count: int = 0
    last_updated: Optional[str] = None
    # Confidence in learned weights (based on sample count)
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskRelevanceWeights":
        return cls(**data)


@dataclass
class RetrievalOutcome:
    """Records the outcome of a retrieval for learning."""
    task_type: str
    query: str
    retrieved_layers: List[str]
    retrieved_fields: Dict[str, List[str]]  # layer -> fields
    success: bool
    user_feedback: Optional[str] = None  # "positive", "negative", None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)


class LearnedRelevanceEngine:
    """Engine for learning and applying relevance weights per task type.

    This engine:
    - Learns relevance weights from successful retrieval outcomes
    - Combines learned scores with static relevance mappings
    - Falls back to static mappings when learning data is insufficient
    - Persists learned weights to disk
    """

    # Minimum samples needed before learned weights are trusted
    MIN_SAMPLES_FOR_LEARNING = 5
    # Minimum samples for high confidence
    HIGH_CONFIDENCE_SAMPLES = 20
    # Learning rate for weight updates
    LEARNING_RATE = 0.1
    # Decay factor for older samples
    DECAY_FACTOR = 0.99

    def __init__(
        self,
        storage_path: Optional[Path] = None,
        persistence_interval: int = 50,
        min_samples: int = 5,
        learning_rate: float = 0.1,
    ):
        """Initialize the learned relevance engine.

        Args:
            storage_path: Path to persist learned weights
            persistence_interval: Save after this many outcome recordings
            min_samples: Minimum samples before using learned weights
            learning_rate: Rate at which weights adapt
        """
        if isinstance(storage_path, str):
            storage_path = Path(storage_path)
        self.storage_path = storage_path or Path("data/world_model/learned_relevance.json")
        self.persistence_interval = persistence_interval
        self.min_samples = min_samples
        self.learning_rate = learning_rate

        # Task type -> learned weights
        self._learned_weights: Dict[str, TaskRelevanceWeights] = {}
        # Recent outcomes for batch learning
        self._outcome_buffer: List[RetrievalOutcome] = []
        self._outcome_counter = 0
        self._lock = threading.RLock()

        # Initialize with static defaults
        self._init_static_weights()

        # Load existing learned weights
        self._load()

    def _init_static_weights(self) -> None:
        """Initialize learned weights with static mapping as baseline."""
        for task_type in TASK_TYPES:
            if task_type == "unknown":
                continue

            # Create weights from static relevance
            layer_weights = {}
            field_weights = {}

            relevant_layers = TASK_RELEVANCE.get(task_type, TASK_RELEVANCE["unknown"])
            for layer in relevant_layers:
                # All relevant layers get equal base weight
                layer_weights[layer] = 1.0 / len(relevant_layers) if relevant_layers else 0.0

                # Field weights for this layer
                fields = FIELD_RELEVANCE.get(layer, {}).get(task_type, [])
                if fields:
                    field_weights[layer] = {field: 1.0 / len(fields) for field in fields}
                else:
                    field_weights[layer] = {}

            self._learned_weights[task_type] = TaskRelevanceWeights(
                task_type=task_type,
                layer_weights=layer_weights,
                field_weights=field_weights,
                sample_count=0,
                confidence=0.0,
            )

    def _load(self) -> None:
        """Load learned weights from disk."""
        try:
            if not self.storage_path.exists():
                return

            with open(self.storage_path, "r") as f:
                data = json.load(f)

            with self._lock:
                for task_type, weights_data in data.get("learned_weights", {}).items():
                    self._learned_weights[task_type] = TaskRelevanceWeights.from_dict(weights_data)

                logger.info(f"Loaded learned relevance weights for {len(self._learned_weights)} task types")

        except Exception as e:
            logger.warning(f"Failed to load learned relevance weights: {e}")

    def _save(self) -> None:
        """Persist learned weights to disk."""
        try:
            with self._lock:
                self.storage_path.parent.mkdir(parents=True, exist_ok=True)

                data = {
                    "learned_weights": {
                        task_type: weights.to_dict()
                        for task_type, weights in self._learned_weights.items()
                    },
                    "saved_at": datetime.now(timezone.utc).isoformat(),
                    "version": 1,
                }

                temp_path = self.storage_path.with_suffix(".tmp")
                with open(temp_path, "w") as f:
                    json.dump(data, f, indent=2)
                temp_path.replace(self.storage_path)

        except Exception as e:
            logger.warning(f"Failed to save learned relevance weights: {e}")

    def _maybe_persist(self) -> None:
        """Persist if enough new outcomes recorded."""
        if self._outcome_counter % self.persistence_interval == 0:
            self._save()

    def record_outcome(self, outcome: RetrievalOutcome) -> None:
        """Record a retrieval outcome for learning.

        Args:
            outcome: The retrieval outcome to learn from
        """
        with self._lock:
            self._outcome_buffer.append(outcome)
            self._outcome_counter += 1

            # Process buffer in batches
            if len(self._outcome_buffer) >= 10:
                self._process_outcomes()

            self._maybe_persist()

    def _process_outcomes(self) -> None:
        """Process buffered outcomes to update learned weights."""
        if not self._outcome_buffer:
            return

        # Group outcomes by task type
        by_task = defaultdict(list)
        for outcome in self._outcome_buffer:
            by_task[outcome.task_type].append(outcome)

        for task_type, outcomes in by_task.items():
            if task_type not in self._learned_weights:
                # Unknown task type, initialize from static
                self._init_task_weights(task_type)

            weights = self._learned_weights[task_type]

            # Calculate success rate per layer and field
            layer_success = defaultdict(lambda: {"success": 0, "total": 0})
            field_success = defaultdict(lambda: defaultdict(lambda: {"success": 0, "total": 0}))

            for outcome in outcomes:
                for layer in outcome.retrieved_layers:
                    layer_success[layer]["total"] += 1
                    if outcome.success:
                        layer_success[layer]["success"] += 1

                for layer, fields in outcome.retrieved_fields.items():
                    for field in fields:
                        field_success[layer][field]["total"] += 1
                        if outcome.success:
                            field_success[layer][field]["success"] += 1

            # Update weights based on success rates
            self._update_weights(weights, layer_success, field_success)

        self._outcome_buffer.clear()

    def _init_task_weights(self, task_type: str) -> None:
        """Initialize weights for a new task type from static mapping."""
        relevant_layers = TASK_RELEVANCE.get(task_type, TASK_RELEVANCE["unknown"])
        layer_weights = {}
        field_weights = {}

        for layer in relevant_layers:
            layer_weights[layer] = 1.0 / len(relevant_layers) if relevant_layers else 0.0
            fields = FIELD_RELEVANCE.get(layer, {}).get(task_type, [])
            field_weights[layer] = {field: 1.0 / len(fields) for field in fields} if fields else {}

        self._learned_weights[task_type] = TaskRelevanceWeights(
            task_type=task_type,
            layer_weights=layer_weights,
            field_weights=field_weights,
            sample_count=0,
            confidence=0.0,
        )

    def _update_weights(
        self,
        weights: TaskRelevanceWeights,
        layer_success: Dict[str, Dict[str, int]],
        field_success: Dict[str, Dict[str, Dict[str, int]]],
    ) -> None:
        """Update weights based on observed success rates."""
        lr = self.learning_rate

        # Update layer weights
        for layer, stats in layer_success.items():
            if stats["total"] < 2:  # Need at least a couple samples
                continue

            success_rate = stats["success"] / stats["total"]
            current_weight = weights.layer_weights.get(layer, 0.5)

            # Adjust weight toward success rate
            if success_rate > 0.6:
                # Layer correlates with success, increase weight
                new_weight = current_weight + lr * (success_rate - 0.5)
            elif success_rate < 0.4:
                # Layer correlates with failure, decrease weight
                new_weight = current_weight - lr * (0.5 - success_rate)
            else:
                new_weight = current_weight

            weights.layer_weights[layer] = max(0.01, min(1.0, new_weight))

        # Update field weights
        for layer, fields in field_success.items():
            if layer not in weights.field_weights:
                weights.field_weights[layer] = {}

            for field, stats in fields.items():
                if stats["total"] < 2:
                    continue

                success_rate = stats["success"] / stats["total"]
                current_weight = weights.field_weights[layer].get(field, 0.5)

                if success_rate > 0.6:
                    new_weight = current_weight + lr * (success_rate - 0.5)
                elif success_rate < 0.4:
                    new_weight = current_weight - lr * (0.5 - success_rate)
                else:
                    new_weight = current_weight

                weights.field_weights[layer][field] = max(0.01, min(1.0, new_weight))

        # Renormalize layer weights
        total = sum(weights.layer_weights.values())
        if total > 0:
            for layer in weights.layer_weights:
                weights.layer_weights[layer] /= total

        # Renormalize field weights per layer
        for layer, fields in weights.field_weights.items():
            total = sum(fields.values())
            if total > 0:
                for field in fields:
                    fields[field] /= total

        # Update statistics
        total_samples = sum(s["total"] for s in layer_success.values())
        weights.sample_count += total_samples
        weights.last_updated = datetime.now(timezone.utc).isoformat()
        weights.confidence = min(1.0, weights.sample_count / self.HIGH_CONFIDENCE_SAMPLES)

    def get_layer_relevance(self, task_type: str, layer: str) -> float:
        """Get relevance score for a layer given a task type.

        Returns a score between 0.0 and 1.0 combining static and learned relevance.
        Falls back to static mapping when insufficient learning data exists.

        Args:
            task_type: The type of task
            layer: The layer name (e.g., "project", "runtime", "git")

        Returns:
            Relevance score (0.0 to 1.0)
        """
        with self._lock:
            # Check static relevance first
            relevant_layers = TASK_RELEVANCE.get(task_type, TASK_RELEVANCE["unknown"])
            static_relevant = layer in relevant_layers

            # Get learned weights
            weights = self._learned_weights.get(task_type)
            if not weights:
                return 1.0 if static_relevant else 0.0

            # If insufficient learning data, fall back to static
            if weights.sample_count < self.min_samples or weights.confidence < 0.3:
                return 1.0 if static_relevant else 0.0

            # Combine static and learned
            learned_weight = weights.layer_weights.get(layer, 0.0)
            static_weight = 1.0 if static_relevant else 0.0

            # Blend based on confidence: more confidence = more learned influence
            blend = weights.confidence
            combined = (1 - blend) * static_weight + blend * learned_weight

            return max(0.0, min(1.0, combined))

    def get_field_relevance(self, task_type: str, layer: str, field: str) -> float:
        """Get relevance score for a specific field within a layer.

        Args:
            task_type: The type of task
            layer: The layer name
            field: The field name

        Returns:
            Relevance score (0.0 to 1.0)
        """
        with self._lock:
            # Check static relevance
            static_fields = FIELD_RELEVANCE.get(layer, {}).get(task_type, [])
            static_relevant = field in static_fields

            # Get learned weights
            weights = self._learned_weights.get(task_type)
            if not weights:
                return 1.0 if static_relevant else 0.0

            # If insufficient learning data, fall back to static
            if weights.sample_count < self.min_samples or weights.confidence < 0.3:
                return 1.0 if static_relevant else 0.0

            # Combine static and learned
            learned_weight = weights.field_weights.get(layer, {}).get(field, 0.0)
            static_weight = 1.0 if static_relevant else 0.0

            blend = weights.confidence
            combined = (1 - blend) * static_weight + blend * learned_weight

            return max(0.0, min(1.0, combined))

    def get_relevant_layers(self, task_type: str, threshold: float = 0.3) -> List[str]:
        """Get list of relevant layers for a task type, ranked by learned relevance.

        Args:
            task_type: The type of task
            threshold: Minimum relevance score to include

        Returns:
            List of layer names sorted by relevance (highest first)
        """
        with self._lock:
            relevant_layers = TASK_RELEVANCE.get(task_type, TASK_RELEVANCE["unknown"])
            weights = self._learned_weights.get(task_type)

            if not weights or weights.sample_count < self.min_samples:
                return relevant_layers

            # Score all known layers
            scored_layers = []
            for layer in set(relevant_layers) | set(weights.layer_weights.keys()):
                score = self.get_layer_relevance(task_type, layer)
                if score >= threshold:
                    scored_layers.append((layer, score))

            # Sort by score descending
            scored_layers.sort(key=lambda x: x[1], reverse=True)
            return [layer for layer, _ in scored_layers]

    def get_relevant_fields(self, task_type: str, layer: str, threshold: float = 0.3) -> List[str]:
        """Get list of relevant fields for a layer and task type, ranked by learned relevance.

        Args:
            task_type: The type of task
            layer: The layer name
            threshold: Minimum relevance score to include

        Returns:
            List of field names sorted by relevance (highest first)
        """
        with self._lock:
            # Get static fields
            static_fields = FIELD_RELEVANCE.get(layer, {}).get(task_type, [])
            weights = self._learned_weights.get(task_type)

            if not weights or weights.sample_count < self.min_samples:
                return static_fields

            # Score all known fields
            all_fields = set(static_fields) | set(weights.field_weights.get(layer, {}).keys())
            scored_fields = []
            for field in all_fields:
                score = self.get_field_relevance(task_type, layer, field)
                if score >= threshold:
                    scored_fields.append((field, score))

            scored_fields.sort(key=lambda x: x[1], reverse=True)
            return [field for field, _ in scored_fields]

    def get_weight_summary(self, task_type: str) -> Dict[str, Any]:
        """Get a summary of learned weights for a task type.

        Args:
            task_type: The type of task

        Returns:
            Dictionary with learned weights and metadata
        """
        with self._lock:
            weights = self._learned_weights.get(task_type)
            if not weights:
                return {"task_type": task_type, "learned": False}

            return {
                "task_type": task_type,
                "learned": True,
                "sample_count": weights.sample_count,
                "confidence": weights.confidence,
                "last_updated": weights.last_updated,
                "layer_weights": weights.layer_weights,
                "field_weights": weights.field_weights,
            }

    def get_all_weights(self) -> Dict[str, Dict[str, Any]]:
        """Get all learned weights for all task types."""
        with self._lock:
            return {tt: self.get_weight_summary(tt) for tt in self._learned_weights}

    def reset_task_weights(self, task_type: str) -> None:
        """Reset learned weights for a task type to static defaults."""
        with self._lock:
            if task_type in TASK_TYPES:
                # Re-initialize from static
                relevant_layers = TASK_RELEVANCE.get(task_type, TASK_RELEVANCE["unknown"])
                layer_weights = {}
                field_weights = {}

                for layer in relevant_layers:
                    layer_weights[layer] = 1.0 / len(relevant_layers) if relevant_layers else 0.0
                    fields = FIELD_RELEVANCE.get(layer, {}).get(task_type, [])
                    field_weights[layer] = {field: 1.0 / len(fields) for field in fields} if fields else {}

                self._learned_weights[task_type] = TaskRelevanceWeights(
                    task_type=task_type,
                    layer_weights=layer_weights,
                    field_weights=field_weights,
                    sample_count=0,
                    confidence=0.0,
                )
                self._save()


def create_learned_relevance_engine(
    storage_path: Optional[Path] = None,
    **kwargs,
) -> LearnedRelevanceEngine:
    """Factory function to create a LearnedRelevanceEngine instance."""
    return LearnedRelevanceEngine(storage_path=storage_path, **kwargs)