"""Two-process probe used by the durable-memory restart integration test."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from app.core.events import EventBus
from app.memory.coordinator import MemoryCoordinator
from app.memory.engineering_lessons import LessonSeverity, LessonType

MARKERS = {
    "conversation": "Persistence conversation marker CONV-731. Atlas uses port 7319.",
    "semantic": "Persistence semantic marker SEM-731. Atlas uses port 7319.",
    "episodic": "Persistence episode marker EPI-731",
    "project": "Persistence project marker PROJ-731",
    "experience": "Persistence experience marker EXP-731",
    "lesson": "Persistence engineering marker ENG-731",
    "goal": "Persistence goal marker GOAL-731",
    "task": "Persistence task marker TASK-731",
}


def build(workspace: Path) -> MemoryCoordinator:
    return MemoryCoordinator(workspace, EventBus())


def write_phase(workspace: Path) -> None:
    coordinator = build(workspace)
    coordinator.record_conversation({"role": "user", "content": MARKERS["conversation"]})
    coordinator.semantic_memory.set("persistence", "semantic_marker", MARKERS["semantic"])
    coordinator.episodic_memory.record("milestone", MARKERS["episodic"], "restart verification")
    project = coordinator.project_memory.record("note", {"marker": MARKERS["project"]})
    coordinator.experience_memory.store(title=MARKERS["experience"], description="durable experience", category="test")
    coordinator.engineering_lessons.store(
        title=MARKERS["lesson"], description="durable lesson", lesson_type=LessonType.PATTERN.value,
        category="test", severity=LessonSeverity.RECOMMENDED.value,
    )
    goal = coordinator.goal_storage.create(name=MARKERS["goal"], description="durable goal")
    coordinator.task_memory.start_task("task-731", MARKERS["task"])
    coordinator.cross_memory_references.add_node("semantic", "semantic_marker", "semantic", MARKERS["semantic"])
    coordinator.cross_memory_references.add_node("project", project["timestamp"], "project", MARKERS["project"])
    coordinator.cross_memory_references.add_reference(
        "semantic", "semantic_marker", "project", project["timestamp"], "related", confidence=1.0,
    )
    print(json.dumps({"phase": "write", "goal_id": goal.id, "project_id": project["timestamp"]}))


def read_phase(workspace: Path) -> None:
    coordinator = build(workspace)
    semantic_results = coordinator.conversation_memory.search_conversations(
        "Which port does Atlas use?", max_results=5, min_similarity=0.1,
    )
    refs = coordinator.cross_memory_references.get_references("semantic", "semantic_marker")
    print(json.dumps({
        "phase": "read",
        "conversation": [turn.content for turn in coordinator.conversation_memory.get_history()],
        "semantic": coordinator.semantic_memory.get("persistence", "semantic_marker").content,
        "episodic": [event.title for event in coordinator.episodic_memory.recent()],
        "project": coordinator.project_memory.search("PROJ-731"),
        "experience": [entry.title for entry in coordinator.experience_memory.all()],
        "lessons": [lesson.title for lesson in coordinator.engineering_lessons.all()],
        "goals": [goal.name for goal in coordinator.goal_storage.all()],
        "tasks": [task.description for task in coordinator.task_memory.get_task_history()],
        "semantic_recall": [result["content"] for result in semantic_results],
        "references": [reference.to_dict() for reference in refs],
    }))


if __name__ == "__main__":
    workspace = Path(sys.argv[1])
    (write_phase if sys.argv[2] == "write" else read_phase)(workspace)
