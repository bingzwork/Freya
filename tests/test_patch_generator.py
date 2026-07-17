import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from unittest.mock import Mock
from app.editing.patch_generator import PatchGenerator

def test_patch_generator_returns_operations():
    # Mock LLM that returns a simple replace operation
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
    # Use a real PatchEngine to parse the payload
    generator = PatchGenerator(mock_llm)
    # Provide dummy task and context (they are not used because we mock LLM)
    operations = generator.propose("make test.txt say world", "dummy context")
    # Should be a list of PatchOperation
    assert len(operations) == 1
    op = operations[0]
    assert op.action == "replace"
    assert op.path == "test.txt"
    assert op.old_text == "hello"
    assert op.new_text == "world"

if __name__ == "__main__":
    test_patch_generator_returns_operations()
    print("Test passed")
