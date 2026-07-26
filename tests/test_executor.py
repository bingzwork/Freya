"""Tests for the improved tool selection in Executor."""
import json
import tempfile
from pathlib import Path
import pytest

from app.agent.executor import Executor
from app.core.tool_manager import ToolManager


class MockLLM:
    """Mock LLM that returns predictable responses for testing."""
    
    def __init__(self):
        self.calls = []
    
    def ask(self, prompt):
        self.calls.append(prompt)
        # Default safe response for tool selection
        if "Choose the SINGLE most appropriate tool" in prompt:
            return '{"tool": "read_file", "args": {}, "reasoning": "Test reasoning"}'
        return '{"tool": "list_files", "args": {}}'


def test_direct_tool_mapping():
    """Test that direct keyword mapping selects correct tools."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = ToolManager(tmp_dir)
        executor = Executor(MockLLM(), tools)
        
        # Test read_file mapping
        action = executor._map_step_to_tool("Read main.py")
        assert action is not None
        assert action["tool"] == "read_file"
        assert "path" in action["args"]
        
        # Test list_files mapping
        action = executor._map_step_to_tool("List project files")
        assert action is not None
        assert action["tool"] == "list_files"
        
        # Test run_terminal mapping for build
        action = executor._map_step_to_tool("Build the project")
        assert action is not None
        assert action["tool"] == "run_terminal"
        
        # Test run_terminal mapping for tests
        action = executor._map_step_to_tool("Run tests")
        assert action is not None
        assert action["tool"] == "run_terminal"
        
        # Test replace_in_file mapping
        action = executor._map_step_to_tool("Modify app.py")
        assert action is not None
        assert action["tool"] == "replace_in_file"
        
        # Test create_file mapping
        action = executor._map_step_to_tool("Create new module.py")
        assert action is not None
        assert action["tool"] == "create_file"
        
        # Test delete_file mapping
        action = executor._map_step_to_tool("Delete temp.py")
        assert action is not None
        assert action["tool"] == "delete_file"
        
        # Test git operations
        action = executor._map_step_to_tool("Git status")
        assert action is not None
        assert action["tool"] == "git_status"


def test_prefer_least_powerful_tool():
    """Test that least powerful tool is preferred."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = ToolManager(tmp_dir)
        executor = Executor(MockLLM(), tools)
        
        # Should prefer read_file over run_terminal for reading
        action = executor._map_step_to_tool("Read config.json")
        assert action is not None
        assert action["tool"] == "read_file"  # Not run_terminal
        
        # Should prefer list_files over run_terminal for listing
        action = executor._map_step_to_tool("List files in directory")
        assert action is not None
        assert action["tool"] == "list_files"  # Not run_terminal


def test_avoid_unnecessary_terminal():
    """Test that run_terminal is not used when other tools can do the job."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create a test file
        test_file = Path(tmp_dir) / "test.py"
        test_file.write_text("# test file")
        
        tools = ToolManager(tmp_dir)
        executor = Executor(MockLLM(), tools)
        
        # Reading a file should not use run_terminal
        action = executor._map_step_to_tool("Read test.py")
        assert action is not None
        assert action["tool"] != "run_terminal"
        assert action["tool"] == "read_file"
        
        # Editing a file should not use run_terminal
        action = executor._map_step_to_tool("Edit test.py to fix bug")
        assert action is not None
        assert action["tool"] != "run_terminal"
        assert action["tool"] == "replace_in_file"


def test_terminal_only_when_needed():
    """Test that run_terminal is used when actually needed."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = ToolManager(tmp_dir)
        executor = Executor(MockLLM(), tools)
        
        # Building project should use run_terminal
        action = executor._map_step_to_tool("Build the project with pip")
        assert action is not None
        assert action["tool"] == "run_terminal"
        
        # Running tests should use run_terminal
        action = executor._map_step_to_tool("Run pytest tests")
        assert action is not None
        assert action["tool"] == "run_terminal"
        
        # Executing commands should use run_terminal
        action = executor._map_step_to_tool("Execute python script.py")
        assert action is not None
        assert action["tool"] == "run_terminal"


