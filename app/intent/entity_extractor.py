"""Entity Extraction & Slot Filling.

Extracts important entities from user messages such as files, dates, times,
people, URLs, tasks, topics, numbers, and tool names.
"""

import re
from datetime import datetime, timedelta, date
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from app.core.logger import logger


class EntityType(Enum):
    """Types of entities that can be extracted."""

    FILE = "file"
    FOLDER = "folder"
    PROJECT = "project"
    DATE = "date"
    TIME = "time"
    DATETIME = "datetime"
    PERSON = "person"
    URL = "url"
    TASK = "task"
    TOPIC = "topic"
    NUMBER = "number"
    TOOL = "tool"
    EMAIL = "email"
    PHONE = "phone"
    IP_ADDRESS = "ip_address"
    VERSION = "version"
    COMMIT_HASH = "commit_hash"
    FILE_PATH = "file_path"
    REPOSITORY = "repository"


@dataclass
class ExtractedEntity:
    """An entity extracted from user text."""

    entity_type: EntityType
    value: str
    normalized_value: Any = None
    start: int = 0
    end: int = 0
    confidence: float = 0.8
    context: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.entity_type.value,
            "value": self.value,
            "normalized_value": self.normalized_value,
            "start": self.start,
            "end": self.end,
            "confidence": self.confidence,
            "context": self.context,
            "metadata": self.metadata,
        }


@dataclass
class SlotFillingResult:
    """Result of slot filling for a request."""

    required_slots: Dict[str, EntityType]
    filled_slots: Dict[str, ExtractedEntity]
    missing_slots: Dict[str, EntityType]
    is_complete: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "required_slots": {k: v.value for k, v in self.required_slots.items()},
            "filled_slots": {k: v.to_dict() for k, v in self.filled_slots.items()},
            "missing_slots": {k: v.value for k, v in self.missing_slots.items()},
            "is_complete": self.is_complete,
        }


# Common file extensions
FILE_EXTENSIONS = {
    "py", "js", "ts", "jsx", "tsx", "java", "cpp", "c", "h", "hpp",
    "cs", "go", "rs", "rb", "php", "swift", "kt", "scala", "r", "m",
    "pl", "sh", "bash", "zsh", "fish", "ps1", "bat", "cmd",
    "dockerfile", "makefile", "cmake", "gradle", "xml", "json",
    "yaml", "yml", "toml", "ini", "cfg", "conf", "md", "txt",
    "html", "css", "scss", "sass", "less", "vue", "svelte",
    "sql", "graphql", "proto", "avro", "thrift",
}

# File patterns
FILE_PATTERNS = [
    # File paths with extensions
    r'(?:\b|["\'])([a-zA-Z0-9_\-./\\]+\.(?:' + '|'.join(FILE_EXTENSIONS) + r'))(?:\b|["\'])',
    # Relative paths with ./
    r'(?:\b|["\'])(\./[a-zA-Z0-9_\-./\\]+)(?:\b|["\'])',
    # Absolute paths (Unix)
    r'(?:\b|["\'])((?:/[\w\-./]+)+)(?:\b|["\'])',
    # Absolute paths (Windows)
    r'(?:\b|["\'])((?:[A-Za-z]:)?\\[\w\-.\\[\]]+)(?:\b|["\'])',
]

# Folder/directory patterns
FOLDER_PATTERNS = [
    r'(?:\b|["\'])([a-zA-Z0-9_\-./\\]+/)(?:\b|["\'])',
    r'(?:folder|directory|dir)\s+([a-zA-Z0-9_\-./\\]+)',
]

# Date patterns with normalization functions
def _normalize_today(_match) -> str:
    return datetime.now().date().isoformat()

def _normalize_tomorrow(_match) -> str:
    return (datetime.now() + timedelta(days=1)).date().isoformat()

def _normalize_yesterday(_match) -> str:
    return (datetime.now() - timedelta(days=1)).date().isoformat()

def _normalize_relative_day(match) -> Optional[str]:
    """Normalize 'this/next/last monday' etc."""
    qualifier = match.group(1).lower()
    day_name = match.group(2).lower()

    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    target_day = days.index(day_name)
    today = datetime.now().weekday()

    if qualifier == "this":
        delta = (target_day - today) % 7
    elif qualifier == "next":
        delta = (target_day - today) % 7
        if delta == 0:
            delta = 7
    elif qualifier == "last":
        delta = (target_day - today) % 7
        delta = delta - 7 if delta > 0 else delta
    else:
        return None

    target_date = datetime.now() + timedelta(days=delta)
    return target_date.date().isoformat()

