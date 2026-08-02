"""Storage layer for Long-Term Autonomy."""

import json
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
from uuid import uuid4

from app.core.logger import logger
from app.long_term_autonomy.models import (
    AutonomyStateData,
    AutonomousTask,
    AutonomyConfig,
)


class AutonomyStorage:
    """Handles persistence of autonomy state and tasks."""

    def __init__(
        self,
        workspace: str = ".",
        state_storage_path: str = "data/memory/autonomy_state.json",
        tasks_storage_path: str = "data/memory/autonomy_tasks.json",
        config_storage_path: str = "data/memory/autonomy_config.json",
    ):
        self.workspace = Path(workspace).resolve()
        self.state_storage_path = self.workspace / state_storage_path
        self.tasks_storage_path = self.workspace / tasks_storage_path
        self.config_storage_path = self.workspace / config_storage_path
        self._lock = threading.RLock()
        self._state: AutonomyStateData = AutonomyStateData()
        self._tasks: Dict[str, AutonomousTask] = {}
        self._config: AutonomyConfig = AutonomyConfig()
        self._load_all()

    def _ensure_storage_dir(self, path: Path) -> None:
        """Ensure the directory for a storage file exists."""
        path.parent.mkdir(parents=True, exist_ok=True)

    def _now(self) -> str:
        """Get current timestamp in ISO format."""
        return datetime.now(timezone.utc).isoformat()

    def _load_json(self, path: Path, default: Any) -> Any:
        """Load JSON data from a file, returning default if file doesn't exist or is invalid."""
        if not path.exists():
            return default
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return default

    def _save_json(self, path: Path, data: Any) -> None:
        """Save data as JSON to a file atomically."""
        self._ensure_storage_dir(path)
        temp_path = path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        temp_path.replace(path)

    def _load_all(self) -> None:
        """Load state, tasks, and configuration from storage."""
        with self._lock:
            # Load state
            state_data = self._load_json(self.state_storage_path, {})
            if state_data:
                # Filter to only include fields defined in AutonomyStateData
                import dataclasses
                valid_fields = {f.name for f in dataclasses.fields(AutonomyStateData)}
                filtered_state_data = {k: v for k, v in state_data.items() if k in valid_fields}
                # Convert string timestamps back to appropriate types if needed
                self._state = AutonomyStateData(**filtered_state_data)
            else:
                self._state = AutonomyStateData()

            # Load tasks
            tasks_data = self._load_json(self.tasks_storage_path, {})
            if tasks_data:
                self._tasks = {
                    tid: AutonomousTask(**tdata) for tid, tdata in tasks_data.items()
                }
            else:
                self._tasks = {}

            # Load config
            config_data = self._load_json(self.config_storage_path, {})
            if config_data:
                self._config = AutonomyConfig(**config_data)
            else:
                self._config = AutonomyConfig()

    def save_state(self) -> None:
        """Save the current autonomy state."""
        with self._lock:
            self._state.updated_at = self._now()
            self._save_json(self.state_storage_path, self._state.__dict__)

    def load_state(self) -> AutonomyStateData:
        """Load the autonomy state."""
        with self._lock:
            return self._state

    def update_state(self, **kwargs) -> None:
        """Update specific fields in the autonomy state."""
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self._state, key):
                    setattr(self._state, key, value)
            self._state.updated_at = self._now()
            self.save_state()

    def save_tasks(self) -> None:
        """Save all autonomous tasks."""
        with self._lock:
            tasks_dict = {
                tid: task.__dict__ for tid, task in self._tasks.items()
            }
            self._save_json(self.tasks_storage_path, tasks_dict)

    def load_tasks(self) -> Dict[str, AutonomousTask]:
        """Load all autonomous tasks."""
        with self._lock:
            return self._tasks.copy()

    def save_task(self, task: AutonomousTask) -> AutonomousTask:
        """Save a single autonomous task."""
        with self._lock:
            self._tasks[task.id] = task
            self.save_tasks()
            return task

    def get_task(self, task_id: str) -> Optional[AutonomousTask]:
        """Get a specific autonomous task by ID."""
        with self._lock:
            return self._tasks.get(task_id)

    def delete_task(self, task_id: str) -> bool:
        """Delete an autonomous task by ID."""
        with self._lock:
            if task_id in self._tasks:
                del self._tasks[task_id]
                self.save_tasks()
                return True
            return False

    def list_tasks(self) -> List[AutonomousTask]:
        """List all autonomous tasks."""
        with self._lock:
            return list(self._tasks.values())

    def save_config(self) -> None:
        """Save the autonomy configuration."""
        with self._lock:
            self._save_json(self.config_storage_path, self._config.__dict__)

    def load_config(self) -> AutonomyConfig:
        """Load the autonomy configuration."""
        with self._lock:
            return self._config

    def update_config(self, **kwargs) -> None:
        """Update specific fields in the autonomy configuration."""
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self._config, key):
                    setattr(self._config, key, value)
            self.save_config()

    def clear_all(self) -> None:
        """Clear all stored state, tasks, and configuration (reset to defaults)."""
        with self._lock:
            self._state = AutonomyStateData()
            self._tasks = {}
            self._config = AutonomyConfig()
            self.save_state()
            self.save_tasks()
            self.save_config()

    def compact(self) -> int:
        """Compact storage by removing completed/failed tasks older than retention period.

        Returns:
            Number of tasks removed
        """
        with self._lock:
            original_count = len(self._tasks)
            # Remove completed/failed tasks older than 30 days
            from datetime import datetime, timedelta
            cutoff = datetime.now(timezone.utc) - timedelta(days=30)

            tasks_to_remove = []
            for tid, task in self._tasks.items():
                if task.status in ('completed', 'failed', 'cancelled'):
                    if task.updated_at:
                        try:
                            updated = datetime.fromisoformat(task.updated_at.replace('Z', '+00:00'))
                            if updated < cutoff:
                                tasks_to_remove.append(tid)
                        except Exception:
                            pass

            for tid in tasks_to_remove:
                del self._tasks[tid]

            if tasks_to_remove:
                self.save_tasks()

            removed_count = len(tasks_to_remove)
            logger.info(f"[AutonomyStorage] Compacted: removed {removed_count} old tasks")
            return removed_count

    def backup(self) -> str:
        """Create a backup of all autonomy data.

        Returns:
            Path to the backup directory
        """
        import shutil
        from datetime import datetime

        backup_dir = self.workspace / "data" / "backups" / f"autonomy_backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        backup_dir.mkdir(parents=True, exist_ok=True)

        # Copy all storage files
        for src_path, name in [
            (self.state_storage_path, "autonomy_state.json"),
            (self.tasks_storage_path, "autonomy_tasks.json"),
            (self.config_storage_path, "autonomy_config.json"),
        ]:
            if src_path.exists():
                shutil.copy2(src_path, backup_dir / name)

        logger.info(f"[AutonomyStorage] Backup created at {backup_dir}")
        return str(backup_dir)