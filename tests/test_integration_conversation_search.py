"""Integration tests for cross-session conversation search functionality."""

import tempfile
import time
from pathlib import Path
from app.memory.conversation_memory import ConversationMemory


def test_conversation_memory_vector_storage_and_search():
    """Test that conversations are stored in vector DB and can be searched."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create conversation memory instance
        conv_memory = ConversationMemory(
            workspace=tmp_dir,
            storage_path="conversation_test.json",
            vector_db_name="test_conversation_vectors"
        )

        # Add some test conversations
        conv_memory.add_message("user", "How do I implement a binary search tree in Python?")
        conv_memory.add_message("assistant", "To implement a binary search tree in Python, you need to create a Node class with left and right children...")
        conv_memory.add_message("user", "What about the time complexity of BST operations?")
        conv_memory.add_message("assistant", "The average time complexity for search, insert, and delete operations in a BST is O(log n)...")

        # Add another conversation on a different topic
        conv_memory.add_message("user", "How do I bake a chocolate cake?")
        conv_memory.add_message("assistant", "To bake a chocolate cake, you'll need flour, sugar, cocoa powder, eggs, and butter...")

        # Give some time for background operations if any
        time.sleep(0.1)

        # Search for the BST conversation
        results = conv_memory.search_conversations("binary search tree python")
        assert len(results) > 0, "Should find conversations about binary search trees"

        # Check that we found relevant content
        bst_found = any("binary search" in result["content"].lower() or "bst" in result["content"].lower()
                       for result in results)
        assert bst_found, "Should find content related to binary search trees"

        # Search for the cake recipe
        results = conv_memory.search_conversations("chocolate cake recipe")
        assert len(results) > 0, "Should find conversations about chocolate cake"

        cake_found = any("chocolate cake" in result["content"].lower()
                        for result in results)
        assert cake_found, "Should find content related to chocolate cake"


def test_conversation_memory_topic_search():
    """Test topic-based search with temporal weighting."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create conversation memory instance
        conv_memory = ConversationMemory(
            workspace=tmp_dir,
            storage_path="conversation_test2.json",
            vector_db_name="test_conversation_vectors2"
        )

        # Add conversations
        conv_memory.add_message("user", "Explain machine learning concepts")
        conv_memory.add_message("assistant", "Machine learning is a subset of artificial intelligence that enables systems to learn from data...")

        # Wait a bit to simulate time passage
        time.sleep(0.1)

        conv_memory.add_message("user", "What is deep learning?")
        conv_memory.add_message("assistant", "Deep learning is a subset of machine learning that uses neural networks with multiple layers...")

        # Search by topic
        results = conv_memory.search_conversations_by_topic("machine learning")
        assert len(results) > 0, "Should find conversations about machine learning"

        # Check that results are properly formatted
        for result in results:
            assert "id" in result
            assert "similarity" in result
            assert "weighted_score" in result
            assert "content" in result
            assert "role" in result
            assert "timestamp" in result


def test_conversation_thread_retrieval():
    """Test retrieving conversation threads for context."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create conversation memory instance
        conv_memory = ConversationMemory(
            workspace=tmp_dir,
            storage_path="conversation_test3.json",
            vector_db_name="test_conversation_vectors3"
        )

        # Add a conversation
        conv_memory.add_message("user", "What is the capital of France?")
        conv_memory.add_message("assistant", "The capital of France is Paris.")
        conv_memory.add_message("user", "What about Germany?")
        conv_memory.add_message("assistant", "The capital of Germany is Berlin.")

        # Get thread around the second user message (index 2)
        thread = conv_memory.get_conversation_thread(target_turn_index=2, context_size=1)
        assert len(thread) == 3, "Should get 3 turns in the thread (index 1, 2, 3)"

        # Check the content
        assert thread[0]["content"] == "The capital of France is Paris."
        assert thread[1]["content"] == "What about Germany?"
        assert thread[2]["content"] == "The capital of Germany is Berlin."


def test_conversation_persistence_with_vector_db():
    """Test that conversations persist correctly with vector database storage."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        storage_path = Path(tmp_dir) / "persistent_conversation.json"

        # Create first conversation memory instance
        conv_memory1 = ConversationMemory(
            workspace=tmp_dir,
            storage_path=str(storage_path),
            vector_db_name="test_persistent_vectors"
        )

        # Add conversations
        conv_memory1.add_message("user", "Tell me about renewable energy")
        conv_memory1.add_message("assistant", "Renewable energy comes from natural sources like sunlight, wind, rain, tides, and geothermal heat.")

        # Force persistence
        del conv_memory1  # This should trigger cleanup

        # Create second instance pointing to the same storage
        conv_memory2 = ConversationMemory(
            workspace=tmp_dir,
            storage_path=str(storage_path),
            vector_db_name="test_persistent_vectors"
        )

        # Check that conversations were loaded
        history = conv_memory2.get_history()
        assert len(history) == 2, "Should have loaded 2 conversation turns"

        # Search should also work
        results = conv_memory2.search_conversations("renewable energy")
        assert len(results) > 0, "Should be able to search persisted conversations"


if __name__ == "__main__":
    test_conversation_memory_vector_storage_and_search()
    test_conversation_memory_topic_search()
    test_conversation_thread_retrieval()
    test_conversation_persistence_with_vector_db()
    print("All integration tests passed!")