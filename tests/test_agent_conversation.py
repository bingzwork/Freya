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
