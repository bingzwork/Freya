from pathlib import Path

from app.core.events import EventBus
from app.memory.coordinator import create_memory_coordinator
from app.memory.cross_references import CrossMemoryReferences
from app.memory.episodic_memory import create_episodic_memory
from app.memory.long_term_memory import LongTermEntry, create_long_term_memory
from app.memory.unified_retrieval import (
    MemoryRetriever,
    RetrievalQuery,
    RetrievalResult,
    UnifiedRetrieval,
)


class _StaticRetriever(MemoryRetriever):
    def __init__(self, source: str, results: list[RetrievalResult]):
        self._source = source
        self._results = results

    @property
    def source_name(self) -> str:
        return self._source

    def is_available(self) -> bool:
        return True

    def retrieve(self, query: RetrievalQuery) -> list[RetrievalResult]:
        return list(self._results)


def test_unified_retrieval_uses_one_canonical_retriever_per_extended_source():
    """The production module exposes one implementation for each extended source."""
    from app.memory import unified_retrieval

    for class_name in (
        "TaskMemoryRetriever",
        "LongTermMemoryRetriever",
        "EpisodicMemoryRetriever",
        "SemanticMemoryRetriever",
    ):
        definitions = Path(unified_retrieval.__file__).read_text(encoding="utf-8").splitlines()
        assert sum(f"class {class_name}(MemoryRetriever):" in line for line in definitions) == 1


def test_unified_retrieval_deterministically_ranks_candidates_by_score():
    retrieval = UnifiedRetrieval()
    retrieval.add_retriever(
        _StaticRetriever(
            "test",
            [
                RetrievalResult("lower", "test", "2", 0.2),
                RetrievalResult("higher", "test", "1", 0.9),
            ],
        )
    )

    results = retrieval.retrieve(RetrievalQuery("query", max_results=2, min_score=0.0))

    assert [result.content for result in results] == ["higher", "lower"]
    assert [result.score for result in results] == [0.9, 0.2]


def test_long_term_memory_persists_and_reconstructs_equivalent_entries(tmp_path: Path):
    memory = create_long_term_memory(tmp_path)
    stored = memory.set(
        "preference",
        "editor",
        "vim",
        confidence=0.85,
        description="The preferred editor for Freya work.",
    )

    reloaded = create_long_term_memory(tmp_path)
    reconstructed = reloaded.get_entry("preference", "editor")

    assert isinstance(stored, LongTermEntry)
    assert reconstructed is not None
    assert reconstructed.entry_id == stored.entry_id
    assert reconstructed.value == "vim"
    assert reconstructed.confidence == 0.85
    assert reconstructed.description == stored.description


def test_episodic_memory_persists_and_reconstructs_events(tmp_path: Path):
    memory = create_episodic_memory(tmp_path)
    event = memory.record(
        event_type="task_execution",
        title="Task 16 verification",
        description="Validated durable memory reconstruction.",
        outcome="success",
        tags=["memory", "retrieval"],
    )

    reloaded = create_episodic_memory(tmp_path)
    reconstructed = reloaded.get_events_by_type("task_execution")

    assert len(reconstructed) == 1
    assert reconstructed[0].event_id == event.event_id
    assert reconstructed[0].description == event.description
    assert reconstructed[0].tags == ["memory", "retrieval"]


def test_cross_memory_inference_is_triggered_by_canonical_coordinator_write(tmp_path: Path):
    coordinator = create_memory_coordinator(tmp_path, EventBus())
    coordinator.add_fact(
        "architecture",
        "retrieval",
        "Freya uses memory first retrieval architecture",
        description="Canonical retrieval preference.",
    )
    coordinator.record_conversation(
        {
            "role": "user",
            "content": "Freya uses memory first retrieval architecture for planning.",
        }
    )

    graph = coordinator.cross_memory_references
    exported = graph.export_graph()
    assert len(exported["edges"]) == 1
    edge = exported["edges"][0]
    assert {edge["source_memory"], edge["target_memory"]} == {"conversation", "long_term"}
    assert edge["metadata"]["inferred"] is True

    # Re-running inference for the same write is idempotent, and self-links are ignored.
    conversation_id = edge["source_id"] if edge["source_memory"] == "conversation" else edge["target_id"]
    coordinator._infer_cross_memory_references(
        "conversation",
        conversation_id,
        "Freya uses memory first retrieval architecture for planning.",
    )
    assert len(graph.export_graph()["edges"]) == 1
    assert graph.infer_references_from_content(
        "conversation",
        conversation_id,
        "same content",
        {"conversation": [(conversation_id, "same content")]},
    ) == []

    restarted = CrossMemoryReferences(
        storage_path=tmp_path / "data" / "memory" / "cross_references.json",
        auto_infer=True,
        event_bus=EventBus(),
    )
    assert len(restarted.export_graph()["edges"]) == 1
    assert restarted.export_graph()["edges"][0]["reference_id"] == edge["reference_id"]


def test_coordinator_task_execution_uses_real_task_and_episodic_write_contracts(tmp_path: Path):
    coordinator = create_memory_coordinator(tmp_path, EventBus())
    coordinator.task_memory.start_task("task-16", "Verify coordinator persistence")

    coordinator.record_task_execution(
        "task-16",
        {"success": True, "data": "Task 16 persistence verification completed."},
    )

    task = coordinator.task_memory.get_task("task-16")
    assert task is not None
    assert task.status == "completed"

    restarted_events = create_episodic_memory(tmp_path).get_events_by_task("task-16")
    assert len(restarted_events) == 1
    assert restarted_events[0].outcome == "success"
    assert "persistence verification completed" in restarted_events[0].description
