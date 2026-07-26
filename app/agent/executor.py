import json
import re
import sys
from typing import Any
from app.core.logger import logger
from app.ui.permission_menu import permission_prompt


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
    def __init__(self, llm, tools):
        self.llm = llm
        self.tools = tools

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
                    # Try to extract filename from step
                    file_extensions = [".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".js", ".ts", ".css", ".html"]
                    for word in step.split():
                        if any(word.endswith(ext) for ext in file_extensions):
                            args["path"] = word
                            break
                    if "path" not in args:
                        # Check for common config files
                        common_files = ["requirements.txt", "package.json", "pyproject.toml", "setup.py", "README.md"]
                        for f in common_files:
                            if f in step_lower:
                                args["path"] = f
                                break
                elif tool == "write_file" or tool == "create_file":
                    # Try to extract filename
                    for word in step.split():
                        if word.endswith((".py", ".md", ".txt", ".json", ".yaml", ".yml")):
                            args["path"] = word
                            break
                elif tool == "replace_in_file":
                    # Look for file mention in the step
                    for word in step.split():
                        if word.endswith((".py", ".md", ".txt", ".json", ".yaml", ".yml")):
                            args["path"] = word
                            break

                # Generate descriptive reason based on tool and step
                reason = self._generate_reason(tool, step)

                # Log in the format matching documentation example
                logger.info(f"[Tool Selector]")
                logger.info(f"Planning Step:\n{step}")
                logger.info(f"")
                logger.info(f"Selected Tool:\n{tool}")
                logger.info(f"")
                logger.info(f"Reason:\n{reason}")
                logger.info(f"")
                if args:
                    logger.info(f"Args: {args}")

                return {"tool": tool, "args": args}

        return None

    def _generate_reason(self, tool: str, step: str) -> str:
        """Generate a descriptive reason for the tool selection based on the planning step."""
        step_lower = step.lower()

        # Specific reasons for common patterns
        if tool == "run_terminal":
            if "build" in step_lower:
                return "Project build required."
            elif "test" in step_lower or "pytest" in step_lower:
                return "Test execution required."
            elif "install" in step_lower or "pip" in step_lower or "npm" in step_lower:
                return "Dependency installation required."
            elif "lint" in step_lower or "format" in step_lower:
                return "Code quality check required."
            else:
                return "Terminal command execution required."

        elif tool == "read_file":
            return "Reading file content to analyze or explain."

        elif tool == "write_file" or tool == "create_file":
            return "Creating new file with content."

        elif tool == "replace_in_file":
            if "fix" in step_lower or "debug" in step_lower:
                return "Applying fix to resolve issue."
            elif "refactor" in step_lower:
                return "Refactoring code to improve structure."
            else:
                return "Modifying file content."

        elif tool == "list_files":
            return "Listing files to explore project structure."

        elif tool == "delete_file":
            return "Removing file from project."

        elif tool.startswith("git_"):
            if "status" in step_lower:
                return "Checking repository status."
            elif "diff" in step_lower:
                return "Viewing repository changes."
            elif "log" in step_lower:
                return "Viewing commit history."
            elif "commit" in step_lower:
                return "Committing changes to repository."
            elif "push" in step_lower:
                return "Pushing changes to remote."
            elif "pull" in step_lower:
                return "Pulling changes from remote."
            elif "checkout" in step_lower or "branch" in step_lower:
                return "Switching or managing branches."
            else:
                return "Performing git operation."

        elif tool.startswith("http_"):
            return "Making HTTP request."

        elif tool == "format_file":
            return "Formatting code file."

        return "Executing planning step."

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
TOOL SELECTION GUIDELINES:
1. MATCH TOOL TO STEP: Choose the tool that directly accomplishes the planning step
2. PREFER LEAST POWERFUL: Always choose the simplest tool capable of completing the task
3. AVOID UNNECESSARY TERMINAL: Do not use run_terminal when another tool can perform the action

TOOL SELECTION EXAMPLES:
- Read project configuration -> read_file
- Search for a function -> list_files (then read_file)
- Build the project -> run_terminal (only if no other tool available)
- Run tests -> run_terminal (only if no other tool available)
- Modify a Python file -> replace_in_file
- Create a new file -> create_file or write_file
- List project files -> list_files
- Git operations -> git_* tools

TOOL PREFERENCE ORDER (least powerful to most powerful):
1. Read operations: list_files, read_file
2. File operations: create_file, write_file, delete_file, replace_in_file
3. Git operations: git_* tools
4. HTTP operations: http_* tools  
5. Terminal operations: run_terminal (use LAST RESORT)

ONLY use run_terminal when:
- Building projects
- Running tests
- Executing shell commands
- Using package managers (pip, npm, etc.)
- Executing scripts directly
"""
        
        prompt = f"""You are Freya's tool selector. Choose the SINGLE most appropriate tool for this planning step.

Planning Step: {step}

{selection_guidelines}

AVAILABLE TOOLS:
{chr(10).join([f'- {tool}: {desc}' for tool, desc in available_tools.items()])}

RETURN ONLY JSON. Format:
{{
  "tool": "tool_name",
  "args": {{ "arg1": "value1" }},
  "reasoning": "Why this tool was selected"
}}

REMEMBER:
- Match the tool to the planning step
- Prefer the least powerful tool capable of the task
- Avoid run_terminal when another tool can do the job
- Do NOT return multiple tools - ONLY ONE"""

        answer = self.llm.ask(prompt)  
        answer = re.sub(r"```json|```", "", answer).strip()
        
        try:
            result = json.loads(answer)
            tool_name = result.get("tool")
            args = result.get("args", {})
            reasoning = result.get("reasoning", "")

            # Log in the format matching documentation example
            logger.info(f"[Tool Selector]")
            logger.info(f"Planning Step:\n{step}")
            logger.info(f"")
            logger.info(f"Selected Tool:\n{tool_name}")
            logger.info(f"")
            logger.info(f"Reason:\n{reasoning}")
            logger.info(f"")
            if args:
                logger.info(f"Args: {args}")

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

    def execute_step(
        self, step: str, allowed_tools: set[str] | None = None,
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
        self, plan: dict[str, Any], allowed_tools: set[str] | None = None,
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