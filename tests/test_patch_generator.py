"""Tests for the PatchGenerator prompt and JSON contract."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from unittest.mock import Mock
import pytest

from app.editing.patch_generator import PatchGenerator


def test_patch_generator_returns_operations():
    """Return a list of PatchOperations from a clean LLM JSON response."""
    mock_llm = Mock()
    mock_llm.ask.return_value = '''{
        "operations": [
            {
                "action": "replace",
                "path": "test.txt",
                "old_text": "hello",
                "new_text": "world"
            }
        ]
    }'''
    generator = PatchGenerator(mock_llm)
    operations = generator.propose("make test.txt say world", "dummy context")
    assert len(operations) == 1
    op = operations[0]
    assert op.action == "replace"
    assert op.path == "test.txt"
    assert op.old_text == "hello"
    assert op.new_text == "world"


def test_patch_generator_prompt_includes_task():
    """The prompt sent to the LLM must include the task verbatim."""
    captured = {}

    def capture(prompt):
        captured["prompt"] = prompt
        return '{"operations": [{"action": "create", "path": "x.py", "new_text": "y"}]}'

    mock_llm = Mock()
    mock_llm.ask.side_effect = capture
    PatchGenerator(mock_llm).propose("change greeting in hello.py", "ctx")
    assert "change greeting in hello.py" in captured["prompt"]


def test_patch_generator_prompt_includes_context():
    """The prompt must include the LLM-relevant code context."""
    captured = {}

    def capture(prompt):
        captured["prompt"] = prompt
        return '{"operations": [{"action": "create", "path": "x.py", "new_text": "y"}]}'

    mock_llm = Mock()
    mock_llm.ask.side_effect = capture
    PatchGenerator(mock_llm).propose("task", "def hello():\n    return 1\n")
    assert "def hello():" in captured["prompt"]
    assert "Relevant code:" in captured["prompt"]


def test_patch_generator_prompt_requests_only_create_or_replace():
    """Prompt rules forbid actions other than create/replace."""
    captured = {}

    def capture(prompt):
        captured["prompt"] = prompt
        return '{"operations": [{"action": "create", "path": "x.py", "new_text": "y"}]}'

    mock_llm = Mock()
    mock_llm.ask.side_effect = capture
    PatchGenerator(mock_llm).propose("task", "ctx")
    p = captured["prompt"]
    assert '"create"' in p or "create" in p
    assert '"replace"' in p or 'Only "create" or "replace"' in p


def test_patch_generator_prompt_specifies_json_only_contract():
    """Prompt forbids markdown fences and prose around the JSON."""
    captured = {}

    def capture(prompt):
        captured["prompt"] = prompt
        return '{"operations": [{"action": "create", "path": "x.py", "new_text": "y"}]}'

    mock_llm = Mock()
    mock_llm.ask.side_effect = capture
    PatchGenerator(mock_llm).propose("task", "ctx")
    p = captured["prompt"].lower()
    assert "no markdown" in p
    # The schema block must paint the exact operations shape.
    assert '"operations"' in captured["prompt"]


def test_patch_generator_strips_markdown_fences():
    """LLM responses wrapped in fences should be stripped before parsing."""
    mock_llm = Mock()
    mock_llm.ask.return_value = '```json\n{"operations": [{"action": "create", "path": "x.py", "new_text": "y"}]}\n```'
    operations = PatchGenerator(mock_llm).propose("create x.py", "")
    assert len(operations) == 1
    assert operations[0].action == "create"
    assert operations[0].path == "x.py"


def test_patch_generator_strips_unfenced_markdown():
    """Fences without `json` language tag should also be stripped."""
    mock_llm = Mock()
    mock_llm.ask.return_value = '```\n{"operations": [{"action": "create", "path": "y.py", "new_text": "z"}]}\n```'
    operations = PatchGenerator(mock_llm).propose("create y.py", "")
    assert len(operations) == 1
    assert operations[0].path == "y.py"


def test_patch_generator_raises_on_invalid_json():
    """Garbage LLM output raises a clear ValueError rather than silent data."""
    mock_llm = Mock()
    mock_llm.ask.return_value = "Sorry, I cannot help with that."
    generator = PatchGenerator(mock_llm)
    with pytest.raises(ValueError, match="valid patch JSON"):
        generator.propose("task", "ctx")


def test_patch_generator_rejects_empty_operations_list():
    """A JSON response with no operations fails patch-engine validation."""
    mock_llm = Mock()
    mock_llm.ask.return_value = '{"operations": []}'
    generator = PatchGenerator(mock_llm)
    with pytest.raises(Exception):
        generator.propose("task", "ctx")


def test_patch_generator_rejects_unsupported_action():
    """An action other than create/replace is rejected by the patch engine."""
    mock_llm = Mock()
    mock_llm.ask.return_value = '{"operations": [{"action": "delete", "path": "x.py"}]}'
    generator = PatchGenerator(mock_llm)
    with pytest.raises(Exception):
        generator.propose("delete x.py", "ctx")


def test_patch_generator_supports_multiple_operations():
    """Multiple operations in one response should be returned in order."""
    mock_llm = Mock()
    mock_llm.ask.return_value = '''{
        "operations": [
            {"action": "create", "path": "new.py", "new_text": "print(1)"},
            {"action": "replace", "path": "old.py", "old_text": "v1", "new_text": "v2"}
        ]
    }'''
    operations = PatchGenerator(mock_llm).propose("two ops", "")
    assert len(operations) == 2
    assert operations[0].action == "create"
    assert operations[1].action == "replace"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