def _normalize_weekday(_match) -> Optional[str]:
    """Normalize bare weekday name (assume this week)."""
    day_name = _match.group(1).lower()
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    target_day = days.index(day_name)
    today = datetime.now().weekday()
    delta = (target_day - today) % 7
    target_date = datetime.now() + timedelta(days=delta)
    return target_date.date().isoformat()

def _normalize_month_day(match) -> Optional[str]:
    """Normalize 'jan 15' or '15 jan'."""
    months = {
        "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
        "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
        "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10,
        "nov": 11, "november": 11, "dec": 12, "december": 12,
    }

    if match.group(1).lower() in months:
        month = months[match.group(1).lower()]
        day = int(match.group(2))
    else:
        day = int(match.group(1))
        month = months[match.group(2).lower()]

    year = datetime.now().year
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None

def _normalize_slash_date(match) -> Optional[str]:
    """Normalize mm/dd/yyyy or dd/mm/yyyy."""
    parts = [int(match.group(i)) for i in range(1, 4)]
    # Heuristic: if first part > 12, assume dd/mm/yyyy
    if parts[0] > 12:
        day, month, year = parts
    else:
        month, day, year = parts
    if year < 100:
        year += 2000
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None

def _normalize_iso_date(match) -> Optional[str]:
    """Normalize yyyy-mm-dd."""
    year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None

def _normalize_relative_time(match) -> Optional[str]:
    """Normalize 'in 3 days', '3 weeks from now'."""
    amount = int(match.group(1))
    unit = match.group(2).lower()

    if unit.startswith("day"):
        target = datetime.now() + timedelta(days=amount)
    elif unit.startswith("week"):
        target = datetime.now() + timedelta(weeks=amount)
    elif unit.startswith("month"):
        target = datetime.now() + timedelta(weeks=amount * 4)  # Approximate
    elif unit.startswith("year"):
        target = datetime.now() + timedelta(weeks=amount * 52)  # Approximate
    else:
        return None

    return target.date().isoformat()

DATE_PATTERNS = [
    (r'\b(today)\b', _normalize_today),
    (r'\b(tomorrow)\b', _normalize_tomorrow),
    (r'\b(yesterday)\b', _normalize_yesterday),
    (r'\b(this|next|last)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b', _normalize_relative_day),
    (r'\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b', _normalize_weekday),
    (r'\b(jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)\s+(\d{1,2})(?:st|nd|rd|th)?\b', _normalize_month_day),
    (r'\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)\b', _normalize_month_day),
    (r'\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b', _normalize_slash_date),
    (r'\b(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})\b', _normalize_iso_date),
    (r'\bin\s+(\d+)\s+(day|week|month|year)s?\b', _normalize_relative_time),
]

def _normalize_time_12h(match) -> Optional[str]:
    """Normalize 3pm, 3:00pm, etc."""
    hour = int(match.group(1))
    minute = int(match.group(2)) if match.group(2) else 0
    meridiem = match.group(3).lower()

    if meridiem == "pm" and hour != 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0

    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None

    return f"{hour:02d}:{minute:02d}"

def _normalize_time_24h(match) -> Optional[str]:
    """Normalize 15:30."""
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"

def _normalize_time_word(match) -> Optional[str]:
    """Normalize noon, midnight, morning, etc."""
    word = match.group(1).lower()
    if word == "noon":
        return "12:00"
    elif word == "midnight":
        return "00:00"
    elif word == "morning":
        return "09:00"
    elif word == "afternoon":
        return "14:00"
    elif word == "evening":
        return "18:00"
    return None

TIME_PATTERNS = [
    (r'\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b', _normalize_time_12h),
    (r'\b(\d{1,2}):(\d{2})\b', _normalize_time_24h),
    (r'\b(noon|midnight|morning|afternoon|evening)\b', _normalize_time_word),
]

# Person/name patterns
PERSON_PATTERNS = [
    r'\b(?:with|for|to|from|by|@)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b',
    r'\b(?:assign(?:ed)?|ask|tell|notify)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b',
]

# URL pattern
URL_PATTERN = r'https?://[^\s/$.?#].[^\s]*'

# Email pattern
EMAIL_PATTERN = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'

