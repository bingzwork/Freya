"""Production retrieval integration tests for durable conversation recall."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from app.core.events import EventBus
from app.memory.coordinator import create_memory_coordinator
from app.memory.conversation_memory import ConversationMemory, ConversationTurn
from app.memory.unified_retrieval import RetrievalQuery, create_unified_retrieval


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _conversation_memory(workspace: Path, name: str = "production_conversations") -> ConversationMemory:
    return ConversationMemory(
        workspace=str(workspace),
        storage_path="data/memory/production_conversation.json",
        vector_db_name=name,
    )


def test_canonical_memory_coordinator_returns_ranked_semantic_conversation_results():
    """The production coordinator reaches UnifiedRetrieval and ranks the relevant memory first."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        coordinator = create_memory_coordinator(Path(tmp_dir), EventBus())
        coordinator.record_conversation(ConversationTurn(
            role="user",
            content="The user prefers working on Freya with a memory-first learning architecture.",
        ))
        coordinator.record_conversation(ConversationTurn(
            role="assistant",
            content="That preference will guide the implementation plan.",
        ))
        coordinator.record_conversation(ConversationTurn(
            role="user",
            content="The deployment checklist includes a health probe and release notes.",
        ))

        results = coordinator.unified_retrieval.retrieve(
            RetrievalQuery(
                query="What architecture preference was established for Freya?",
                sources=["conversation"],
                max_results=3,
                min_score=0.1,
            )
        )

        assert results
        assert "memory-first learning architecture" in results[0].content
        assert results[0].source == "conversation"
        assert results[0].metadata["similarity"] == results[0].score
        assert results == sorted(results, key=lambda result: result.score, reverse=True)


def test_canonical_retrieval_returns_deterministic_empty_results_for_no_match():
    """No semantic match is represented as an empty list by the stable production contract."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        conversation = _conversation_memory(Path(tmp_dir))
        conversation.add_message("user", "Freya uses durable conversation memory for retrieval.")
        retrieval = create_unified_retrieval(conversation_memory=conversation)

        results = retrieval.retrieve(
            RetrievalQuery(
                query="qzxvplm unrelated query token",
                sources=["conversation"],
                min_score=1.0,
            )
        )

        assert results == []


def test_cross_process_restart_retrieves_persisted_semantic_conversation_memory():
    """A child process writes the memory; a fresh canonical retriever reads it after restart."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        workspace = Path(tmp_dir)
        session_a = workspace / "write_conversation_session.py"
        session_a.write_text(
            "from app.memory.conversation_memory import ConversationMemory\n"
            f"memory = ConversationMemory(workspace={str(workspace)!r}, "
            "storage_path='data/memory/production_conversation.json', "
            "vector_db_name='production_conversations')\n"
            "memory.add_message('user', "
            "'The user prefers working on Freya with a memory-first learning architecture.')\n"
            "memory.add_message('assistant', "
            "'The team also tracks implementation estimates for the next release.')\n"
            "memory.add_message('user', "
            "'The team also keeps unrelated release notes for deployments.')\n",
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment["PYTHONPATH"] = os.pathsep.join(
            filter(None, [str(PROJECT_ROOT), environment.get("PYTHONPATH")])
        )
        completed = subprocess.run(
            [sys.executable, str(session_a)],
            cwd=PROJECT_ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr

        # This is a new object in a different process from the writer. It must
        # reconstruct the persisted FAISS index and metadata from disk.
        restarted_memory = _conversation_memory(workspace)
        retrieval = create_unified_retrieval(conversation_memory=restarted_memory)
        results = retrieval.retrieve(
            RetrievalQuery(
                query="Which Freya architecture preference was previously established?",
                sources=["conversation"],
                max_results=2,
                min_score=0.1,
            )
        )

        assert results
        assert "memory-first learning architecture" in results[0].content
        assert restarted_memory.get_history()[0].content.startswith("The user prefers")
        assert (workspace / "data" / "vector_db" / "production_conversations.faiss").exists()
        assert (workspace / "data" / "vector_db" / "production_conversations.metadata.json").exists()
