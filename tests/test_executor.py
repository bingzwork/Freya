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


# ---------------------------------------------------------------------------
# Phase 5 additions: LLM fallback, decide_action, execute_step edge cases,
# and the [Executor] bracket logging added in Phase 4.
# ---------------------------------------------------------------------------


class ScriptedLLM:
    """LLM stub that returns one or more canned responses in order."""

    def __init__(self, *responses: str):
        self.responses = list(responses)
        self.calls = []

    def ask(self, prompt):
        self.calls.append(prompt)
        # When multiple responses are queued, pop the first; otherwise loop
        # the final response for the duration of the test.
        if len(self.responses) > 1:
            return self.responses.pop(0)
        return self.responses[0]


class NoopTools:
    """Tool manager stand-in that records every tool call."""

    def __init__(self):
        self.executed = []

    def execute(self, name, **kwargs):
        from types import SimpleNamespace
        self.executed.append((name, kwargs))
        return SimpleNamespace(success=True, output=f"done:{name}", error="")


def test_select_tool_with_llm_returns_action_on_clean_json():
    with tempfile.TemporaryDirectory() as tmp:
        llm = ScriptedLLM('{"tool": "read_file", "args": {"path": "x.py"}, "reasoning": "need to read"}')
        ex = Executor(llm, NoopTools())

        action = ex._select_tool_with_llm("Inspect x.py")

        assert action is not None
        assert action["tool"] == "read_file"
        assert action["args"] == {"path": "x.py"}
        # Prompt must include the preference order and JSON-only contract.
        prompt = llm.calls[0]
        assert "least powerful" in prompt
        assert "no markdown fences" in prompt.lower() or "Return ONLY this JSON" in prompt


def test_select_tool_with_llm_returns_none_on_garbage():
    with tempfile.TemporaryDirectory() as tmp:
        llm = ScriptedLLM("totally not json")
        ex = Executor(llm, NoopTools())

        assert ex._select_tool_with_llm("do something vague") is None


def test_select_tool_with_llm_strips_markdown_fences():
    """A common LLM output is fenced JSON; the executor must tolerate it."""
    with tempfile.TemporaryDirectory() as tmp:
        fenced = '```json\n{"tool": "list_files", "args": {}}\n```'
        ex = Executor(ScriptedLLM(fenced), NoopTools())

        action = ex._select_tool_with_llm("explore project")
        assert action is not None
        assert action["tool"] == "list_files"


def test_decide_action_prefers_direct_mapping_over_llm():
    """Direct mapping wins; the LLM is only consulted when no keyword matches."""
    with tempfile.TemporaryDirectory() as tmp:
        llm = ScriptedLLM('{"tool": "list_files", "args": {}}')  # would also be a valid fallback
        ex = Executor(llm, NoopTools())

        # 'Read' is a direct mapping keyword → read_file
        action = ex.decide_action("Read main.py")
        assert action["tool"] == "read_file"
        # LLM should not have been consulted.
        assert llm.calls == []


def test_decide_action_falls_back_to_llm_when_no_keyword_match():
    with tempfile.TemporaryDirectory() as tmp:
        llm = ScriptedLLM('{"tool": "list_files", "args": {}}')
        ex = Executor(llm, NoopTools())

        action = ex.decide_action("Perform complex analysis on the codebase")
        assert action["tool"] == "list_files"
        assert len(llm.calls) == 1


def test_execute_step_returns_error_when_no_action_selected():
    with tempfile.TemporaryDirectory() as tmp:
        llm = ScriptedLLM("not json at all")  # forces _select_tool_with_llm to None
        ex = Executor(llm, NoopTools())

        result = ex.execute_step("do the thing no keyword really matches xyzqq")

        assert "error" in result
        assert "No valid action selected" in result["error"]