# Phone pattern
PHONE_PATTERN = r'\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b'

# IP address pattern
IP_PATTERN = r'\b(?:\d{1,3}\.){3}\d{1,3}\b'

# Version pattern (semver, etc.)
VERSION_PATTERN = r'\bv?\d+\.\d+\.\d+(?:-[a-zA-Z0-9.-]+)?\b'

# Commit hash pattern
COMMIT_HASH_PATTERN = r'\b[a-fA-F0-9]{7,40}\b'

# Tool names
TOOL_NAMES = {
    "git", "docker", "npm", "yarn", "pnpm", "pip", "poetry", "conda", "uv",
    "pytest", "jest", "vitest", "mocha", "cypress", "playwright",
    "eslint", "prettier", "black", "ruff", "flake8", "mypy", "pylint",
    "webpack", "vite", "rollup", "tsc", "babel", "swc",
    "terraform", "ansible", "kubernetes", "kubectl", "helm",
    "aws", "gcloud", "az", "vercel", "netlify",
    "make", "cmake", "gradle", "maven", "sbt", "cargo",
    "go", "rustc", "javac", "python", "python3", "pip3",
    "redis", "postgres", "mysql", "mongodb", "sqlite",
    "nginx", "apache", "traefik", "caddy",
    "prometheus", "grafana", "datadog", "newrelic",
    "github", "gitlab", "bitbucket", "gitlab-ci", "github-actions",
    "jenkins", "circleci", "travis", "drone",
}

# Topic keywords
TOPIC_KEYWORDS = {
    "api": ["api", "rest", "graphql", "endpoint", "swagger", "openapi"],
    "database": ["database", "db", "sql", "nosql", "postgres", "mysql", "mongodb", "redis", "sqlite", "query", "migration"],
    "frontend": ["frontend", "ui", "react", "vue", "angular", "svelte", "component", "css", "html", "jsx", "tsx"],
    "backend": ["backend", "server", "api", "microservice", "endpoint", "middleware"],
    "testing": ["test", "testing", "pytest", "jest", "unit test", "integration test", "e2e", "coverage"],
    "deployment": ["deploy", "deployment", "ci/cd", "pipeline", "build", "release", "docker", "kubernetes", "k8s"],
    "security": ["security", "auth", "authentication", "authorization", "oauth", "jwt", "ssl", "tls", "encryption"],
    "performance": ["performance", "optimization", "speed", "latency", "throughput", "benchmark", "profiling"],
    "debugging": ["debug", "bug", "error", "exception", "crash", "traceback", "log", "logging"],
    "refactoring": ["refactor", "rewrite", "restructure", "clean up", "technical debt", "code quality"],
    "documentation": ["document", "documentation", "readme", "docs", "comment", "docstring"],
    "git": ["git", "commit", "branch", "merge", "rebase", "pull request", "pr", "push", "pull", "fetch"],
    "configuration": ["config", "configuration", "settings", "env", "environment", ".env"],
}

# Task action verbs (for extracting task entities)
TASK_VERBS = {
    "create", "build", "make", "generate", "produce", "develop",
    "write", "implement", "add", "remove", "delete", "move", "copy",
    "rename", "organize", "structure", "setup", "configure", "install",
    "update", "upgrade", "migrate", "transform", "convert",
    "process", "analyze", "audit", "review", "optimize", "improve",
    "fix", "solve", "resolve", "debug", "test", "verify", "validate",
    "check", "inspect", "examine", "investigate", "find", "locate",
    "search", "discover", "identify",
    "refactor", "rewrite", "fix bug", "implement", "code review",
    "analyze code", "explain code", "document code",
    "add feature", "extend", "modify code", "change code",
    "test code", "write test", "debug code",
}


