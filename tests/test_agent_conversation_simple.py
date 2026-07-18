"""Simple tests for conversation state in FreyaAgent without tmp paths."""

from app.brain.state import ConversationState, Message
from app.agent.core_agent import FreyaAgent


def test_agent_initializes_with_conversation():
    """Test that FreyaAgent can be created (without full initialization)."""
    # This test just verifies the conversation attribute exists
    # We can't fully initialize the agent due to workspace dependencies
    # but we can check that the class has the right structure

    # Check that the __init__ signature accepts max_conversation_history
    import inspect
    sig = inspect.signature(FreyaAgent.__init__)
    params = list(sig.parameters.keys())
    assert 'workspace' in params
    assert 'max_conversation_history' in params
    assert sig.parameters['max_conversation_history'].default == 20


def test_conversation_state_import():
    """Test that ConversationState can be imported from agent module."""
    from app.agent import ConversationState, Message

    conversation = ConversationState()
    assert isinstance(conversation, ConversationState)
    assert len(conversation) == 0


def test_conversation_in_memory():
    """Test that conversation history is maintained correctly."""
    conversation = ConversationState(max_history=10)

    # Add some messages
    conversation.add_message("user", "Hello")
    conversation.add_message("assistant", "Hi there!")
    conversation.add_message("user", "How are you?")

    assert len(conversation) == 3

    history = conversation.get_history()
    assert len(history) == 3
    assert history[0].role == "user"
    assert history[0].content == "Hello"
    assert history[1].role == "assistant"
    assert history[1].content == "Hi there!"
    assert history[2].role == "user"
    assert history[2].content == "How are you?"

    # Test history text
    text = conversation.get_history_text()
    assert "User: Hello" in text
    assert "Freya: Hi there!" in text
    assert "User: How are you?" in text


def test_conversation_max_history():
    """Test that conversation respects max_history limit."""
    conversation = ConversationState(max_history=2)

    conversation.add_message("user", "First")
    conversation.add_message("assistant", "Response 1")
    conversation.add_message("user", "Second")

    assert len(conversation) == 2
    history = conversation.get_history()
    assert history[0].content == "Response 1"
    assert history[1].content == "Second"
