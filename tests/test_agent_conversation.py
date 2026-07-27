"""Integration tests for conversation state in FreyaAgent."""

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from app.agent.core_agent import FreyaAgent
from app.brain.state import ConversationState, Message


class MockLLM:
    """Mock LLM for testing."""

    def __init__(self, response="Test response"):
        self.response = response

    def ask(self, prompt):
        return self.response


@pytest.fixture
def mock_agent(tmp_path: Path):
    """Create a FreyaAgent with mocked components."""
    with patch("app.agent.core_agent.LLM") as mock_llm_cls, \
         patch("app.agent.core_agent.ToolManager") as mock_tools_cls, \
         patch("app.agent.core_agent.ProjectMemory") as mock_memory_cls, \
         patch("app.agent.core_agent.Executor") as mock_executor_cls, \
         patch("app.agent.core_agent.Planner") as mock_planner_cls, \
         patch("app.agent.core_agent.PatchEngine") as mock_patch_engine_cls, \
         patch("app.agent.core_agent.PatchGenerator") as mock_patch_gen_cls, \
         patch("app.agent.core_agent.VerificationRunner") as mock_verifier_cls, \
         patch("app.core.project_index.ProjectIndex") as mock_proj_index_cls, \
         patch("app.core.symbol_index.SymbolIndex") as mock_sym_index_cls, \
         patch("app.intelligence.file_locator.FileLocator") as mock_file_locator_cls, \
         patch("app.intelligence.lexical_search.LexicalSearch") as mock_lexical_cls, \
         patch("app.intelligence.dependency_graph.DependencyGraph") as mock_dep_graph_cls, \
         patch("app.intelligence.context_builder.ContextBuilder") as mock_ctx_builder_cls, \
         patch("app.rag.SimpleRetriever") as mock_retriever_cls:

        # Setup mocks
        mock_llm = MockLLM("Test answer")
        mock_llm_cls.return_value = mock_llm

        mock_tools = MagicMock()
        mock_tools_cls.return_value = mock_tools

        mock_memory = MagicMock()
        mock_memory_cls.return_value = mock_memory

        mock_executor = MagicMock()
        mock_executor_cls.return_value = mock_executor

        mock_planner = MagicMock()
        mock_planner.return_value = {"steps": []}
        mock_planner_cls.return_value = mock_planner

        mock_patch_engine = MagicMock()
        mock_patch_engine_cls.return_value = mock_patch_engine

        mock_patch_gen = MagicMock()
        mock_patch_gen_cls.return_value = mock_patch_gen

        mock_verifier = MagicMock()
        mock_verifier_cls.return_value = mock_verifier

        mock_proj_index = MagicMock()
        mock_proj_index.files = {}
        mock_proj_index_cls.return_value = mock_proj_index

        mock_sym_index = MagicMock()
        mock_sym_index.files = {}
        mock_sym_index.symbols = {}
        mock_sym_index_cls.return_value = mock_sym_index

        mock_file_locator = MagicMock()
        mock_file_locator.locate.return_value = []
        mock_file_locator_cls.return_value = mock_file_locator

        mock_lexical = MagicMock()
        mock_lexical.search.return_value = []
        mock_lexical_cls.return_value = mock_lexical

        mock_dep_graph = MagicMock()
        mock_dep_graph.build.return_value = None
        mock_dep_graph_cls.return_value = mock_dep_graph

        mock_ctx_builder = MagicMock()
        mock_ctx_builder.build.return_value = ""
        mock_ctx_builder_cls.return_value = mock_ctx_builder

        mock_retriever = MagicMock()
        mock_retriever.retrieve.return_value = []
        mock_retriever_cls.return_value = mock_retriever

        # Create agent
        with patch("app.core.logger.logger") as mock_logger:
            agent = FreyaAgent(str(tmp_path))

        yield agent


