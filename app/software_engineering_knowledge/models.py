"""Data models for Software Engineering Knowledge.

Defines the structured knowledge object format, categories, and related enums
for software engineering knowledge that can be shared across all projects.
"""

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class EngineeringDomain(Enum):
    """Top-level engineering knowledge domains."""
    PROGRAMMING_LANGUAGES = "programming_languages"
    FRAMEWORKS = "frameworks"
    LIBRARIES = "libraries"
    SOFTWARE_ARCHITECTURE = "software_architecture"
    DESIGN_PATTERNS = "design_patterns"
    PROGRAMMING_PARADIGMS = "programming_paradigms"
    ALGORITHMS = "algorithms"
    DATA_STRUCTURES = "data_structures"
    APIS = "apis"
    DATABASES = "databases"
    NETWORKING = "networking"
    SECURITY = "security"
    AUTHENTICATION = "authentication"
    PERFORMANCE_OPTIMIZATION = "performance_optimization"
    DEBUGGING = "debugging"
    TESTING = "testing"
    GIT = "git"
    CI_CD = "ci_cd"
    BUILD_SYSTEMS = "build_systems"
    DEPENDENCY_MANAGEMENT = "dependency_management"
    DOCUMENTATION = "documentation"
    CODE_QUALITY = "code_quality"
    CODE_REVIEW = "code_review"
    REFACTORING = "refactoring"
    DEVOPS = "devops"
    CLOUD = "cloud"
    DESKTOP_DEVELOPMENT = "desktop_development"
    WEB_DEVELOPMENT = "web_development"
    AI_ENGINEERING = "ai_engineering"
    PROMPT_ENGINEERING = "prompt_engineering"
    TOOL_DEVELOPMENT = "tool_development"
    PROJECT_STRUCTURE = "project_structure"
    BUG_PATTERNS = "bug_patterns"
    ROOT_CAUSES = "root_causes"
    SOLUTIONS = "solutions"
    BEST_PRACTICES = "best_practices"
    ENGINEERING_LESSONS = "engineering_lessons"
    ORGANIZATION_STANDARDS = "organization_standards"
    UNKNOWN = "unknown"


class EngineeringKnowledgeType(Enum):
    """Types of engineering knowledge."""
    CONCEPT = "concept"                    # e.g., "What is a singleton pattern"
    DEFINITION = "definition"              # e.g., "Definition of SOLID principles"
    EXPLANATION = "explanation"            # e.g., "How dependency injection works"
    PROCEDURE = "procedure"                # Step-by-step guide
    ALGORITHM = "algorithm"                # Algorithm implementation/description
    BEST_PRACTICE = "best_practice"        # Recommended practice
    RECOMMENDATION = "recommendation"      # Specific recommendation
    WORKFLOW = "workflow"                  # Multi-step process
    TROUBLESHOOTING = "troubleshooting"    # Problem solving guide
    WARNING = "warning"                    # Pitfall to avoid
    REFERENCE = "reference"                # Reference material
    ARCHITECTURE = "architecture"          # Architectural pattern/decision
    CODE_PATTERN = "code_pattern"          # Reusable code pattern
    ANTI_PATTERN = "anti_pattern"          # Pattern to avoid
    DEBUGGING_STRATEGY = "debugging_strategy"  # Debugging approach
    TESTING_STRATEGY = "testing_strategy"  # Testing approach
    DECISION_RATIONALE = "decision_rationale"  # Why a decision was made
    LESSON_LEARNED = "lesson_learned"      # Lesson from experience
    EXAMPLE = "example"                    # Code example
    FACT = "fact"                          # Verifiable fact
    CUSTOM = "custom"                      # Custom knowledge type


class KnowledgeSource(Enum):
    """Source of the engineering knowledge."""
    PROJECT_CODE = "project_code"              # Extracted from project source code
    DOCUMENTATION = "documentation"            # Extracted from project docs (README, etc.)
    EXPERIENCE_MEMORY = "experience_memory"    # From ExperienceMemory entries
    ENGINEERING_LESSONS = "engineering_lessons"  # From EngineeringLessons storage
    REFLECTION = "reflection"                  # From self-reflection
    EXTERNAL_DOCS = "external_docs"            # Official documentation
    INTERNET_RESEARCH = "internet_research"    # Web research
    USER_INPUT = "user_input"                  # Directly taught by user
    LLM_TRAINING = "llm_training"              # From model training knowledge
    SYNTHESIZED = "synthesized"                # Derived from multiple sources
    UNKNOWN = "unknown"


class ValidationStatus(Enum):
    """Validation status of a knowledge item."""
    VALIDATED = "validated"          # Passed validation
    PENDING = "pending"              # Not yet validated
    CONFLICT = "conflict"            # Conflicts with other knowledge
    DUPLICATE = "duplicate"          # Duplicate of existing knowledge
    LOW_CONFIDENCE = "low_confidence"  # Below confidence threshold
    REJECTED = "rejected"            # Failed validation