class EntityExtractor:
    """Extracts entities from user messages."""

    def __init__(self):
        self._compile_patterns()

    def _compile_patterns(self):
        """Compile regex patterns for efficiency."""
        # Pre-compile file patterns
        self._file_patterns = [re.compile(p, re.IGNORECASE) for p in FILE_PATTERNS]
        self._folder_patterns = [re.compile(p, re.IGNORECASE) for p in FOLDER_PATTERNS]
        self._date_patterns = [(re.compile(p, re.IGNORECASE), fn) for p, fn in DATE_PATTERNS]
        self._time_patterns = [(re.compile(p, re.IGNORECASE), fn) for p, fn in TIME_PATTERNS]
        self._person_patterns = [re.compile(p, re.IGNORECASE) for p in PERSON_PATTERNS]
        self._url_pattern = re.compile(URL_PATTERN, re.IGNORECASE)
        self._email_pattern = re.compile(EMAIL_PATTERN, re.IGNORECASE)
        self._phone_pattern = re.compile(PHONE_PATTERN, re.IGNORECASE)
        self._ip_pattern = re.compile(IP_PATTERN, re.IGNORECASE)
        self._version_pattern = re.compile(VERSION_PATTERN, re.IGNORECASE)
        self._commit_hash_pattern = re.compile(COMMIT_HASH_PATTERN, re.IGNORECASE)

    def extract(self, message: str, entity_types: Optional[List[EntityType]] = None) -> List[ExtractedEntity]:
        """Extract entities from a message.

        Args:
            message: The user message to extract entities from.
            entity_types: Optional list of entity types to extract. If None, extracts all.

        Returns:
            List of ExtractedEntity objects.
        """
        if not message or not isinstance(message, str):
            return []

        entities = []

        # Determine which extractors to run
        extract_all = entity_types is None

        if extract_all or EntityType.FILE in entity_types or EntityType.FILE_PATH in entity_types:
            entities.extend(self._extract_files(message))

        if extract_all or EntityType.FOLDER in entity_types:
            entities.extend(self._extract_folders(message))

        if extract_all or EntityType.DATE in entity_types:
            entities.extend(self._extract_dates(message))

        if extract_all or EntityType.TIME in entity_types:
            entities.extend(self._extract_times(message))

        if extract_all or EntityType.PERSON in entity_types:
            entities.extend(self._extract_people(message))

        if extract_all or EntityType.URL in entity_types:
            entities.extend(self._extract_urls(message))

        if extract_all or EntityType.EMAIL in entity_types:
            entities.extend(self._extract_emails(message))

        if extract_all or EntityType.PHONE in entity_types:
            entities.extend(self._extract_phones(message))

        if extract_all or EntityType.IP_ADDRESS in entity_types:
            entities.extend(self._extract_ips(message))

        if extract_all or EntityType.VERSION in entity_types:
            entities.extend(self._extract_versions(message))

        if extract_all or EntityType.COMMIT_HASH in entity_types:
            entities.extend(self._extract_commit_hashes(message))

        if extract_all or EntityType.TOOL in entity_types:
            entities.extend(self._extract_tools(message))

        if extract_all or EntityType.TOPIC in entity_types:
            entities.extend(self._extract_topics(message))

        if extract_all or EntityType.TASK in entity_types:
            entities.extend(self._extract_tasks(message))

        if extract_all or EntityType.NUMBER in entity_types:
            entities.extend(self._extract_numbers(message))

        if extract_all or EntityType.REPOSITORY in entity_types:
            entities.extend(self._extract_repositories(message))

        # Sort by position in text
        entities.sort(key=lambda e: e.start)

        # Remove duplicates (same type, overlapping positions)
        entities = self._deduplicate(entities)

        logger.debug(f"[EntityExtractor] Extracted {len(entities)} entities from: {message[:50]}...")
        return entities

    def _extract_files(self, message: str) -> List[ExtractedEntity]:
        """Extract file paths."""
        entities = []
        for pattern in self._file_patterns:
            for match in pattern.finditer(message):
                value = match.group(1)
                # Skip if it's just a folder path (ends with / or \)
                if value.endswith('/') or value.endswith('\\'):
                    continue
                entities.append(ExtractedEntity(
                    entity_type=EntityType.FILE,
                    value=value,
                    normalized_value=value.replace('\\', '/'),
                    start=match.start(1),
                    end=match.end(1),
                    confidence=0.9,
                    context=message[max(0, match.start()-20):match.end()+20],
                ))
        return entities

    def _extract_folders(self, message: str) -> List[ExtractedEntity]:
        """Extract folder paths."""
        entities = []
        for pattern in self._folder_patterns:
            for match in pattern.finditer(message):
                if match.lastindex:
                    value = match.group(1)
                else:
                    value = match.group(0)
                entities.append(ExtractedEntity(
                    entity_type=EntityType.FOLDER,
                    value=value,
                    normalized_value=value.replace('\\', '/'),
                    start=match.start(1) if match.lastindex else match.start(),
                    end=match.end(1) if match.lastindex else match.end(),
                    confidence=0.8,
                    context=message[max(0, match.start()-20):match.end()+20],
                ))
        return entities

    def _extract_dates(self, message: str) -> List[ExtractedEntity]:
        """Extract and normalize dates."""
        entities = []
        for pattern, normalizer in self._date_patterns:
            for match in pattern.finditer(message):
                try:
                    normalized = normalizer(match)
                except Exception:
                    normalized = None

                if normalized:
                    # Determine which group to use as value
                    if match.lastindex and match.lastindex >= 1:
                        value = match.group(0)
                    else:
                        value = match.group(0)

                    entities.append(ExtractedEntity(
                        entity_type=EntityType.DATE,
                        value=value,
                        normalized_value=normalized,
                        start=match.start(),
                        end=match.end(),
                        confidence=0.85,
                        context=message[max(0, match.start()-20):match.end()+20],
                    ))
        return entities

    def _extract_times(self, message: str) -> List[ExtractedEntity]:
        """Extract and normalize times."""
        entities = []
        for pattern, normalizer in self._time_patterns:
            for match in pattern.finditer(message):
                try:
                    normalized = normalizer(match)
                except Exception:
                    normalized = None

                if normalized:
                    entities.append(ExtractedEntity(
                        entity_type=EntityType.TIME,
                        value=match.group(0),
                        normalized_value=normalized,
                        start=match.start(),
                        end=match.end(),
                        confidence=0.85,
                        context=message[max(0, match.start()-20):match.end()+20],
                    ))
        return entities

    def _extract_people(self, message: str) -> List[ExtractedEntity]:
        """Extract person names."""
        entities = []
        for pattern in self._person_patterns:
            for match in pattern.finditer(message):
                if match.lastindex and match.lastindex >= 1:
                    value = match.group(1)
                    start = match.start(1)
                    end = match.end(1)
                else:
                    value = match.group(0)
                    start = match.start()
                    end = match.end()

                # Filter out common false positives
                if value.lower() in {"the", "a", "an", "this", "that", "it", "they", "them"}:
                    continue

                entities.append(ExtractedEntity(
                    entity_type=EntityType.PERSON,
                    value=value,
                    normalized_value=value,
                    start=start,
                    end=end,
                    confidence=0.75,
                    context=message[max(0, match.start()-20):match.end()+20],
                ))
        return entities

    def _extract_urls(self, message: str) -> List[ExtractedEntity]:
        """Extract URLs."""
        entities = []
        for match in self._url_pattern.finditer(message):
            entities.append(ExtractedEntity(
                entity_type=EntityType.URL,
                value=match.group(0),
                normalized_value=match.group(0),
                start=match.start(),
                end=match.end(),
                confidence=0.95,
                context=message[max(0, match.start()-20):match.end()+20],
            ))
        return entities

    def _extract_emails(self, message: str) -> List[ExtractedEntity]:
        """Extract email addresses."""
        entities = []
        for match in self._email_pattern.finditer(message):
            entities.append(ExtractedEntity(
                entity_type=EntityType.EMAIL,
                value=match.group(0),
                normalized_value=match.group(0).lower(),
                start=match.start(),
                end=match.end(),
                confidence=0.95,
                context=message[max(0, match.start()-20):match.end()+20],
            ))
        return entities

    def _extract_phones(self, message: str) -> List[ExtractedEntity]:
        """Extract phone numbers."""
        entities = []
        for match in self._phone_pattern.finditer(message):
            entities.append(ExtractedEntity(
                entity_type=EntityType.PHONE,
                value=match.group(0),
                normalized_value=match.group(0),
                start=match.start(),
                end=match.end(),
                confidence=0.8,
                context=message[max(0, match.start()-20):match.end()+20],
            ))
        return entities

    def _extract_ips(self, message: str) -> List[ExtractedEntity]:
        """Extract IP addresses."""
        entities = []
        for match in self._ip_pattern.finditer(message):
            value = match.group(0)
            # Validate IP octets
            octets = value.split('.')
            if all(0 <= int(o) <= 255 for o in octets):
                entities.append(ExtractedEntity(
                    entity_type=EntityType.IP_ADDRESS,
                    value=value,
                    normalized_value=value,
                    start=match.start(),
                    end=match.end(),
                    confidence=0.9,
                    context=message[max(0, match.start()-20):match.end()+20],
                ))
        return entities

    def _extract_versions(self, message: str) -> List[ExtractedEntity]:
        """Extract version strings."""
        entities = []
        for match in self._version_pattern.finditer(message):
            entities.append(ExtractedEntity(
                entity_type=EntityType.VERSION,
                value=match.group(0),
                normalized_value=match.group(0).lstrip('v'),
                start=match.start(),
                end=match.end(),
                confidence=0.85,
                context=message[max(0, match.start()-20):match.end()+20],
            ))
        return entities

    def _extract_commit_hashes(self, message: str) -> List[ExtractedEntity]:
        """Extract git commit hashes."""
        entities = []
        for match in self._commit_hash_pattern.finditer(message):
            value = match.group(0)
            # Skip if it looks like a hex color or other false positive
            if len(value) >= 7:
                entities.append(ExtractedEntity(
                    entity_type=EntityType.COMMIT_HASH,
                    value=value,
                    normalized_value=value,
                    start=match.start(),
                    end=match.end(),
                    confidence=0.8,
                    context=message[max(0, match.start()-20):match.end()+20],
                ))
        return entities

    def _extract_tools(self, message: str) -> List[ExtractedEntity]:
        """Extract tool names mentioned in the message."""
        entities = []
        message_lower = message.lower()

        for tool in TOOL_NAMES:
            # Use word boundaries to avoid partial matches
            pattern = r'\b' + re.escape(tool) + r'\b'
            for match in re.finditer(pattern, message_lower, re.IGNORECASE):
                entities.append(ExtractedEntity(
                    entity_type=EntityType.TOOL,
                    value=match.group(0),
                    normalized_value=tool,
                    start=match.start(),
                    end=match.end(),
                    confidence=0.8,
                    context=message[max(0, match.start()-20):match.end()+20],
                ))
        return entities

    def _extract_topics(self, message: str) -> List[ExtractedEntity]:
        """Extract topic categories."""
        entities = []
        message_lower = message.lower()

        for topic, keywords in TOPIC_KEYWORDS.items():
            for keyword in keywords:
                pattern = r'\b' + re.escape(keyword) + r'\b'
                for match in re.finditer(pattern, message_lower, re.IGNORECASE):
                    entities.append(ExtractedEntity(
                        entity_type=EntityType.TOPIC,
                        value=match.group(0),
                        normalized_value=topic,
                        start=match.start(),
                        end=match.end(),
                        confidence=0.7,
                        context=message[max(0, match.start()-30):match.end()+30],
                        metadata={"matched_keyword": keyword, "topic": topic},
                    ))
        return entities

    def _extract_tasks(self, message: str) -> List[ExtractedEntity]:
        """Extract task descriptions."""
        entities = []
        message_lower = message.lower()

        for verb in TASK_VERBS:
            pattern = r'\b' + re.escape(verb) + r'\b'
            for match in re.finditer(pattern, message_lower, re.IGNORECASE):
                # Extract surrounding context as the task
                start = max(0, match.start() - 10)
                end = min(len(message), match.end() + 50)
                context = message[start:end].strip()

                entities.append(ExtractedEntity(
                    entity_type=EntityType.TASK,
                    value=context,
                    normalized_value=verb,
                    start=match.start(),
                    end=match.end(),
                    confidence=0.65,
                    context=context,
                    metadata={"action_verb": verb},
                ))
        return entities

    def _extract_numbers(self, message: str) -> List[ExtractedEntity]:
        """Extract numeric values."""
        entities = []
        # Match integers, decimals, and numbers with units
        number_pattern = r'\b(\d+(?:\.\d+)?)\s*(kb|mb|gb|tb|px|ms|s|min|h|%)?\b'
        for match in re.finditer(number_pattern, message, re.IGNORECASE):
            value = match.group(1)
            unit = match.group(2) if match.lastindex >= 2 else None

            entities.append(ExtractedEntity(
                entity_type=EntityType.NUMBER,
                value=value,
                normalized_value=float(value) if '.' in value else int(value),
                start=match.start(1),
                end=match.end(1),
                confidence=0.7,
                context=message[max(0, match.start()-20):match.end()+20],
                metadata={"unit": unit} if unit else {},
            ))
        return entities

    def _extract_repositories(self, message: str) -> List[ExtractedEntity]:
        """Extract repository references (owner/repo or URLs)."""
        entities = []
        # GitHub/GitLab style: owner/repo
        repo_pattern = r'\b([a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+)\b'
        for match in re.finditer(repo_pattern, message):
            value = match.group(1)
            # Heuristic: likely a repo if it contains common words or is in context
            if any(kw in message.lower() for kw in ["repo", "github", "gitlab", "repository", "fork", "clone", "star"]):
                entities.append(ExtractedEntity(
                    entity_type=EntityType.REPOSITORY,
                    value=value,
                    normalized_value=value,
                    start=match.start(),
                    end=match.end(),
                    confidence=0.75,
                    context=message[max(0, match.start()-20):match.end()+20],
                ))
        return entities

    def _deduplicate(self, entities: List[ExtractedEntity]) -> List[ExtractedEntity]:
        """Remove duplicate/overlapping entities."""
        if not entities:
            return []

        # Sort by start position, then by confidence (descending)
        entities.sort(key=lambda e: (e.start, -e.confidence))

        result = []
        last_end = -1
        last_type = None

        for entity in entities:
            # Skip if overlapping with previous entity of same or similar type
            if entity.start < last_end and entity.entity_type == last_type:
                continue

            # Skip if completely contained in previous
            if entity.start >= (result[-1].start if result else 0) and entity.end <= (result[-1].end if result else 0):
                continue

            result.append(entity)
            last_end = entity.end
            last_type = entity.entity_type

        return result


