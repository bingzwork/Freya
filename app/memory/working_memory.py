"""Working Memory for Freya AI.

This module provides a temporary scratchpad for the currently executing task.
It stores the execution plan, active task state, recent tool outputs, intermediate
reasoning results, and temporary file references.

Features:
- Persists throughout a single solve() execution
- Automatically clears after task completion
- Prevents leakage between unrelated tasks
- Lightweight implementation with thread safety
"""

import json
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional, Union


@dataclass
class ToolOutput:
    """Record of a tool execution for working memory."""
    tool_name: str
    arguments: Dict[str, Any]
    result: Any
    success: bool
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolOutput":
        return cls(**data)


@dataclass
class ReasoningStep:
    """An intermediate reasoning step during task execution."""
    step_type: str  # "plan", "analysis", "decision", "observation", "hypothesis"
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReasoningStep":
        return cls(**data)


@dataclass
class ExecutionPlan:
    """The current execution plan being worked on."""
    plan_id: str
    description: str
    steps: List[Dict[str, Any]] = field(default_factory=list)
    current_step_index: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionPlan":
        return cls(**data)


class WorkingMemory:
    """Temporary scratchpad for the currently executing task.

    Stores:
    - Current execution plan
    - Active task state
    - Recent tool outputs (at least 5)
    - Intermediate reasoning results
    - Temporary file references

    Behavior:
    - Persists throughout a single solve() execution
    - Automatically clears after task completion
    - Prevents leakage between unrelated tasks
    - Lightweight implementation
    """

    def __init__(
        self,
        max_tool_outputs: int = 20,
        max_reasoning_steps: int = 50,
        max_file_refs: int = 50,
    ):
        """Initialize Working Memory.

        Args:
            max_tool_outputs: Maximum tool outputs to retain (minimum 5)
            max_reasoning_steps: Maximum reasoning steps to retain
            max_file_refs: Maximum file references to retain
        """
        self.max_tool_outputs = max(5, max_tool_outputs)
        self.max_reasoning_steps = max(10, max_reasoning_steps)
        self.max_file_refs = max(10, max_file_refs)
        self._lock = threading.RLock()

        # Core state
        self._plan: Optional[ExecutionPlan] = None
        self._task_state: Dict[str, Any] = {}
        self._tool_outputs: List[ToolOutput] = []
        self._reasoning_steps: List[ReasoningStep] = []
        self._file_references: Dict[str, Any] = {}  # filepath -> metadata
        self._variables: Dict[str, Any] = {}  # Arbitrary key-value scratchpad
        self._task_id: Optional[str] = None
        self._active: bool = False

    def start_task(self, task_id: Optional[str] = None) -> None:
        """Start a new task, clearing any previous state.

        Args:
            task_id: Optional identifier for the task
        """
        with self._lock:
            self.clear()
            self._task_id = task_id or f"task_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
            self._active = True

    def end_task(self) -> None:
        """End the current task and clear working memory."""
        with self._lock:
            self.clear()
            self._active = False

    def clear(self) -> None:
        """Clear all working memory state."""
        with self._lock:
            self._plan = None
            self._task_state = {}
            self._tool_outputs = []
            self._reasoning_steps = []
            self._file_references = {}
            self._variables = {}

    # --- Plan Management ---

    def set_plan(self, plan: ExecutionPlan) -> None:
        """Set the current execution plan."""
        with self._lock:
            self._plan = plan

    def get_plan(self) -> Optional[ExecutionPlan]:
        """Get the current execution plan."""
        with self._lock:
            return self._plan

    def update_plan_step(self, step_index: int, **updates) -> bool:
        """Update a specific step in the plan.

        Args:
            step_index: Index of the step to update
            **updates: Fields to update

        Returns:
            True if step was updated, False if index out of range
        """
        with self._lock:
            if self._plan and 0 <= step_index < len(self._plan.steps):
                self._plan.steps[step_index].update(updates)
                self._plan.updated_at = datetime.now(timezone.utc).isoformat()
                return True
            return False

    def advance_plan(self) -> bool:
        """Advance to the next plan step.

        Returns:
            True if advanced, False if no plan or at end
        """
        with self._lock:
            if self._plan and self._plan.current_step_index < len(self._plan.steps) - 1:
                self._plan.current_step_index += 1
                self._plan.updated_at = datetime.now(timezone.utc).isoformat()
                return True
            return False

    # --- Task State ---

    def set_task_state(self, key: str, value: Any) -> None:
        """Set a task state variable."""
        with self._lock:
            self._task_state[key] = value

    def get_task_state(self, key: str, default: Any = None) -> Any:
        """Get a task state variable."""
        with self._lock:
            return self._task_state.get(key, default)

    def update_task_state(self, updates: Dict[str, Any]) -> None:
        """Update multiple task state variables at once."""
        with self._lock:
            self._task_state.update(updates)

    def get_all_task_state(self) -> Dict[str, Any]:
        """Get all task state variables."""
        with self._lock:
            return self._task_state.copy()

    # --- Tool Outputs ---

    def record_tool_output(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        result: Any,
        success: bool = True,
        error: Optional[str] = None,
    ) -> ToolOutput:
        """Record a tool execution output.

        Args:
            tool_name: Name of the tool executed
            arguments: Arguments passed to the tool
            result: Tool result
            success: Whether the tool succeeded
            error: Error message if failed

        Returns:
            The recorded ToolOutput
        """
        with self._lock:
            output = ToolOutput(
                tool_name=tool_name,
                arguments=arguments,
                result=result,
                success=success,
                error=error,
            )
            self._tool_outputs.append(output)
            # Trim to max
            if len(self._tool_outputs) > self.max_tool_outputs:
                self._tool_outputs = self._tool_outputs[-self.max_tool_outputs:]
            return output

    def get_recent_tool_outputs(self, limit: int = 5) -> List[ToolOutput]:
        """Get the most recent tool outputs.

        Args:
            limit: Maximum number of outputs to return (default 5, minimum 5 per spec)

        Returns:
            List of recent ToolOutput objects (newest last)
        """
        with self._lock:
            effective_limit = max(5, limit)
            return self._tool_outputs[-effective_limit:].copy()

    def get_tool_outputs_by_name(self, tool_name: str, limit: int = 10) -> List[ToolOutput]:
        """Get recent tool outputs for a specific tool."""
        with self._lock:
            matches = [o for o in self._tool_outputs if o.tool_name == tool_name]
            return matches[-limit:].copy()

    def get_last_tool_output(self) -> Optional[ToolOutput]:
        """Get the most recent tool output."""
        with self._lock:
            return self._tool_outputs[-1] if self._tool_outputs else None

    # --- Reasoning Steps ---

    def add_reasoning_step(
        self,
        step_type: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ReasoningStep:
        """Add an intermediate reasoning step.

        Args:
            step_type: Type of reasoning ("plan", "analysis", "decision", "observation", "hypothesis")
            content: The reasoning content
            metadata: Optional metadata

        Returns:
            The created ReasoningStep
        """
        with self._lock:
            step = ReasoningStep(
                step_type=step_type,
                content=content,
                metadata=metadata or {},
            )
            self._reasoning_steps.append(step)
            if len(self._reasoning_steps) > self.max_reasoning_steps:
                self._reasoning_steps = self._reasoning_steps[-self.max_reasoning_steps:]
            return step

    def get_reasoning_steps(
        self,
        step_type: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[ReasoningStep]:
        """Get reasoning steps, optionally filtered by type."""
        with self._lock:
            steps = self._reasoning_steps
            if step_type:
                steps = [s for s in steps if s.step_type == step_type]
            if limit:
                steps = steps[-limit:]
            return steps.copy()

    def get_latest_reasoning(self, step_type: Optional[str] = None) -> Optional[ReasoningStep]:
        """Get the most recent reasoning step, optionally filtered by type."""
        with self._lock:
            if step_type:
                for step in reversed(self._reasoning_steps):
                    if step.step_type == step_type:
                        return step
                return None
            return self._reasoning_steps[-1] if self._reasoning_steps else None

    # --- File References ---

    def add_file_reference(
        self,
        filepath: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Add a temporary file reference.

        Args:
            filepath: Path to the file
            metadata: Optional metadata (e.g., {"purpose": "read", "content_preview": "..."})
        """
        with self._lock:
            self._file_references[filepath] = {
                "added_at": datetime.now(timezone.utc).isoformat(),
                "metadata": metadata or {},
            }
            # Trim if over limit
            if len(self._file_references) > self.max_file_refs:
                # Remove oldest
                oldest_key = min(
                    self._file_references.keys(),
                    key=lambda k: self._file_references[k]["added_at"]
                )
                del self._file_references[oldest_key]

    def get_file_references(self) -> Dict[str, Dict[str, Any]]:
        """Get all file references."""
        with self._lock:
            return self._file_references.copy()

    def has_file_reference(self, filepath: str) -> bool:
        """Check if a file is referenced."""
        with self._lock:
            return filepath in self._file_references

    def remove_file_reference(self, filepath: str) -> bool:
        """Remove a file reference."""
        with self._lock:
            if filepath in self._file_references:
                del self._file_references[filepath]
                return True
            return False

    # --- Scratchpad Variables ---

    def set_variable(self, key: str, value: Any) -> None:
        """Set a scratchpad variable."""
        with self._lock:
            self._variables[key] = value

    def get_variable(self, key: str, default: Any = None) -> Any:
        """Get a scratchpad variable."""
        with self._lock:
            return self._variables.get(key, default)

    def pop_variable(self, key: str, default: Any = None) -> Any:
        """Get and remove a scratchpad variable."""
        with self._lock:
            return self._variables.pop(key, default)

    def get_all_variables(self) -> Dict[str, Any]:
        """Get all scratchpad variables."""
        with self._lock:
            return self._variables.copy()

    # --- Context Building ---

    def build_context(self, max_chars: int = 8000) -> str:
        """Build a context string for LLM prompts.

        Includes plan, recent tool outputs, and recent reasoning.
        """
        with self._lock:
            parts = []

            # Plan
            if self._plan:
                parts.append(f"CURRENT PLAN: {self._plan.description}")
                if self._plan.steps:
                    parts.append("Plan Steps:")
                    for i, step in enumerate(self._plan.steps):
                        status = "→" if i == self._plan.current_step_index else " "
                        parts.append(f"  {status} {i+1}. {step.get('title', step.get('description', str(step)))}")
                parts.append("")

            # Task state
            if self._task_state:
                parts.append("TASK STATE:")
                for k, v in self._task_state.items():
                    parts.append(f"  {k}: {v}")
                parts.append("")

            # Recent tool outputs (last 5)
            if self._tool_outputs:
                parts.append("RECENT TOOL OUTPUTS:")
                for output in self._tool_outputs[-5:]:
                    status = "✓" if output.success else "✗"
                    result_preview = str(output.result)[:200]
                    if isinstance(output.result, str) and len(output.result) > 200:
                        result_preview += "..."
                    parts.append(f"  {status} {output.tool_name}({output.arguments}) -> {result_preview}")
                parts.append("")

            # Recent reasoning (last 3)
            if self._reasoning_steps:
                parts.append("RECENT REASONING:")
                for step in self._reasoning_steps[-3:]:
                    parts.append(f"  [{step.step_type}] {step.content[:200]}")
                parts.append("")

            # File references
            if self._file_references:
                parts.append("FILE REFERENCES:")
                for fp, info in list(self._file_references.items())[-10:]:
                    parts.append(f"  {fp}")
                parts.append("")

            context = "\n".join(parts)
            if len(context) > max_chars:
                context = context[-max_chars:]
            return context

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the working memory state."""
        with self._lock:
            return {
                "active": self._active,
                "task_id": self._task_id,
                "has_plan": self._plan is not None,
                "plan_steps": len(self._plan.steps) if self._plan else 0,
                "plan_current_step": self._plan.current_step_index if self._plan else 0,
                "task_state_keys": list(self._task_state.keys()),
                "tool_outputs_count": len(self._tool_outputs),
                "reasoning_steps_count": len(self._reasoning_steps),
                "file_references_count": len(self._file_references),
                "variables_count": len(self._variables),
            }

    # --- Properties ---

    @property
    def is_active(self) -> bool:
        """Check if a task is currently active."""
        return self._active

    @property
    def task_id(self) -> Optional[str]:
        """Get the current task ID."""
        return self._task_id


# Global working memory instance (for single-task execution)
_global_working_memory: Optional[WorkingMemory] = None


def get_working_memory() -> WorkingMemory:
    """Get or create the global working memory instance."""
    global _global_working_memory
    if _global_working_memory is None:
        _global_working_memory = WorkingMemory()
    return _global_working_memory


def reset_working_memory() -> None:
    """Reset the global working memory (for testing/new tasks)."""
    global _global_working_memory
    _global_working_memory = WorkingMemory()