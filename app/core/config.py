import math
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = BASE_DIR / ".env"

load_dotenv(ENV_FILE)


LEARNING_THRESHOLD_ENV_KEYS = (
    "LEARNING_MIN_RELEVANCE",
    "LEARNING_MIN_NOVELTY",
    "LEARNING_MIN_ACTIONABILITY",
    "LEARNING_MIN_CONFIDENCE",
    "LEARNING_WORTH_REMEMBERING_THRESHOLD",
)
REPAIR_PROMPT_POLICIES = ("standard", "concise")


def _read_float_env(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return float(raw_value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be a number") from error


def _read_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be an integer") from error


def _validate_unit_interval(name: str, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number between 0 and 1")
    if not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")


@dataclass(frozen=True)
class LearningPolicyConfig:
    """Validated thresholds that control learning acceptance and storage."""

    min_relevance: float = 0.3
    min_novelty: float = 0.2
    min_actionability: float = 0.2
    min_confidence: float = 0.1
    worth_remembering_threshold: float = 0.4
    min_items_for_storage: int = 1

    def __post_init__(self) -> None:
        for name in (
            "min_relevance",
            "min_novelty",
            "min_actionability",
            "min_confidence",
            "worth_remembering_threshold",
        ):
            _validate_unit_interval(name, getattr(self, name))
        if (
            isinstance(self.min_items_for_storage, bool)
            or not isinstance(self.min_items_for_storage, int)
            or self.min_items_for_storage < 1
        ):
            raise ValueError("min_items_for_storage must be an integer greater than or equal to 1")

    @classmethod
    def from_environment(cls) -> "LearningPolicyConfig":
        return cls(
            min_relevance=_read_float_env("LEARNING_MIN_RELEVANCE", cls.min_relevance),
            min_novelty=_read_float_env("LEARNING_MIN_NOVELTY", cls.min_novelty),
            min_actionability=_read_float_env("LEARNING_MIN_ACTIONABILITY", cls.min_actionability),
            min_confidence=_read_float_env("LEARNING_MIN_CONFIDENCE", cls.min_confidence),
            worth_remembering_threshold=_read_float_env(
                "LEARNING_WORTH_REMEMBERING_THRESHOLD",
                cls.worth_remembering_threshold,
            ),
            min_items_for_storage=_read_int_env(
                "LEARNING_MIN_ITEMS_FOR_STORAGE",
                cls.min_items_for_storage,
            ),
        )

    @staticmethod
    def is_valid_threshold(value: object) -> bool:
        try:
            _validate_unit_interval("learning threshold", value)
        except ValueError:
            return False
        return True

    @staticmethod
    def is_valid_min_items(value: object) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value >= 1


@dataclass(frozen=True)
class RepairPolicyConfig:
    """Validated retry and prompt-selection policy for answer repair."""

    max_attempts: int = 3
    prompt_policy: str = "standard"

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_attempts, bool)
            or not isinstance(self.max_attempts, int)
            or not 1 <= self.max_attempts <= 10
        ):
            raise ValueError("max_attempts must be an integer between 1 and 10")
        if not isinstance(self.prompt_policy, str) or self.prompt_policy.strip() not in REPAIR_PROMPT_POLICIES:
            allowed = ", ".join(REPAIR_PROMPT_POLICIES)
            raise ValueError(f"prompt_policy must be one of: {allowed}")
        object.__setattr__(self, "prompt_policy", self.prompt_policy.strip())

    @classmethod
    def from_environment(cls) -> "RepairPolicyConfig":
        return cls(
            max_attempts=_read_int_env("ANSWER_REPAIR_MAX_ATTEMPTS", cls.max_attempts),
            prompt_policy=os.getenv("ANSWER_REPAIR_PROMPT_POLICY", cls.prompt_policy),
        )

    @staticmethod
    def is_valid_max_attempts(value: object) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 10

    @staticmethod
    def is_valid_prompt_policy(value: object) -> bool:
        return isinstance(value, str) and value.strip() in REPAIR_PROMPT_POLICIES


class Config:
    """Configuration loaded from the project .env file with validated policy settings."""

    def __init__(self):
        self.project_name = os.getenv("PROJECT_NAME", "Freya")
        self.model = os.getenv("MODEL", "qwen3:8b")
        self.workspace = os.getenv("WORKSPACE", str(BASE_DIR))
        self.memory_path = os.getenv("MEMORY_PATH", "data/memory")
        self.vector_path = os.getenv("VECTOR_PATH", "data/vector_db")
        self.learning_policy = LearningPolicyConfig.from_environment()
        self.repair_policy = RepairPolicyConfig.from_environment()

    def get(self, key, default=None):
        return os.getenv(key, default)


config = Config()
