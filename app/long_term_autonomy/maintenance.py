"""Autonomous Project Maintenance for Long-Term Autonomy.

This module implements periodic maintenance tasks like dependency updates,
code quality checks, technical debt monitoring, and automated fixes.
"""

import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4
from pathlib import Path


class MaintenanceTaskType(Enum):
    """Types of maintenance tasks."""
    DEPENDENCY_UPDATE = "dependency_update"
    CODE_FORMATTING = "code_formatting"
    LINTING = "linting"
    TEST_RUN = "test_run"
    SECURITY_SCAN = "security_scan"
    DOCUMENTATION_UPDATE = "documentation_update"
    TECHNICAL_DEBT_REVIEW = "technical_debt_review"
    BUILD_VERIFICATION = "build_verification"
    DATABASE_OPTIMIZATION = "database_optimization"
    LOG_CLEANUP = "log_cleanup"
    CACHE_CLEANUP = "cache_cleanup"
    BACKUP = "backup"


class MaintenanceStatus(Enum):
    """Status of a maintenance task."""
    PENDING = "pending"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class MaintenanceTask:
    """Represents a maintenance task."""
    id: str = field(default_factory=lambda: f"maint_{uuid4().hex[:8]}")
    type: MaintenanceTaskType = MaintenanceTaskType.DEPENDENCY_UPDATE
    name: str = ""
    description: str = ""
    schedule: str = ""  # cron-like or interval
    interval_seconds: float = 86400.0  # Default: daily
    last_run: Optional[str] = None
    next_run: Optional[str] = None
    status: MaintenanceStatus = MaintenanceStatus.PENDING
    enabled: bool = True
    priority: int = 2  # 1=low, 2=medium, 3=high, 4=critical
    timeout_seconds: float = 300.0
    command: str = ""  # Shell command or function reference
    args: Dict[str, Any] = field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    run_count: int = 0
    consecutive_failures: int = 0


@dataclass
class MaintenanceConfig:
    """Configuration for the maintenance system."""
    # General settings
    enabled: bool = True
    check_interval: float = 300.0  # 5 minutes

    # Default schedules
    dependency_update_interval: float = 86400.0  # Daily
    code_formatting_interval: float = 86400.0  # Daily
    linting_interval: float = 3600.0  # Hourly
    test_run_interval: float = 1800.0  # Every 30 minutes
    security_scan_interval: float = 86400.0  # Daily
    documentation_update_interval: float = 604800.0  # Weekly
    technical_debt_review_interval: float = 259200.0  # 3 days
    build_verification_interval: float = 3600.0  # Hourly
    database_optimization_interval: float = 604800.0  # Weekly
    log_cleanup_interval: float = 86400.0  # Daily
    cache_cleanup_interval: float = 3600.0  # Hourly
    backup_interval: float = 86400.0  # Daily

    # Resource limits
    max_concurrent_tasks: int = 3
    task_timeout: float = 300.0  # 5 minutes

    # Retry settings
    max_retries: int = 3
    retry_backoff_factor: float = 2.0


