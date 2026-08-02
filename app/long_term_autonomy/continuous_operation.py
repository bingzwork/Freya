"""Continuous Operation Support for Long-Term Autonomy.

This module implements persistent runtime management, graceful shutdown,
state checkpointing, and recovery across sessions.
"""

import threading
import time
import atexit
import signal
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import json


class ShutdownReason(Enum):
    """Reasons for system shutdown."""
    USER_REQUESTED = "user_requested"
    SCHEDULED = "scheduled"
    ERROR = "error"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    MAINTENANCE = "maintenance"
    SYSTEM_SIGNAL = "system_signal"  # SIGTERM, SIGINT
    HEALTH_CHECK_FAILED = "health_check_failed"


class CheckpointType(Enum):
    """Types of checkpoints."""
    FULL = "full"           # Complete state snapshot
    INCREMENTAL = "incremental"  # Only changed state
    EMERGENCY = "emergency"  # Before potential crash


@dataclass
class Checkpoint:
    """Represents a state checkpoint."""
    id: str = field(default_factory=lambda: f"cp_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}")
    type: CheckpointType = CheckpointType.INCREMENTAL
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    data: Dict[str, Any] = field(default_factory=dict)
    size_bytes: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ContinuousOperationConfig:
    """Configuration for continuous operation."""
    # State persistence
    checkpoint_interval: float = 300.0  # 5 minutes
    max_checkpoints: int = 50
    checkpoint_on_shutdown: bool = True
    emergency_checkpoint_threshold: float = 0.1  # Disk space threshold (10%)

    # Graceful shutdown
    shutdown_timeout: float = 2.0  # seconds (reduced for faster testing)
    force_kill_timeout: float = 1.0  # seconds after graceful timeout

    # Recovery
    auto_recover: bool = True
    recovery_check_interval: float = 60.0

    # Health monitoring
    health_check_interval: float = 1.0  # seconds (reduced for faster responsiveness)
    max_consecutive_health_failures: int = 3

    # Resource monitoring
    min_disk_space_gb: float = 1.0
    min_memory_mb: float = 512.0

    # Session management
    session_id: str = ""  # Will be generated on first run
    max_session_duration: float = 0.0  # 0 = unlimited


