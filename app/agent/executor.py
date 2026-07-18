import json
import re
import sys
from typing import Any

from app.core.logger import logger
from app.ui.permission_menu import permission_prompt


class Executor:

    READ_ONLY_TOOLS = {
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
    MUTATING_TOOLS = {
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

    def __init__(
        self,
        llm,
        tools,
    ):

        self.llm = llm
        self.tools = tools

    def decide_action(self, step: str) -> dict[str, Any] | None:

        prompt = f"""
You are Freya, an autonomous coding agent.

Choose an action for this task:

{step}

Available tools:

- read_file(path)
- write_file(path, content)
- replace_in_file(path, old_text, new_text)
- list_files()
- run_terminal(command)

Return ONLY JSON.

Examples:

{{
"tool": "list_files",
"args": {{
}}
}}

or

{{
"tool": "read_file",
"args": {{
"path":"main.py"
}}
}}
"""

        answer = self.llm.ask(prompt)

        answer = re.sub(
            r"```json|```",
            "",
            answer
        ).strip()

        try:

            return json.loads(answer)

        except:

            return None

    def execute_step(
        self,
        step: str,
        allowed_tools: set[str] | None = None,
    ) -> dict[str, Any]:
        logger.info(f"Executing: {step}")

        action = self.decide_action(step)

        if not isinstance(action, dict):
            return {"error": "No valid action selected"}

        tool = action.get("tool")
        args = action.get("args", {})
        allowed_tools = allowed_tools or self.READ_ONLY_TOOLS

        # Ask for confirmation for mutating tools
        if tool in self.MUTATING_TOOLS:
            action_desc = f"{tool}({args})"
            choice = permission_prompt(
                title=f"Agent requests permission to execute: {action_desc}",
                options=["Yes", "No"],
                default="No",
            )
            if choice != "Yes":
                return {
                    "action": action,
                    "error": f"User denied permission for {tool}.",
                }

        if tool not in allowed_tools:
            return {
                "action": action,
                "error": f"Tool '{tool}' requires explicit mutation approval.",
            }

        if not isinstance(args, dict):
            return {"action": action, "error": "Tool arguments must be a JSON object."}

        result = self.tools.execute(tool, **args)

        return {
            "action": action,
            "result": result.output if result.success else result.error
        }

    def execute_plan(
        self,
        plan: dict[str, Any],
        allowed_tools: set[str] | None = None,
    ) -> list[dict[str, Any]]:

        results = []

        for step in plan.get("steps", [])[:8]:

            results.append(
                {
                    "step": step,
                    "result": self.execute_step(step, allowed_tools)
                }
            )

        return results
