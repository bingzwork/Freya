"""
Configuration Hot-Reload for Freya.

This module provides hot-reload functionality for configuration files,
integrating with the existing EventBus and FileWatcher infrastructure.
"""

import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set
from copy import deepcopy

from app.core.config import Config, BASE_DIR, LearningPolicyConfig, RepairPolicyConfig
from app.core.events import EventBus, get_event_bus, Event
from app.core.file_watcher import FileWatcher, FileEventBusIntegration, FileEventType
from app.core.logger import logger


@dataclass
class ConfigChange:
    """Represents a single configuration change."""
    key: str
    old_value: Any
    new_value: Any
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ReloadResult:
    """Result of a configuration reload attempt."""
    success: bool
    changes: List[ConfigChange] = field(default_factory=list)
    error: Optional[str] = None
    rolled_back: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ConfigValidator:
    """Validates configuration values."""

    # Type validators for known config keys
    VALIDATORS: Dict[str, Callable[[Any], bool]] = {
        "PROJECT_NAME": lambda v: isinstance(v, str) and len(v) > 0,
        "MODEL": lambda v: isinstance(v, str) and len(v) > 0,
        "WORKSPACE": lambda v: isinstance(v, str) and len(v) > 0,
        "MEMORY_PATH": lambda v: isinstance(v, str) and len(v) > 0,
        "VECTOR_PATH": lambda v: isinstance(v, str) and len(v) > 0,
        "DEFAULT_PROVIDER": lambda v: isinstance(v, str) and len(v.strip()) > 0,
        "PROVIDER_ORDER": lambda v: isinstance(v, str),
        "FALLBACK_PROVIDERS": lambda v: isinstance(v, str),
        "OLLAMA_BASE_URL": lambda v: isinstance(v, str) and v.startswith(("http://", "https://")),
        "OLLAMA_MODEL": lambda v: isinstance(v, str) and len(v) > 0,
        "OLLAMA_TIMEOUT": lambda v: _try_parse_number(v) is not None and _try_parse_number(v) > 0,
        "CLAUDE_API_KEY": lambda v: isinstance(v, str),
        "CLAUDE_MODEL": lambda v: isinstance(v, str) and len(v) > 0,
        "OPENAI_API_KEY": lambda v: isinstance(v, str),
        "OPENAI_MODEL": lambda v: isinstance(v, str) and len(v) > 0,
        "GEMINI_API_KEY": lambda v: isinstance(v, str),
        "GEMINI_MODEL": lambda v: isinstance(v, str) and len(v) > 0,
        "DEEPSEEK_API_KEY": lambda v: isinstance(v, str),
        "DEEPSEEK_MODEL": lambda v: isinstance(v, str) and len(v) > 0,
        "HEALTH_CHECK_ON_STARTUP": lambda v: _try_parse_bool(v) is not None,
        "HEALTH_CHECK_TIMEOUT": lambda v: _try_parse_number(v) is not None and _try_parse_number(v) > 0,
        "LOG_LEVEL": lambda v: isinstance(v, str) and v.upper() in ("DEBUG", "INFO", "WARNING", "ERROR"),
        "LOG_PROVIDER_REQUESTS": lambda v: _try_parse_bool(v) is not None,
        "MAX_INDEX_SIZE": lambda v: _try_parse_int(v) is not None and _try_parse_int(v) > 0,
        "INDEX_BATCH_SIZE": lambda v: _try_parse_int(v) is not None and _try_parse_int(v) > 0,
        "LLM_TIMEOUT": lambda v: _try_parse_number(v) is not None and _try_parse_number(v) > 0,
        "LEARNING_MIN_RELEVANCE": LearningPolicyConfig.is_valid_threshold,
        "LEARNING_MIN_NOVELTY": LearningPolicyConfig.is_valid_threshold,
        "LEARNING_MIN_ACTIONABILITY": LearningPolicyConfig.is_valid_threshold,
        "LEARNING_MIN_CONFIDENCE": LearningPolicyConfig.is_valid_threshold,
        "LEARNING_WORTH_REMEMBERING_THRESHOLD": LearningPolicyConfig.is_valid_threshold,
        "LEARNING_MIN_ITEMS_FOR_STORAGE": LearningPolicyConfig.is_valid_min_items,
        "ANSWER_REPAIR_MAX_ATTEMPTS": RepairPolicyConfig.is_valid_max_attempts,
        "ANSWER_REPAIR_PROMPT_POLICY": RepairPolicyConfig.is_valid_prompt_policy,
    }

    @staticmethod
    def _parse_value(value: str) -> Any:
        """Parse string value to appropriate type."""
        # Try boolean
        if isinstance(value, str):
            v_lower = value.lower()
            if v_lower in ("true", "false"):
                return v_lower == "true"
            # Try integer
            try:
                return int(value)
            except ValueError:
                pass
            # Try float
            try:
                return float(value)
            except ValueError:
                pass
        return value

    @classmethod
    def validate(cls, key: str, value: Any) -> bool:
        """Validate a single configuration value."""
        # Parse string values first
        if isinstance(value, str):
            parsed = cls._parse_value(value)
        else:
            parsed = value

        validator = cls.VALIDATORS.get(key)
        if validator:
            try:
                return validator(parsed)
            except Exception:
                return False
        return True  # Unknown keys pass by default

    @classmethod
    def validate_all(cls, config: Dict[str, str]) -> List[str]:
        """Validate all configuration values. Returns list of invalid keys."""
        invalid = []
        for key, value in config.items():
            if not cls.validate(key, value):
                invalid.append(key)
        return invalid


