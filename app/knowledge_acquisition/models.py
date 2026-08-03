"""Data models for Knowledge Acquisition.

Defines the structured data types for the unified knowledge acquisition pipeline
including sources, jobs, results, and configuration.
"""

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


class AcquisitionSourceType(Enum):
    """Supported source types for knowledge acquisition."""
    # Local sources
    FILE = "file"
    DIRECTORY = "directory"
    CODE_REPOSITORY = "code_repository"
    DOCUMENTATION = "documentation"
    CONVERSATION_HISTORY = "conversation_history"
    LLM_RESPONSE = "llm_response"
    TOOL_OUTPUT = "tool_output"
    PROJECT_METADATA = "project_metadata"
    DEPENDENCY_LOCKFILE = "dependency_lockfile"

    # External sources
    WEB_DOCUMENTATION = "web_documentation"
    PACKAGE_DOCUMENTATION = "package_documentation"
    INTERNET_RESEARCH = "internet_research"
    STANDARDS_BODY = "standards_body"  # RFC, ISO, W3C, ECMA
    STACKOVERFLOW = "stackoverflow"
    GITHUB_REPOSITORY = "github_repository"
    VENDOR_DOCUMENTATION = "vendor_documentation"  # AWS, GCP, Azure, etc.

    # System sources
    SYSTEM_EVENT = "system_event"
    FILE_WATCH_EVENT = "file_watch_event"
    BACKGROUND_JOB = "background_job"


class AcquisitionStatus(Enum):
    """Status of an acquisition job."""
    PENDING = "pending"
    EXTRACTING = "extracting"
    VALIDATING = "validating"
    STORING = "storing"
    INDEXING = "indexing"
    COMPLETED = "completed"
    PARTIAL = "partial"  # Some items succeeded, some failed
    FAILED = "failed"
    SKIPPED = "skipped"  # Duplicate or low confidence


@dataclass
class AcquisitionSource:
    """Configuration for a knowledge acquisition source."""
    source_type: AcquisitionSourceType
    identifier: str  # File path, URL, package name, query, etc.
    name: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    priority: int = 0  # Higher = more important
    config: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["source_type"] = self.source_type.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AcquisitionSource":
        data = data.copy()
        if "source_type" in data and isinstance(data["source_type"], str):
            data["source_type"] = AcquisitionSourceType(data["source_type"])
        return cls(**data)


@dataclass
class AcquisitionJob:
    """A knowledge acquisition job."""
    id: str = field(default_factory=lambda: f"acq_{uuid.uuid4().hex[:12]}")
    source: AcquisitionSource = None
    status: AcquisitionStatus = AcquisitionStatus.PENDING
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    # Results
    extraction_result: Optional[Dict[str, Any]] = None
    validation_result: Optional[Dict[str, Any]] = None
    storage_result: Optional[Dict[str, Any]] = None
    indexing_result: Optional[Dict[str, Any]] = None

    # Statistics
    items_extracted: int = 0
    items_validated: int = 0
    items_stored: int = 0
    items_indexed: int = 0
    items_skipped: int = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["source"] = self.source.to_dict() if self.source else None
        data["status"] = self.status.value
        return data


@dataclass
class AcquisitionResult:
    """Result of a knowledge acquisition operation."""
    job_id: str
    success: bool
    items_acquired: List[Dict[str, Any]] = field(default_factory=list)
    items_failed: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    extraction_time: float = 0.0
    validation_time: float = 0.0
    storage_time: float = 0.0
    indexing_time: float = 0.0
    total_time: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def total_items(self) -> int:
        return len(self.items_acquired) + len(self.items_failed)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class KnowledgeAcquisitionConfig:
    """Configuration for the knowledge acquisition pipeline."""
    # Extraction settings
    extract_batch_size: int = 10
    extract_timeout_seconds: float = 30.0
    max_file_size_mb: int = 10

    # Validation settings
    min_confidence_threshold: float = 0.7
    high_confidence_threshold: float = 0.85
    duplicate_similarity_threshold: float = 0.85
    check_conflicts: bool = True
    conflict_similarity_threshold: float = 0.7

    # Storage settings
    storage_path: Optional[Path] = None
    auto_store_validated: bool = True
    store_pending_threshold: float = 0.7  # Confidence >= this gets auto-stored

    # Indexing settings
    auto_index: bool = True
    index_batch_size: int = 50

    # External acquisition settings
    enable_external: bool = True
    external_rate_limit: float = 1.0  # requests per second
    external_max_results: int = 10
    external_timeout_seconds: float = 30.0
    external_cache_ttl_hours: int = 24

    # Event/Automation settings
    auto_trigger_on_file_watch: bool = True
    auto_trigger_on_new_dependency: bool = True
    auto_trigger_on_project_change: bool = True
    scheduled_acquisition_interval_hours: int = 24

    # Observability
    enable_analytics: bool = True
    enable_health_checks: bool = True
    log_level: str = "INFO"

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        if self.storage_path:
            data["storage_path"] = str(self.storage_path)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeAcquisitionConfig":
        data = data.copy()
        if "storage_path" in data and isinstance(data["storage_path"], str):
            data["storage_path"] = Path(data["storage_path"])
        return cls(**data)