class TestFreyaAgentConversation:
    """Test conversation state integration in FreyaAgent."""

    def test_agent_has_conversation_state(self, mock_agent):
        """FreyaAgent should initialize with ConversationState."""
        assert hasattr(mock_agent, "conversation")
        assert isinstance(mock_agent.conversation, ConversationState)

    def test_agent_conversation_default_max_history(self, mock_agent):
        """FreyaAgent should use default max_history of 20."""
        assert mock_agent.conversation.max_history == 20

    def test_agent_conversation_custom_max_history(self, tmp_path: Path):
        """FreyaAgent should accept custom max_conversation_history."""
        with patch("app.agent.core_agent.LLM"), \
             patch("app.agent.core_agent.ToolManager"), \
             patch("app.agent.core_agent.ProjectMemory"), \
             patch("app.agent.core_agent.Executor"), \
             patch("app.agent.core_agent.Planner"), \
             patch("app.core.project_index.ProjectIndex"), \
             patch("app.core.symbol_index.SymbolIndex"), \
             patch("app.intelligence.file_locator.FileLocator"), \
             patch("app.intelligence.lexical_search.LexicalSearch"), \
             patch("app.intelligence.dependency_graph.DependencyGraph"), \
             patch("app.intelligence.context_builder.ContextBuilder"), \
             patch("app.rag.SimpleRetriever"), \
             patch("app.core.logger.logger"):

            agent = FreyaAgent(str(tmp_path), max_conversation_history=10)
            assert agent.conversation.max_history == 10

    def test_new_conversation_clears_history(self, mock_agent):
        """new_conversation should clear the conversation state."""
        # Add some messages
        mock_agent.conversation.add_message("user", "Test")
        assert len(mock_agent.conversation) == 1

        mock_agent.new_conversation()
        assert len(mock_agent.conversation) == 0

    def test_clear_conversation_clears_history(self, mock_agent):
        """clear_conversation should clear the conversation state."""
        mock_agent.conversation.add_message("user", "Test")
        assert len(mock_agent.conversation) == 1

        mock_agent.clear_conversation()
        assert len(mock_agent.conversation) == 0

    def test_get_conversation_history(self, mock_agent):
        """get_conversation_history should return the message history."""
        mock_agent.conversation.add_message("user", "Hello")
        mock_agent.conversation.add_message("assistant", "Hi there!")

        history = mock_agent.get_conversation_history()
        assert len(history) == 2
        assert history[0].role == "user"
        assert history[1].role == "assistant"

    def test_get_conversation_length(self, mock_agent):
        """get_conversation_length should return the number of messages."""
        assert mock_agent.get_conversation_length() == 0

        mock_agent.conversation.add_message("user", "Test")
        assert mock_agent.get_conversation_length() == 1

        mock_agent.conversation.add_message("assistant", "Response")
        assert mock_agent.get_conversation_length() == 2

    def test_agent_conversation_persistence_path(self, tmp_path: Path):
        """FreyaAgent should accept conversation_persistence_path."""
        with patch("app.agent.core_agent.LLM"), \
             patch("app.agent.core_agent.ToolManager"), \
             patch("app.agent.core_agent.ProjectMemory"), \
             patch("app.agent.core_agent.Executor"), \
             patch("app.agent.core_agent.Planner"), \
             patch("app.agent.core_agent.PatchEngine"), \
             patch("app.agent.core_agent.PatchGenerator"), \
             patch("app.agent.core_agent.VerificationRunner"), \
             patch("app.core.project_index.ProjectIndex"), \
             patch("app.core.symbol_index.SymbolIndex"), \
             patch("app.intelligence.file_locator.FileLocator"), \
             patch("app.intelligence.lexical_search.LexicalSearch"), \
             patch("app.intelligence.dependency_graph.DependencyGraph"), \
             patch("app.intelligence.context_builder.ContextBuilder"), \
             patch("app.rag.SimpleRetriever"), \
             patch("app.core.logger.logger"):

            save_path = str(tmp_path / "conversation.json")
            agent = FreyaAgent(str(tmp_path), max_conversation_history=10, conversation_persistence_path=save_path)
            assert agent.conversation._persistence_path == save_path

    def test_save_conversation_method(self, mock_agent, tmp_path: Path):
        """save_conversation should save conversation to file."""
        import os
        mock_agent.conversation.add_message("user", "Test")
        mock_agent.conversation.add_message("assistant", "Response")

        save_path = str(tmp_path / "conversation.json")
        mock_agent.save_conversation(save_path)

        assert os.path.exists(save_path)

    def test_load_conversation_method(self, mock_agent, tmp_path: Path):
        """load_conversation should load conversation from file."""
        import os
        save_path = str(tmp_path / "conversation.json")

        # Save a conversation
        mock_agent.conversation.add_message("user", "Saved message")
        mock_agent.save_conversation(save_path)
        mock_agent.clear_conversation()
        assert len(mock_agent.conversation) == 0

        # Load it back
        mock_agent.load_conversation(save_path)
        assert len(mock_agent.conversation) == 1
        assert mock_agent.get_conversation_history()[0].content == "Saved message"


class TestFreyaAgentConversationalControl:
    """Tests verifying that CONVERSATIONAL_CONTROL commands short-circuit the
    LLM pipeline in FreyaAgent.run.
    """

    def test_stop_short_circuits_before_llm(self, mock_agent):
        """A 'stop' command must NOT call MockLLM.ask and return its default 'Test answer'."""
        # The MockLLM always returns 'Test answer'. If short-circuit fails,
        # the agent would invoke the LLM and we'd see 'Test answer' in the
        # reply.
        result = mock_agent.run("stop")
        assert "Test answer" not in result
        assert "Stopped" in result or "stop" in result.lower()

    def test_cancel_short_circuits_before_llm(self, mock_agent):
        result = mock_agent.run("cancel")
        # The MockLLM returns 'Test answer'. If short-circuit fails, the
        # LLM is invoked and 'Test answer' shows up in the reply.
        assert "Test answer" not in result
        assert "cancel" in result.lower()

    def test_undo_short_circuits_before_llm(self, mock_agent):
        result = mock_agent.run("undo")
        assert "Test answer" not in result
        assert "undo" in result.lower()

    def test_status_short_circuits_before_llm(self, mock_agent):
        result = mock_agent.run("status")
        assert "Test answer" not in result

    def test_control_command_added_to_conversation_history(self, mock_agent):
        mock_agent.run("stop")
        history = mock_agent.get_conversation_history()
        assert len(history) == 2
        assert history[0].role == "user"
        assert history[0].content == "stop"
        assert history[1].role == "assistant"

    def test_compound_control_with_greeting_still_short_circuits(self, mock_agent):
        """'hi stop' should still trigger conversational control (control wins)."""
        result = mock_agent.run("hi stop")
        assert "Test answer" not in result
