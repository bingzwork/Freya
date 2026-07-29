import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Union, Optional, List

from app.core.logger import logger
from app.ui.permission_menu import permission_prompt
from app.planner.plan_manager import Plan, PlanConfig, Task, TaskPriority, TaskCategory, TaskStatus
from app.planner.task_graph import CycleDetectedError
from app.planner.scheduler import Scheduler, SchedulingStrategy
from app.planner.resource_allocator import ResourceAllocator, Resource, ResourceType


# File extensions recognized when extracting a path from a planning step.
# `read_file` accepts the broader set; write/replace tools only target source
# formats so unknown extensions like `.css`/`.html` aren't mis-routed.
_READ_PATH_EXTENSIONS = (
    ".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".cfg",
    ".ini", ".js", ".ts", ".css", ".html",
)
_WRITE_PATH_EXTENSIONS = (
    ".py", ".md", ".txt", ".json", ".yaml", ".yml",
)

# Well-known config / manifest filenames (no spaces, no extension tail) that
# `read_file` should match even when the planner doesn't quote the extension.
_COMMON_FILE_NAMES = (
    "requirements.txt", "package.json", "pyproject.toml", "setup.py", "README.md",
)


class Executor:
    READ_ONLY_TOOLS = {
        "list_files", "read_file", "http_get", "http_post", "http_put", "http_delete",
        "http_patch", "http_head", "http_request", "git_status", "git_diff",
        "git_log", "git_branch_list", "git_is_repo",
    }

    MUTATING_TOOLS = {
        "write_file", "replace_in_file", "run_terminal", "create_file", "delete_file",
        "format_file", "git_add", "git_commit", "git_push", "git_pull", "git_checkout",
    }

    # Tool mapping for common planning steps
    # ORDER: Most specific (multi-word) phrases first, then general keywords
    TOOL_MAPPING = {
        # === PHRASE-BASED MAPPINGS (Check these FIRST) ===
        # Build/Install operations
        "restore dependencies if required": "run_terminal",
        "restore dependencies": "run_terminal",
        "detect project type": "list_files",
        "build project": "run_terminal",
        "run build command": "run_terminal",
        "fix build errors": "replace_in_file",
        "rebuild": "run_terminal",
        "report results": "list_files",

        # Debug/Fix operations
        "read error file": "read_file",
        "read code files": "read_file",
        "locate relevant code": "list_files",
        "fix the code": "replace_in_file",
        "run validation tests": "run_terminal",
        "run tests": "run_terminal",

        # Refactor operations
        "read existing implementation": "read_file",
        "modify code files": "replace_in_file",

        # Create/Implement operations
        "read requirements": "read_file",
        "write implementation files": "write_file",
        "add tests": "write_file",
        "run validation": "run_terminal",

        # Review operations
        "read code files": "read_file",
        "write feedback": "write_file",
        "suggest fixes": "write_file",

        # Test operations
        "write test files": "write_file",
        "fix issues": "replace_in_file",
        "re-run tests": "run_terminal",

        # Optimize operations
        "profile performance": "run_terminal",
        "implement optimizations": "replace_in_file",
        "run benchmarks": "run_terminal",
        "compare results": "read_file",

        # Git operations - these should be checked before general keywords
        "git status": "git_status",
        "git diff": "git_diff",
        "git log": "git_log",
        "git add": "git_add",
        "git commit": "git_commit",
        "git push": "git_push",
        "git pull": "git_pull",
        "git checkout": "git_checkout",
        "git branch": "git_branch_list",

        # Install operations
        "install dependencies": "run_terminal",
        "install packages": "run_terminal",

        # File deletion
        "delete file": "delete_file",
        "delete temp": "delete_file",
        "remove file": "delete_file",
        "remove temp": "delete_file",
        "inspect files": "list_files",

        # === WORD-BASED MAPPINGS (Check these SECOND) ===
        # File operations
        "read": "read_file",
        "view": "read_file",
        "open": "read_file",
        "refactor": "replace_in_file",
        "fix": "replace_in_file",
        "browse": "list_files",
        "list": "list_files",
        "find": "list_files",
        "search": "list_files",
        "create": "create_file",
        "write": "write_file",
        "modify": "replace_in_file",
        "edit": "replace_in_file",
        "update": "replace_in_file",
        "replace": "replace_in_file",
        "remove": "delete_file",
        "delete": "delete_file",

        # Terminal execution
        "build": "run_terminal",
        "run": "run_terminal",
        "execute": "run_terminal",
        "compile": "run_terminal",
        "test": "run_terminal",
        "pytest": "run_terminal",
        "lint": "run_terminal",
        "black": "run_terminal",
        "flake8": "run_terminal",

        "python": "run_terminal",
        "node": "run_terminal",
        "terminal": "run_terminal",
        "command": "run_terminal",

        # HTTP operations
        "http get": "http_get",
        "http post": "http_post",
        "get": "http_get",
        "post": "http_post",
        "put": "http_put",
        "patch": "http_patch",
        "http": "http_get",
        "request": "http_request",

        # Git (single word should come after multi-word)
        "git": "git_status",

        # Install (single word should come after multi-word)
        "install": "run_terminal",
        "pip": "run_terminal",
        "npm": "run_terminal",
    }
    # Severities surfaced in the LLM tool-selection prompt (Priority 4).
    _EXEC_LESSON_SEVERITY_WHITELIST = ("critical", "important", "recommended")
    _EXEC_SEVERITY_RANK = {"critical": 0, "important": 1, "recommended": 2}
    _EXEC_LESSON_LIMIT = 2

    def __init__(self, llm, tools, engineering_lessons=None):
        self.llm = llm
        self.tools = tools
        self.engineering_lessons = engineering_lessons

        # Initialize scheduler and resource allocator
        self._scheduler = None
        self._allocator = ResourceAllocator()
        self._initialize_default_resources()

    def _initialize_default_resources(self) -> None:
        """Initialize default machine and tool resources for task execution."""
        # Default machine resource
        machine_resource = Resource(
            id="resource_machine_default",
            name="Default Machine",
            resource_type=ResourceType.MACHINE,
            capacity=1.0,
            available=1.0,
            unit="machine",
            description="Default execution machine",
        )
        self._allocator.add_resource(machine_resource)

        # Default tool resources (common development tools)
        tool_resource = Resource(
            id="resource_tools_default",
            name="Development Tools",
            resource_type=ResourceType.TOOL,
            capacity=1.0,
            available=1.0,
            unit="toolset",
            description="Standard development toolset (git, build tools, test runners, etc.)",
        )
        self._allocator.add_resource(tool_resource)

        # GPU resource (if available)
        gpu_resource = Resource(
            id="resource_gpu_default",
            name="GPU Resource",
            resource_type=ResourceType.GPU,
            capacity=1.0,
            available=1.0,
            unit="gpu",
            description="GPU acceleration resource",
        )
        self._allocator.add_resource(gpu_resource)

    def _map_step_to_tool(self, step: str) -> dict[str, Any] | None:
        """
        Direct mapping from planning step to tool based on keywords.
        This provides immediate, deterministic tool selection for common patterns.
        """
        step_lower = step.lower()

        # Check for direct matches first (sorted by specificity - longest keywords first)
        for keyword, tool in self.TOOL_MAPPING.items():
            if keyword in step_lower:
                # Extract arguments based on tool type
                args = {}
                if tool == "read_file":
                    for word in step.split():
                        if any(word.endswith(ext) for ext in _READ_PATH_EXTENSIONS):
                            args["path"] = word
                            break
                    if "path" not in args:
                        for name in _COMMON_FILE_NAMES:
                            if name in step_lower:
                                args["path"] = name
                                break
                elif tool in ("write_file", "create_file", "replace_in_file"):
                    # Write/create/replace all share the same source-format extension set.
                    for word in step.split():
                        if any(word.endswith(ext) for ext in _WRITE_PATH_EXTENSIONS):
                            args["path"] = word
                            break

                # Log a concise per-step tool selection
                logger.info("[Tool Selector]")
                logger.info(tool)

                return {"tool": tool, "args": args}

        return None

    def _select_tool_with_llm(self, step: str) -> dict[str, Any] | None:
        """
        Use LLM to select tool when direct mapping doesn't work.
        Enhanced with better prompt engineering for tool selection.
        """
        # Build tool selection context
        available_tools = {
            "read_file": "Read the content of a file (requires path argument)",
            "write_file": "Create or overwrite a file (requires path and content arguments)",
            "replace_in_file": "Replace text in a file (requires path, old_text, new_text arguments)",
            "list_files": "List all files in a directory (requires path argument, defaults to current)",
            "run_terminal": "Execute a shell command (requires command argument)",
            "create_file": "Create a new file (requires path and content arguments)",
            "delete_file": "Delete a file (requires path argument)",
            "format_file": "Format a file using available formatters",
            "git_status": "Check git repository status",
            "git_diff": "Show git differences",
            "git_log": "Show git commit history",
            "git_add": "Stage files for git commit",
            "git_commit": "Commit staged files to git",
            "git_push": "Push commits to remote repository",
            "git_pull": "Pull changes from remote repository",
            "git_checkout": "Checkout git branch",
            "git_branch_list": "List git branches",
            "http_get": "Make HTTP GET request",
            "http_post": "Make HTTP POST request",
            "http_put": "Make HTTP PUT request", 
            "http_delete": "Make HTTP DELETE request",
            "http_patch": "Make HTTP PATCH request",
            "http_request": "Make generic HTTP request",
        }
        
        # Tool selection guidelines
        selection_guidelines = """
Pick the single tool that directly does the step; prefer the least powerful tool that can.

Preference order (least powerful first):
1. Read: list_files, read_file
2. Files: create_file, write_file, replace_in_file, delete_file, format_file
3. Git: git_* tools
4. HTTP: http_* tools
5. run_terminal — last resort, only when no other tool can do it
   (build, test, install/upgrade, package manager, run a script).
"""

        prompt = f"""Pick the single tool that fits this step: {step}

{self._build_pre_execute_lessons_block(step)}{selection_guidelines}
Available tools:
{chr(10).join([f'- {tool}: {desc}' for tool, desc in available_tools.items()])}

Return ONLY this JSON, no markdown, no extra text:
{{
  "tool": "<one tool from the list>",
  "args": {{ "<arg>": "<value>" }},
  "reasoning": "<short reason>"
}}"""

        answer = self.llm.ask(prompt)  
        answer = re.sub(r"```json|```", "", answer).strip()
        
        try:
            result = json.loads(answer)
            tool_name = result.get("tool")
            args = result.get("args", {})
            reasoning = (result.get("reasoning") or "").strip()

            # Log a concise per-step tool selection (LLM fallback)
            logger.info("[Tool Selector]")
            logger.info(str(tool_name))

            # Surface the LLM's reasoning as a second concise block; omit it
            # entirely when the field is missing or empty so behaviour is
            # identical to the direct-mapping path.
            if reasoning:
                logger.info("[Tool Selector]")
                logger.info(f"Reason: {reasoning}")

            return {"tool": tool_name, "args": args}
        except Exception as e:
            logger.error(f"[Tool Selector] Error parsing tool selection: {e}")
            return None

    def decide_action(self, step: str) -> dict[str, Any] | None:
        """
        Choose the most appropriate tool for a planning step.
        Uses direct mapping first, then falls back to LLM-based selection with improved prompt engineering.
        """
        # Try direct mapping first
        action = self._map_step_to_tool(step)
        if action:
            return action
            
        # Fall back to LLM-based selection with enhanced prompt
        action = self._select_tool_with_llm(step)
        return action

    # ------------------------------------------------------------------
    # Priority 4 helpers (Self-Learning read-side).
    # ------------------------------------------------------------------

    def _build_pre_execute_lessons_block(self, step: str) -> str:
        """Render up to two PATTERN lessons matching the step.

        Reuses ``EngineeringLessonStorage.get_patterns`` unchanged; mirrors
        the filtering used in ``Planner._build_lessons_context`` so the
        Planner and Executor surface a consistent severity ranking.
        """
        if self.engineering_lessons is None or not step:
            return ""
        try:
            patterns = self.engineering_lessons.get_patterns(limit=10)
        except Exception:
            return ""
        eligible = [
            p for p in patterns
            if p.severity in self._EXEC_LESSON_SEVERITY_WHITELIST
        ]
        if not eligible:
            return ""
        eligible.sort(
            key=lambda p: self._EXEC_SEVERITY_RANK.get(p.severity, 99)
        )
        selected = eligible[: self._EXEC_LESSON_LIMIT]
        lines = ["Past Lessons (Engineering):"]
        for lesson in selected:
            description = (lesson.description or "")[:120]
            lines.append(
                f"- [{lesson.severity}] {lesson.title}: {description}"
            )
        return "\n".join(lines) + "\n\n"

    def _log_anti_pattern_hints(self, step: str) -> None:
        """Log up to two ANTI_PATTERN lessons after a tool execution failure.

        Best-effort: never raises, never alters the result shape.
        """
        if self.engineering_lessons is None:
            return
        try:
            lessons = self.engineering_lessons.get_anti_patterns(limit=2)
        except Exception:
            return
        if not lessons:
            return
        logger.info("[Executor]")
        logger.info("Past Anti-Patterns after failed tool step:")
        for lesson in lessons:
            description = (lesson.description or "")[:120]
            logger.info(f"- {lesson.title}: {description}")

    def execute_step(
        self, step: str, allowed_tools: set[str] | None = None,
    ) -> dict[str, Any]:
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
        if not result.success:
            self._log_anti_pattern_hints(step)
        return {
            "action": action,
            "result": result.output if result.success else result.error
        }

    def execute_plan(
        self, plan: Union[Plan, dict[str, Any]], allowed_tools: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        logger.info("[Executor]")
        logger.info("Started")

        # Extract tasks from Plan object or dict (backward compatibility)
        if isinstance(plan, Plan):
            # Build and validate TaskGraph before execution
            if plan._graph is not None:
                try:
                    # Get topological order from graph (respects dependencies)
                    topo_order = plan._graph.topological_sort()
                    tasks = [plan._graph.get_task(tid) for tid in topo_order if plan._graph.get_task(tid)]
                except CycleDetectedError as e:
                    logger.error(f"[Executor] Cycle detected in plan: {e}")
                    raise ValueError(f"Plan contains cyclic dependencies: {e}") from e
            else:
                # Fallback: use plan tasks in order
                tasks = plan.tasks[:8]
        else:
            # Backward compatibility: convert dict steps to simple tasks
            tasks = []
            for i, step in enumerate(plan.get("steps", [])[:8]):
                task = Task(
                    id=f"task_{uuid.uuid4().hex[:8]}",
                    title=step,
                    priority=TaskPriority.MEDIUM,
                    category=TaskCategory.IMPLEMENTATION,
                    estimated_hours=1.0,
                )
                tasks.append(task)

        if not tasks:
            logger.info("[Executor]")
            logger.info("Finished")
            return []

        # Initialize scheduler with the task graph and plan's scheduling strategy
        if isinstance(plan, Plan) and plan._graph is not None:
            graph = plan._graph
            strategy = plan.config.scheduling_strategy if plan.config else SchedulingStrategy.ASAP
        else:
            # Create a temporary graph for dict-based plans
            graph = plan._graph if isinstance(plan, Plan) else None
            if graph is None:
                from app.planner.task_graph import TaskGraph
                graph = TaskGraph()
                for i, task in enumerate(tasks):
                    graph.add_task(task)
                    if i > 0:
                        # Add sequential dependency for backward compatibility
                        graph.add_dependency(tasks[i-1].id, task.id)
            strategy = plan.config.scheduling_strategy if isinstance(plan, Plan) and plan.config else SchedulingStrategy.ASAP

        self._scheduler = Scheduler(graph, strategy)

        # Allocate resources for each task
        self._allocate_resources_for_tasks(tasks)

        # Generate schedule
        schedule = self._scheduler.schedule()

        # Execute tasks in scheduled order
        results = []
        for schedule_item in schedule.items:
            task = graph.get_task(schedule_item.task_id)
            if not task:
                continue

            # Check if resources are available
            if not self._check_resources_for_task(task):
                logger.warning(f"[Executor] Resources not available for task {task.id}, skipping")
                results.append({
                    "step": task.title,
                    "result": {"action": {}, "error": "Insufficient resources"}
                })
                continue

            # Allocate resources
            self._allocate_for_task(task)

            # Mark task as READY (dependencies satisfied, ready to start)
            if isinstance(plan, Plan) and hasattr(plan, '_tracker') and plan._tracker:
                task.mark_ready()
                plan._tracker.on_task_status_changed(task, transition="PENDING → READY")

            # Mark task as IN_PROGRESS
            if isinstance(plan, Plan) and hasattr(plan, '_tracker') and plan._tracker:
                task.mark_in_progress()
                plan._tracker.on_task_status_changed(task, transition="READY → IN_PROGRESS")

            # Execute the task step
            try:
                result = self.execute_step(task.title, allowed_tools)
                results.append({
                    "step": task.title,
                    "result": result,
                    "task_id": task.id,
                    "scheduled_start": schedule_item.start_time,
                    "scheduled_end": schedule_item.end_time,
                })

                # Mark task as COMPLETED on success
                if isinstance(plan, Plan) and hasattr(plan, '_tracker') and plan._tracker:
                    task.mark_completed()
                    plan._tracker.on_task_status_changed(task, transition="IN_PROGRESS → COMPLETED")

                # Release resources after execution
                self._release_for_task(task)
            except Exception as e:
                logger.error(f"[Executor] Error executing task {task.id}: {e}")
                results.append({
                    "step": task.title,
                    "result": {"action": {}, "error": str(e)},
                    "task_id": task.id,
                })

                # Mark task as FAILED on exception
                if isinstance(plan, Plan) and hasattr(plan, '_tracker') and plan._tracker:
                    task.mark_failed(str(e))
                    plan._tracker.on_task_status_changed(task, transition="IN_PROGRESS → FAILED")

                self._release_for_task(task)

        logger.info("[Executor]")
        logger.info("Finished")
        return results

    def execute_plan_partial(
        self, plan: Union[Plan, dict[str, Any]], allowed_tools: set[str] | None = None,
        start_from_task_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Execute only the incomplete tasks from a plan (for adaptive replanning).

        Args:
            plan: The Plan object or dict to execute
            allowed_tools: Set of allowed tool names
            start_from_task_id: If provided, only execute tasks from this task_id onwards
                               (including its dependents). Tasks before this remain as-is.

        Returns:
            List of execution results for the executed tasks
        """
        logger.info("[Executor]")
        logger.info("Started (partial execution)")

        # Extract tasks from Plan object or dict (backward compatibility)
        if isinstance(plan, Plan):
            # Build and validate TaskGraph before execution
            if plan._graph is not None:
                try:
                    # Get topological order from graph (respects dependencies)
                    topo_order = plan._graph.topological_sort()
                    all_tasks = [plan._graph.get_task(tid) for tid in topo_order if plan._graph.get_task(tid)]
                except CycleDetectedError as e:
                    logger.error(f"[Executor] Cycle detected in plan: {e}")
                    raise ValueError(f"Plan contains cyclic dependencies: {e}") from e
            else:
                # Fallback: use plan tasks in order
                all_tasks = plan.tasks[:8]
        else:
            # Backward compatibility: convert dict steps to simple tasks
            all_tasks = []
            for i, step in enumerate(plan.get("steps", [])[:8]):
                task = Task(
                    id=f"task_{uuid.uuid4().hex[:8]}",
                    title=step,
                    priority=TaskPriority.MEDIUM,
                    category=TaskCategory.IMPLEMENTATION,
                    estimated_hours=1.0,
                )
                all_tasks.append(task)

        if not all_tasks:
            logger.info("[Executor]")
            logger.info("Finished")
            return []

        # Filter to only execute incomplete tasks
        if start_from_task_id:
            # Find the start task and all its transitive dependents
            if isinstance(plan, Plan) and plan._graph:
                graph = plan._graph
                # Get all dependents of the start task
                dependent_ids = graph.get_all_dependents(start_from_task_id)
                # Include the start task itself
                task_ids_to_run = {start_from_task_id} | dependent_ids
                # Also include any tasks that are not completed and not blocked by completed tasks
                tasks = [t for t in all_tasks if t.id in task_ids_to_run and t.status != TaskStatus.COMPLETED]
            else:
                # Fallback: run all incomplete tasks
                tasks = [t for t in all_tasks if t.status != TaskStatus.COMPLETED]
        else:
            # Default: run all incomplete tasks
            tasks = [t for t in all_tasks if t.status != TaskStatus.COMPLETED]

        if not tasks:
            logger.info("[Executor] No incomplete tasks to execute")
            logger.info("[Executor]")
            logger.info("Finished")
            return []

        # Initialize scheduler with the task graph and plan's scheduling strategy
        if isinstance(plan, Plan) and plan._graph is not None:
            graph = plan._graph
            strategy = plan.config.scheduling_strategy if plan.config else SchedulingStrategy.ASAP
        else:
            # Create a temporary graph for dict-based plans
            graph = plan._graph if isinstance(plan, Plan) else None
            if graph is None:
                from app.planner.task_graph import TaskGraph
                graph = TaskGraph()
                for i, task in enumerate(tasks):
                    graph.add_task(task)
                    if i > 0:
                        # Add sequential dependency for backward compatibility
                        graph.add_dependency(tasks[i-1].id, task.id)
            strategy = plan.config.scheduling_strategy if isinstance(plan, Plan) and plan.config else SchedulingStrategy.ASAP

        self._scheduler = Scheduler(graph, strategy)

        # Allocate resources for each task
        self._allocate_resources_for_tasks(tasks)

        # Generate schedule
        schedule = self._scheduler.schedule()

        # Execute tasks in scheduled order
        results = []
        for schedule_item in schedule.items:
            task = graph.get_task(schedule_item.task_id)
            if not task:
                continue

            # Skip completed tasks
            if task.status == TaskStatus.COMPLETED:
                continue

            # Check if resources are available
            if not self._check_resources_for_task(task):
                logger.warning(f"[Executor] Resources not available for task {task.id}, skipping")
                results.append({
                    "step": task.title,
                    "result": {"action": {}, "error": "Insufficient resources"}
                })
                continue

            # Allocate resources
            self._allocate_for_task(task)

            # Mark task as READY (dependencies satisfied, ready to start)
            if isinstance(plan, Plan) and hasattr(plan, '_tracker') and plan._tracker:
                task.mark_ready()
                plan._tracker.on_task_status_changed(task, transition="PENDING → READY")

            # Mark task as IN_PROGRESS
            if isinstance(plan, Plan) and hasattr(plan, '_tracker') and plan._tracker:
                task.mark_in_progress()
                plan._tracker.on_task_status_changed(task, transition="READY → IN_PROGRESS")

            # Execute the task step
            try:
                result = self.execute_step(task.title, allowed_tools)
                results.append({
                    "step": task.title,
                    "result": result,
                    "task_id": task.id,
                    "scheduled_start": schedule_item.start_time,
                    "scheduled_end": schedule_item.end_time,
                })

                # Mark task as COMPLETED on success
                if isinstance(plan, Plan) and hasattr(plan, '_tracker') and plan._tracker:
                    task.mark_completed()
                    plan._tracker.on_task_status_changed(task, transition="IN_PROGRESS → COMPLETED")

                # Release resources after execution
                self._release_for_task(task)
            except Exception as e:
                logger.error(f"[Executor] Error executing task {task.id}: {e}")
                results.append({
                    "step": task.title,
                    "result": {"action": {}, "error": str(e)},
                    "task_id": task.id,
                })

                # Mark task as FAILED on exception
                if isinstance(plan, Plan) and hasattr(plan, '_tracker') and plan._tracker:
                    task.mark_failed(str(e))
                    plan._tracker.on_task_status_changed(task, transition="IN_PROGRESS → FAILED")

                self._release_for_task(task)

        logger.info("[Executor]")
        logger.info("Finished")
        return results

    def _allocate_resources_for_tasks(self, tasks: list) -> None:
        """Pre-allocate required resources for all tasks."""
        for task in tasks:
            # Check task's required_resources field
            required = getattr(task, 'required_resources', [])
            for resource_id in required:
                if not self._allocator.is_available(resource_id):
                    logger.warning(f"[Executor] Resource {resource_id} not available for task {task.id}")

    def _check_resources_for_task(self, task: Task) -> bool:
        """Check if all required resources are available for a task."""
        required = getattr(task, 'required_resources', [])
        # Default: require machine and tool resources
        default_resources = ["resource_machine_default", "resource_tools_default"]
        all_required = list(set(required + default_resources))
        return all(self._allocator.is_available(rid) for rid in all_required)

    def _allocate_for_task(self, task: Task) -> list:
        """Allocate resources for a task."""
        required = getattr(task, 'required_resources', [])
        default_resources = ["resource_machine_default", "resource_tools_default"]
        all_required = list(set(required + default_resources))
        allocations = []
        for resource_id in all_required:
            allocation = self._allocator.allocate(task.id, resource_id, 1.0)
            if allocation:
                allocations.append(allocation)
        return allocations

    def _release_for_task(self, task: Task) -> None:
        """Release all resources allocated to a task."""
        self._allocator.release_for_task(task.id)