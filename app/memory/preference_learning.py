"""User Preference Learning.

This module provides learning and application of long-term user preferences
by integrating with the LongTermMemory system. It learns from user interactions
and applies preferences automatically to improve the user experience.
"""

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from enum import Enum

from app.core.logger import logger
from app.memory.long_term_memory import LongTermMemory, LongTermEntry, create_long_term_memory


def _is_testing() -> bool:
    """Check if running in a test environment."""
    return "PYTEST_CURRENT_TEST" in os.environ or "pytest" in os.environ.get("_", "")


def _get_test_storage_path() -> str:
    """Get a test-specific storage path."""
    import tempfile
    import uuid
    return os.path.join(tempfile.gettempdir(), f"freya_test_preferences_{uuid.uuid4().hex[:8]}.json")


class PreferenceCategory(Enum):
    """Categories of user preferences."""
    CODING_STYLE = "coding_style"
    COMMUNICATION = "communication"
    TOOLS = "tools"
    WORKFLOW = "workflow"
    ENVIRONMENT = "environment"
    GENERAL = "general"


class PreferenceSource(Enum):
    """Source of a learned preference."""
    EXPLICIT = "explicit"        # User explicitly stated the preference
    INFERRED = "inferred"        # Inferred from user behavior
    PROJECT = "project"          # From project configuration
    DOCUMENTATION = "documentation"  # From documentation
    CORRECTION = "correction"    # User corrected a previous action


@dataclass
class UserPreference:
    """A single user preference."""
    key: str
    category: PreferenceCategory
    value: Any
    confidence: float = 1.0
    source: PreferenceSource = PreferenceSource.INFERRED
    description: str = ""
    tags: List[str] = field(default_factory=list)
    learned_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_applied: Optional[str] = None
    application_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_long_term_entry(self) -> LongTermEntry:
        """Convert to LongTermEntry for storage."""
        return LongTermEntry(
            entry_id=f"preference.{self.category.value}.{self.key}",
            category="preference",
            key=f"{self.category.value}.{self.key}",
            value=self.value,
            confidence=self.confidence,
            source=self.source.value,
            tags=self.tags + [f"pref_category:{self.category.value}"],
            description=self.description or f"User preference: {self.key}",
            metadata={
                **self.metadata,
                "learned_at": self.learned_at,
                "last_applied": self.last_applied,
                "application_count": self.application_count,
            }
        )

    @classmethod
    def from_long_term_entry(cls, entry: LongTermEntry) -> "UserPreference":
        """Create from LongTermEntry."""
        meta = entry.metadata or {}
        # Extract category from key
        key_parts = entry.key.split(".", 1)
        category_str = key_parts[0] if len(key_parts) > 1 else "general"
        key = key_parts[1] if len(key_parts) > 1 else entry.key
        try:
            category = PreferenceCategory(category_str)
        except ValueError:
            category = PreferenceCategory.GENERAL

        return cls(
            key=key,
            category=category,
            value=entry.value,
            confidence=entry.confidence,
            source=PreferenceSource(entry.source),
            description=entry.description,
            tags=[t for t in entry.tags if not t.startswith("pref_category:")],
            learned_at=meta.get("learned_at", entry.created_at),
            last_applied=meta.get("last_applied"),
            application_count=meta.get("application_count", 0),
            metadata={k: v for k, v in meta.items() if k not in ("learned_at", "last_applied", "application_count")},
        )