def _try_parse_bool(value: Any) -> Optional[bool]:
    """Try to parse value as boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v_lower = value.lower()
        if v_lower in ("true", "1", "yes", "on"):
            return True
        if v_lower in ("false", "0", "no", "off"):
            return False
    return None


def _try_parse_int(value: Any) -> Optional[int]:
    """Try to parse value as integer."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            pass
    return None


def _try_parse_number(value: Any) -> Optional[float]:
    """Try to parse value as number (int or float)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            pass
    return None


class ConfigHotReload:
    """
    Hot-reload manager for configuration.

    Monitors .env file for changes and safely reloads configuration
    with validation and rollback support.
    """

    def __init__(
        self,
        config: Config,
        env_path: Optional[Path] = None,
        event_bus: Optional[EventBus] = None,
        validate_on_reload: bool = True,
        reload_callback: Optional[Callable[[Config, List[ConfigChange]], None]] = None,
    ):
        """
        Initialize the hot-reload manager.

        Args:
            config: The Config instance to reload
            env_path: Path to .env file (default: BASE_DIR / .env)
            event_bus: EventBus for notifications (default: global)
            validate_on_reload: Whether to validate before applying
            reload_callback: Called after successful reload with (config, changes)
        """
        self.config = config
        self.env_path = env_path or (BASE_DIR / ".env")
        self.event_bus = event_bus or get_event_bus()
        self.validate_on_reload = validate_on_reload
        self.reload_callback = reload_callback

        # State
        self._current_env: Dict[str, str] = {}
        self._last_reload_result: Optional[ReloadResult] = None
        self._lock = threading.RLock()
        self._reload_in_progress = False

        # File watcher
        self._file_watcher: Optional[FileWatcher] = None
        self._file_integration: Optional[FileEventBusIntegration] = None
        self._subscription_id: Optional[str] = None

        # Load initial config
        self._load_env_file()

    def _load_env_file(self) -> Dict[str, str]:
        """Load environment variables from .env file."""
        env_vars = {}
        if self.env_path.exists():
            try:
                with open(self.env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, value = line.split("=", 1)
                            env_vars[key.strip()] = value.strip()
            except Exception as e:
                logger.error(f"Failed to load .env file: {e}")
        return env_vars

    def _parse_env_value(self, value: str) -> Any:
        """Parse environment variable value to appropriate type."""
        # Try boolean
        if value.lower() in ("true", "false"):
            return value.lower() == "true"
        # Try integer
        try:
            return int(value)
        except ValueError:
            pass
        # Try float
        try:
            return float(value)
        except ValueError:
            pass
        # Return as string
        return value

    def _get_current_config(self) -> Dict[str, Any]:
        """Get current configuration as dict with parsed values."""
        result = {}
        for key in self._current_env:
            result[key] = self._parse_env_value(self._current_env[key])
        return result

    def start(self) -> bool:
        """Start watching for configuration changes."""
        with self._lock:
            if self._file_watcher and self._file_watcher.is_running():
                logger.warning("ConfigHotReload already running")
                return False

            if not self.env_path.exists():
                logger.warning(f".env file does not exist: {self.env_path}")
                # Still start watching for creation
                pass

            # Create file watcher for .env file
            watch_dir = self.env_path.parent
            self._file_watcher = FileWatcher(
                event_bus=self.event_bus,
                paths=[str(watch_dir)],
                recursive=False,
                ignore_patterns=["*.pyc", "__pycache__/*", ".git/*"],
                debounce_ms=500,
            )

            self._file_integration = FileEventBusIntegration(
                self.event_bus, self._file_watcher
            )

            # Subscribe to config file changes
            self._subscription_id = self._file_integration.on_config_file_changed(
                self._on_config_file_changed
            )

            self._file_watcher.start()
            logger.info(f"ConfigHotReload started watching: {self.env_path}")
            return True

    def stop(self) -> None:
        """Stop watching for configuration changes."""
        with self._lock:
            if self._subscription_id:
                self.event_bus.unsubscribe(self._subscription_id)
                self._subscription_id = None

            if self._file_watcher:
                self._file_watcher.stop()
                self._file_watcher = None

            self._file_integration = None
            logger.info("ConfigHotReload stopped")

    def _on_config_file_changed(self, event: Event) -> None:
        """Handle config file change event."""
        path = event.data.get("path", "")
        if Path(path).name == ".env" or Path(path).name == ".env.example":
            logger.info(f"Configuration file changed: {path}")
            self.reload()

    def reload(self) -> ReloadResult:
        """
        Reload configuration from .env file.

        Returns:
            ReloadResult with success status and changes
        """
        with self._lock:
            if self._reload_in_progress:
                return ReloadResult(success=False, error="Reload already in progress")

            self._reload_in_progress = True

        try:
            return self._perform_reload()
        finally:
            with self._lock:
                self._reload_in_progress = False

    def _perform_reload(self) -> ReloadResult:
        """Perform the actual reload."""
        # Load new configuration
        new_env = self._load_env_file()

        # Compare with current
        changes = self._detect_changes(new_env)

        if not changes:
            return ReloadResult(success=True, changes=[])

        # Validate if enabled
        if self.validate_on_reload:
            invalid_keys = ConfigValidator.validate_all(new_env)
            if invalid_keys:
                error_msg = f"Invalid configuration keys: {', '.join(invalid_keys)}"
                logger.error(error_msg)
                # Emit error event
                self.event_bus.emit(
                    "config.reload.failed",
                    {"error": error_msg, "invalid_keys": invalid_keys},
                    source="config_hot_reload",
                )
                return ReloadResult(success=False, error=error_msg)

        # Store backup of current config
        backup_env = deepcopy(self._current_env)

        try:
            # Apply new configuration to os.environ
            self._apply_to_environment(new_env)

            # Update internal state
            self._current_env = new_env

            # Re-instantiate Config object to pick up new values
            self._refresh_config_object()

            # Create result
            result = ReloadResult(success=True, changes=changes)

            # Call callback if provided
            if self.reload_callback:
                try:
                    self.reload_callback(self.config, changes)
                except Exception as e:
                    logger.error(f"Error in reload callback: {e}")

            # Emit success event
            self.event_bus.emit(
                "config.reload.success",
                {
                    "changes": [{"key": c.key, "old_value": c.old_value, "new_value": c.new_value} for c in changes]
                },
                source="config_hot_reload",
            )

            logger.info(f"Configuration reloaded successfully: {len(changes)} changes")
            return result

        except Exception as e:
            # Rollback on failure
            logger.error(f"Configuration reload failed, rolling back: {e}")
            self._apply_to_environment(backup_env)
            self._current_env = backup_env
            self._refresh_config_object()

            result = ReloadResult(
                success=False,
                error=str(e),
                changes=changes,
                rolled_back=True,
            )

            self.event_bus.emit(
                "config.reload.rolled_back",
                {"error": str(e), "changes": [c.key for c in changes]},
                source="config_hot_reload",
            )

            return result

    def _detect_changes(self, new_env: Dict[str, str]) -> List[ConfigChange]:
        """Detect changes between current and new environment."""
        changes = []
        all_keys = set(self._current_env.keys()) | set(new_env.keys())

        for key in all_keys:
            old_val = self._current_env.get(key)
            new_val = new_env.get(key)

            if old_val != new_val:
                changes.append(ConfigChange(
                    key=key,
                    old_value=old_val,
                    new_value=new_val,
                ))

        return changes

    def _apply_to_environment(self, env_dict: Dict[str, str]) -> None:
        """Apply configuration to os.environ."""
        for key, value in env_dict.items():
            os.environ[key] = value

        # Also remove keys that are no longer present
        current_keys = set(env_dict.keys())
        # We don't remove from os.environ to avoid affecting other processes

    def _refresh_config_object(self) -> None:
        """Refresh the Config object by re-initializing its attributes."""
        # Create a new Config instance to pick up updated env vars
        new_config = Config()
        # Copy attributes to existing config object
        for attr in dir(new_config):
            if not attr.startswith("_"):
                try:
                    setattr(self.config, attr, getattr(new_config, attr))
                except Exception:
                    pass

    def get_reload_history(self, limit: int = 10) -> List[ReloadResult]:
        """Get recent reload results."""
        return [self._last_reload_result] if self._last_reload_result else []

    def get_current_config(self) -> Dict[str, Any]:
        """Get current configuration with parsed values."""
        return self._get_current_config()

    def is_running(self) -> bool:
        """Check if hot-reload is running."""
        return self._file_watcher is not None and self._file_watcher.is_running()

    def force_reload(self) -> ReloadResult:
        """Force a reload even if no file changes detected."""
        return self.reload()


def create_config_hot_reload(
    config: Optional[Config] = None,
    env_path: Optional[Path] = None,
    event_bus: Optional[EventBus] = None,
    **kwargs,
) -> ConfigHotReload:
    """
    Factory function to create ConfigHotReload.

    Args:
        config: Config instance (default: global config)
        env_path: Path to .env file
        event_bus: EventBus instance
        **kwargs: Additional arguments for ConfigHotReload

    Returns:
        ConfigHotReload instance
    """
    from app.core.config import config as global_config
    return ConfigHotReload(
        config=config or global_config,
        env_path=env_path,
        event_bus=event_bus,
        **kwargs,
    )


# Convenience function for automatic setup with agent
def setup_config_hot_reload_for_agent(agent) -> Optional[ConfigHotReload]:
    """
    Set up config hot-reload for a Freya agent.

    Args:
        agent: FreyaAgent instance

    Returns:
        ConfigHotReload instance or None if setup failed
    """
    from app.core.config import config as global_config
    from app.core.events import get_event_bus

    try:
        hot_reload = ConfigHotReload(
            config=global_config,
            event_bus=get_event_bus(),
            reload_callback=lambda cfg, changes: _on_agent_config_reload(agent, cfg, changes),
        )
        hot_reload.start()
        return hot_reload
    except Exception as e:
        logger.error(f"Failed to setup config hot-reload for agent: {e}")
        return None


def _on_agent_config_reload(agent, config: Config, changes: List[ConfigChange]) -> None:
    """Handle config reload for agent components."""
    logger.info(f"Agent config reloaded with {len(changes)} changes")

    # Notify agent components that config changed
    # This is where specific components would re-initialize if needed
    for change in changes:
        key = change.key
        if key in (
            "MODEL", "DEFAULT_PROVIDER", "PROVIDER_ORDER", "FALLBACK_PROVIDERS",
            "OLLAMA_MODEL", "CLAUDE_MODEL", "OPENAI_MODEL",
        ):
            # Model changed - notify LLM components
            if hasattr(agent, 'llm') and agent.llm:
                logger.info(f"Model config changed: {key} = {change.new_value}")
        elif key in ("MEMORY_PATH", "VECTOR_PATH"):
            # Storage paths changed
            logger.info(f"Storage path changed: {key} = {change.new_value}")
        elif key == "LOG_LEVEL":
            # Log level changed
            import logging
            logging.getLogger().setLevel(change.new_value.upper())
            logger.info(f"Log level changed to {change.new_value}")