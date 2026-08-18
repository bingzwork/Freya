from app.routing.knowledge_first_resolver import _classify_conversational_request


def test_greeting_and_identity_are_conversational():
    assert _classify_conversational_request("hello") == "greeting"
    assert _classify_conversational_request("what is your name?") == "identity"


def test_stable_explanation_does_not_enter_research_or_planning():
    assert _classify_conversational_request("what is Python?") == "stable_explanation"
    assert _classify_conversational_request("what is a database?") == "stable_explanation"


def test_explicit_research_bypasses_stable_explanation_gate():
    assert _classify_conversational_request("what is the latest AI news?") is None
    assert _classify_conversational_request("search the web for Python news") is None


def test_task_language_bypasses_stable_explanation_gate():
    assert _classify_conversational_request("what is Python and build a web app") is None