class PreferenceLearner:
    """Learns user preferences from interactions."""

    # Patterns to detect explicit preference statements
    EXPLICIT_PATTERNS = [
        (r"I prefer\s+(\w+(?:\s+\w+)*)\s+(?:to|over)\s+(\w+(?:\s+\w+)*)", "explicit_choice"),
        (r"I like\s+(\w+(?:\s+\w+)*)\s+better", "explicit_choice"),
        (r"I always\s+(?:use|want|prefer)\s+(\w+(?:\s+\w+)*)", "explicit_always"),
        (r"(?:my|the)\s+preferred?\s+(\w+(?:\s+\w+)*)\s+is\s+(\w+(?:\s+\w+)*)", "explicit_setting"),
        (r"use\s+(\w+(?:\s+\w+)*)\s+for\s+(\w+(?:\s+\w+)*)", "explicit_tool"),
        (r"default\s+(\w+(?:\s+\w+)*)\s+(?:to|is|should be)\s+(\w+(?:\s+\w+)*)", "explicit_default"),
        # "I prefer X" without comparison - e.g., "I prefer 4-space indentation"
        (r"I prefer\s+([\w\s\-]+?)(?:\.|$|\s+(?:for|because|since|as|,))", "explicit_prefer"),
        # "I want X" / "I'd like X" / "I would like X"
        (r"(?:I|I'd|I would)\s+(?:want|like|love|prefer)\s+([\w\s\-]+?)(?:\.|$|\s+(?:for|because|since|as|,))", "explicit_want"),
    ]

    # Patterns to infer preferences from behavior
    BEHAVIOR_PATTERNS = [
        (r"(?:use|using|run|running)\s+(\w+)\s+(?:for|to)\s+(\w+)", "tool_usage"),
        (r"(?:open|edit|create|write)\s+.*\.(\w+)", "file_extension"),
        (r"(?:indent|tab|space).*?(\d+)", "indentation"),
        (r"(?:pytest|unittest|jest|vitest)", "test_framework"),
        (r"(?:black|ruff|prettier|eslint)", "formatter"),
        (r"(?:mypy|pyright|typescript)", "type_checker"),
    ]

    # Known preference keys and their categories
    PREFERENCE_SCHEMA = {
        "indent_size": (PreferenceCategory.CODING_STYLE, int),
        "indent_style": (PreferenceCategory.CODING_STYLE, str),  # spaces, tabs
        "max_line_length": (PreferenceCategory.CODING_STYLE, int),
        "test_framework": (PreferenceCategory.TOOLS, str),
        "formatter": (PreferenceCategory.TOOLS, str),
        "linter": (PreferenceCategory.TOOLS, str),
        "type_checker": (PreferenceCategory.TOOLS, str),
        "preferred_editor": (PreferenceCategory.ENVIRONMENT, str),
        "preferred_shell": (PreferenceCategory.ENVIRONMENT, str),
        "preferred_language": (PreferenceCategory.CODING_STYLE, str),
        "default_branch": (PreferenceCategory.WORKFLOW, str),
        "commit_style": (PreferenceCategory.WORKFLOW, str),  # conventional, simple, etc.
        "auto_commit": (PreferenceCategory.WORKFLOW, bool),
        "verbose_output": (PreferenceCategory.COMMUNICATION, bool),
        "explain_commands": (PreferenceCategory.COMMUNICATION, bool),
        "concise_responses": (PreferenceCategory.COMMUNICATION, bool),
        "use_colors": (PreferenceCategory.COMMUNICATION, bool),
        "async_execution": (PreferenceCategory.WORKFLOW, bool),
        "auto_test": (PreferenceCategory.WORKFLOW, bool),
        "git_hooks": (PreferenceCategory.WORKFLOW, bool),
    }

    def __init__(self, long_term_memory: Optional[LongTermMemory] = None):
        """Initialize the preference learner.

        Args:
            long_term_memory: LongTermMemory instance (creates default if None)
        """
        if long_term_memory is None:
            self.ltm = create_long_term_memory()
        else:
            self.ltm = long_term_memory
        self._load_preferences()

    def _load_preferences(self) -> None:
        """Load all preferences from long-term memory."""
        self._preferences: Dict[str, UserPreference] = {}
        for entry in self.ltm.get_category("preference").values():
            try:
                pref = UserPreference.from_long_term_entry(entry)
                self._preferences[pref.key] = pref
            except Exception as e:
                logger.warning(f"Failed to load preference {entry.key}: {e}")

    def _save_preference(self, pref: UserPreference) -> None:
        """Save a preference to long-term memory."""
        entry = pref.to_long_term_entry()
        self.ltm.set(
            category=entry.category,
            key=entry.key,
            value=entry.value,
            confidence=entry.confidence,
            source=entry.source,
            tags=entry.tags,
            description=entry.description,
            metadata=entry.metadata,
        )
        self._preferences[pref.key] = pref

    def learn_from_message(self, user_message: str, assistant_response: str = "") -> List[UserPreference]:
        """Learn preferences from a user message and assistant response.

        Args:
            user_message: The user's input message.
            assistant_response: The assistant's response (to detect corrections).

        Returns:
            List of newly learned or updated preferences.
        """
        learned = []

        # Check for explicit preference statements
        learned.extend(self._learn_explicit_preferences(user_message))

        # Check for behavior patterns
        learned.extend(self._learn_from_behavior(user_message))

        # Check for corrections in assistant response
        if assistant_response:
            learned.extend(self._learn_from_correction(user_message, assistant_response))

        return learned

    def _learn_explicit_preferences(self, message: str) -> List[UserPreference]:
        """Learn from explicit preference statements."""
        learned = []
        message_lower = message.lower()
        seen_keys: Set[str] = set()

        for pattern, pattern_type in self.EXPLICIT_PATTERNS:
            matches = re.finditer(pattern, message_lower, re.IGNORECASE)
            for match in matches:
                try:
                    pref = self._extract_explicit_preference(pattern_type, match)
                    if pref and pref.key not in seen_keys:
                        seen_keys.add(pref.key)
                        learned.append(pref)
                        self._save_preference(pref)
                except Exception as e:
                    logger.debug(f"Failed to extract explicit preference: {e}")

        return learned

    def _extract_explicit_preference(self, pattern_type: str, match: re.Match) -> Optional[UserPreference]:
        """Extract a preference from a regex match."""
        groups = match.groups()

        if pattern_type == "explicit_choice" and len(groups) >= 2:
            # "I prefer X to Y" or "I like X better"
            key = groups[0].strip().replace(" ", "_")
            value = groups[1].strip()
            category, value_type = self._infer_category_and_type(key, value)
            return UserPreference(
                key=key,
                category=category,
                value=value_type(value) if value_type != str else value,
                confidence=0.9,
                source=PreferenceSource.EXPLICIT,
                description=f"User explicitly prefers {value} for {key}",
            )

        elif pattern_type == "explicit_always" and len(groups) >= 1:
            # "I always use X"
            key = groups[0].strip().replace(" ", "_")
            category, value_type = self._infer_category_and_type(key, "true")
            return UserPreference(
                key=key,
                category=category,
                value=True,
                confidence=0.85,
                source=PreferenceSource.EXPLICIT,
                description=f"User stated they always use {key}",
            )

        elif pattern_type == "explicit_setting" and len(groups) >= 2:
            # "my preferred X is Y"
            key = groups[0].strip().replace(" ", "_")
            value = groups[1].strip()
            # Map common keys to schema keys
            if key == "editor":
                key = "preferred_editor"
                # Normalize editor names
                value_lower = value.lower()
                if "vs code" in value_lower or "vscode" in value_lower:
                    value = "vscode"
                elif "pycharm" in value_lower:
                    value = "pycharm"
                elif "intellij" in value_lower:
                    value = "intellij"
                elif "vim" in value_lower:
                    value = "vim"
                elif "emacs" in value_lower:
                    value = "emacs"
            elif key == "shell":
                key = "preferred_shell"
            elif key == "language":
                key = "preferred_language"
            category, value_type = self._infer_category_and_type(key, value)
            return UserPreference(
                key=key,
                category=category,
                value=value_type(value) if value_type != str else value,
                confidence=0.9,
                source=PreferenceSource.EXPLICIT,
                description=f"User set {key} to {value}",
            )

        elif pattern_type == "explicit_tool" and len(groups) >= 2:
            # "use X for Y"
            tool = groups[0].strip().replace(" ", "_")
            purpose = groups[1].strip().replace(" ", "_")
            key = f"{purpose}_tool"
            category, value_type = self.PREFERENCE_SCHEMA.get(key, (PreferenceCategory.TOOLS, str))
            return UserPreference(
                key=key,
                category=category,
                value=tool,
                confidence=0.85,
                source=PreferenceSource.EXPLICIT,
                description=f"User wants to use {tool} for {purpose}",
            )

        elif pattern_type == "explicit_default" and len(groups) >= 2:
            # "default X to Y"
            key = groups[0].strip().replace(" ", "_")
            value = groups[1].strip()
            category, value_type = self._infer_category_and_type(key, value)
            try:
                typed_value = value_type(value) if value_type != str else value
            except (ValueError, TypeError):
                typed_value = value
            return UserPreference(
                key=key,
                category=category,
                value=typed_value,
                confidence=0.85,
                source=PreferenceSource.EXPLICIT,
                description=f"User set default {key} to {value}",
            )

        elif pattern_type == "explicit_prefer" and len(groups) >= 1:
            # "I prefer X" - extract the preference from the text
            value = groups[0].strip()
            # Try to extract key=value from the preference
            # e.g., "4-space indentation" -> key="indent_size", value=4
            key, extracted_value = self._parse_preference_phrase(value)
            if key:
                category, value_type = self._infer_category_and_type(key, str(extracted_value))
                return UserPreference(
                    key=key,
                    category=category,
                    value=value_type(extracted_value) if value_type != str else extracted_value,
                    confidence=0.8,
                    source=PreferenceSource.EXPLICIT,
                    description=f"User explicitly prefers {value}",
                )

        elif pattern_type == "explicit_want" and len(groups) >= 1:
            # "I want X" / "I'd like X" / "I would like X"
            value = groups[0].strip()
            key, extracted_value = self._parse_preference_phrase(value)
            if key:
                category, value_type = self._infer_category_and_type(key, str(extracted_value))
                return UserPreference(
                    key=key,
                    category=category,
                    value=value_type(extracted_value) if value_type != str else extracted_value,
                    confidence=0.75,
                    source=PreferenceSource.EXPLICIT,
                    description=f"User wants {value}",
                )

        return None

    def _parse_preference_phrase(self, phrase: str) -> tuple:
        """Parse a preference phrase into key-value pair.

        Args:
            phrase: e.g., "4-space indentation", "pytest for testing", "VS Code as editor"

        Returns:
            Tuple of (key, value) or (None, None) if not parseable.
        """
        phrase_lower = phrase.lower()

        # Indentation preferences - with number
        indent_match = re.search(r'(\d+)[-\s]?(?:space|tab)', phrase_lower)
        if indent_match:
            if 'tab' in phrase_lower:
                return "indent_style", "tabs"
            return "indent_size", int(indent_match.group(1))

        # Indentation preferences - without number (just "tabs" or "spaces")
        if re.search(r'\b(tabs?)\b', phrase_lower):
            return "indent_style", "tabs"
        if re.search(r'\b(spaces?)\b', phrase_lower):
            return "indent_style", "spaces"

        # File extension / language
        lang_match = re.search(r'\b(python|javascript|typescript|java|go|rust|c\+\+|c#|ruby|php)\b', phrase_lower)
        if lang_match:
            return "preferred_language", lang_match.group(1)

        # Editor
        editor_match = re.search(r'\b(vs\s*code|vscode|vim|emacs|sublime|intellij|pycharm|webstorm)\b', phrase_lower)
        if editor_match:
            return "preferred_editor", editor_match.group(1).replace(" ", "")

        # Shell
        shell_match = re.search(r'\b(bash|zsh|fish|powershell|cmd|pwsh)\b', phrase_lower)
        if shell_match:
            return "preferred_shell", shell_match.group(1)

        # Testing framework
        test_match = re.search(r'\b(pytest|unittest|jest|vitest|mocha|jasmine|go\s+test|cargo\s+test)\b', phrase_lower)
        if test_match:
            return "test_framework", test_match.group(1).replace(" ", "_")

        # Formatter
        fmt_match = re.search(r'\b(black|ruff|prettier|eslint|gofmt|rustfmt|clang-format)\b', phrase_lower)
        if fmt_match:
            return "formatter", fmt_match.group(1)

        # Linter
        lint_match = re.search(r'\b(pylint|flake8|ruff|eslint|golangci-lint|clippy)\b', phrase_lower)
        if lint_match:
            return "linter", lint_match.group(1)

        # Type checker
        type_match = re.search(r'\b(mypy|pyright|typescript|tsc|go\s+vet)\b', phrase_lower)
        if type_match:
            return "type_checker", type_match.group(1).replace(" ", "_")

        # Commit style
        commit_match = re.search(r'\b(conventional|angular|simple|github|gitmoji)\b', phrase_lower)
        if commit_match:
            return "commit_style", commit_match.group(1)

        # Boolean preferences
        if any(word in phrase_lower for word in ['verbose', 'detailed', 'explain']):
            if 'not' not in phrase_lower and 'don\'t' not in phrase_lower and 'no ' not in phrase_lower:
                return "verbose_output", True
        if any(word in phrase_lower for word in ['concise', 'brief', 'short']):
            return "concise_responses", True
        if any(word in phrase_lower for word in ['color', 'colored', 'colours', 'coloured']):
            return "use_colors", True
        if 'auto' in phrase_lower and ('test' in phrase_lower or 'commit' in phrase_lower):
            return "auto_test", True

        # Default: use the phrase as key
        key = phrase.strip().replace(" ", "_").replace("-", "_")
        return key, phrase.strip()

    def _learn_from_behavior(self, message: str) -> List[UserPreference]:
        """Learn preferences from usage behavior."""
        learned = []
        message_lower = message.lower()
        seen_keys: Set[str] = set()

        for pattern, pattern_type in self.BEHAVIOR_PATTERNS:
            matches = re.finditer(pattern, message_lower, re.IGNORECASE)
            for match in matches:
                try:
                    pref = self._extract_behavior_preference(pattern_type, match)
                    if pref and pref.key not in seen_keys:
                        seen_keys.add(pref.key)
                        learned.append(pref)
                        self._save_preference(pref)
                except Exception as e:
                    logger.debug(f"Failed to extract behavior preference: {e}")

        return learned

    def _extract_behavior_preference(self, pattern_type: str, match: re.Match) -> Optional[UserPreference]:
        """Extract a preference from behavior pattern."""
        groups = match.groups()

        if pattern_type == "tool_usage" and len(groups) >= 2:
            tool = groups[0].strip().replace(" ", "_")
            purpose = groups[1].strip().replace(" ", "_")
            key = f"{purpose}_tool"
            category, value_type = self.PREFERENCE_SCHEMA.get(key, (PreferenceCategory.TOOLS, str))

            # Only update if we don't have explicit preference or confidence is low
            existing = self._preferences.get(key)
            if existing and existing.source == PreferenceSource.EXPLICIT and existing.confidence > 0.7:
                return None

            return UserPreference(
                key=key,
                category=category,
                value=tool,
                confidence=0.6,
                source=PreferenceSource.INFERRED,
                description=f"Inferred from usage: {tool} for {purpose}",
            )

        elif pattern_type == "file_extension" and len(groups) >= 1:
            ext = groups[0].strip()
            key = f"primary_file_extension"
            category, value_type = PreferenceCategory.CODING_STYLE, str

            existing = self._preferences.get(key)
            if existing and existing.source == PreferenceSource.EXPLICIT:
                return None

            return UserPreference(
                key=key,
                category=category,
                value=ext,
                confidence=0.5,
                source=PreferenceSource.INFERRED,
                description=f"Inferred primary file extension: .{ext}",
            )

        elif pattern_type == "indentation" and len(groups) >= 1:
            try:
                size = int(groups[0])
                if size in (2, 4, 8):
                    key = "indent_size"
                    category, value_type = self.PREFERENCE_SCHEMA[key]

                    existing = self._preferences.get(key)
                    if existing and existing.source == PreferenceSource.EXPLICIT and existing.confidence > 0.7:
                        return None

                    return UserPreference(
                        key=key,
                        category=category,
                        value=size,
                        confidence=0.6,
                        source=PreferenceSource.INFERRED,
                        description=f"Inferred indent size: {size}",
                    )
            except ValueError:
                pass

        elif pattern_type in ("test_framework", "formatter", "type_checker"):
            tool = match.group(0).strip()
            key = f"preferred_{pattern_type}"
            category, value_type = self.PREFERENCE_SCHEMA.get(key, (PreferenceCategory.TOOLS, str))

            existing = self._preferences.get(key)
            if existing and existing.source == PreferenceSource.EXPLICIT and existing.confidence > 0.7:
                return None

            return UserPreference(
                key=key,
                category=category,
                value=tool,
                confidence=0.6,
                source=PreferenceSource.INFERRED,
                description=f"Inferred preferred {pattern_type}: {tool}",
            )

        return None

    def _learn_from_correction(self, user_message: str, assistant_response: str) -> List[UserPreference]:
        """Learn from user corrections to assistant actions."""
        learned = []

        # If user says "no" or corrects after an assistant action
        correction_patterns = [
            (r"(?:no|not|don't|didn't mean|actually|instead|rather)\s+(?:use|want|prefer)\s+(\w+(?:\s+\w+)*)", "correction"),
            (r"(?:wrong|incorrect|that's not|it's not)\s+(\w+(?:\s+\w+)*)", "negative_correction"),
        ]

        combined = f"{user_message} {assistant_response}".lower()

        for pattern, pattern_type in correction_patterns:
            matches = re.finditer(pattern, combined, re.IGNORECASE)
            for match in matches:
                try:
                    groups = match.groups()
                    if groups:
                        key = groups[0].strip().replace(" ", "_")
                        # Find what the preference should be - this is complex
                        # For now, just note the correction
                        logger.info(f"Detected correction for: {key}")
                except Exception:
                    pass

        return learned

    def _infer_category_and_type(self, key: str, value: str) -> tuple:
        """Infer category and value type from key and value."""
        # Check known schema first
        if key in self.PREFERENCE_SCHEMA:
            return self.PREFERENCE_SCHEMA[key]

        # Try to infer from key name
        if any(k in key for k in ["indent", "style", "format", "line", "length"]):
            return PreferenceCategory.CODING_STYLE, str
        elif any(k in key for k in ["tool", "framework", "linter", "formatter", "test"]):
            return PreferenceCategory.TOOLS, str
        elif any(k in key for k in ["shell", "editor", "env", "path", "config"]):
            return PreferenceCategory.ENVIRONMENT, str
        elif any(k in key for k in ["commit", "branch", "workflow", "git", "auto"]):
            return PreferenceCategory.WORKFLOW, str
        elif any(k in key for k in ["verbose", "explain", "concise", "color", "response"]):
            return PreferenceCategory.COMMUNICATION, str

        # Try to infer type from value
        if value.lower() in ("true", "false", "yes", "no", "on", "off"):
            return PreferenceCategory.GENERAL, bool
        try:
            int(value)
            return PreferenceCategory.GENERAL, int
        except ValueError:
            pass
        try:
            float(value)
            return PreferenceCategory.GENERAL, float
        except ValueError:
            pass

        return PreferenceCategory.GENERAL, str

    def get_preference(self, key: str, default: Any = None) -> Any:
        """Get a preference value by key."""
        pref = self._preferences.get(key)
        if pref:
            pref.application_count += 1
            pref.last_applied = datetime.now(timezone.utc).isoformat()
            self._save_preference(pref)
            return pref.value
        return default

    def get_preference_obj(self, key: str) -> Optional[UserPreference]:
        """Get the full preference object."""
        return self._preferences.get(key)

    def get_all_preferences(self) -> Dict[str, UserPreference]:
        """Get all preferences as a dict."""
        return self._preferences.copy()

    def get_preferences_by_category(self, category: PreferenceCategory) -> Dict[str, UserPreference]:
        """Get all preferences in a category."""
        return {
            k: v for k, v in self._preferences.items()
            if v.category == category
        }

    def set_preference(
        self,
        key: str,
        value: Any,
        category: Optional[PreferenceCategory] = None,
        source: PreferenceSource = PreferenceSource.EXPLICIT,
        confidence: float = 1.0,
        description: str = "",
    ) -> UserPreference:
        """Explicitly set a preference.

        Args:
            key: Preference key.
            value: Value to set.
            category: Category (auto-inferred if not provided).
            source: Source of the preference.
            confidence: Confidence level.
            description: Description.

        Returns:
            The created/updated UserPreference.
        """
        if category is None:
            category, _ = self._infer_category_and_type(key, str(value))

        pref = UserPreference(
            key=key,
            category=category,
            value=value,
            confidence=confidence,
            source=source,
            description=description or f"User set {key} = {value}",
        )
        self._save_preference(pref)
        return pref

    def delete_preference(self, key: str) -> bool:
        """Delete a preference."""
        if key in self._preferences:
            # Delete from LTM
            for cat in PreferenceCategory:
                composite_key = f"preference.{cat.value}.{key}"
                self.ltm.delete("preference", f"{cat.value}.{key}")
            del self._preferences[key]
            return True
        return False

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about learned preferences."""
        categories: Dict[str, int] = {}
        sources: Dict[str, int] = {}
        total_confidence = 0

        for pref in self._preferences.values():
            cat = pref.category.value
            categories[cat] = categories.get(cat, 0) + 1
            src = pref.source.value
            sources[src] = sources.get(src, 0) + 1
            total_confidence += pref.confidence

        return {
            "total_preferences": len(self._preferences),
            "categories": categories,
            "sources": sources,
            "avg_confidence": total_confidence / len(self._preferences) if self._preferences else 0,
        }


class PreferenceApplier:
    """Applies learned preferences to agent behavior."""

    def __init__(self, learner: PreferenceLearner):
        """Initialize with a PreferenceLearner."""
        self.learner = learner

    def apply_to_code_generation(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Apply preferences to code generation context."""
        prefs = self.learner.get_preferences_by_category(PreferenceCategory.CODING_STYLE)

        for key, pref in prefs.items():
            if key == "indent_size":
                context["indent_size"] = pref.value
            elif key == "indent_style":
                context["indent_style"] = pref.value
            elif key == "max_line_length":
                context["max_line_length"] = pref.value
            elif key == "preferred_language":
                context["preferred_language"] = pref.value

        return context

    def apply_to_file_operations(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Apply preferences to file operations."""
        prefs = self.learner.get_all_preferences()

        if "preferred_editor" in prefs:
            context["editor"] = prefs["preferred_editor"].value
        if "preferred_shell" in prefs:
            context["shell"] = prefs["preferred_shell"].value

        return context

    def apply_to_communication(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Apply communication preferences."""
        prefs = self.learner.get_preferences_by_category(PreferenceCategory.COMMUNICATION)

        for key, pref in prefs.items():
            context[f"comm_{key}"] = pref.value

        return context

    def apply_to_workflow(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Apply workflow preferences."""
        prefs = self.learner.get_preferences_by_category(PreferenceCategory.WORKFLOW)

        for key, pref in prefs.items():
            context[f"workflow_{key}"] = pref.value

        return context

    def apply_to_tools(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Apply tool preferences."""
        prefs = self.learner.get_preferences_by_category(PreferenceCategory.TOOLS)

        for key, pref in prefs.items():
            context[f"tool_{key}"] = pref.value

        return context

    def apply_all(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Apply all preferences to a context dict."""
        context = self.apply_to_code_generation(context)
        context = self.apply_to_file_operations(context)
        context = self.apply_to_communication(context)
        context = self.apply_to_workflow(context)
        context = self.apply_to_tools(context)
        return context


# Global instance
_learner: Optional[PreferenceLearner] = None
_applier: Optional[PreferenceApplier] = None


def reset_global_learner() -> None:
    """Reset the global PreferenceLearner instance. Useful for testing."""
    global _learner, _applier
    _learner = None
    _applier = None


def get_preference_learner() -> PreferenceLearner:
    """Get the global PreferenceLearner instance.

    In test environments, uses an isolated temporary storage to avoid
    polluting user preferences.
    """
    global _learner
    if _learner is None:
        is_test = _is_testing()
        print(f"[DEBUG] get_preference_learner: _is_testing()={is_test}, _learner is None")
        if is_test:
            # Use isolated storage for tests
            from app.memory import create_long_term_memory
            test_path = _get_test_storage_path()
            print(f"[DEBUG] Creating test LTM with path: {test_path}")
            ltm = create_long_term_memory(storage_path=test_path)
            _learner = PreferenceLearner(ltm)
        else:
            _learner = PreferenceLearner()
    return _learner


def get_preference_applier() -> PreferenceApplier:
    """Get the global PreferenceApplier instance."""
    global _applier
    if _applier is None:
        _applier = PreferenceApplier(get_preference_learner())
    return _applier


def learn_from_interaction(user_message: str, assistant_response: str = "") -> List[UserPreference]:
    """Convenience function to learn from an interaction."""
    return get_preference_learner().learn_from_message(user_message, assistant_response)


def get_preference(key: str, default: Any = None) -> Any:
    """Convenience function to get a preference."""
    return get_preference_learner().get_preference(key, default)


def set_preference(key: str, value: Any, **kwargs) -> UserPreference:
    """Convenience function to set a preference."""
    return get_preference_learner().set_preference(key, value, **kwargs)


def apply_preferences(context: Dict[str, Any]) -> Dict[str, Any]:
    """Convenience function to apply all preferences."""
    return get_preference_applier().apply_all(context)