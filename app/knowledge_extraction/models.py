"""Data models for Knowledge Extraction.

Defines the structured knowledge object format and related enums/errors.
"""

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class SourceType(Enum):
    """Supported source types for knowledge extraction."""
    LLM_RESPONSE = "llm_response"
    MARKDOWN = "markdown"
    PDF = "pdf"
    SOURCE_CODE = "source_code"
    USER_INPUT = "user_input"
    TOOL_OUTPUT = "tool_output"
    LOG = "log"
    API_RESPONSE = "api_response"
    DOCUMENTATION = "documentation"
    UNKNOWN = "unknown"


class KnowledgeCategory(Enum):
    """Categories for classified knowledge."""
    FACT = "fact"
    EXPLANATION = "explanation"
    PROCEDURE = "procedure"
    ALGORITHM = "algorithm"
    BEST_PRACTICE = "best_practice"
    RECOMMENDATION = "recommendation"
    WORKFLOW = "workflow"
    TROUBLESHOOTING = "troubleshooting"
    CONCEPT = "concept"
    DEFINITION = "definition"
    EXAMPLE = "example"
    WARNING = "warning"
    REFERENCE = "reference"
    ARCHITECTURE = "architecture"
    OTHER = "other"


@dataclass
class KnowledgeObject:
    """A structured knowledge item extracted from a source.

    This is the core output of the knowledge extraction pipeline.
    All extractors produce KnowledgeObjects that follow this schema.
    """
    # Unique identifier
    id: str = field(default_factory=lambda: f"kobj_{uuid.uuid4().hex[:12]}")

    # Core content
    title: str = ""
    summary: str = ""
    content: str = ""

    # Source information
    source: str = ""                    # Original source (file path, URL, conversation ID, etc.)
    source_type: SourceType = SourceType.UNKNOWN
    author: Optional[str] = None        # Author if available

    # Classification
    category: KnowledgeCategory = KnowledgeCategory.OTHER
    tags: List[str] = field(default_factory=list)

    # Extraction metadata
    extracted_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    confidence: float = 0.5             # Initial extraction confidence estimate (0-1)
    language: Optional[str] = None      # Language of content if applicable

    # Relationships
    related_entities: List[str] = field(default_factory=list)  # Entity names/IDs
    related_knowledge_ids: List[str] = field(default_factory=list)  # Links to other knowledge objects

    # Additional structured data
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        data = asdict(self)
        data["source_type"] = self.source_type.value
        data["category"] = self.category.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeObject":
        """Create from dictionary."""
        data = data.copy()
        if "source_type" in data and isinstance(data["source_type"], str):
            data["source_type"] = SourceType(data["source_type"])
        if "category" in data and isinstance(data["category"], str):
            data["category"] = KnowledgeCategory(data["category"])
        return cls(**data)

    def __repr__(self) -> str:
        return f"KnowledgeObject(id={self.id}, title={self.title[:40]}, category={self.category.value})"


@dataclass
class ExtractionError(Exception):
    """Error during knowledge extraction.

    Contains detailed information about what went wrong to aid debugging
    and allow graceful handling by the pipeline.
    """
    message: str
    source_type: SourceType = SourceType.UNKNOWN
    source: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.source_type.value}] {self.message}"


@dataclass
class KnowledgeExtractionResult:
    """Result of a knowledge extraction operation.

    Contains the extracted knowledge objects or error information.
    """
    success: bool
    knowledge_objects: List[KnowledgeObject] = field(default_factory=list)
    error: Optional[ExtractionError] = None
    source: str = ""
    source_type: SourceType = SourceType.UNKNOWN
    extraction_time: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "success": self.success,
            "knowledge_objects": [obj.to_dict() for obj in self.knowledge_objects],
            "error": {
                "message": self.error.message,
                "source_type": self.error.source_type.value,
                "source": self.error.source,
                "details": self.error.details,
            } if self.error else None,
            "source": self.source,
            "source_type": self.source_type.value,
            "extraction_time": self.extraction_time,
            "metadata": self.metadata,
        }

    @staticmethod
    def success_result(
        knowledge_objects: List[KnowledgeObject],
        source: str,
        source_type: SourceType,
        extraction_time: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "KnowledgeExtractionResult":
        """Create a successful extraction result."""
        return KnowledgeExtractionResult(
            success=True,
            knowledge_objects=knowledge_objects,
            source=source,
            source_type=source_type,
            extraction_time=extraction_time,
            metadata=metadata or {},
        )

    @staticmethod
    def error_result(
        error: ExtractionError,
        source: str,
        source_type: SourceType,
        extraction_time: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "KnowledgeExtractionResult":
        """Create an error extraction result."""
        return KnowledgeExtractionResult(
            success=False,
            error=error,
            source=source,
            source_type=source_type,
            extraction_time=extraction_time,
            metadata=metadata or {},
        )