"""Capability Registry for tracking project capabilities.

This module defines the registry of all capabilities that Freya should have,
along with their current status and metadata.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, List, Any
import json
from pathlib import Path


class CapabilityStatus(Enum):
    """Status of a capability."""
    NOT_IMPLEMENTED = "not_implemented"
    PARTIALLY_IMPLEMENTED = "partially_implemented"
    FULLY_IMPLEMENTED = "fully_implemented"
    DEPRECATED = "deprecated"
    REMOVED = "removed"


class CapabilityPriority(Enum):
    """Priority level for a capability."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CapabilityCategory(Enum):
    """Category of a capability."""
    CORE = "core"
    AGENT = "agent"
    INTELLIGENCE = "intelligence"
    EDITING = "editing"
    VERIFICATION = "verification"
    MEMORY = "memory"
    RAG = "rag"
    SEMANTIC = "semantic"
    VECTOR_DB = "vector_db"
    TOOLS = "tools"
    UI = "ui"
    MONITORING = "monitoring"
    DIAGNOSTICS = "diagnostics"
    PLANNING = "planning"
    REVIEW = "review"
    RISK = "risk"
    CONFIDENCE = "confidence"
    BENCHMARKING = "benchmarking"
    DOCUMENTATION = "documentation"
    GIT = "git"
    METRICS = "metrics"


@dataclass
class Capability:
    """Represents a single capability in the Freya project."""
    id: str
    name: str
    description: str
    category: CapabilityCategory
    status: CapabilityStatus
    priority: CapabilityPriority = CapabilityPriority.MEDIUM
    module: Optional[str] = None
    file_path: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)
    tests: List[str] = field(default_factory=list)
    documentation: Optional[str] = None
    notes: str = ""
    version_added: Optional[str] = None
    last_updated: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert capability to dictionary for serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category.value,
            "status": self.status.value,
            "priority": self.priority.value,
            "module": self.module,
            "file_path": self.file_path,
            "dependencies": self.dependencies,
            "tests": self.tests,
            "documentation": self.documentation,
            "notes": self.notes,
            "version_added": self.version_added,
            "last_updated": self.last_updated,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Capability":
        """Create capability from dictionary."""
        # Map string priority to enum
        priority_map = {
            "critical": CapabilityPriority.CRITICAL,
            "high": CapabilityPriority.HIGH,
            "medium": CapabilityPriority.MEDIUM,
            "low": CapabilityPriority.LOW,
        }
        priority = priority_map.get(data.get("priority", "medium"), CapabilityPriority.MEDIUM)

        return cls(
            id=data["id"],
            name=data["name"],
            description=data["description"],
            category=CapabilityCategory(data["category"]),
            status=CapabilityStatus(data["status"]),
            priority=priority,
            module=data.get("module"),
            file_path=data.get("file_path"),
            dependencies=data.get("dependencies", []),
            tests=data.get("tests", []),
            documentation=data.get("documentation"),
            notes=data.get("notes", ""),
            version_added=data.get("version_added"),
            last_updated=data.get("last_updated"),
        )