class StatePersister:
    """
    Handles state persistence and recovery.

    This class manages saving and loading the complete system state,
    including all subsystem states, task queues, and configuration.
    """

    def __init__(self, workspace: str = ".", config: ContinuousOperationConfig = None):
        self.workspace = Path(workspace).resolve()
        self.config = config or ContinuousOperationConfig()
        self._lock = threading.RLock()
        self._state_dir = self.workspace / "data" / "long_term_autonomy" / "checkpoints"
        self._state_dir.mkdir(parents=True, exist_ok=True)

    def save_checkpoint(self, checkpoint: Checkpoint) -> bool:
        """Save a checkpoint to disk."""
        with self._lock:
            try:
                filepath = self._state_dir / f"{checkpoint.id}.json"
                checkpoint.size_bytes = len(json.dumps(checkpoint.data, indent=2).encode('utf-8'))
                with open(filepath, 'w') as f:
                    json.dump({
                        'id': checkpoint.id,
                        'type': checkpoint.type.value,
                        'created_at': checkpoint.created_at,
                        'data': checkpoint.data,
                        'size_bytes': checkpoint.size_bytes,
                        'metadata': checkpoint.metadata
                    }, f, indent=2)
                return True
            except Exception as e:
                print(f"Failed to save checkpoint: {e}")
                return False

    def load_checkpoint(self, checkpoint_id: str) -> Optional[Checkpoint]:
        """Load a checkpoint from disk."""
        with self._lock:
            try:
                filepath = self._state_dir / f"{checkpoint_id}.json"
                if not filepath.exists():
                    return None
                with open(filepath, 'r') as f:
                    data = json.load(f)
                return Checkpoint(
                    id=data['id'],
                    type=CheckpointType(data['type']),
                    created_at=data['created_at'],
                    data=data['data'],
                    size_bytes=data['size_bytes'],
                    metadata=data.get('metadata', {})
                )
            except Exception as e:
                print(f"Failed to load checkpoint: {e}")
                return None

    def list_checkpoints(self) -> List[Checkpoint]:
        """List all available checkpoints."""
        with self._lock:
            checkpoints = []
            for filepath in sorted(self._state_dir.glob("*.json")):
                try:
                    with open(filepath, 'r') as f:
                        data = json.load(f)
                    checkpoints.append(Checkpoint(
                        id=data['id'],
                        type=CheckpointType(data['type']),
                        created_at=data['created_at'],
                        data=data['data'],
                        size_bytes=data['size_bytes'],
                        metadata=data.get('metadata', {})
                    ))
                except Exception:
                    pass
            return checkpoints

    def delete_checkpoint(self, checkpoint_id: str) -> bool:
        """Delete a checkpoint."""
        with self._lock:
            filepath = self._state_dir / f"{checkpoint_id}.json"
            if filepath.exists():
                filepath.unlink()
                return True
            return False

    def cleanup_old_checkpoints(self) -> int:
        """Remove old checkpoints beyond max limit."""
        checkpoints = self.list_checkpoints()
        checkpoints.sort(key=lambda c: c.created_at, reverse=True)

        deleted = 0
        for checkpoint in checkpoints[self.config.max_checkpoints:]:
            if self.delete_checkpoint(checkpoint.id):
                deleted += 1
        return deleted

    def create_full_state(self, subsystems: Dict[str, Any]) -> Checkpoint:
        """Create a full state checkpoint from all subsystems."""
        state_data = {}
        for name, subsystem in subsystems.items():
            if hasattr(subsystem, 'get_state_for_checkpoint'):
                state_data[name] = subsystem.get_state_for_checkpoint()
            elif hasattr(subsystem, '__dict__'):
                # Fallback to object's dict - filter for JSON-serializable values
                serializable_dict = {}
                for k, v in subsystem.__dict__.items():
                    if not k.startswith('_') and self._is_json_serializable(v):
                        serializable_dict[k] = self._make_serializable(v)
                state_data[name] = serializable_dict

        return Checkpoint(
            type=CheckpointType.FULL,
            data=state_data,
            metadata={'subsystems': list(state_data.keys())}
        )

    def _is_json_serializable(self, obj: Any) -> bool:
        """Check if an object is JSON serializable."""
        try:
            import json
            json.dumps(obj)
            return True
        except (TypeError, OverflowError):
            return False

    def _make_serializable(self, obj: Any) -> Any:
        """Convert an object to a JSON-serializable form."""
        if obj is None or isinstance(obj, (str, int, float, bool)):
            return obj
        elif isinstance(obj, (list, tuple)):
            return [self._make_serializable(item) for item in obj]
        elif isinstance(obj, dict):
            return {self._make_serializable(k): self._make_serializable(v) for k, v in obj.items()}
        elif hasattr(obj, '__dict__'):
            # For objects with __dict__, serialize their attributes
            result = {}
            for k, v in obj.__dict__.items():
                if not k.startswith('_') and self._is_json_serializable(v):
                    result[k] = self._make_serializable(v)
            return result
        elif hasattr(obj, 'value'):  # Enum
            return obj.value
        elif hasattr(obj, 'isoformat'):  # datetime
            return obj.isoformat()
        elif isinstance(obj, Path):
            return str(obj)
        else:
            # Try to convert to string as last resort
            try:
                return str(obj)
            except Exception:
                return None

    def restore_state(self, checkpoint: Checkpoint, subsystems: Dict[str, Any]) -> bool:
        """Restore state from a checkpoint."""
        try:
            for name, state_data in checkpoint.data.items():
                if name in subsystems:
                    subsystem = subsystems[name]
                    if hasattr(subsystem, 'restore_state_from_checkpoint'):
                        subsystem.restore_state_from_checkpoint(state_data)
            return True
        except Exception as e:
            print(f"Failed to restore state: {e}")
            return False


