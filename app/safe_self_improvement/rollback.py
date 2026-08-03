"""
Rollback Checkpoints with Automatic Rollback.

Manages rollback checkpoints for safe self-improvement operations.
Provides automatic rollback on verification failure, test failure, or regression.
"""

import logging
import threading
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import json
import uuid
from enum import Enum

from app.safe_self_improvement.models import (
    FileModification,
    ImprovementCandidate,
    RollbackCheckpoint,
    RollbackReason,
    ExecutionResult,
)
from app.core.logger import logger


class RollbackAction(Enum):
    """Types of rollback actions."""

    RESTORE_FILE = "restore_file"
    DELETE_FILE = "delete_file"
    REVERT_RENAME = "revert_rename"
    REVERT_MOVE = "revert_move"
    CUSTOM = "custom"


@dataclass
class RollbackPlan:
    """Plan for rolling back a candidate's modifications."""

    candidate_id: str
    checkpoint_id: str
    actions: List[Dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RollbackManager:
    """
    Manages rollback checkpoints and executes rollbacks.

    Integrates with PatchEngine for transactional rollback capability.
    """

    def __init__(
        self,
        checkpoint_dir: str = "data/checkpoints",
        retention_hours: int = 24,
        max_checkpoints: int = 100,
        auto_cleanup: bool = True,
    ):
        self.checkpoint_dir = Path(checkpoint_dir)
        self.retention_hours = retention_hours
        self.max_checkpoints = max_checkpoints
        self.auto_cleanup = auto_cleanup

        self._lock = threading.RLock()
        self._checkpoints: Dict[str, RollbackCheckpoint] = {}
        self._checkpoint_plans: Dict[str, RollbackPlan] = {}
        self._rollback_history: List[Dict[str, Any]] = []
        self._stats = {
            "checkpoints_created": 0,
            "rollbacks_executed": 0,
            "rollbacks_successful": 0,
            "rollbacks_failed": 0,
            "files_restored": 0,
        }

        # Create checkpoint directory
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        # Load existing checkpoints
        self._load_checkpoints()

    def create_checkpoint(
        self,
        candidate: ImprovementCandidate,
        description: str = "",
    ) -> RollbackCheckpoint:
        """
        Create a rollback checkpoint before applying modifications.

        Captures the current state of all affected files.
        """
        with self._lock:
            file_snapshots = {}

            for mod in candidate.modifications:
                file_path = Path(mod.file_path)

                if file_path.exists():
                    # Read existing content
                    try:
                        content = file_path.read_text(encoding="utf-8")
                        file_snapshots[mod.file_path] = content
                    except Exception as e:
                        logger.warning(f"[RollbackManager] Failed to read {file_path}: {e}")
                        file_snapshots[mod.file_path] = None
                else:
                    # File doesn't exist yet (CREATE operation)
                    file_snapshots[mod.file_path] = None

            checkpoint = RollbackCheckpoint(
                id=f"rb_{uuid.uuid4().hex[:8]}",
                candidate_id=candidate.id,
                file_snapshots=file_snapshots,
                description=description or f"Checkpoint for {candidate.title}",
            )

            # Save checkpoint to disk
            self._save_checkpoint(checkpoint)

            self._checkpoints[checkpoint.id] = checkpoint
            self._stats["checkpoints_created"] += 1

            # Create rollback plan
            self._create_rollback_plan(checkpoint, candidate)

            # Cleanup old checkpoints if needed
            if self.auto_cleanup:
                self._cleanup_old_checkpoints()

            return checkpoint

    def _create_rollback_plan(
        self, checkpoint: RollbackCheckpoint, candidate: ImprovementCandidate
    ) -> RollbackPlan:
        """Create a rollback plan from a checkpoint."""
        actions = []

        for mod in candidate.modifications:
            old_content = checkpoint.file_snapshots.get(mod.file_path)

            if mod.modification_type.value == "create":
                # Rollback create = delete the file
                actions.append({
                    "action": RollbackAction.DELETE_FILE.value,
                    "file_path": mod.file_path,
                })
            elif mod.modification_type.value == "modify":
                # Rollback modify = restore old content
                actions.append({
                    "action": RollbackAction.RESTORE_FILE.value,
                    "file_path": mod.file_path,
                    "content": old_content,
                })
            elif mod.modification_type.value == "delete":
                # Rollback delete = restore old content
                actions.append({
                    "action": RollbackAction.RESTORE_FILE.value,
                    "file_path": mod.file_path,
                    "content": old_content,
                })
            elif mod.modification_type.value == "rename":
                # Rollback rename = rename back
                actions.append({
                    "action": RollbackAction.REVERT_RENAME.value,
                    "file_path": mod.file_path,
                    "original_path": mod.new_content,  # new_content stores the new name
                })
            elif mod.modification_type.value == "move":
                # Rollback move = move back
                actions.append({
                    "action": RollbackAction.REVERT_MOVE.value,
                    "file_path": mod.file_path,
                    "destination": mod.new_content,  # new_content stores destination
                })

        plan = RollbackPlan(
            candidate_id=candidate.id,
            checkpoint_id=checkpoint.id,
            actions=actions,
        )
        self._checkpoint_plans[checkpoint.id] = plan
        return plan

    def rollback(
        self,
        candidate_id: str,
        reason: RollbackReason = RollbackReason.VERIFICATION_FAILED,
        checkpoint_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute rollback for a candidate.

        Args:
            candidate_id: ID of the candidate to rollback
            reason: Reason for rollback
            checkpoint_id: Specific checkpoint to use (latest if not provided)

        Returns:
            Dict with rollback result
        """
        with self._lock:
            # Find checkpoint
            if checkpoint_id:
                checkpoint = self._checkpoints.get(checkpoint_id)
            else:
                # Find latest checkpoint for this candidate
                checkpoint = None
                for cp in reversed(list(self._checkpoints.values())):
                    if cp.candidate_id == candidate_id:
                        checkpoint = cp
                        break

            if not checkpoint:
                return {
                    "success": False,
                    "error": f"No checkpoint found for candidate {candidate_id}",
                    "reason": reason.value,
                }

            plan = self._checkpoint_plans.get(checkpoint.id)
            if not plan:
                return {
                    "success": False,
                    "error": f"No rollback plan for checkpoint {checkpoint.id}",
                    "reason": reason.value,
                }

            # Execute rollback actions
            results = self._execute_rollback_plan(plan)

            # Record rollback
            rollback_record = {
                "id": f"rb_exec_{uuid.uuid4().hex[:8]}",
                "candidate_id": candidate_id,
                "checkpoint_id": checkpoint.id,
                "reason": reason.value,
                "actions_executed": len(plan.actions),
                "actions_succeeded": sum(1 for r in results if r.get("success", False)),
                "actions_failed": sum(1 for r in results if not r.get("success", False)),
                "details": results,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self._rollback_history.append(rollback_record)
            self._stats["rollbacks_executed"] += 1

            if rollback_record["actions_failed"] == 0:
                self._stats["rollbacks_successful"] += 1
                self._stats["files_restored"] += rollback_record["actions_succeeded"]
            else:
                self._stats["rollbacks_failed"] += 1

            # Keep last 1000
            if len(self._rollback_history) > 1000:
                self._rollback_history = self._rollback_history[-1000:]

            return {
                "success": rollback_record["actions_failed"] == 0,
                "checkpoint_id": checkpoint.id,
                "reason": reason.value,
                "actions": results,
            }

    def _execute_rollback_plan(self, plan: RollbackPlan) -> List[Dict[str, Any]]:
        """Execute a rollback plan."""
        results = []

        for action in plan.actions:
            try:
                action_type = action["action"]
                file_path = Path(action["file_path"])

                if action_type == RollbackAction.RESTORE_FILE.value:
                    content = action.get("content")
                    if content is not None:
                        file_path.parent.mkdir(parents=True, exist_ok=True)
                        file_path.write_text(content, encoding="utf-8")
                    else:
                        # File didn't exist before, delete it
                        if file_path.exists():
                            file_path.unlink()
                    results.append({"success": True, "action": action_type, "file": str(file_path)})

                elif action_type == RollbackAction.DELETE_FILE.value:
                    if file_path.exists():
                        file_path.unlink()
                    results.append({"success": True, "action": action_type, "file": str(file_path)})

                elif action_type == RollbackAction.REVERT_RENAME.value:
                    original_path = Path(action["original_path"])
                    if file_path.exists():
                        file_path.rename(original_path)
                    results.append({"success": True, "action": action_type, "file": str(file_path)})

                elif action_type == RollbackAction.REVERT_MOVE.value:
                    destination = Path(action["destination"])
                    if destination.exists():
                        destination.rename(file_path)
                    results.append({"success": True, "action": action_type, "file": str(file_path)})

                else:
                    results.append({"success": False, "action": action_type, "error": "Unknown action type"})

            except Exception as e:
                logger.error(f"[RollbackManager] Rollback action failed: {e}")
                results.append({
                    "success": False,
                    "action": action.get("action", "unknown"),
                    "file": action.get("file_path", "unknown"),
                    "error": str(e),
                })

        return results

    def _save_checkpoint(self, checkpoint: RollbackCheckpoint) -> None:
        """Save checkpoint to disk."""
        try:
            checkpoint_path = self.checkpoint_dir / f"{checkpoint.id}.json"
            with open(checkpoint_path, "w", encoding="utf-8") as f:
                json.dump(checkpoint.to_dict(), f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[RollbackManager] Failed to save checkpoint: {e}")

    def _load_checkpoints(self) -> None:
        """Load checkpoints from disk."""
        try:
            for checkpoint_file in self.checkpoint_dir.glob("*.json"):
                try:
                    with open(checkpoint_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    checkpoint = RollbackCheckpoint(
                        id=data["id"],
                        candidate_id=data["candidate_id"],
                        file_snapshots=data["file_snapshots"],
                        created_at=data["created_at"],
                        description=data["description"],
                    )
                    self._checkpoints[checkpoint.id] = checkpoint
                except Exception as e:
                    logger.warning(f"[RollbackManager] Failed to load {checkpoint_file}: {e}")
        except Exception as e:
            logger.warning(f"[RollbackManager] Failed to load checkpoints: {e}")

    def _cleanup_old_checkpoints(self) -> None:
        """Remove old checkpoints beyond retention."""
        try:
            cutoff = datetime.now(timezone.utc).timestamp() - (self.retention_hours * 3600)
            to_remove = []

            for cp_id, cp in self._checkpoints.items():
                cp_time = datetime.fromisoformat(cp.created_at.replace("Z", "+00:00")).timestamp()
                if cp_time < cutoff:
                    to_remove.append(cp_id)

            for cp_id in to_remove:
                # Delete file
                checkpoint_file = self.checkpoint_dir / f"{cp_id}.json"
                if checkpoint_file.exists():
                    checkpoint_file.unlink()
                # Remove from memory
                del self._checkpoints[cp_id]
                if cp_id in self._checkpoint_plans:
                    del self._checkpoint_plans[cp_id]

            # Also enforce max count
            if len(self._checkpoints) > self.max_checkpoints:
                sorted_cps = sorted(
                    self._checkpoints.values(),
                    key=lambda c: c.created_at
                )
                for cp in sorted_cps[:len(self._checkpoints) - self.max_checkpoints]:
                    checkpoint_file = self.checkpoint_dir / f"{cp.id}.json"
                    if checkpoint_file.exists():
                        checkpoint_file.unlink()
                    del self._checkpoints[cp.id]
                    if cp.id in self._checkpoint_plans:
                        del self._checkpoint_plans[cp.id]

        except Exception as e:
            logger.warning(f"[RollbackManager] Cleanup failed: {e}")

    def get_checkpoint(self, checkpoint_id: str) -> Optional[RollbackCheckpoint]:
        """Get a checkpoint by ID."""
        with self._lock:
            return self._checkpoints.get(checkpoint_id)

    def get_candidate_checkpoints(self, candidate_id: str) -> List[RollbackCheckpoint]:
        """Get all checkpoints for a candidate."""
        with self._lock:
            return [
                cp for cp in self._checkpoints.values()
                if cp.candidate_id == candidate_id
            ]

    def get_latest_checkpoint(self, candidate_id: str) -> Optional[RollbackCheckpoint]:
        """Get the latest checkpoint for a candidate."""
        checkpoints = self.get_candidate_checkpoints(candidate_id)
        if not checkpoints:
            return None
        return max(checkpoints, key=lambda c: c.created_at)

    def delete_checkpoint(self, checkpoint_id: str) -> bool:
        """Delete a checkpoint."""
        with self._lock:
            if checkpoint_id in self._checkpoints:
                checkpoint_file = self.checkpoint_dir / f"{checkpoint_id}.json"
                if checkpoint_file.exists():
                    checkpoint_file.unlink()
                del self._checkpoints[checkpoint_id]
                if checkpoint_id in self._checkpoint_plans:
                    del self._checkpoint_plans[checkpoint_id]
                return True
            return False

    def get_rollback_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get rollback history."""
        with self._lock:
            return self._rollback_history[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        """Get rollback statistics."""
        with self._lock:
            return {
                **self._stats,
                "active_checkpoints": len(self._checkpoints),
                "checkpoint_dir": str(self.checkpoint_dir),
            }

    def clear_checkpoints(self, older_than_hours: Optional[int] = None) -> int:
        """Clear checkpoints, optionally only older than specified hours."""
        with self._lock:
            count = 0
            if older_than_hours is None:
                # Clear all
                for cp_id in list(self._checkpoints.keys()):
                    self.delete_checkpoint(cp_id)
                    count += 1
            else:
                cutoff = datetime.now(timezone.utc).timestamp() - (older_than_hours * 3600)
                to_remove = []
                for cp_id, cp in self._checkpoints.items():
                    cp_time = datetime.fromisoformat(cp.created_at.replace("Z", "+00:00")).timestamp()
                    if cp_time < cutoff:
                        to_remove.append(cp_id)
                for cp_id in to_remove:
                    self.delete_checkpoint(cp_id)
                    count += 1
            return count


def create_rollback_manager(
    checkpoint_dir: str = "data/checkpoints",
    retention_hours: int = 24,
) -> RollbackManager:
    """Create a RollbackManager with sensible defaults."""
    return RollbackManager(
        checkpoint_dir=checkpoint_dir,
        retention_hours=retention_hours,
    )