# Global extractor instance
_extractor = EntityExtractor()


def extract_entities(
    message: str,
    entity_types: Optional[List[EntityType]] = None
) -> List[ExtractedEntity]:
    """Convenience function to extract entities from a message.

    Args:
        message: The user message.
        entity_types: Optional filter for entity types.

    Returns:
        List of ExtractedEntity objects.
    """
    return _extractor.extract(message, entity_types)


def fill_slots(
    message: str,
    required_slots: Dict[str, EntityType],
    entity_types: Optional[List[EntityType]] = None
) -> SlotFillingResult:
    """Fill required slots from a message.

    Args:
        message: The user message.
        required_slots: Dict mapping slot names to required entity types.
        entity_types: Optional filter for entity types to extract.

    Returns:
        SlotFillingResult with filled and missing slots.
    """
    entities = extract_entities(message, entity_types)

    filled_slots = {}
    missing_slots = {}

    # Group entities by type
    entities_by_type: Dict[EntityType, List[ExtractedEntity]] = {}
    for entity in entities:
        if entity.entity_type not in entities_by_type:
            entities_by_type[entity.entity_type] = []
        entities_by_type[entity.entity_type].append(entity)

    # Try to fill each required slot
    for slot_name, slot_type in required_slots.items():
        candidates = entities_by_type.get(slot_type, [])
        if candidates:
            # Use the first (highest confidence) candidate
            filled_slots[slot_name] = candidates[0]
        else:
            missing_slots[slot_name] = slot_type

    return SlotFillingResult(
        required_slots=required_slots,
        filled_slots=filled_slots,
        missing_slots=missing_slots,
        is_complete=len(missing_slots) == 0,
    )


