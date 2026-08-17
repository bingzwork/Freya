from app.intent.classifier import IntentType, classify_intent


def test_windows_file_read_request_is_file_operation():
    classification = classify_intent(
        "Please read C:\\AI Projects\\Freya\\tests\\.mvp_dry_run\\hello.txt and tell me what it contains."
    )

    assert classification.intent is IntentType.FILE_OPERATION
    assert classification.should_plan is True
    assert classification.should_answer_directly is False


def test_relative_file_request_is_file_operation():
    classification = classify_intent("Open tests/.mvp_dry_run/hello.txt and summarize it.")

    assert classification.intent is IntentType.FILE_OPERATION
    assert classification.should_plan is True


def test_executor_preserves_absolute_windows_path_with_spaces():
    from app.agent.executor import Executor
    from app.core.tool_manager import ToolManager

    executor = Executor(None, ToolManager("."))
    action = executor._map_step_to_tool(
        "Read C:\\AI Projects\\Freya\\tests\\.mvp_dry_run\\hello.txt"
    )

    assert action == {
        "tool": "read_file",
        "args": {"path": "C:\\AI Projects\\Freya\\tests\\.mvp_dry_run\\hello.txt"},
    }