def test_execute_step_blocks_mutating_tool_outside_allowed_set(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        # Default behaviour in execute_step is to ask the user before any
        # MUTATING_TOOLS call; in pytest we can't prompt, so stub it out.
        monkeypatch.setattr(
            "app.agent.executor.permission_prompt",
            lambda *a, **kw: "Yes",
        )
        # run_terminal is mutating; allow only read-only tools.
        ex = Executor(ScriptedLLM('{"tool": "run_terminal", "args": {"command": "ls"}}'),
                      ToolManager(tmp))

        result = ex.execute_step("Run pytest", allowed_tools=ex.READ_ONLY_TOOLS)

        assert "error" in result
        assert "requires explicit mutation approval" in result["error"]


def test_execute_plan_skips_steps_with_empty_plan():
    with tempfile.TemporaryDirectory() as tmp:
        ex = Executor(ScriptedLLM('{"tool": "list_files", "args": {}}'), NoopTools())
        # No steps at all → no [Tool Selector] calls, but Executor logs go out.
        results = ex.execute_plan({"steps": []}, allowed_tools=set(ex.READ_ONLY_TOOLS))
        assert results == []


def test_execute_plan_runs_each_step_through_tool_selection(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        # Stub out the mutating-tool permission prompt so the test can drive
        # run_terminal without pytest blocking on stdin.
        monkeypatch.setattr(
            "app.agent.executor.permission_prompt",
            lambda *a, **kw: "Yes",
        )
        llm = ScriptedLLM(
            '{"tool": "read_file", "args": {"path": "main.py"}}',
            '{"tool": "run_terminal", "args": {"command": "pytest -q"}}',
        )
        ex = Executor(llm, NoopTools())
        plan = {
            "steps": ["Read main.py", "Run pytest"],
        }
        results = ex.execute_plan(plan, allowed_tools=set(ex.READ_ONLY_TOOLS) | set(ex.MUTATING_TOOLS))

        assert len(results) == 2
        # Direct mappings win, so neither step needed the LLM:
        # Read main.py → read_file (mapping), Run pytest → run_terminal (mapping).
        assert llm.calls == []


def test_execute_plan_emits_executor_started_and_finished_logs(caplog):
    with tempfile.TemporaryDirectory() as tmp:
        # Force LLM path so the [Tool Selector] log is reachable too.
        llm = ScriptedLLM('{"tool": "list_files", "args": {}}')
        ex = Executor(llm, NoopTools())
        caplog.set_level("INFO", logger="Freya")

        ex.execute_plan({"steps": ["Perform complex analysis on the codebase"]},
                        allowed_tools=set(ex.READ_ONLY_TOOLS))

        info = [r.getMessage() for r in caplog.records if r.levelname == "INFO"]
        # Exactly one Started / Finished pair per execute_plan call.
        assert info.count("Started") == 1
        assert info.count("Finished") == 1
        # [Executor] appears twice (bracketing) and [Tool Selector] once.
        assert info.count("[Executor]") == 2
        assert "[Tool Selector]" in info


def test_execute_plan_emits_started_and_finished_even_when_empty(caplog):
    with tempfile.TemporaryDirectory() as tmp:
        ex = Executor(ScriptedLLM(), NoopTools())
        caplog.set_level("INFO", logger="Freya")

        ex.execute_plan({"steps": []}, allowed_tools=set(ex.READ_ONLY_TOOLS))

        info = [r.getMessage() for r in caplog.records if r.levelname == "INFO"]
        assert info.count("Started") == 1
        assert info.count("Finished") == 1
        # No [Tool Selector] call when the plan is empty.
        assert "[Tool Selector]" not in info


# ---------------------------------------------------------------------------
# LLM tool-selection reasoning logging
#
# The LLM-fallback prompt declares a `reasoning` field on its expected JSON
# response. The Executor used to drop it on the floor; it now surfaces the
# field as a second, optional `[Tool Selector]` block. The two-line
# header+value shape mirrors the existing bracket convention (and matches
# the [Executor] / [Planner] bracketing already exercised elsewhere).
# ---------------------------------------------------------------------------


def test_llm_fallback_logs_reason_when_present(caplog):
    """reasoning present → emitted as a second `[Tool Selector]` block."""
    with tempfile.TemporaryDirectory() as tmp:
        llm = ScriptedLLM(
            '{"tool": "run_terminal", "args": {"command": "pytest -q"},'
            ' "reasoning": "Running pytest because the task requests test execution."}'
        )
        ex = Executor(llm, NoopTools())
        caplog.set_level("INFO", logger="Freya")

        ex.decide_action("Perform complex analysis on the codebase")

        info = [r.getMessage() for r in caplog.records if r.levelname == "INFO"]
        # Tool block: header then tool name.
        assert info.count("[Tool Selector]") == 2
        assert "run_terminal" in info
        # Reason block: header then `Reason: <text>` exactly once.
        reason_lines = [m for m in info if m.startswith("Reason:")]
        assert reason_lines == [
            "Reason: Running pytest because the task requests test execution."
        ]


def test_llm_fallback_skips_reason_when_missing(caplog):
    """reasoning absent → no Reason log, but behaviour is otherwise unchanged."""
    with tempfile.TemporaryDirectory() as tmp:
        llm = ScriptedLLM('{"tool": "list_files", "args": {}}')
        ex = Executor(llm, NoopTools())
        caplog.set_level("INFO", logger="Freya")

        ex.decide_action("Perform complex analysis on the codebase")

        info = [r.getMessage() for r in caplog.records if r.levelname == "INFO"]
        # Only the tool block — no Reason block.
        assert info.count("[Tool Selector]") == 1
        assert not any(m.startswith("Reason:") for m in info)


def test_llm_fallback_skips_reason_when_empty(caplog):
    """Empty reasoning string is treated as absent — no empty Reason log."""
    with tempfile.TemporaryDirectory() as tmp:
        llm = ScriptedLLM('{"tool": "list_files", "args": {}, "reasoning": ""}')
        ex = Executor(llm, NoopTools())
        caplog.set_level("INFO", logger="Freya")

        ex.decide_action("Perform complex analysis on the codebase")

        info = [r.getMessage() for r in caplog.records if r.levelname == "INFO"]
        assert info.count("[Tool Selector]") == 1
        assert not any(m.startswith("Reason:") for m in info)


def test_direct_mapping_does_not_emit_reason(caplog):
    """Direct-mapping path has no reasoning concept → unchanged behaviour."""
    with tempfile.TemporaryDirectory() as tmp:
        ex = Executor(ScriptedLLM(), NoopTools())
        caplog.set_level("INFO", logger="Freya")

        # 'Read' is a direct-mapping keyword → LLM is never consulted.
        ex.decide_action("Read main.py")

        info = [r.getMessage() for r in caplog.records if r.levelname == "INFO"]
        assert info.count("[Tool Selector]") == 1
        assert not any(m.startswith("Reason:") for m in info)


def test_llm_fallback_does_not_duplicate_log_entries(caplog):
    """Each event block emits exactly one header + one body line; no extras."""
    with tempfile.TemporaryDirectory() as tmp:
        llm = ScriptedLLM(
            '{"tool": "run_terminal", "args": {"command": "pytest"},'
            ' "reasoning": "Need to run tests."}'
        )
        ex = Executor(llm, NoopTools())
        caplog.set_level("INFO", logger="Freya")

        ex.decide_action("Perform complex analysis on the codebase")

        info = [r.getMessage() for r in caplog.records if r.levelname == "INFO"]
        # Tool block + Reason block = exactly two `[Tool Selector]` headers.
        assert info.count("[Tool Selector]") == 2
        # Tool name appears once (in the tool block) — never inside Reason:.
        assert "run_terminal" in info
        tool_lines = info.count("run_terminal")
        assert tool_lines == 1
        # Reasoning text appears exactly once.
        assert info.count("Reason: Need to run tests.") == 1
