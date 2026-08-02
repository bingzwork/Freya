import os
import subprocess
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Callable, Optional, List, Dict
from contextlib import asynccontextmanager

from app.core.file_allowlist import FileAllowlist, get_file_allowlist, FileOperation, AccessRule
from app.core.logger import logger


@dataclass
class ToolResult:
    success: bool
    output: Any = None
    error: str = ""


@dataclass
class ParallelExecutionResult:
    """Result of parallel tool execution."""
    results: List[ToolResult]
    total_time: float
    successful_count: int
    failed_count: int
    tool_names: List[str]

    def get_successful_results(self) -> List[ToolResult]:
        """Get only successful results."""
        return [r for r in self.results if r.success]

    def get_failed_results(self) -> List[ToolResult]:
        """Get only failed results."""
        return [r for r in self.results if not r.success]

    def get_result_by_name(self, name: str) -> Optional[ToolResult]:
        """Get result for a specific tool by name."""
        for r in self.results:
            if hasattr(r, '_tool_name') and r._tool_name == name:
                return r
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_time": self.total_time,
            "successful_count": self.successful_count,
            "failed_count": self.failed_count,
            "tool_names": self.tool_names,
            "results": [
                {
                    "tool_name": getattr(r, '_tool_name', f'tool_{i}'),
                    "success": r.success,
                    "output": r.output,
                    "error": r.error,
                }
                for i, r in enumerate(self.results)
            ],
        }