@dataclass
class EngineeringKnowledgeItem:
    """A structured software engineering knowledge item.

    This is the core object stored in the Software Engineering Knowledge base.
    All extraction, import, and synthesis operations produce these items.
    """
    # Unique identifier
    id: str = field(default_factory=lambda: f"eng_{uuid.uuid4().hex[:12]}")

    # Core content
    title: str = ""
    summary: str = ""
    content: str = ""

    # Domain classification
    domain: EngineeringDomain = EngineeringDomain.UNKNOWN
    sub_category: str = ""  # Specific sub-category within domain

    # Knowledge type
    knowledge_type: EngineeringKnowledgeType = EngineeringKnowledgeType.CUSTOM

    # Source information
    source: KnowledgeSource = KnowledgeSource.UNKNOWN
    source_uri: str = ""  # File path, URL, conversation ID, etc.
    source_metadata: Dict[str, Any] = field(default_factory=dict)

    # Classification & metadata
    tags: List[str] = field(default_factory=list)
    language: Optional[str] = None  # e.g., "python", "javascript", "agnostic"
    frameworks: List[str] = field(default_factory=list)  # e.g., ["django", "react"]

    # Confidence & quality
    confidence: float = 0.5  # Initial confidence (0-1)
    validation_status: ValidationStatus = ValidationStatus.PENDING
    validation_notes: str = ""

    # Version tracking
    version: int = 1
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    created_by: str = "system"  # "system", "extraction", "user", "synthesis"

    # Relationships
    related_items: List[str] = field(default_factory=list)  # Other engineering knowledge IDs
    prerequisites: List[str] = field(default_factory=list)  # Required knowledge IDs
    supersedes: List[str] = field(default_factory=list)  # IDs this item replaces

    # Usage tracking
    access_count: int = 0
    success_count: int = 0  # Times this knowledge led to successful outcome
    last_accessed: Optional[str] = None

    # Additional structured data
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        data = asdict(self)
        data["domain"] = self.domain.value
        data["knowledge_type"] = self.knowledge_type.value
        data["source"] = self.source.value
        data["validation_status"] = self.validation_status.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EngineeringKnowledgeItem":
        """Create from dictionary."""
        data = data.copy()
        if "domain" in data and isinstance(data["domain"], str):
            data["domain"] = EngineeringDomain(data["domain"])
        if "knowledge_type" in data and isinstance(data["knowledge_type"], str):
            data["knowledge_type"] = EngineeringKnowledgeType(data["knowledge_type"])
        if "source" in data and isinstance(data["source"], str):
            data["source"] = KnowledgeSource(data["source"])
        if "validation_status" in data and isinstance(data["validation_status"], str):
            data["validation_status"] = ValidationStatus(data["validation_status"])
        return cls(**data)


@dataclass
class EngineeringCategory:
    """A category in the engineering knowledge domain structure."""
    name: str
    domain: EngineeringDomain
    description: str = ""
    priority: int = 50  # 0-100, higher = more important
    sub_categories: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    is_active: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "domain": self.domain.value,
            "description": self.description,
            "priority": self.priority,
            "sub_categories": self.sub_categories,
            "tags": self.tags,
            "is_active": self.is_active,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EngineeringCategory":
        data = data.copy()
        if "domain" in data and isinstance(data["domain"], str):
            data["domain"] = EngineeringDomain(data["domain"])
        return cls(**data)


@dataclass
class ExtractionResult:
    """Result of an engineering knowledge extraction operation."""
    success: bool
    items: List[EngineeringKnowledgeItem] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    source: str = ""
    source_type: KnowledgeSource = KnowledgeSource.UNKNOWN
    extraction_time: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "items": [item.to_dict() for item in self.items],
            "errors": self.errors,
            "source": self.source,
            "source_type": self.source_type.value,
            "extraction_time": self.extraction_time,
            "metadata": self.metadata,
        }


@dataclass
class ValidationResult:
    """Result of validating an engineering knowledge item."""
    is_valid: bool
    confidence: float
    validation_status: ValidationStatus
    conflicts: List[str] = field(default_factory=list)  # IDs of conflicting items
    duplicates: List[str] = field(default_factory=list)  # IDs of duplicate items
    notes: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EngineeringExpertise:
    """Higher-level engineering expertise built from accumulated knowledge."""
    domain: EngineeringDomain
    id: str = field(default_factory=lambda: f"exp_{uuid.uuid4().hex[:12]}")
    title: str = ""
    description: str = ""
    # The knowledge items that form this expertise
    knowledge_item_ids: List[str] = field(default_factory=list)
    # Confidence in this expertise
    confidence: float = 0.5
    # Usage statistics
    usage_count: int = 0
    success_rate: float = 0.0
    # When this expertise was built/refined
    built_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["domain"] = self.domain.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EngineeringExpertise":
        data = data.copy()
        if "domain" in data and isinstance(data["domain"], str):
            data["domain"] = EngineeringDomain(data["domain"])
        return cls(**data)