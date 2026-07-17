"""Tests for Autonomous Approval for Non-destructive Tools."""

import pytest
from unittest.mock import MagicMock, patch

from app.agent.executor import Executor
from app.core.tool_manager import ToolManager


@pytest.fixture
def mock_llm():
    """Create a mock LLM that returns a valid tool response."""
    mock = MagicMock()
    mock.ask.return_value = '{"tool": "list_files", "args": {}}'
    return mock


@pytest.fixture
def executor(mock_llm):
    """Create an Executor with mock LLM and real ToolManager."""
    tm = ToolManager()
    return Executor(mock_llm, tm)


def test_all_tools_classified():
    """Test that all registered tools are classified as read-only or mutating."""
    tm = ToolManager()
    all_tools = set(tm.tools.keys())
    classified = Executor.READ_ONLY_TOOLS | Executor.MUTATING_TOOLS
    unclassified = all_tools - classified

    assert len(unclassified) == 0, f"Unclassified tools: {unclassified}"


def test_read_only_tools_defined():
    """Test that READ_ONLY_TOOLS set contains expected tools."""
    expected_read_only = {
        "list_files",
        "read_file",
        "http_get",
        "http_post",
        "http_put",
        "http_delete",
        "http_patch",
        "http_head",
        "http_request",
        "git_status",
        "git_diff",
        "git_log",
        "git_branch_list",
        "git_is_repo",
    }
    assert expected_read_only.issubset(Executor.READ_ONLY_TOOLS)


def test_mutating_tools_defined():
    """Test that MUTATING_TOOLS set contains expected tools."""
    expected_mutating = {
        "write_file",
        "replace_in_file",
        "run_terminal",
        "create_file",
        "delete_file",
        "format_file",
        "git_add",
        "git_commit",
        "git_push",
        "git_pull",
        "git_checkout",
    }
    assert expected_mutating.issubset(Executor.MUTATING_TOOLS)


def test_read_only_tools_no_confirmation(mock_llm):
    """Test that read-only tools do NOT prompt for user confirmation."""
    tm = ToolManager()
    executor = Executor(mock_llm, tm)

    mock_llm.ask.return_value = '{"tool": "list_files", "args": {}}'

    with patch.object(tm, 'execute') as mock_execute:
        mock_execute.return_value = MagicMock(success=True, output=["file1.py"])

        with patch('sys.stdout') as mock_stdout:
            with patch('sys.stdin') as mock_stdin:
                mock_stdout.write = MagicMock()
                mock_stdin.readline = MagicMock(return_value="1")

                result = executor.execute_step("List files")

                for call in mock_stdout.write.call_args_list:
                    args = call[0]
                    if isinstance(args, str):
                        assert "requests permission" not in args.lower()
                        assert "yes" not in args.lower() or "choose" not in args.lower()

                assert result["action"]["tool"] == "list_files"


def test_mutating_tools_require_confirmation(mock_llm):
    """Test that mutating tools DO prompt for user confirmation."""
    tm = ToolManager()
    executor = Executor(mock_llm, tm)

    mock_llm.ask.return_value = '{"tool": "write_file", "args": {"path": "test.py", "content": ""}}'

    with patch.object(tm, 'execute') as mock_execute:
        mock_execute.return_value = MagicMock(success=True, output="saved")

        with patch('sys.stdout') as mock_stdout:
            with patch('sys.stdin') as mock_stdin:
                mock_stdout.write = MagicMock()
                mock_stdin.readline = MagicMock(return_value="1")

                result = executor.execute_step("Write a file")

                stdout_calls = [str(c[0][0]) for c in mock_stdout.write.call_args_list if c[0]]
                output = ''.join(stdout_calls)
                assert "requests permission" in output.lower()
                assert "write_file" in output

                assert result["action"]["tool"] == "write_file"


def test_mutating_tool_denied(mock_llm):
    """Test that mutating tools are blocked when user denies permission."""
    tm = ToolManager()
    executor = Executor(mock_llm, tm)

    mock_llm.ask.return_value = '{"tool": "write_file", "args": {"path": "test.py", "content": ""}}'

    with patch('sys.stdout') as mock_stdout:
        with patch('sys.stdin') as mock_stdin:
            mock_stdout.write = MagicMock()
            mock_stdin.readline = MagicMock(return_value="2")

            result = executor.execute_step("Write a file")

            assert result["error"] == "User denied permission for write_file."


def test_allowed_tools_restriction(mock_llm):
    """Test that tools outside allowed_tools are blocked."""
    tm = ToolManager()
    executor = Executor(mock_llm, tm)

    mock_llm.ask.return_value = '{"tool": "write_file", "args": {"path": "test.py", "content": ""}}'

    with patch('sys.stdout') as mock_stdout:
        with patch('sys.stdin') as mock_stdin:
            mock_stdout.write = MagicMock()
            mock_stdin.readline = MagicMock(return_value="1")

            result = executor.execute_step("Write a file", allowed_tools=set(Executor.READ_ONLY_TOOLS))

            assert "requires explicit mutation approval" in result["error"]


def test_http_tools_classified_as_read_only():
    """Test that all HTTP tools are classified as read-only."""
    http_tools = {
        "http_get",
        "http_post",
        "http_put",
        "http_delete",
        "http_patch",
        "http_head",
        "http_request",
    }
    assert http_tools.issubset(Executor.READ_ONLY_TOOLS)


def test_git_read_tools_classified_as_read_only():
    """Test that git read-only tools are classified as read-only."""
    git_read_tools = {
        "git_status",
        "git_diff",
        "git_log",
        "git_branch_list",
        "git_is_repo",
    }
    assert git_read_tools.issubset(Executor.READ_ONLY_TOOLS)


def test_git_write_tools_classified_as_mutating():
    """Test that git write tools are classified as mutating."""
    git_write_tools = {
        "git_add",
        "git_commit",
        "git_push",
        "git_pull",
        "git_checkout",
    }
    assert git_write_tools.issubset(Executor.MUTATING_TOOLS)