class MaintenanceRunner:
    """
    Executes maintenance tasks.

    This class handles the actual execution of maintenance commands,
    including shell commands, Python functions, and integration with
    existing Freya systems.
    """

    def __init__(self, workspace: str = ".", config: MaintenanceConfig = None):
        self.workspace = Path(workspace).resolve()
        self.config = config or MaintenanceConfig()
        self._lock = threading.RLock()

    def execute_task(self, task: MaintenanceTask) -> Dict[str, Any]:
        """
        Execute a maintenance task.

        Args:
            task: The maintenance task to execute

        Returns:
            Dictionary with execution results
        """
        result = {
            "task_id": task.id,
            "task_type": task.type.value,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "success": False,
            "output": "",
            "error": None,
            "duration_seconds": 0
        }

        start_time = time.time()

        try:
            if task.command:
                result = self._execute_shell_command(task, result)
            else:
                # Built-in task handlers
                result = self._execute_builtin_task(task, result)

            result["success"] = result.get("error") is None
        except Exception as e:
            result["error"] = str(e)
            result["success"] = False
        finally:
            result["duration_seconds"] = time.time() - start_time
            result["completed_at"] = datetime.now(timezone.utc).isoformat()

        return result

    def _execute_shell_command(self, task: MaintenanceTask, result: Dict) -> Dict:
        """Execute a shell command."""
        import subprocess

        try:
            # Prepare command
            cmd = task.command
            if isinstance(cmd, list):
                command = cmd
            else:
                # Split command string safely
                import shlex
                command = shlex.split(cmd)

            # Execute
            proc = subprocess.run(
                command,
                cwd=self.workspace,
                capture_output=True,
                text=True,
                timeout=task.timeout_seconds
            )

            result["output"] = proc.stdout
            if proc.stderr:
                result["error"] = proc.stderr
            if proc.returncode != 0:
                result["error"] = result["error"] or f"Command exited with code {proc.returncode}"
                result["success"] = False

        except subprocess.TimeoutExpired:
            result["error"] = f"Task timed out after {task.timeout_seconds}s"
            result["success"] = False
        except Exception as e:
            result["error"] = str(e)
            result["success"] = False

        return result

    def _execute_builtin_task(self, task: MaintenanceTask, result: Dict) -> Dict:
        """Execute a built-in maintenance task."""
        task_type = task.type

        if task_type == MaintenanceTaskType.DEPENDENCY_UPDATE:
            return self._update_dependencies(task, result)
        elif task_type == MaintenanceTaskType.CODE_FORMATTING:
            return self._format_code(task, result)
        elif task_type == MaintenanceTaskType.LINTING:
            return self._run_linting(task, result)
        elif task_type == MaintenanceTaskType.TEST_RUN:
            return self._run_tests(task, result)
        elif task_type == MaintenanceTaskType.SECURITY_SCAN:
            return self._security_scan(task, result)
        elif task_type == MaintenanceTaskType.DOCUMENTATION_UPDATE:
            return self._update_documentation(task, result)
        elif task_type == MaintenanceTaskType.TECHNICAL_DEBT_REVIEW:
            return self._review_technical_debt(task, result)
        elif task_type == MaintenanceTaskType.BUILD_VERIFICATION:
            return self._verify_build(task, result)
        elif task_type == MaintenanceTaskType.LOG_CLEANUP:
            return self._cleanup_logs(task, result)
        elif task_type == MaintenanceTaskType.CACHE_CLEANUP:
            return self._cleanup_cache(task, result)
        else:
            result["error"] = f"Unknown maintenance task type: {task_type.value}"
            return result

    def _update_dependencies(self, task: MaintenanceTask, result: Dict) -> Dict:
        """Update project dependencies."""
        # Detect project type and run appropriate commands
        if (self.workspace / "requirements.txt").exists() or (self.workspace / "pyproject.toml").exists():
            # Python project
            result["output"] = "Python project - dependency update would run pip install -U"
        elif (self.workspace / "package.json").exists():
            # Node.js project
            result["output"] = "Node.js project - dependency update would run npm update"
        else:
            result["output"] = "No recognized project type for dependency update"
        return result

    def _format_code(self, task: MaintenanceTask, result: Dict) -> Dict:
        """Format code files."""
        # Check for formatters
        if (self.workspace / ".prettierrc").exists() or (self.workspace / "prettier.config.js").exists():
            result["output"] = "Prettier config found - would run prettier --write"
        elif (self.workspace / "pyproject.toml").exists():
            import subprocess
            try:
                proc = subprocess.run(
                    ["black", "--check", "."],
                    cwd=self.workspace,
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                if proc.returncode != 0:
                    result["output"] = "Black would format files"
                else:
                    result["output"] = "Code already formatted"
            except FileNotFoundError:
                result["output"] = "Black not available"
        else:
            result["output"] = "No formatter configured"
        return result

    def _run_linting(self, task: MaintenanceTask, result: Dict) -> Dict:
        """Run linting checks."""
        # Check for linters
        if (self.workspace / ".eslintrc").exists() or (self.workspace / "eslint.config.js").exists():
            result["output"] = "ESLint config found - would run eslint"
        elif (self.workspace / "pyproject.toml").exists():
            import subprocess
            try:
                proc = subprocess.run(
                    ["flake8", "."],
                    cwd=self.workspace,
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                result["output"] = f"Flake8 found {proc.stdout.count(chr(10))} issues" if proc.stdout else "No issues"
            except FileNotFoundError:
                result["output"] = "Flake8 not available"
        else:
            result["output"] = "No linter configured"
        return result

    def _run_tests(self, task: MaintenanceTask, result: Dict) -> Dict:
        """Run test suite."""
        import subprocess

        # Try multiple test runners
        test_commands = [
            ["pytest", "--tb=short"],
            ["npm", "test"],
            ["python", "-m", "pytest", "--tb=short"]
        ]

        for cmd in test_commands:
            try:
                proc = subprocess.run(
                    cmd,
                    cwd=self.workspace,
                    capture_output=True,
                    text=True,
                    timeout=task.timeout_seconds
                )
                result["output"] = proc.stdout
                if proc.stderr:
                    result["error"] = proc.stderr
                result["success"] = proc.returncode == 0
                return result
            except FileNotFoundError:
                continue

        result["error"] = "No test runner found"
        result["success"] = False
        return result

    def _security_scan(self, task: MaintenanceTask, result: Dict) -> Dict:
        """Run security scan."""
        import subprocess

        # Try different security scanners
        if (self.workspace / "requirements.txt").exists():
            try:
                proc = subprocess.run(
                    ["pip-audit", "--desc"],
                    cwd=self.workspace,
                    capture_output=True,
                    text=True,
                    timeout=task.timeout_seconds
                )
                result["output"] = proc.stdout
                result["error"] = proc.stderr if proc.stderr else None
                return result
            except FileNotFoundError:
                pass

        result["output"] = "Security scan not configured"
        return result

    def _update_documentation(self, task: MaintenanceTask, result: Dict) -> Dict:
        """Update documentation."""
        result["output"] = "Documentation update would be performed here"
        return result

    def _review_technical_debt(self, task: MaintenanceTask, result: Dict) -> Dict:
        """Review technical debt."""
        result["output"] = "Technical debt review would be performed here"
        return result

    def _verify_build(self, task: MaintenanceTask, result: Dict) -> Dict:
        """Verify build works."""
        import subprocess

        if (self.workspace / "package.json").exists():
            try:
                proc = subprocess.run(
                    ["npm", "run", "build"],
                    cwd=self.workspace,
                    capture_output=True,
                    text=True,
                    timeout=task.timeout_seconds
                )
                result["output"] = proc.stdout
                result["success"] = proc.returncode == 0
                return result
            except FileNotFoundError:
                pass

        result["output"] = "Build verification not configured"
        result["success"] = True  # Not an error if not configured
        return result

    def _cleanup_logs(self, task: MaintenanceTask, result: Dict) -> Dict:
        """Clean up old log files."""
        import glob
        import os

        # Find log files older than 30 days
        log_dirs = [
            self.workspace / "logs",
            self.workspace / "data" / "logs",
            Path.home() / ".freya" / "logs"
        ]

        deleted_count = 0
        for log_dir in log_dirs:
            if log_dir.exists():
                cutoff = time.time() - (30 * 24 * 3600)
                for log_file in log_dir.glob("*.log*"):
                    try:
                        if log_file.stat().st_mtime < cutoff:
                            log_file.unlink()
                            deleted_count += 1
                    except Exception:
                        pass

        result["output"] = f"Cleaned up {deleted_count} old log files"
        return result

    def _cleanup_cache(self, task: MaintenanceTask, result: Dict) -> Dict:
        """Clean up cache directories."""
        cache_dirs = [
            self.workspace / ".pytest_cache",
            self.workspace / "__pycache__",
            self.workspace / "node_modules" / ".cache",
            self.workspace / ".mypy_cache",
            Path.home() / ".cache" / "freya"
        ]

        cleaned = 0
        for cache_dir in cache_dirs:
            if cache_dir.exists():
                try:
                    import shutil
                    shutil.rmtree(cache_dir)
                    cleaned += 1
                except Exception:
                    pass

        result["output"] = f"Cleaned up {cleaned} cache directories"
        return result


class MaintenanceManager:
    """
    Manages autonomous project maintenance.

    This class schedules and executes periodic maintenance tasks
    to keep projects healthy over long periods.
    """

    def __init__(self, workspace: str = ".", config: MaintenanceConfig = None):
        """
        Initialize the maintenance manager.

        Args:
            workspace: Workspace directory
            config: Maintenance configuration
        """
        self.workspace = workspace
        self.config = config or MaintenanceConfig()
        self._lock = threading.RLock()

        # Create default maintenance tasks
        self._tasks: Dict[str, MaintenanceTask] = {}
        self._initialize_default_tasks()

        # Runner
        self._runner = MaintenanceRunner(workspace, config)

        # Scheduler
        self._running = False
        self._scheduler_thread = None
        self._shutdown_event = threading.Event()

        # Active tasks
        self._active_tasks: Dict[str, threading.Thread] = {}

        # Callbacks
        self._task_completion_callback: Optional[Callable] = None

    def _initialize_default_tasks(self) -> None:
        """Initialize default maintenance tasks."""
        default_tasks = [
            MaintenanceTask(
                type=MaintenanceTaskType.DEPENDENCY_UPDATE,
                name="Update Dependencies",
                description="Check and update project dependencies",
                interval_seconds=self.config.dependency_update_interval,
                priority=2
            ),
            MaintenanceTask(
                type=MaintenanceTaskType.CODE_FORMATTING,
                name="Format Code",
                description="Format code according to project style guide",
                interval_seconds=self.config.code_formatting_interval,
                priority=1
            ),
            MaintenanceTask(
                type=MaintenanceTaskType.LINTING,
                name="Run Linting",
                description="Run code linting checks",
                interval_seconds=self.config.linting_interval,
                priority=2
            ),
            MaintenanceTask(
                type=MaintenanceTaskType.TEST_RUN,
                name="Run Tests",
                description="Execute test suite to verify nothing is broken",
                interval_seconds=self.config.test_run_interval,
                priority=3
            ),
            MaintenanceTask(
                type=MaintenanceTaskType.SECURITY_SCAN,
                name="Security Scan",
                description="Scan for security vulnerabilities",
                interval_seconds=self.config.security_scan_interval,
                priority=4
            ),
            MaintenanceTask(
                type=MaintenanceTaskType.DOCUMENTATION_UPDATE,
                name="Update Documentation",
                description="Update documentation based on code changes",
                interval_seconds=self.config.documentation_update_interval,
                priority=1
            ),
            MaintenanceTask(
                type=MaintenanceTaskType.TECHNICAL_DEBT_REVIEW,
                name="Technical Debt Review",
                description="Review and report on technical debt",
                interval_seconds=self.config.technical_debt_review_interval,
                priority=2
            ),
            MaintenanceTask(
                type=MaintenanceTaskType.BUILD_VERIFICATION,
                name="Verify Build",
                description="Verify that the project builds successfully",
                interval_seconds=self.config.build_verification_interval,
                priority=3
            ),
            MaintenanceTask(
                type=MaintenanceTaskType.LOG_CLEANUP,
                name="Cleanup Logs",
                description="Remove old log files",
                interval_seconds=self.config.log_cleanup_interval,
                priority=1
            ),
            MaintenanceTask(
                type=MaintenanceTaskType.CACHE_CLEANUP,
                name="Cleanup Cache",
                description="Remove temporary cache files",
                interval_seconds=self.config.cache_cleanup_interval,
                priority=1
            ),
        ]

        for task in default_tasks:
            task.next_run = datetime.now(timezone.utc).isoformat()
            self._tasks[task.id] = task

    def set_task_completion_callback(self, callback: Callable[[MaintenanceTask, Dict], None]) -> None:
        """Set callback for task completion."""
        self._task_completion_callback = callback

    def start(self) -> None:
        """Start the maintenance scheduler."""
        if self._running:
            return

        self._running = True
        self._shutdown_event.clear()
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop,
            daemon=True,
            name="MaintenanceScheduler"
        )
        self._scheduler_thread.start()

    def stop(self) -> None:
        """Stop the scheduler."""
        if not self._running:
            return

        self._running = False
        self._shutdown_event.set()
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            self._scheduler_thread.join(timeout=5.0)

    def _scheduler_loop(self) -> None:
        """Main scheduler loop."""
        while not self._shutdown_event.is_set():
            try:
                self._check_and_run_tasks()
            except Exception as e:
                print(f"Maintenance scheduler error: {e}")

            # Sleep until next check
            self._shutdown_event.wait(self.config.check_interval)

    def _check_and_run_tasks(self) -> None:
        """Check for tasks that need to run and execute them."""
        now = datetime.now(timezone.utc)

        with self._lock:
            # Find tasks that are due
            due_tasks = []
            for task in self._tasks.values():
                if not task.enabled:
                    continue
                if task.status == MaintenanceStatus.RUNNING:
                    continue
                if task.next_run:
                    next_run = datetime.fromisoformat(task.next_run)
                    if now >= next_run:
                        due_tasks.append(task)

            # Sort by priority (higher first)
            due_tasks.sort(key=lambda t: t.priority, reverse=True)

        # Run due tasks (outside lock)
        for task in due_tasks:
            # Check concurrent task limit
            with self._lock:
                if len(self._active_tasks) >= self.config.max_concurrent_tasks:
                    break

            self._run_task_async(task)

    def _run_task_async(self, task: MaintenanceTask) -> None:
        """Run a maintenance task asynchronously."""
        thread = threading.Thread(
            target=self._run_task,
            args=(task,),
            daemon=True,
            name=f"Maintenance-{task.name}"
        )

        with self._lock:
            task.status = MaintenanceStatus.RUNNING
            self._active_tasks[task.id] = thread

        thread.start()

    def _run_task(self, task: MaintenanceTask) -> None:
        """Run a maintenance task."""
        try:
            result = self._runner.execute_task(task)

            with self._lock:
                task.status = MaintenanceStatus.COMPLETED if result["success"] else MaintenanceStatus.FAILED
                task.result = result
                task.error = result.get("error")
                task.last_run = datetime.now(timezone.utc).isoformat()
                task.run_count += 1

                if result["success"]:
                    task.consecutive_failures = 0
                else:
                    task.consecutive_failures += 1

                # Schedule next run
                next_run = datetime.now(timezone.utc).timestamp() + task.interval_seconds
                task.next_run = datetime.fromtimestamp(next_run, timezone.utc).isoformat()

                # Remove from active tasks
                if task.id in self._active_tasks:
                    del self._active_tasks[task.id]

            # Call completion callback
            if self._task_completion_callback:
                try:
                    self._task_completion_callback(task, result)
                except Exception as e:
                    print(f"Task completion callback error: {e}")

        except Exception as e:
            with self._lock:
                task.status = MaintenanceStatus.FAILED
                task.error = str(e)
                task.consecutive_failures += 1
                if task.id in self._active_tasks:
                    del self._active_tasks[task.id]

    def get_task(self, task_id: str) -> Optional[MaintenanceTask]:
        """Get a maintenance task by ID."""
        with self._lock:
            return self._tasks.get(task_id)

    def get_all_tasks(self) -> List[MaintenanceTask]:
        """Get all maintenance tasks."""
        with self._lock:
            return list(self._tasks.values())

    def get_pending_tasks(self) -> List[MaintenanceTask]:
        """Get tasks that are pending (not running)."""
        with self._lock:
            return [
                t for t in self._tasks.values()
                if t.status == MaintenanceStatus.PENDING
            ]

    def get_running_tasks(self) -> List[MaintenanceTask]:
        """Get currently running tasks."""
        with self._lock:
            return [
                t for t in self._tasks.values()
                if t.status == MaintenanceStatus.RUNNING
            ]

    def enable_task(self, task_id: str) -> bool:
        """Enable a maintenance task."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.enabled = True
                return True
            return False

    def disable_task(self, task_id: str) -> bool:
        """Disable a maintenance task."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.enabled = False
                return True
            return False

    def add_custom_task(self, task: MaintenanceTask) -> str:
        """Add a custom maintenance task."""
        with self._lock:
            task.next_run = datetime.now(timezone.utc).isoformat()
            self._tasks[task.id] = task
            return task.id

    def get_status(self) -> Dict[str, Any]:
        """Get status of the maintenance system."""
        with self._lock:
            return {
                "running": self._running,
                "enabled": self.config.enabled,
                "total_tasks": len(self._tasks),
                "by_status": {
                    status.value: len([t for t in self._tasks.values() if t.status == status])
                    for status in MaintenanceStatus
                },
                "active_tasks": len(self._active_tasks),
                "check_interval": self.config.check_interval,
                "max_concurrent_tasks": self.config.max_concurrent_tasks
            }