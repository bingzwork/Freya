import json


class ToolCaller:

    def __init__(self, llm):
        self.llm = llm

    def choose(self, task):

        text = task.lower()

        # ---------- Read / Explain ----------
        if (
            text.startswith("explain")
            or text.startswith("describe")
            or text.startswith("what is")
            or text.startswith("show")
            or text.startswith("review")
            or text.startswith("analyze")
        ):
            return {
                "tool": "list_files",
                "args": {}
            }

        # ---------- Read file ----------
        if text.startswith("read "):
            return {
                "tool": "read_file",
                "args": {
                    "path": task[5:].strip()
                }
            }

        # ---------- Write file ----------
        if text.startswith("write "):
            return {
                "tool": "write_file",
                "args": {}
            }

        # ---------- Terminal ----------
        if (
            "terminal" in text
            or "pip " in text
            or "python " in text
            or "pytest" in text
            or "flake8" in text
            or "run " in text
        ):
            return {
                "tool": "run_terminal",
                "args": {
                    "command": task
                }
            }

        # ---------- Ask LLM ----------
        prompt = f"""
Choose ONE tool.

Available tools:

- read_file
- write_file
- list_files
- run_terminal

Return ONLY JSON.

Task:
{task}
"""

        answer = self.llm.ask(prompt)

        try:
            return json.loads(answer)
        except Exception:
            return {
                "tool": "list_files",
                "args": {}
            }