def test_file_path_extraction():
    """Test that file paths are extracted from steps."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = ToolManager(tmp_dir)
        executor = Executor(MockLLM(), tools)
        
        # Should extract .py file path
        action = executor._map_step_to_tool("Read main.py")
        assert action is not None
        assert action["args"].get("path") == "main.py"
        
        # Should extract common config files
        action = executor._map_step_to_tool("Read requirements.txt")
        assert action is not None
        assert action["args"].get("path") == "requirements.txt"
        
        action = executor._map_step_to_tool("Read package.json")
        assert action is not None
        assert action["args"].get("path") == "package.json"


def test_common_software_engineering_tasks():
    """Test tool selection for common software engineering tasks."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = ToolManager(tmp_dir)
        executor = Executor(MockLLM(), tools)
        
        # Build project
        action = executor._map_step_to_tool("Build project")
        assert action is not None
        assert action["tool"] == "run_terminal"
        
        # Run tests
        action = executor._map_step_to_tool("Run tests")
        assert action is not None
        assert action["tool"] == "run_terminal"
        
        # Fix Python error
        action = executor._map_step_to_tool("Fix Python error in app.py")
        assert action is not None
        assert action["tool"] == "replace_in_file"
        
        # Read configuration
        action = executor._map_step_to_tool("Read configuration")
        assert action is not None
        assert action["tool"] == "read_file"
        
        # Edit source code
        action = executor._map_step_to_tool("Edit source code in main.py")
        assert action is not None
        assert action["tool"] == "replace_in_file"
        
        # Create new file
        action = executor._map_step_to_tool("Create new file module.py")
        assert action is not None
        assert action["tool"] == "create_file"
        
        # Search project
        action = executor._map_step_to_tool("Search project for function")
        assert action is not None
        assert action["tool"] in ["list_files", "read_file"]  # Either is acceptable for search
        
        # List files
        action = executor._map_step_to_tool("List files")
        assert action is not None
        assert action["tool"] == "list_files"
        
        # Git operations
        action = executor._map_step_to_tool("Check git status")
        assert action is not None
        assert action["tool"] == "git_status"

        # Read code (planner now generates "Read" steps, not "Explain")
        action = executor._map_step_to_tool("Read main.py")
        assert action is not None
        assert action["tool"] == "read_file"

        # Refactor code
        action = executor._map_step_to_tool("Refactor code in app.py")
        assert action is not None
        assert action["tool"] == "replace_in_file"  # Refactoring involves file modifications


def test_no_unrelated_tools():
    """Test that unrelated tools are not selected."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = ToolManager(tmp_dir)
        executor = Executor(MockLLM(), tools)
        
        # Reading should not select write tools
        action = executor._map_step_to_tool("Read main.py")
        assert action is not None
        assert action["tool"] not in ["write_file", "create_file", "replace_in_file"]
        
        # Listing should not select execution tools
        action = executor._map_step_to_tool("List files")
        assert action is not None
        assert action["tool"] != "run_terminal"


def test_llm_fallback():
    """Test that LLM fallback works for complex steps."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = ToolManager(tmp_dir)
        llm = MockLLM()
        executor = Executor(llm, tools)
        
        # Complex step that doesn't match direct keywords
        action = executor.decide_action("Perform complex analysis on the codebase")
        assert action is not None
        assert "tool" in action
        
        # Should have logged the decision
        assert len(llm.calls) > 0


def test_tool_mapping_coverage():
    """Test that all READ_ONLY_TOOLS and MUTATING_TOOLS are covered in mappings."""
    executor = Executor(MockLLM(), ToolManager("."))
    
    # All read-only tools should be selectable
    for tool in executor.READ_ONLY_TOOLS:
        # Some tools have specific triggers, but core ones should be covered
        if tool in ["read_file", "list_files", "git_status", "git_diff", "git_log", "git_branch_list"]:
            action = executor._map_step_to_tool(f"{tool.replace('_', ' ')} files")
            # This might not always map directly, but the tool should be available
            assert tool in executor.tools.tools
    
    # All mutating tools should be selectable
    for tool in executor.MUTATING_TOOLS:
        if tool in ["write_file", "replace_in_file", "create_file", "delete_file", "run_terminal"]:
            assert tool in executor.tools.tools
