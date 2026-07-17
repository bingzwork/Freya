import os
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ToolResult:
    success: bool
    output: Any = None
    error: str = ""


class ToolManager:

    def __init__(self, workspace="."):

        self.workspace = Path(workspace).resolve()

        self.tools = {}

        self.register_defaults()

    def register(self, name: str, function: Callable[..., Any]):

        self.tools[name] = function

    def execute(self, name, **kwargs):

        if name not in self.tools:

            return ToolResult(
                False,
                error=f"Tool not found: {name}"
            )

        try:

            result = self.tools[name](**kwargs)

            return ToolResult(
                True,
                result
            )

        except Exception as e:

            return ToolResult(
                False,
                error=str(e)
            )

    def safe_path(self, path: str | Path) -> Path:

        full = (
            self.workspace / path
        ).resolve()

        try:

            full.relative_to(self.workspace)

        except ValueError as error:

            raise PermissionError("Access denied outside the workspace") from error

        return full

    def read_file(self, path: str) -> str:

        file = self.safe_path(path)

        return file.read_text(
            encoding="utf-8"
        )

    def write_file(self, path: str, content: str) -> str:

        file = self.safe_path(path)

        file.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        file.write_text(content, encoding="utf-8")

        return "saved"

    def create_file(self, path: str, content: str) -> str:

        file = self.safe_path(path)

        if file.exists():

            raise FileExistsError(f"Refusing to overwrite existing file: {path}")

        file.parent.mkdir(parents=True, exist_ok=True)

        file.write_text(content, encoding="utf-8")

        return f"created {path}"

    def delete_file(self, path: str) -> str:

        """Delete one workspace file; directories are never removed."""

        file = self.safe_path(path)

        if not file.is_file():

            raise FileNotFoundError(f"File not found: {path}")

        file.unlink()

        return f"deleted {path}"

    def replace_in_file(self, path: str, old_text: str, new_text: str) -> str:

        """Apply one unambiguous text replacement inside the workspace."""

        file = self.safe_path(path)

        if not file.is_file():

            raise FileNotFoundError(f"File not found: {path}")

        content = file.read_text(encoding="utf-8")

        occurrences = content.count(old_text)

        if occurrences != 1:

            raise ValueError(

                "Expected the original text exactly once; "

                f"found {occurrences} occurrences."

            )

        file.write_text(content.replace(old_text, new_text, 1), encoding="utf-8")

        return f"updated {path}"

    def list_files(self, path="."):

        root = self.safe_path(path)

        ignore = {

            ".venv",

            ".git",

            "__pycache__",

            "node_modules"

        }

        files = []

        for folder, dirs, filenames in os.walk(root):

            dirs[:] = [

                d for d in dirs

                if d not in ignore

            ]

            for filename in filenames:

                files.append(

                    str(

                        Path(folder) / filename

                    )

                )

        return files

    def run_terminal(self, command: str) -> dict[str, Any]:

        result = subprocess.run(

            command,

            shell=True,

            cwd=self.workspace,

            capture_output=True,

            text=True

        )

        return {

            "stdout": result.stdout,

            "stderr": result.stderr,

            "code": result.returncode

        }

    # Git tool wrappers - these accept tool arguments and prepend workspace

    def _git_status(self, path: str = ".") -> Any:

        from app.tools.git_tools import git_status

        return git_status(str(self.workspace), path)

    def _git_diff(self, path: str, staged: bool = False) -> Any:

        from app.tools.git_tools import git_diff

        return git_diff(str(self.workspace), path, staged)

    def _git_log(self, path: str = ".", limit: int = 10) -> Any:

        from app.tools.git_tools import git_log

        return git_log(str(self.workspace), path, limit)

    def _git_add(self, path: str) -> Any:

        from app.tools.git_tools import git_add

        return git_add(str(self.workspace), path)

    def _git_commit(self, message: str, all_files: bool = False) -> Any:

        from app.tools.git_tools import git_commit

        return git_commit(str(self.workspace), message, all_files)

    def _git_push(self, branch: str = "") -> Any:

        from app.tools.git_tools import git_push

        return git_push(str(self.workspace), branch)

    def _git_pull(self, branch: str = "") -> Any:

        from app.tools.git_tools import git_pull

        return git_pull(str(self.workspace), branch)

    def _git_checkout(self, branch: str) -> Any:

        from app.tools.git_tools import git_checkout

        return git_checkout(str(self.workspace), branch)

    def _git_branch_list(self) -> Any:

        from app.tools.git_tools import git_branch_list

        return git_branch_list(str(self.workspace))

    def _git_is_repo(self, path: str = ".") -> Any:

        from app.tools.git_tools import git_is_repo

        return git_is_repo(str(self.workspace), path)

    def register_defaults(self):

        self.register(

            "read_file",

            self.read_file

        )

        self.register(

            "write_file",

            self.write_file

        )

        self.register("create_file", self.create_file)

        self.register("delete_file", self.delete_file)

        self.register(

            "replace_in_file",

            self.replace_in_file,

        )

        self.register(

            "list_files",

            self.list_files

        )

        self.register(

            "run_terminal",

            self.run_terminal

        )

        # Register the code formatting tool

        # Import inside the function to avoid circular import issues

        from app.tools.format_tools import format_file

        self.register(

            "format_file",

            format_file

        )

        # Register git tools - use wrapper methods to pass workspace

        self.register("git_status", self._git_status)

        self.register("git_diff", self._git_diff)

        self.register("git_log", self._git_log)

        self.register("git_add", self._git_add)

        self.register("git_commit", self._git_commit)

        self.register("git_push", self._git_push)

        self.register("git_pull", self._git_pull)

        self.register("git_checkout", self._git_checkout)

        self.register("git_branch_list", self._git_branch_list)

        self.register("git_is_repo", self._git_is_repo)