def get_missing_slots_prompt(result: SlotFillingResult) -> str:
    """Generate a friendly prompt asking for missing information.

    Args:
        result: The SlotFillingResult with missing slots.

    Returns:
        A natural language question asking for the missing info.
    """
    if result.is_complete:
        return ""

    missing = list(result.missing_slots.items())
    if not missing:
        return ""

    # Map entity types to friendly prompts
    prompts = {
        EntityType.FILE: "Which file would you like me to work with?",
        EntityType.FOLDER: "Which folder?",
        EntityType.DATE: "What date?",
        EntityType.TIME: "What time?",
        EntityType.PERSON: "Who?",
        EntityType.URL: "What's the URL?",
        EntityType.TASK: "What would you like me to do?",
        EntityType.TOPIC: "What topic?",
        EntityType.NUMBER: "How many?",
        EntityType.TOOL: "Which tool?",
        EntityType.REPOSITORY: "Which repository?",
        EntityType.VERSION: "Which version?",
    }

    if len(missing) == 1:
        slot_name, slot_type = missing[0]
        prompt = prompts.get(slot_type, f"What {slot_name}?")
        return prompt

    # Multiple missing - combine into one question
    parts = []
    for slot_name, slot_type in missing:
        prompt = prompts.get(slot_type, f"{slot_name}")
        parts.append(prompt)

    return "I need a bit more information: " + ", ".join(parts) + "?"