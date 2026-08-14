"""Integration coverage for durable conversation-vector persistence and recall.

The tests use ``ConversationMemory`` and ``UnifiedRetrieval`` exactly as the
production path does.  The default deterministic embedding fallback remains
active, so the tests never contact an external embedding service.
"""

from pathlib import Path

from app.memory.conversation_memory import ConversationMemory
from app.memory.unified_retrieval import RetrievalQuery, create_unified_retrieval


def _memory(workspace: Path, storage_name: str, vector_name: str) -> ConversationMemory:
    return ConversationMemory(
        workspace=str(workspace),
        storage_path=f"data/memory/{storage_name}",
        vector_db_name=vector_name,
    )


def test_conversation_history_survives_new_memory_instance(tmp_path: Path) -> None:
    """A new instance reloads the JSON conversation history written by Session A."""
    vector_name = "conversation_persistence"
    session_a = _memory(tmp_path, "session_a.json", vector_name)
    session_a.add_message(
        "user",
        "The cobalt migration protocol requires archive verification before release.",
    )

    session_b = _memory(tmp_path, "session_a.json", vector_name)

    assert session_b is not session_a
    assert session_b._vector_db is not session_a._vector_db
    assert [turn.content for turn in session_b.get_history()] == [
        "The cobalt migration protocol requires archive verification before release."
    ]
    assert (tmp_path / "data" / "vector_db" / f"{vector_name}.faiss").exists()
    assert (tmp_path / "data" / "vector_db" / f"{vector_name}.metadata.json").exists()


def test_semantic_recall_survives_new_memory_instance(tmp_path: Path) -> None:
    """A recreated canonical retriever finds a semantically related stored turn."""
    vector_name = "conversation_semantic_restart"
    session_a = _memory(tmp_path, "session_a.json", vector_name)
    session_a.add_message(
        "user",
        "The cobalt migration protocol requires archive verification before release.",
    )
    session_a.add_message(
        "assistant",
        "The deployment checklist contains unrelated network readiness notes.",
    )

    session_b = _memory(tmp_path, "session_a.json", vector_name)
    results = create_unified_retrieval(conversation_memory=session_b).retrieve(
        RetrievalQuery(
            query="Which migration protocol needs archive verification?",
            sources=["conversation"],
            max_results=2,
            min_score=0.1,
        )
    )

    assert results
    assert results[0].content == (
        "The cobalt migration protocol requires archive verification before release."
    )
    assert results[0].source == "conversation"


def test_fresh_session_recalls_shared_persistent_conversation_vectors(tmp_path: Path) -> None:
    """An empty Session C searches vectors persisted by two earlier sessions."""
    vector_name = "conversation_cross_session"
    session_a = _memory(tmp_path, "session_a.json", vector_name)
    session_a.add_message(
        "user",
        "Harbor optics calibration requires a polarizer alignment worksheet.",
    )

    session_b = _memory(tmp_path, "session_b.json", vector_name)
    session_b.add_message(
        "user",
        "The sourdough starter schedule is unrelated to the engineering work.",
    )

    session_c = _memory(tmp_path, "session_c.json", vector_name)
    assert session_c.is_empty()
    assert not (tmp_path / "data" / "memory" / "session_c.json").exists()

    results = create_unified_retrieval(conversation_memory=session_c).retrieve(
        RetrievalQuery(
            query="Where is the polarizer alignment calibration worksheet?",
            sources=["conversation"],
            max_results=2,
            min_score=0.1,
        )
    )

    assert results
    assert results[0].content == (
        "Harbor optics calibration requires a polarizer alignment worksheet."
    )
    assert results[0].source == "conversation"
    assert results[0].metadata["similarity"] == results[0].score