class ContinuousOperationManager:
    """
    Manages continuous long-term operation of the autonomy system.

    Features:
    - Periodic state checkpointing
    - Graceful shutdown handling
    - Automatic recovery after crashes
    - Session management
    - Health monitoring
    """

    def __init__(
        self,
        workspace: str = ".",
        config: ContinuousOperationConfig = None
    ):
        """
        Initialize the continuous operation manager.

        Args:
            workspace: Workspace directory
            config: Configuration for continuous operation
        """
        self.workspace = Path(workspace).resolve()
        self.config = config or ContinuousOperationConfig()
        self._lock = threading.RLock()

        if not self.config.session_id:
            self.config.session_id = f"session_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

        # State persister
        self._persister = StatePersister(workspace, self.config)

        # Subsystems to manage
        self._subsystems: Dict[str, Any] = {}

        # Lifecycle state
        self._running = False
        self._shutting_down = False
        self._shutdown_reason: Optional[ShutdownReason] = None

        # Threads
        self._checkpoint_thread = None
        self._health_thread = None
        self._recovery_thread = None
        self._shutdown_event = threading.Event()

        # Health tracking
        self._health_failures = 0
        self._last_health_check: Optional[datetime] = None
        self._start_time = datetime.now(timezone.utc)

        # Callbacks
        self._shutdown_callbacks: List[Callable] = []
        self._recovery_callbacks: List[Callable] = []

        # Register signal handlers
        self._register_signal_handlers()

        # Register atexit handler
        atexit.register(self._atexit_handler)

    def _register_signal_handlers(self) -> None:
        """Register signal handlers for graceful shutdown."""
        try:
            signal.signal(signal.SIGTERM, self._signal_handler)
            signal.signal(signal.SIGINT, self._signal_handler)
        except Exception:
            pass  # Not available on all platforms

    def _signal_handler(self, signum, frame) -> None:
        """Handle system signals."""
        reason = ShutdownReason.SYSTEM_SIGNAL
        self.initiate_shutdown(reason)

    def _atexit_handler(self) -> None:
        """Handle process exit."""
        if self._running and not self._shutting_down:
            self.initiate_shutdown(ShutdownReason.USER_REQUESTED)

    def register_subsystem(self, name: str, subsystem: Any) -> None:
        """
        Register a subsystem for state management.

        Args:
            name: Subsystem name
            subsystem: Subsystem instance
        """
        with self._lock:
            self._subsystems[name] = subsystem

    def add_shutdown_callback(self, callback: Callable[[ShutdownReason], None]) -> None:
        """Add a callback for shutdown events."""
        with self._lock:
            self._shutdown_callbacks.append(callback)

    def add_recovery_callback(self, callback: Callable[[], None]) -> None:
        """Add a callback for recovery events."""
        with self._lock:
            self._recovery_callbacks.append(callback)

    def start(self) -> bool:
        """Start continuous operation management."""
        with self._lock:
            if self._running:
                return False

            self._running = True
            self._shutting_down = False
            self._shutdown_event.clear()
            self._health_failures = 0
            self._start_time = datetime.now(timezone.utc)

            # Attempt recovery if enabled
            if self.config.auto_recover:
                self._attempt_recovery()

        # Start background threads
        self._checkpoint_thread = threading.Thread(
            target=self._checkpoint_loop,
            daemon=True,
            name="ContinuousOps-Checkpoint"
        )
        self._checkpoint_thread.start()

        self._health_thread = threading.Thread(
            target=self._health_loop,
            daemon=True,
            name="ContinuousOps-Health"
        )
        self._health_thread.start()

        self._recovery_thread = threading.Thread(
            target=self._recovery_loop,
            daemon=True,
            name="ContinuousOps-Recovery"
        )
        self._recovery_thread.start()

        return True

    def stop(self) -> bool:
        """Stop continuous operation management."""
        with self._lock:
            if not self._running:
                return False

        self.initiate_shutdown(ShutdownReason.USER_REQUESTED)
        return True

    def initiate_shutdown(self, reason: ShutdownReason) -> None:
        """
        Initiate graceful shutdown.

        Args:
            reason: Reason for shutdown
        """
        with self._lock:
            if self._shutting_down:
                return

            self._shutting_down = True
            self._shutdown_reason = reason

        # Call shutdown callbacks
        for callback in self._shutdown_callbacks:
            try:
                callback(reason)
            except Exception as e:
                print(f"Shutdown callback error: {e}")

        # Save final checkpoint if enabled
        if self.config.checkpoint_on_shutdown:
            self._save_emergency_checkpoint()

        # Signal shutdown to background threads
        self._shutdown_event.set()

        # Wait for threads with timeout
        threads = [self._checkpoint_thread, self._health_thread, self._recovery_thread]
        for thread in threads:
            if thread and thread.is_alive():
                thread.join(timeout=self.config.shutdown_timeout)

        # Force kill if needed
        remaining = [t for t in threads if t and t.is_alive()]
        if remaining:
            time.sleep(self.config.force_kill_timeout)

        with self._lock:
            self._running = False

    def _save_emergency_checkpoint(self) -> None:
        """Save an emergency checkpoint before shutdown."""
        try:
            checkpoint = self._persister.create_full_state(self._subsystems)
            checkpoint.type = CheckpointType.EMERGENCY
            checkpoint.metadata['shutdown_reason'] = self._shutdown_reason.value if self._shutdown_reason else 'unknown'
            self._persister.save_checkpoint(checkpoint)
            self._persister.cleanup_old_checkpoints()
        except Exception as e:
            print(f"Emergency checkpoint failed: {e}")

    def _checkpoint_loop(self) -> None:
        """Periodic checkpoint saving loop."""
        while not self._shutdown_event.is_set():
            try:
                self._save_checkpoint(CheckpointType.INCREMENTAL)
            except Exception as e:
                print(f"Checkpoint error: {e}")

            # Sleep until next checkpoint
            self._shutdown_event.wait(self.config.checkpoint_interval)

    def _save_checkpoint(self, checkpoint_type: CheckpointType) -> None:
        """Save a checkpoint of the current state."""
        checkpoint = self._persister.create_full_state(self._subsystems)
        checkpoint.type = checkpoint_type
        if self._persister.save_checkpoint(checkpoint):
            self._persister.cleanup_old_checkpoints()

    def _health_loop(self) -> None:
        """Health monitoring loop."""
        while not self._shutdown_event.is_set():
            try:
                healthy = self._perform_health_check()
                if not healthy:
                    self._health_failures += 1
                    if self._health_failures >= self.config.max_consecutive_health_failures:
                        print("Too many health check failures, initiating shutdown")
                        self.initiate_shutdown(ShutdownReason.HEALTH_CHECK_FAILED)
                        break
                else:
                    self._health_failures = 0

                self._last_health_check = datetime.now(timezone.utc)

            except Exception as e:
                print(f"Health check error: {e}")
                self._health_failures += 1

            # Sleep until next health check
            self._shutdown_event.wait(self.config.health_check_interval)

    def _perform_health_check(self) -> bool:
        """Perform a health check on the system."""
        # Check disk space
        try:
            import shutil
            disk_usage = shutil.disk_usage(self.workspace)
            free_gb = disk_usage.free / (1024**3)
            if free_gb < self.config.min_disk_space_gb:
                print(f"Low disk space: {free_gb:.2f}GB < {self.config.min_disk_space_gb}GB")
                return False
        except Exception:
            pass

        # Check memory
        try:
            import psutil
            memory = psutil.virtual_memory()
            available_mb = memory.available / (1024**2)
            if available_mb < self.config.min_memory_mb:
                print(f"Low memory: {available_mb:.0f}MB < {self.config.min_memory_mb}MB")
                return False
        except Exception:
            pass

        # Check session duration
        if self.config.max_session_duration > 0:
            duration = (datetime.now(timezone.utc) - self._start_time).total_seconds()
            if duration > self.config.max_session_duration:
                print(f"Max session duration reached: {duration}s")
                return False

        # Check subsystems
        for name, subsystem in self._subsystems.items():
            if hasattr(subsystem, 'is_healthy'):
                try:
                    if not subsystem.is_healthy():
                        print(f"Subsystem {name} is unhealthy")
                        return False
                except Exception:
                    pass

        return True

    def _recovery_loop(self) -> None:
        """Recovery check loop."""
        if not self.config.auto_recover:
            return

        while not self._shutdown_event.is_set():
            try:
                # Check if recovery is needed
                # This would be triggered by external events or health checks
                pass
            except Exception as e:
                print(f"Recovery check error: {e}")

            # Sleep
            self._shutdown_event.wait(self.config.recovery_check_interval)

    def _attempt_recovery(self) -> bool:
        """Attempt to recover from the latest checkpoint."""
        checkpoints = self._persister.list_checkpoints()
        if not checkpoints:
            print("No checkpoints found for recovery")
            return False

        # Use the most recent checkpoint
        latest = checkpoints[0]
        print(f"Attempting recovery from checkpoint: {latest.id}")

        success = self._persister.restore_state(latest, self._subsystems)
        if success:
            print("Recovery successful")
            for callback in self._recovery_callbacks:
                try:
                    callback()
                except Exception as e:
                    print(f"Recovery callback error: {e}")
        else:
            print("Recovery failed")

        return success

    def force_checkpoint(self, checkpoint_type: CheckpointType = CheckpointType.FULL) -> bool:
        """Force an immediate checkpoint."""
        try:
            self._save_checkpoint(checkpoint_type)
            return True
        except Exception as e:
            print(f"Force checkpoint failed: {e}")
            return False

    def get_status(self) -> Dict[str, Any]:
        """Get status of continuous operation."""
        with self._lock:
            uptime = (datetime.now(timezone.utc) - self._start_time).total_seconds()
            checkpoints = self._persister.list_checkpoints()

            return {
                "running": self._running,
                "shutting_down": self._shutting_down,
                "shutdown_reason": self._shutdown_reason.value if self._shutdown_reason else None,
                "session_id": self.config.session_id,
                "uptime_seconds": uptime,
                "health_failures": self._health_failures,
                "last_health_check": self._last_health_check.isoformat() if self._last_health_check else None,
                "checkpoints_count": len(checkpoints),
                "latest_checkpoint": checkpoints[0].id if checkpoints else None,
                "subsystems": list(self._subsystems.keys()),
                "config": {
                    "checkpoint_interval": self.config.checkpoint_interval,
                    "auto_recover": self.config.auto_recover,
                    "max_session_duration": self.config.max_session_duration
                }
            }

    def is_running(self) -> bool:
        """Check if continuous operation is running."""
        return self._running and not self._shutting_down