class ParallelExecutor:
    """Manages parallel execution of tools with concurrency control."""

    def __init__(self, max_workers: int = 4):
        """Initialize the parallel executor.

        Args:
            max_workers: Maximum number of concurrent tool executions
        """
        self.max_workers = max_workers
        self._executor: Optional[ThreadPoolExecutor] = None
        self._local_executor = threading.local()

    def _get_executor(self) -> ThreadPoolExecutor:
        """Get or create thread pool executor."""
        if not hasattr(self._local_executor, 'executor') or self._local_executor.executor is None:
            self._local_executor.executor = ThreadPoolExecutor(max_workers=self.max_workers)
        return self._local_executor.executor

    def shutdown(self):
        """Shutdown the executor."""
        if hasattr(self._local_executor, 'executor') and self._local_executor.executor:
            self._local_executor.executor.shutdown(wait=True)
            self._local_executor.executor = None

    def execute_parallel(
        self,
        tool_manager: 'ToolManager',
        tool_calls: List[Dict[str, Any]],
        max_workers: Optional[int] = None,
    ) -> ParallelExecutionResult:
        """Execute multiple tools in parallel.

        Args:
            tool_manager: The ToolManager instance with registered tools
            tool_calls: List of dicts with 'name' and 'kwargs' keys
            max_workers: Override max workers for this execution

        Returns:
            ParallelExecutionResult with all results
        """
        import time
        start_time = time.time()

        workers = max_workers or self.max_workers
        executor = ThreadPoolExecutor(max_workers=workers)

        # Submit all tasks
        future_to_info = {}
        for idx, call in enumerate(tool_calls):
            tool_name = call['name']
            kwargs = call.get('kwargs', {})
            future = executor.submit(self._execute_single_tool, tool_manager, tool_name, kwargs)
            future_to_info[future] = (tool_name, idx)

        # Collect results
        results = []
        tool_names = []

        for future in as_completed(future_to_info):
            tool_name, idx = future_to_info[future]
            tool_names.append(tool_name)
            try:
                result = future.result()
                result._tool_name = tool_name
                result._tool_index = idx
                results.append(result)
            except Exception as e:
                result = ToolResult(success=False, error=f"Execution failed: {str(e)}")
                result._tool_name = tool_name
                result._tool_index = idx
                results.append(result)

        executor.shutdown(wait=True)

        total_time = time.time() - start_time
        successful_count = sum(1 for r in results if r.success)
        failed_count = len(results) - successful_count

        # Sort results to match original tool_calls order
        # Use index as key since multiple calls may use the same tool name
        index_to_result = {getattr(r, '_tool_index', i): r for i, r in enumerate(results)}
        ordered_results = [index_to_result.get(i) for i in range(len(tool_calls))]
        ordered_results = [r for r in ordered_results if r is not None]

        return ParallelExecutionResult(
            results=ordered_results,
            total_time=total_time,
            successful_count=successful_count,
            failed_count=failed_count,
            tool_names=[c['name'] for c in tool_calls],
        )

    def _execute_single_tool(
        self,
        tool_manager: 'ToolManager',
        tool_name: str,
        kwargs: Dict[str, Any]
    ) -> ToolResult:
        """Execute a single tool."""
        if tool_name not in tool_manager.tools:
            return ToolResult(
                success=False,
                error=f"Tool not found: {tool_name}"
            )

        try:
            result = tool_manager.tools[tool_name](**kwargs)
            return ToolResult(success=True, output=result)
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def execute_parallel_async(
        self,
        tool_manager: 'ToolManager',
        tool_calls: List[Dict[str, Any]],
        max_workers: Optional[int] = None,
    ) -> ParallelExecutionResult:
        """Execute multiple tools in parallel asynchronously.

        Args:
            tool_manager: The ToolManager instance with registered tools
            tool_calls: List of dicts with 'name' and 'kwargs' keys
            max_workers: Override max workers for this execution

        Returns:
            ParallelExecutionResult with all results
        """
        import time
        start_time = time.time()

        workers = max_workers or self.max_workers
        semaphore = asyncio.Semaphore(workers)

        async def execute_one(call: Dict[str, Any], idx: int) -> ToolResult:
            async with semaphore:
                tool_name = call['name']
                kwargs = call.get('kwargs', {})

                if tool_name not in tool_manager.tools:
                    return ToolResult(success=False, error=f"Tool not found: {tool_name}")

                try:
                    # Run sync tool in thread pool
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(
                        None,
                        lambda: tool_manager.tools[tool_name](**kwargs)
                    )
                    tool_result = ToolResult(success=True, output=result)
                    tool_result._tool_name = tool_name
                    tool_result._tool_index = idx
                    return tool_result
                except Exception as e:
                    tool_result = ToolResult(success=False, error=str(e))
                    tool_result._tool_name = tool_name
                    tool_result._tool_index = idx
                    return tool_result

        # Execute all tools concurrently
        tasks = [execute_one(call, i) for i, call in enumerate(tool_calls)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle any exceptions from gather
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                tool_result = ToolResult(success=False, error=str(result))
                tool_result._tool_name = tool_calls[i]['name']
                tool_result._tool_index = i
                processed_results.append(tool_result)
            else:
                processed_results.append(result)

        total_time = time.time() - start_time
        successful_count = sum(1 for r in processed_results if r.success)
        failed_count = len(processed_results) - successful_count

        return ParallelExecutionResult(
            results=processed_results,
            total_time=total_time,
            successful_count=successful_count,
            failed_count=failed_count,
            tool_names=[c['name'] for c in tool_calls],
        )


class ToolManager:

    def __init__(self, workspace=".", file_allowlist: Optional[FileAllowlist] = None):

        self.workspace = Path(workspace).resolve()
        self.file_allowlist = file_allowlist or get_file_allowlist()

        # Configure allowlist for this workspace
        self._configure_allowlist_for_workspace()

        self.tools = {}

        self.register_defaults()

    def _configure_allowlist_for_workspace(self):
        """Configure the file allowlist with workspace-specific rules."""
        workspace_str = str(self.workspace)

        # Add rule for workspace root directory (for LIST operation)
        self.file_allowlist.add_rule(AccessRule(
            pattern=workspace_str,
            operations={FileOperation.LIST, FileOperation.READ},
            description=f"Workspace root directory: {workspace_str}",
            tags={"type": "workspace_root", "workspace": workspace_str},
        ))

        # Add rules for workspace directory contents
        self.file_allowlist.add_rule(AccessRule(
            pattern=f"{workspace_str}/**",
            operations={FileOperation.READ, FileOperation.WRITE, FileOperation.CREATE, FileOperation.MODIFY, FileOperation.DELETE, FileOperation.LIST},
            description=f"Full access to workspace contents: {workspace_str}",
            tags={"type": "workspace", "workspace": workspace_str},
        ))

        # Add rules for common project directories
        common_dirs = [
            "data/**",
            "logs/**",
            "cache/**",
            "tmp/**",
            "temp/**",
            ".freya/**",
        ]
        for dir_pattern in common_dirs:
            full_pattern = f"{workspace_str}/{dir_pattern}"
            self.file_allowlist.add_rule(AccessRule(
                pattern=full_pattern,
                operations={FileOperation.READ, FileOperation.WRITE, FileOperation.CREATE, FileOperation.MODIFY, FileOperation.DELETE, FileOperation.LIST},
                description=f"Project directory: {dir_pattern}",
                tags={"type": "project_dir", "workspace": workspace_str},
            ))

    def _validate_path(self, path: str | Path, operation: FileOperation, source: str = "") -> Path:
        """Validate a path against the file allowlist.

        Args:
            path: The path to validate
            operation: The file operation being performed
            source: The source/component requesting access

        Returns:
            Resolved Path if allowed

        Raises:
            PermissionError: If access is denied
        """
        full_path = (self.workspace / path).resolve()

        # Check if path is within workspace (additional safety)
        try:
            full_path.relative_to(self.workspace)
        except ValueError:
            raise PermissionError(f"Access denied: path outside workspace: {path}")

        # Validate through file allowlist
        self.file_allowlist.require_allowed(full_path, operation, source or "ToolManager")

        return full_path

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

        file = self._validate_path(path, FileOperation.READ, "read_file")

        return file.read_text(
            encoding="utf-8"
        )

    def write_file(self, path: str, content: str) -> str:

        file = self._validate_path(path, FileOperation.WRITE, "write_file")

        file.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        file.write_text(content, encoding="utf-8")

        return "saved"

    def create_file(self, path: str, content: str) -> str:

        file = self._validate_path(path, FileOperation.CREATE, "create_file")

        if file.exists():

            raise FileExistsError(f"Refusing to overwrite existing file: {path}")

        file.parent.mkdir(parents=True, exist_ok=True)

        file.write_text(content, encoding="utf-8")

        return f"created {path}"

    def delete_file(self, path: str) -> str:

        """Delete one workspace file; directories are never removed."""

        file = self._validate_path(path, FileOperation.DELETE, "delete_file")

        if not file.is_file():

            raise FileNotFoundError(f"File not found: {path}")

        file.unlink()

        return f"deleted {path}"

    def replace_in_file(self, path: str, old_text: str, new_text: str) -> str:

        """Apply one unambiguous text replacement inside the workspace."""

        file = self._validate_path(path, FileOperation.MODIFY, "replace_in_file")

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

        path_obj = self._validate_path(path, FileOperation.LIST, "list_files")

        ignore = {

            ".venv",

            ".git",

            "__pycache__",

            "node_modules"

        }

        files = []

        for folder, dirs, filenames in os.walk(path_obj):

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

        # Register HTTP tools
        from app.tools.http_tools import (
            http_get,
            http_post,
            http_put,
            http_delete,
            http_patch,
            http_head,
            http_request,
        )
        self.register("http_get", http_get)
        self.register("http_post", http_post)
        self.register("http_put", http_put)
        self.register("http_delete", http_delete)
        self.register("http_patch", http_patch)
        self.register("http_head", http_head)
        self.register("http_request", http_request)
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

    def execute_parallel(
        self,
        tool_calls: List[Dict[str, Any]],
        max_workers: Optional[int] = None,
    ) -> ParallelExecutionResult:
        """Execute multiple tools in parallel.

        Args:
            tool_calls: List of dicts with 'name' and 'kwargs' keys
                       Example: [{'name': 'read_file', 'kwargs': {'path': 'file.txt'}}, ...]
            max_workers: Maximum concurrent executions (default: from ParallelExecutor)

        Returns:
            ParallelExecutionResult with all results
        """
        from app.core.tool_manager import ParallelExecutor
        executor = ParallelExecutor(max_workers=max_workers or 4)
        try:
            return executor.execute_parallel(self, tool_calls, max_workers)
        finally:
            executor.shutdown()

    async def execute_parallel_async(
        self,
        tool_calls: List[Dict[str, Any]],
        max_workers: Optional[int] = None,
    ) -> ParallelExecutionResult:
        """Execute multiple tools in parallel asynchronously.

        Args:
            tool_calls: List of dicts with 'name' and 'kwargs' keys
            max_workers: Maximum concurrent executions

        Returns:
            ParallelExecutionResult with all results
        """
        from app.core.tool_manager import ParallelExecutor
        executor = ParallelExecutor(max_workers=max_workers or 4)
        try:
            return await executor.execute_parallel_async(self, tool_calls, max_workers)
        finally:
            executor.shutdown()

    def execute_batch(
        self,
        tool_name: str,
        kwargs_list: List[Dict[str, Any]],
        max_workers: Optional[int] = None,
    ) -> ParallelExecutionResult:
        """Execute the same tool multiple times with different arguments in parallel.

        Args:
            tool_name: Name of the tool to execute
            kwargs_list: List of argument dictionaries for each execution
            max_workers: Maximum concurrent executions

        Returns:
            ParallelExecutionResult with all results
        """
        tool_calls = [{'name': tool_name, 'kwargs': kwargs} for kwargs in kwargs_list]
        return self.execute_parallel(tool_calls, max_workers)

    async def execute_batch_async(
        self,
        tool_name: str,
        kwargs_list: List[Dict[str, Any]],
        max_workers: Optional[int] = None,
    ) -> ParallelExecutionResult:
        """Execute the same tool multiple times with different arguments in parallel (async).

        Args:
            tool_name: Name of the tool to execute
            kwargs_list: List of argument dictionaries for each execution
            max_workers: Maximum concurrent executions

        Returns:
            ParallelExecutionResult with all results
        """
        tool_calls = [{'name': tool_name, 'kwargs': kwargs} for kwargs in kwargs_list]
        return await self.execute_parallel_async(tool_calls, max_workers)