class CapabilityRegistry:
    """Registry of all capabilities in the Freya project.

    This class maintains a comprehensive list of all capabilities that Freya
    should have, along with their current implementation status.
    """

    def __init__(self):
        self._capabilities: Dict[str, Capability] = {}
        self._initialized = False

    def initialize(self) -> None:
        """Initialize the registry with all known capabilities."""
        if self._initialized:
            return

        # Register all capabilities
        self._register_core_capabilities()
        self._register_agent_capabilities()
        self._register_intelligence_capabilities()
        self._register_editing_capabilities()
        self._register_verification_capabilities()
        self._register_memory_capabilities()
        self._register_rag_capabilities()
        self._register_semantic_capabilities()
        self._register_vector_db_capabilities()
        self._register_tools_capabilities()
        self._register_ui_capabilities()
        self._register_foundation_capabilities()

        self._initialized = True

    def _register_core_capabilities(self) -> None:
        """Register core system capabilities."""
        core_caps = [
            Capability(
                id="core.llm",
                name="LLM Integration",
                description="Integration with Large Language Models for code generation and reasoning.",
                category=CapabilityCategory.CORE,
                status=CapabilityStatus.PARTIALLY_IMPLEMENTED,
                priority=CapabilityPriority.CRITICAL,
                module="app.core.llm",
                file_path="app/core/llm.py",
                notes="Currently only supports Ollama. Needs multi-provider support (Claude, GPT, etc.).",
            ),
            Capability(
                id="core.config",
                name="Configuration Management",
                description="Environment-based configuration for the agent.",
                category=CapabilityCategory.CORE,
                status=CapabilityStatus.FULLY_IMPLEMENTED,
                priority=CapabilityPriority.HIGH,
                module="app.core.config",
                file_path="app/core/config.py",
            ),
            Capability(
                id="core.logger",
                name="Logging",
                description="File and console logging with timestamps.",
                category=CapabilityCategory.CORE,
                status=CapabilityStatus.FULLY_IMPLEMENTED,
                priority=CapabilityPriority.MEDIUM,
                module="app.core.logger",
                file_path="app/core/logger.py",
            ),
            Capability(
                id="core.events",
                name="Event System",
                description="Pub/sub event bus for inter-component communication.",
                category=CapabilityCategory.CORE,
                status=CapabilityStatus.FULLY_IMPLEMENTED,
                priority=CapabilityPriority.MEDIUM,
                module="app.core.events",
                file_path="app/core/events.py",
            ),
            Capability(
                id="core.tool_manager",
                name="Tool Manager",
                description="Workspace-safe tool execution with comprehensive tool set.",
                category=CapabilityCategory.CORE,
                status=CapabilityStatus.FULLY_IMPLEMENTED,
                priority=CapabilityPriority.CRITICAL,
                module="app.core.tool_manager",
                file_path="app/core/tool_manager.py",
            ),
            Capability(
                id="core.project_index",
                name="Project Index",
                description="Scans and indexes all project files.",
                category=CapabilityCategory.CORE,
                status=CapabilityStatus.FULLY_IMPLEMENTED,
                priority=CapabilityPriority.HIGH,
                module="app.core.project_index",
                file_path="app/core/project_index.py",
            ),
            Capability(
                id="core.symbol_index",
                name="Symbol Index",
                description="AST-based indexing of classes, functions, and symbols.",
                category=CapabilityCategory.CORE,
                status=CapabilityStatus.FULLY_IMPLEMENTED,
                priority=CapabilityPriority.HIGH,
                module="app.core.symbol_index",
                file_path="app/core/symbol_index.py",
            ),
        ]
        for cap in core_caps:
            self._capabilities[cap.id] = cap

    def _register_agent_capabilities(self) -> None:
        """Register agent capabilities."""
        agent_caps = [
            Capability(
                id="agent.freya_agent",
                name="FreyaAgent",
                description="Main agent class that orchestrates all subsystems.",
                category=CapabilityCategory.AGENT,
                status=CapabilityStatus.FULLY_IMPLEMENTED,
                priority=CapabilityPriority.CRITICAL,
                module="app.agent.core_agent",
                file_path="app/agent/core_agent.py",
                notes="Has encoding issues in docstrings (fixed in Phase 1).",
            ),
            Capability(
                id="agent.executor",
                name="Executor",
                description="Executes actions selected by the LLM with permission prompts.",
                category=CapabilityCategory.AGENT,
                status=CapabilityStatus.PARTIALLY_IMPLEMENTED,
                priority=CapabilityPriority.HIGH,
                module="app.agent.executor",
                file_path="app/agent/executor.py",
                notes="No timeout handling for LLM calls. Non-deterministic action selection.",
            ),
            Capability(
                id="agent.planner",
                name="Planner",
                description="Creates JSON plans from task descriptions.",
                category=CapabilityCategory.AGENT,
                status=CapabilityStatus.PARTIALLY_IMPLEMENTED,
                priority=CapabilityPriority.HIGH,
                module="app.agent.planner",
                file_path="app/agent/planner.py",
                notes="Minimal plan validation. No structured schema enforcement.",
            ),
            Capability(
                id="agent.tool_caller",
                name="ToolCaller",
                description="Rule-based tool selection with LLM fallback.",
                category=CapabilityCategory.AGENT,
                status=CapabilityStatus.PARTIALLY_IMPLEMENTED,
                priority=CapabilityPriority.MEDIUM,
                module="app.agent.tool_caller",
                file_path="app/agent/tool_caller.py",
                notes="Very limited rule set (only 4 patterns).",
            ),
            Capability(
                id="agent.brain",
                name="AgentBrain",
                description="Basic project analysis and task solving.",
                category=CapabilityCategory.AGENT,
                status=CapabilityStatus.PARTIALLY_IMPLEMENTED,
                priority=CapabilityPriority.LOW,
                module="app.agent.brain",
                file_path="app/agent/brain.py",
                notes="Not integrated into main FreyaAgent. Very limited functionality.",
            ),
            Capability(
                id="agent.conversation_state",
                name="Conversation State",
                description="Multi-turn conversation state with persistence.",
                category=CapabilityCategory.AGENT,
                status=CapabilityStatus.FULLY_IMPLEMENTED,
                priority=CapabilityPriority.CRITICAL,
                module="app.brain.state",
                file_path="app/brain/state.py",
                version_added="0.3.0",
            ),
        ]
        for cap in agent_caps:
            self._capabilities[cap.id] = cap

    def _register_intelligence_capabilities(self) -> None:
        """Register intelligence capabilities."""
        intel_caps = [
            Capability(
                id="intelligence.file_locator",
                name="File Locator",
                description="Finds relevant files based on symbol and filename matching.",
                category=CapabilityCategory.INTELLIGENCE,
                status=CapabilityStatus.FULLY_IMPLEMENTED,
                priority=CapabilityPriority.HIGH,
                module="app.intelligence.file_locator",
                file_path="app/intelligence/file_locator.py",
            ),
            Capability(
                id="intelligence.context_builder",
                name="Context Builder",
                description="Builds context for LLM prompts from matched files.",
                category=CapabilityCategory.INTELLIGENCE,
                status=CapabilityStatus.FULLY_IMPLEMENTED,
                priority=CapabilityPriority.HIGH,
                module="app.intelligence.context_builder",
                file_path="app/intelligence/context_builder.py",
            ),
            Capability(
                id="intelligence.dependency_graph",
                name="Dependency Graph",
                description="Builds import graph for context expansion.",
                category=CapabilityCategory.INTELLIGENCE,
                status=CapabilityStatus.FULLY_IMPLEMENTED,
                priority=CapabilityPriority.MEDIUM,
                module="app.intelligence.dependency_graph",
                file_path="app/intelligence/dependency_graph.py",
            ),
            Capability(
                id="intelligence.lexical_search",
                name="Lexical Search",
                description="Keyword-based search with TF-like scoring.",
                category=CapabilityCategory.INTELLIGENCE,
                status=CapabilityStatus.FULLY_IMPLEMENTED,
                priority=CapabilityPriority.HIGH,
                module="app.intelligence.lexical_search",
                file_path="app/intelligence/lexical_search.py",
            ),
        ]
        for cap in intel_caps:
            self._capabilities[cap.id] = cap

    def _register_editing_capabilities(self) -> None:
        """Register editing capabilities."""
        editing_caps = [
            Capability(
                id="editing.patch_engine",
                name="Patch Engine",
                description="Validates and applies patches with rollback capability.",
                category=CapabilityCategory.EDITING,
                status=CapabilityStatus.FULLY_IMPLEMENTED,
                priority=CapabilityPriority.CRITICAL,
                module="app.editing.patch_engine",
                file_path="app/editing/patch_engine.py",
                notes="Only supports create and replace actions. No delete or line-based editing.",
            ),
            Capability(
                id="editing.patch_generator",
                name="Patch Generator",
                description="LLM-powered patch proposal generation.",
                category=CapabilityCategory.EDITING,
                status=CapabilityStatus.PARTIALLY_IMPLEMENTED,
                priority=CapabilityPriority.HIGH,
                module="app.editing.patch_generator",
                file_path="app/editing/patch_generator.py",
                notes="No validation that old_text exists in files.",
            ),
            Capability(
                id="editing.ast_refactor",
                name="AST-based Refactoring",
                description="Safe code refactoring using Abstract Syntax Trees.",
                category=CapabilityCategory.EDITING,
                status=CapabilityStatus.NOT_IMPLEMENTED,
                priority=CapabilityPriority.MEDIUM,
                notes="Planned for Phase 2. Will enable rename, extract function, etc.",
            ),
        ]
        for cap in editing_caps:
            self._capabilities[cap.id] = cap

    def _register_verification_capabilities(self) -> None:
        """Register verification capabilities."""
        verify_caps = [
            Capability(
                id="verification.runner",
                name="Verification Runner",
                description="Runs pytest and py_compile linting.",
                category=CapabilityCategory.VERIFICATION,
                status=CapabilityStatus.FULLY_IMPLEMENTED,
                priority=CapabilityPriority.HIGH,
                module="app.verification.runner",
                file_path="app/verification/runner.py",
                notes="Assumes pytest is always available. No test filtering.",
            ),
            Capability(
                id="verification.repair_loop",
                name="Repair Loop",
                description="Iterative fix-and-verify loop.",
                category=CapabilityCategory.VERIFICATION,
                status=CapabilityStatus.FULLY_IMPLEMENTED,
                priority=CapabilityPriority.MEDIUM,
                module="app.verification.repair_loop",
                file_path="app/verification/repair_loop.py",
            ),
        ]
        for cap in verify_caps:
            self._capabilities[cap.id] = cap

    def _register_memory_capabilities(self) -> None:
        """Register memory capabilities."""
        memory_caps = [
            Capability(
                id="memory.project_memory",
                name="Project Memory",
                description="Persistent project memory with semantic similarity search.",
                category=CapabilityCategory.MEMORY,
                status=CapabilityStatus.PARTIALLY_IMPLEMENTED,
                priority=CapabilityPriority.CRITICAL,
                module="app.memory.project_memory",
                file_path="app/memory/project_memory.py",
                notes="Duplicate class definition issue exists in the file. Needs consolidation with project_manager.py.",
            ),
            Capability(
                id="memory.project_manager",
                name="Project Manager",
                description="Small, local, durable memory for project sessions.",
                category=CapabilityCategory.MEMORY,
                status=CapabilityStatus.PARTIALLY_IMPLEMENTED,
                priority=CapabilityPriority.MEDIUM,
                module="app.memory.project_manager",
                file_path="app/memory/project_manager.py",
                notes="Has typo (edges -> edits) which has been fixed. Simpler implementation compared to project_memory.py.",
            ),
            Capability(
                id="memory.experience",
                name="Experience Memory",
                description="Read-only storage for lessons learned and best practices.",
                category=CapabilityCategory.MEMORY,
                status=CapabilityStatus.NOT_IMPLEMENTED,
                priority=CapabilityPriority.MEDIUM,
                notes="Foundation system to be implemented in Phase 1.",
            ),
            Capability(
                id="memory.engineering_lessons",
                name="Engineering Lesson Storage",
                description="Storage for engineering lessons, patterns, and anti-patterns.",
                category=CapabilityCategory.MEMORY,
                status=CapabilityStatus.NOT_IMPLEMENTED,
                priority=CapabilityPriority.MEDIUM,
                notes="Foundation system to be implemented in Phase 1.",
            ),
        ]
        for cap in memory_caps:
            self._capabilities[cap.id] = cap

    def _register_rag_capabilities(self) -> None:
        """Register RAG capabilities."""
        rag_caps = [
            Capability(
                id="rag.simple_retriever",
                name="Simple Retriever",
                description="Keyword-based retrieval using lexical search.",
                category=CapabilityCategory.RAG,
                status=CapabilityStatus.FULLY_IMPLEMENTED,
                priority=CapabilityPriority.MEDIUM,
                module="app.rag",
                file_path="app/rag/__init__.py",
            ),
        ]
        for cap in rag_caps:
            self._capabilities[cap.id] = cap

    def _register_semantic_capabilities(self) -> None:
        """Register semantic capabilities."""
        semantic_caps = [
            Capability(
                id="semantic.search",
                name="Semantic Search",
                description="Sentence transformer-based semantic similarity search.",
                category=CapabilityCategory.SEMANTIC,
                status=CapabilityStatus.FULLY_IMPLEMENTED,
                priority=CapabilityPriority.MEDIUM,
                module="app.semantic.search",
                file_path="app/semantic/search.py",
                notes="Hard dependency on sentence-transformers. Large model may be slow.",
            ),
        ]
        for cap in semantic_caps:
            self._capabilities[cap.id] = cap

    def _register_vector_db_capabilities(self) -> None:
        """Register vector DB capabilities."""
        vector_caps = [
            Capability(
                id="vector_db.vector_db",
                name="Vector Database",
                description="FAISS-based persistent vector database with adaptive indexing.",
                category=CapabilityCategory.VECTOR_DB,
                status=CapabilityStatus.FULLY_IMPLEMENTED,
                priority=CapabilityPriority.HIGH,
                module="app.vector_db",
                file_path="app/vector_db/__init__.py",
                notes="Comprehensive implementation with lazy deletion, benchmarking, and adaptive index selection.",
            ),
        ]
        for cap in vector_caps:
            self._capabilities[cap.id] = cap

    def _register_tools_capabilities(self) -> None:
        """Register tools capabilities."""
        tools_caps = [
            Capability(
                id="tools.file_tools",
                name="File Tools",
                description="File read/write/list operations.",
                category=CapabilityCategory.TOOLS,
                status=CapabilityStatus.FULLY_IMPLEMENTED,
                priority=CapabilityPriority.MEDIUM,
                module="app.core.tool_manager",
                file_path="app/core/tool_manager.py",
                notes="Duplicate implementations exist in app/tools/file_tools.py. those are redundant.",
            ),
            Capability(
                id="tools.edit_tools",
                name="Edit Tools",
                description="Text replacement in files.",
                category=CapabilityCategory.TOOLS,
                status=CapabilityStatus.FULLY_IMPLEMENTED,
                priority=CapabilityPriority.MEDIUM,
                module="app.core.tool_manager",
                file_path="app/core/tool_manager.py",
                notes="Duplicate implementation exists in app/tools/edit_tools.py.",
            ),
            Capability(
                id="tools.format_tools",
                name="Format Tools",
                description="Black code formatting.",
                category=CapabilityCategory.TOOLS,
                status=CapabilityStatus.FULLY_IMPLEMENTED,
                priority=CapabilityPriority.LOW,
                module="app.tools.format_tools",
                file_path="app/tools/format_tools.py",
            ),
            Capability(
                id="tools.git_tools",
                name="Git Tools",
                description="Complete git operations (status, diff, log, add, commit, push, pull, checkout).",
                category=CapabilityCategory.TOOLS,
                status=CapabilityStatus.FULLY_IMPLEMENTED,
                priority=CapabilityPriority.MEDIUM,
                module="app.tools.git_tools",
                file_path="app/tools/git_tools.py",
                notes="No git authentication handling.",
            ),
            Capability(
                id="tools.http_tools",
                name="HTTP Tools",
                description="All HTTP methods (GET, POST, PUT, DELETE, PATCH, HEAD) and generic request.",
                category=CapabilityCategory.TOOLS,
                status=CapabilityStatus.FULLY_IMPLEMENTED,
                priority=CapabilityPriority.MEDIUM,
                module="app.tools.http_tools",
                file_path="app/tools/http_tools.py",
                notes="No retries for transient failures. No rate limiting.",
            ),
        ]
        for cap in tools_caps:
            self._capabilities[cap.id] = cap

    def _register_ui_capabilities(self) -> None:
        """Register UI capabilities."""
        ui_caps = [
            Capability(
                id="ui.permission_menu",
                name="Permission Menu",
                description="Interactive permission prompts using prompt_toolkit.",
                category=CapabilityCategory.UI,
                status=CapabilityStatus.FULLY_IMPLEMENTED,
                priority=CapabilityPriority.MEDIUM,
                module="app.ui.permission_menu",
                file_path="app/ui/permission_menu.py",
                notes="Hardcoded dark theme colors. No accessibility support.",
            ),
        ]
        for cap in ui_caps:
            self._capabilities[cap.id] = cap

    def _register_foundation_capabilities(self) -> None:
        """Register foundation capabilities for autonomous evolution."""
        foundation_caps = [
            Capability(
                id="foundation.capability_audit",
                name="Capability Audit System",
                description="Automated capability auditing and reporting.",
                category=CapabilityCategory.MONITORING,
                status=CapabilityStatus.NOT_IMPLEMENTED,
                priority=CapabilityPriority.CRITICAL,
                notes="Phase 1 foundation system. Being implemented now.",
            ),
            Capability(
                id="foundation.project_health_dashboard",
                name="Project Health Dashboard",
                description="Real-time health metrics for the project.",
                category=CapabilityCategory.MONITORING,
                status=CapabilityStatus.NOT_IMPLEMENTED,
                priority=CapabilityPriority.CRITICAL,
                notes="Phase 1 foundation system.",
            ),
            Capability(
                id="foundation.diagnostics",
                name="Diagnostics System",
                description="Identifies and reports issues in the codebase.",
                category=CapabilityCategory.DIAGNOSTICS,
                status=CapabilityStatus.NOT_IMPLEMENTED,
                priority=CapabilityPriority.CRITICAL,
                notes="Phase 1 foundation system.",
            ),
            Capability(
                id="foundation.system_monitoring",
                name="System Monitoring",
                description="Tracks runtime metrics, resource usage, and performance.",
                category=CapabilityCategory.MONITORING,
                status=CapabilityStatus.NOT_IMPLEMENTED,
                priority=CapabilityPriority.CRITICAL,
                notes="Phase 1 foundation system.",
            ),
            Capability(
                id="foundation.planner",
                name="Planner System",
                description="Enhanced planning with structured validation and multi-step support.",
                category=CapabilityCategory.PLANNING,
                status=CapabilityStatus.NOT_IMPLEMENTED,
                priority=CapabilityPriority.CRITICAL,
                notes="Phase 1 foundation system.",
            ),
            Capability(
                id="foundation.reviewer",
                name="Reviewer System",
                description="Analyzes code changes and provides feedback.",
                category=CapabilityCategory.REVIEW,
                status=CapabilityStatus.NOT_IMPLEMENTED,
                priority=CapabilityPriority.CRITICAL,
                notes="Phase 1 foundation system.",
            ),
            Capability(
                id="foundation.risk_assessment",
                name="Risk Assessment System",
                description="Evaluates potential risks of code changes and decisions.",
                category=CapabilityCategory.RISK,
                status=CapabilityStatus.NOT_IMPLEMENTED,
                priority=CapabilityPriority.CRITICAL,
                notes="Phase 1 foundation system.",
            ),
            Capability(
                id="foundation.confidence_scoring",
                name="Confidence Scoring System",
                description="Evaluates certainty of agent decisions and recommendations.",
                category=CapabilityCategory.CONFIDENCE,
                status=CapabilityStatus.NOT_IMPLEMENTED,
                priority=CapabilityPriority.CRITICAL,
                notes="Phase 1 foundation system.",
            ),
            Capability(
                id="foundation.improvement_backlog",
                name="Improvement Backlog",
                description="Prioritized backlog for tracking improvements and technical debt.",
                category=CapabilityCategory.MONITORING,
                status=CapabilityStatus.NOT_IMPLEMENTED,
                priority=CapabilityPriority.CRITICAL,
                notes="Phase 1 foundation system.",
            ),
            Capability(
                id="foundation.benchmarking",
                name="Benchmarking Framework",
                description="Framework for benchmarking agent performance.",
                category=CapabilityCategory.BENCHMARKING,
                status=CapabilityStatus.NOT_IMPLEMENTED,
                priority=CapabilityPriority.CRITICAL,
                notes="Phase 1 foundation system.",
            ),
            Capability(
                id="foundation.documentation_automation",
                name="Documentation Automation",
                description="Automatic generation and updating of documentation.",
                category=CapabilityCategory.DOCUMENTATION,
                status=CapabilityStatus.NOT_IMPLEMENTED,
                priority=CapabilityPriority.CRITICAL,
                notes="Phase 1 foundation system.",
            ),
            Capability(
                id="foundation.git_automation",
                name="Git Automation",
                description="Enhanced git automation with semantic commits and change tracking.",
                category=CapabilityCategory.GIT,
                status=CapabilityStatus.NOT_IMPLEMENTED,
                priority=CapabilityPriority.CRITICAL,
                notes="Phase 1 foundation system.",
            ),
            Capability(
                id="foundation.experience_memory",
                name="Experience Memory",
                description="Read-only storage for lessons learned and historical context.",
                category=CapabilityCategory.MEMORY,
                status=CapabilityStatus.NOT_IMPLEMENTED,
                priority=CapabilityPriority.CRITICAL,
                notes="Phase 1 foundation system.",
            ),
            Capability(
                id="foundation.engineering_lessons",
                name="Engineering Lesson Storage",
                description="Storage for engineering lessons, patterns, and architectural decisions.",
                category=CapabilityCategory.MEMORY,
                status=CapabilityStatus.NOT_IMPLEMENTED,
                priority=CapabilityPriority.CRITICAL,
                notes="Phase 1 foundation system.",
            ),
            Capability(
                id="foundation.project_metrics",
                name="Project Metrics Collection",
                description="Comprehensive metrics collection for code quality, test coverage, etc.",
                category=CapabilityCategory.METRICS,
                status=CapabilityStatus.NOT_IMPLEMENTED,
                priority=CapabilityPriority.CRITICAL,
                notes="Phase 1 foundation system.",
            ),
        ]
        for cap in foundation_caps:
            self._capabilities[cap.id] = cap

    def get_capability(self, capability_id: str) -> Optional[Capability]:
        """Get a capability by its ID."""
        self.initialize()
        return self._capabilities.get(capability_id)

    def get_all_capabilities(self) -> List[Capability]:
        """Get all registered capabilities."""
        self.initialize()
        return list(self._capabilities.values())

    def get_capabilities_by_status(self, status: CapabilityStatus) -> List[Capability]:
        """Get all capabilities with a specific status."""
        self.initialize()
        return [cap for cap in self._capabilities.values() if cap.status == status]

    def get_capabilities_by_category(self, category: CapabilityCategory) -> List[Capability]:
        """Get all capabilities in a specific category."""
        self.initialize()
        return [cap for cap in self._capabilities.values() if cap.category == category]

    def get_capabilities_by_priority(self, priority: CapabilityPriority) -> List[Capability]:
        """Get all capabilities with a specific priority."""
        self.initialize()
        return [cap for cap in self._capabilities.values() if cap.priority == priority]

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of all capabilities by status and category."""
        self.initialize()

        by_status = {}
        by_category = {}
        by_priority = {}

        for cap in self._capabilities.values():
            # By status
            status_key = cap.status.value
            by_status[status_key] = by_status.get(status_key, 0) + 1

            # By category
            category_key = cap.category.value
            by_category[category_key] = by_category.get(category_key, 0) + 1

            # By priority
            priority_key = cap.priority.value
            by_priority[priority_key] = by_priority.get(priority_key, 0) + 1

        return {
            "total": len(self._capabilities),
            "by_status": by_status,
            "by_category": by_category,
            "by_priority": by_priority,
        }

    def to_dict(self) -> Dict[str, List[Dict[str, Any]]]:
        """Export all capabilities as a dictionary."""
        self.initialize()
        return {
            "capabilities": [cap.to_dict() for cap in self._capabilities.values()],
            "summary": self.get_summary(),
        }

    def save(self, path: str) -> None:
        """Save the registry to a JSON file."""
        path_obj = Path(path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        with open(path_obj, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    def load(self, path: str) -> None:
        """Load the registry from a JSON file."""
        path_obj = Path(path)
        if not path_obj.exists():
            raise FileNotFoundError(f"Capability registry file not found: {path}")

        with open(path_obj, "r", encoding="utf-8") as f:
            data = json.load(f)

        self._capabilities = {}
        for cap_data in data.get("capabilities", []):
            cap = Capability.from_dict(cap_data)
            self._capabilities[cap.id] = cap

        self._initialized = True
