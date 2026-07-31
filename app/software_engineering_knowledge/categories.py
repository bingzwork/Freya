"""Category Registry for Software Engineering Knowledge.

Defines and manages the engineering knowledge domain categories, providing
a structured taxonomy for organizing all software engineering knowledge.
"""

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.software_engineering_knowledge.models import (
    EngineeringCategory,
    EngineeringDomain,
)


# Default category definitions organized by domain
DEFAULT_CATEGORIES: Dict[EngineeringDomain, List[EngineeringCategory]] = {
    EngineeringDomain.PROGRAMMING_LANGUAGES: [
        EngineeringCategory(
            name="python",
            domain=EngineeringDomain.PROGRAMMING_LANGUAGES,
            description="Python language features, syntax, standard library, and best practices",
            priority=90,
            sub_categories=["syntax", "stdlib", "async", "typing", "packaging", "testing", "performance"],
            tags=["python", "language"],
        ),
        EngineeringCategory(
            name="javascript",
            domain=EngineeringDomain.PROGRAMMING_LANGUAGES,
            description="JavaScript/TypeScript language features, ecosystem, and best practices",
            priority=85,
            sub_categories=["es6+", "typescript", "async", "modules", "testing", "bundling"],
            tags=["javascript", "typescript", "language"],
        ),
        EngineeringCategory(
            name="go",
            domain=EngineeringDomain.PROGRAMMING_LANGUAGES,
            description="Go language features, standard library, and idioms",
            priority=70,
            sub_categories=["concurrency", "stdlib", "modules", "testing", "tooling"],
            tags=["go", "golang", "language"],
        ),
        EngineeringCategory(
            name="rust",
            domain=EngineeringDomain.PROGRAMMING_LANGUAGES,
            description="Rust language features, ownership, borrowing, and ecosystem",
            priority=70,
            sub_categories=["ownership", "borrowing", "async", "cargo", "testing", "ffi"],
            tags=["rust", "language"],
        ),
    ],
    EngineeringDomain.FRAMEWORKS: [
        EngineeringCategory(
            name="web_frameworks",
            domain=EngineeringDomain.FRAMEWORKS,
            description="Web application frameworks",
            priority=80,
            sub_categories=["django", "fastapi", "flask", "express", "react", "vue", "nextjs", "svelte"],
            tags=["web", "framework", "backend", "frontend"],
        ),
        EngineeringCategory(
            name="ml_frameworks",
            domain=EngineeringDomain.FRAMEWORKS,
            description="Machine learning frameworks",
            priority=75,
            sub_categories=["pytorch", "tensorflow", "jax", "sklearn", "huggingface"],
            tags=["ml", "ai", "framework"],
        ),
        EngineeringCategory(
            name="testing_frameworks",
            domain=EngineeringDomain.FRAMEWORKS,
            description="Testing frameworks and tools",
            priority=75,
            sub_categories=["pytest", "jest", "vitest", "playwright", "cypress", "unittest"],
            tags=["testing", "framework"],
        ),
    ],
    EngineeringDomain.LIBRARIES: [
        EngineeringCategory(
            name="http_clients",
            domain=EngineeringDomain.LIBRARIES,
            description="HTTP client libraries",
            priority=75,
            sub_categories=["requests", "httpx", "aiohttp", "axios", "fetch"],
            tags=["http", "client", "library"],
        ),
        EngineeringCategory(
            name="database_libraries",
            domain=EngineeringDomain.LIBRARIES,
            description="Database driver and ORM libraries",
            priority=80,
            sub_categories=["sqlalchemy", "django-orm", "prisma", "mongoose", "psycopg2", "asyncpg"],
            tags=["database", "orm", "library"],
        ),
    ],
    EngineeringDomain.SOFTWARE_ARCHITECTURE: [
        EngineeringCategory(
            name="architectural_patterns",
            domain=EngineeringDomain.SOFTWARE_ARCHITECTURE,
            description="High-level architectural patterns and styles",
            priority=90,
            sub_categories=["microservices", "monolith", "modular_monolith", "event_driven", "layered", "hexagonal", "clean_architecture"],
            tags=["architecture", "pattern"],
        ),
        EngineeringCategory(
            name="system_design",
            domain=EngineeringDomain.SOFTWARE_ARCHITECTURE,
            description="System design principles and tradeoffs",
            priority=85,
            sub_categories=["scalability", "availability", "consistency", "partition_tolerance", "caching", "load_balancing"],
            tags=["system_design", "architecture"],
        ),
        EngineeringCategory(
            name="domain_driven_design",
            domain=EngineeringDomain.SOFTWARE_ARCHITECTURE,
            description="DDD concepts, bounded contexts, aggregates, entities, value objects",
            priority=80,
            sub_categories=["bounded_context", "aggregate", "entity", "value_object", "domain_event", "repository"],
            tags=["ddd", "architecture"],
        ),
    ],
    EngineeringDomain.DESIGN_PATTERNS: [
        EngineeringCategory(
            name="creational_patterns",
            domain=EngineeringDomain.DESIGN_PATTERNS,
            description="Creational design patterns",
            priority=80,
            sub_categories=["singleton", "factory", "abstract_factory", "builder", "prototype"],
            tags=["design_pattern", "creational"],
        ),
        EngineeringCategory(
            name="structural_patterns",
            domain=EngineeringDomain.DESIGN_PATTERNS,
            description="Structural design patterns",
            priority=75,
            sub_categories=["adapter", "decorator", "facade", "proxy", "composite", "bridge", "flyweight"],
            tags=["design_pattern", "structural"],
        ),
        EngineeringCategory(
            name="behavioral_patterns",
            domain=EngineeringDomain.DESIGN_PATTERNS,
            description="Behavioral design patterns",
            priority=75,
            sub_categories=["observer", "strategy", "command", "state", "template_method", "visitor", "mediator"],
            tags=["design_pattern", "behavioral"],
        ),
        EngineeringCategory(
            name="concurrency_patterns",
            domain=EngineeringDomain.DESIGN_PATTERNS,
            description="Concurrency and parallelism patterns",
            priority=80,
            sub_categories=["thread_pool", "actor_model", "async_await", "promise_future", "channel", "mutex"],
            tags=["concurrency", "pattern"],
        ),
    ],
    EngineeringDomain.PROGRAMMING_PARADIGMS: [
        EngineeringCategory(
            name="functional_programming",
            domain=EngineeringDomain.PROGRAMMING_PARADIGMS,
            description="Functional programming concepts and techniques",
            priority=70,
            sub_categories=["immutability", "pure_functions", "higher_order", "monads", "functors", "lenses"],
            tags=["functional", "paradigm"],
        ),
        EngineeringCategory(
            name="object_oriented",
            domain=EngineeringDomain.PROGRAMMING_PARADIGMS,
            description="Object-oriented programming principles",
            priority=70,
            sub_categories=["encapsulation", "inheritance", "polymorphism", "solid", "composition"],
            tags=["oop", "paradigm"],
        ),
        EngineeringCategory(
            name="declarative_programming",
            domain=EngineeringDomain.PROGRAMMING_PARADIGMS,
            description="Declarative programming approaches",
            priority=60,
            sub_categories=["sql", "regex", "config_as_code", "infrastructure_as_code"],
            tags=["declarative", "paradigm"],
        ),
    ],
    EngineeringDomain.ALGORITHMS: [
        EngineeringCategory(
            name="sorting_searching",
            domain=EngineeringDomain.ALGORITHMS,
            description="Sorting and searching algorithms",
            priority=75,
            sub_categories=["quicksort", "mergesort", "binary_search", "heap_sort", "radix_sort"],
            tags=["algorithm", "sorting", "searching"],
        ),
        EngineeringCategory(
            name="graph_algorithms",
            domain=EngineeringDomain.ALGORITHMS,
            description="Graph algorithms and techniques",
            priority=75,
            sub_categories=["bfs", "dfs", "dijkstra", "a_star", "topological_sort", "union_find"],
            tags=["algorithm", "graph"],
        ),
        EngineeringCategory(
            name="dynamic_programming",
            domain=EngineeringDomain.ALGORITHMS,
            description="Dynamic programming techniques",
            priority=70,
            sub_categories=["memoization", "tabulation", "knapsack", "lcs", "edit_distance"],
            tags=["algorithm", "dp"],
        ),
    ],
    EngineeringDomain.DATA_STRUCTURES: [
        EngineeringCategory(
            name="basic_structures",
            domain=EngineeringDomain.DATA_STRUCTURES,
            description="Fundamental data structures",
            priority=75,
            sub_categories=["array", "linked_list", "stack", "queue", "hash_table", "tree", "heap"],
            tags=["data_structure", "basic"],
        ),
        EngineeringCategory(
            name="advanced_structures",
            domain=EngineeringDomain.DATA_STRUCTURES,
            description="Advanced data structures",
            priority=70,
            sub_categories=["trie", "b_tree", "red_black_tree", "skip_list", "bloom_filter", "segment_tree"],
            tags=["data_structure", "advanced"],
        ),
    ],
    EngineeringDomain.APIS: [
        EngineeringCategory(
            name="rest_api",
            domain=EngineeringDomain.APIS,
            description="REST API design and implementation",
            priority=85,
            sub_categories=["design", "versioning", "authentication", "rate_limiting", "pagination", "error_handling"],
            tags=["api", "rest"],
        ),
        EngineeringCategory(
            name="graphql",
            domain=EngineeringDomain.APIS,
            description="GraphQL API design and implementation",
            priority=75,
            sub_categories=["schema", "resolvers", "dataloader", "federation", "subscriptions"],
            tags=["api", "graphql"],
        ),
        EngineeringCategory(
            name="grpc",
            domain=EngineeringDomain.APIS,
            description="gRPC API design and implementation",
            priority=70,
            sub_categories=["protobuf", "services", "interceptors", "streaming", "load_balancing"],
            tags=["api", "grpc"],
        ),
    ],
    EngineeringDomain.DATABASES: [
        EngineeringCategory(
            name="relational_databases",
            domain=EngineeringDomain.DATABASES,
            description="Relational database concepts and optimization",
            priority=85,
            sub_categories=["postgresql", "mysql", "indexing", "query_optimization", "transactions", "migrations"],
            tags=["database", "sql", "relational"],
        ),
        EngineeringCategory(
            name="nosql_databases",
            domain=EngineeringDomain.DATABASES,
            description="NoSQL database concepts",
            priority=75,
            sub_categories=["mongodb", "redis", "cassandra", "dynamodb", "elasticsearch"],
            tags=["database", "nosql"],
        ),
        EngineeringCategory(
            name="database_design",
            domain=EngineeringDomain.DATABASES,
            description="Database schema design and normalization",
            priority=80,
            sub_categories=["normalization", "denormalization", "sharding", "replication", "partitioning"],
            tags=["database", "design"],
        ),
    ],
    EngineeringDomain.NETWORKING: [
        EngineeringCategory(
            name="http_protocol",
            domain=EngineeringDomain.NETWORKING,
            description="HTTP/HTTPS protocol details",
            priority=80,
            sub_categories=["methods", "status_codes", "headers", "caching", "compression", "http2", "http3"],
            tags=["networking", "http"],
        ),
        EngineeringCategory(
            name="network_protocols",
            domain=EngineeringDomain.NETWORKING,
            description="Core network protocols",
            priority=65,
            sub_categories=["tcp", "udp", "dns", "tls", "websocket", "grpc"],
            tags=["networking", "protocol"],
        ),
    ],
    EngineeringDomain.SECURITY: [
        EngineeringCategory(
            name="application_security",
            domain=EngineeringDomain.SECURITY,
            description="Application-level security practices",
            priority=90,
            sub_categories=["owasp_top_10", "input_validation", "output_encoding", "csrf", "xss", "sql_injection"],
            tags=["security", "application"],
        ),
        EngineeringCategory(
            name="authentication",
            domain=EngineeringDomain.SECURITY,
            description="Authentication mechanisms",
            priority=85,
            sub_categories=["jwt", "oauth2", "oidc", "session", "mfa", "passkeys", "api_keys"],
            tags=["security", "auth"],
        ),
        EngineeringCategory(
            name="authorization",
            domain=EngineeringDomain.SECURITY,
            description="Authorization patterns",
            priority=85,
            sub_categories=["rbac", "abac", "policies", "permissions", "scopes"],
            tags=["security", "authz"],
        ),
        EngineeringCategory(
            name="cryptography",
            domain=EngineeringDomain.SECURITY,
            description="Cryptographic primitives and usage",
            priority=80,
            sub_categories=["encryption", "hashing", "signing", "key_management", "certificates"],
            tags=["security", "crypto"],
        ),
    ],
    EngineeringDomain.AUTHENTICATION: [],  # Merged into SECURITY
    EngineeringDomain.PERFORMANCE_OPTIMIZATION: [
        EngineeringCategory(
            name="profiling",
            domain=EngineeringDomain.PERFORMANCE_OPTIMIZATION,
            description="Performance profiling techniques",
            priority=80,
            sub_categories=["cpu_profiling", "memory_profiling", "io_profiling", "flame_graphs", "continuous_profiling"],
            tags=["performance", "profiling"],
        ),
        EngineeringCategory(
            name="optimization_techniques",
            domain=EngineeringDomain.PERFORMANCE_OPTIMIZATION,
            description="Code and system optimization techniques",
            priority=80,
            sub_categories=["caching", "lazy_loading", "batching", "connection_pooling", "async_io", "vectorization"],
            tags=["performance", "optimization"],
        ),
        EngineeringCategory(
            name="database_performance",
            domain=EngineeringDomain.PERFORMANCE_OPTIMIZATION,
            description="Database-specific performance optimization",
            priority=80,
            sub_categories=["indexing", "query_optimization", "connection_pooling", "read_replicas", "partitioning"],
            tags=["performance", "database"],
        ),
    ],
    EngineeringDomain.DEBUGGING: [
        EngineeringCategory(
            name="debugging_techniques",
            domain=EngineeringDomain.DEBUGGING,
            description="General debugging approaches",
            priority=85,
            sub_categories=["logging", "breakpoints", "core_dumps", "distributed_tracing", "debuggers"],
            tags=["debugging", "technique"],
        ),
        EngineeringCategory(
            name="common_bugs",
            domain=EngineeringDomain.DEBUGGING,
            description="Common bug patterns and fixes",
            priority=80,
            sub_categories=["null_pointer", "off_by_one", "race_condition", "memory_leak", "deadlock", "infinite_loop"],
            tags=["debugging", "bug"],
        ),
    ],
    EngineeringDomain.TESTING: [
        EngineeringCategory(
            name="testing_strategies",
            domain=EngineeringDomain.TESTING,
            description="Testing methodologies and strategies",
            priority=85,
            sub_categories=["unit_testing", "integration_testing", "e2e_testing", "property_based", "mutation_testing", "contract_testing"],
            tags=["testing", "strategy"],
        ),
        EngineeringCategory(
            name="test_organization",
            domain=EngineeringDomain.TESTING,
            description="Test structure and organization",
            priority=75,
            sub_categories=["test_pyramid", "test_doubles", "fixtures", "factories", "test_data_management"],
            tags=["testing", "organization"],
        ),
    ],
    EngineeringDomain.GIT: [
        EngineeringCategory(
            name="git_workflows",
            domain=EngineeringDomain.GIT,
            description="Git branching and collaboration workflows",
            priority=80,
            sub_categories=["gitflow", "github_flow", "trunk_based", "feature_branches", "release_branches"],
            tags=["git", "workflow"],
        ),
        EngineeringCategory(
            name="git_techniques",
            domain=EngineeringDomain.GIT,
            description="Advanced Git techniques",
            priority=75,
            sub_categories=["rebase", "cherry_pick", "bisect", "hooks", "submodules", "worktrees"],
            tags=["git", "technique"],
        ),
    ],
    EngineeringDomain.CI_CD: [
        EngineeringCategory(
            name="ci_pipelines",
            domain=EngineeringDomain.CI_CD,
            description="Continuous Integration pipeline design",
            priority=85,
            sub_categories=["github_actions", "gitlab_ci", "jenkins", "circleci", "buildkite", "pipeline_stages"],
            tags=["ci", "pipeline"],
        ),
        EngineeringCategory(
            name="cd_strategies",
            domain=EngineeringDomain.CI_CD,
            description="Continuous Deployment strategies",
            priority=80,
            sub_categories=["blue_green", "canary", "rolling", "feature_flags", "progressive_delivery"],
            tags=["cd", "deployment"],
        ),
    ],
    EngineeringDomain.BUILD_SYSTEMS: [
        EngineeringCategory(
            name="build_tools",
            domain=EngineeringDomain.BUILD_SYSTEMS,
            description="Build tools and configuration",
            priority=75,
            sub_categories=["make", "cmake", "bazel", "gradle", "maven", "npm", "yarn", "pnpm", "poetry", "pip"],
            tags=["build", "tool"],
        ),
    ],
    EngineeringDomain.DEPENDENCY_MANAGEMENT: [
        EngineeringCategory(
            name="package_management",
            domain=EngineeringDomain.DEPENDENCY_MANAGEMENT,
            description="Package and dependency management",
            priority=80,
            sub_categories=["semver", "lockfiles", "dependency_resolution", "vulnerability_scanning", "license_compliance"],
            tags=["dependency", "package"],
        ),
    ],
    EngineeringDomain.DOCUMENTATION: [
        EngineeringCategory(
            name="doc_types",
            domain=EngineeringDomain.DOCUMENTATION,
            description="Types of technical documentation",
            priority=70,
            sub_categories=["readme", "api_docs", "architecture_docs", "adr", "runbooks", "tutorials"],
            tags=["documentation", "type"],
        ),
        EngineeringCategory(
            name="doc_tools",
            domain=EngineeringDomain.DOCUMENTATION,
            description="Documentation generation tools",
            priority=65,
            sub_categories=["sphinx", "mkdocs", "docusaurus", "swagger", "redoc", "typedoc"],
            tags=["documentation", "tool"],
        ),
    ],
    EngineeringDomain.CODE_QUALITY: [
        EngineeringCategory(
            name="code_metrics",
            domain=EngineeringDomain.CODE_QUALITY,
            description="Code quality metrics and measurement",
            priority=75,
            sub_categories=["cyclomatic_complexity", "cognitive_complexity", "maintainability_index", "duplication", "coverage"],
            tags=["code_quality", "metric"],
        ),
        EngineeringCategory(
            name="static_analysis",
            domain=EngineeringDomain.CODE_QUALITY,
            description="Static analysis tools and rules",
            priority=75,
            sub_categories=["linting", "type_checking", "security_scan", "dependency_scan", "secrets_detection"],
            tags=["code_quality", "static_analysis"],
        ),
    ],
    EngineeringDomain.CODE_REVIEW: [
        EngineeringCategory(
            name="review_practices",
            domain=EngineeringDomain.CODE_REVIEW,
            description="Code review best practices",
            priority=80,
            sub_categories=["checklist", "feedback_style", "review_size", "automation", "pair_programming"],
            tags=["code_review", "practice"],
        ),
    ],
    EngineeringDomain.REFACTORING: [
        EngineeringCategory(
            name="refactoring_techniques",
            domain=EngineeringDomain.REFACTORING,
            description="Code refactoring techniques",
            priority=80,
            sub_categories=["extract_method", "extract_class", "inline", "rename", "move_method", "replace_conditional"],
            tags=["refactoring", "technique"],
        ),
        EngineeringCategory(
            name="legacy_code",
            domain=EngineeringDomain.REFACTORING,
            description="Working with legacy code",
            priority=75,
            sub_categories=["characterization_tests", "seams", "strangler_fig", "anti_corruption_layer"],
            tags=["refactoring", "legacy"],
        ),
    ],
    EngineeringDomain.DEVOPS: [
        EngineeringCategory(
            name="infrastructure",
            domain=EngineeringDomain.DEVOPS,
            description="Infrastructure as code and management",
            priority=80,
            sub_categories=["terraform", "pulumi", "ansible", "kubernetes", "docker", "helm", "argocd"],
            tags=["devops", "infrastructure"],
        ),
        EngineeringCategory(
            name="monitoring",
            domain=EngineeringDomain.DEVOPS,
            description="Observability and monitoring",
            priority=80,
            sub_categories=["logging", "metrics", "tracing", "alerting", "dashboards", "slo_sli"],
            tags=["devops", "monitoring"],
        ),
    ],
    EngineeringDomain.CLOUD: [
        EngineeringCategory(
            name="cloud_providers",
            domain=EngineeringDomain.CLOUD,
            description="Cloud platform knowledge",
            priority=75,
            sub_categories=["aws", "gcp", "azure", "multi_cloud", "serverless", "edge"],
            tags=["cloud", "provider"],
        ),
        EngineeringCategory(
            name="cloud_services",
            domain=EngineeringDomain.CLOUD,
            description="Core cloud services",
            priority=75,
            sub_categories=["compute", "storage", "database", "networking", "security", "analytics", "ai_ml"],
            tags=["cloud", "service"],
        ),
    ],
    EngineeringDomain.DESKTOP_DEVELOPMENT: [
        EngineeringCategory(
            name="desktop_frameworks",
            domain=EngineeringDomain.DESKTOP_DEVELOPMENT,
            description="Desktop application frameworks",
            priority=60,
            sub_categories=["electron", "tauri", "wpf", "winui", "swiftui", "flutter_desktop", "qt"],
            tags=["desktop", "framework"],
        ),
    ],
    EngineeringDomain.WEB_DEVELOPMENT: [
        EngineeringCategory(
            name="frontend",
            domain=EngineeringDomain.WEB_DEVELOPMENT,
            description="Frontend web development",
            priority=80,
            sub_categories=["html", "css", "javascript", "typescript", "responsive", "accessibility", "performance", "seo"],
            tags=["web", "frontend"],
        ),
        EngineeringCategory(
            name="backend",
            domain=EngineeringDomain.WEB_DEVELOPMENT,
            description="Backend web development",
            priority=80,
            sub_categories=["api_design", "authentication", "database", "caching", "queue", "microservices"],
            tags=["web", "backend"],
        ),
    ],
    EngineeringDomain.AI_ENGINEERING: [
        EngineeringCategory(
            name="llm_engineering",
            domain=EngineeringDomain.AI_ENGINEERING,
            description="Large Language Model engineering",
            priority=85,
            sub_categories=["prompt_engineering", "rag", "fine_tuning", "eval", "guardrails", "agents", "tools"],
            tags=["ai", "llm"],
        ),
        EngineeringCategory(
            name="mlops",
            domain=EngineeringDomain.AI_ENGINEERING,
            description="MLOps practices",
            priority=75,
            sub_categories=["model_registry", "feature_store", "pipeline", "monitoring", "drift_detection", "ab_testing"],
            tags=["ai", "mlops"],
        ),
    ],
    EngineeringDomain.PROMPT_ENGINEERING: [],
    EngineeringDomain.TOOL_DEVELOPMENT: [
        EngineeringCategory(
            name="cli_tools",
            domain=EngineeringDomain.TOOL_DEVELOPMENT,
            description="Command-line tool development",
            priority=70,
            sub_categories=["argparse", "click", "typer", "cobra", "completion", "testing"],
            tags=["tool", "cli"],
        ),
        EngineeringCategory(
            name="editor_tools",
            domain=EngineeringDomain.TOOL_DEVELOPMENT,
            description="Editor/IDE tool development",
            priority=65,
            sub_categories=["vscode_extension", "vim_plugin", "lsp", "dap", "snippets"],
            tags=["tool", "editor"],
        ),
    ],
    EngineeringDomain.PROJECT_STRUCTURE: [
        EngineeringCategory(
            name="project_layout",
            domain=EngineeringDomain.PROJECT_STRUCTURE,
            description="Project directory structure conventions",
            priority=75,
            sub_categories=["monorepo", "polyrepo", "modular", "layered", "feature_based"],
            tags=["project", "structure"],
        ),
        EngineeringCategory(
            name="configuration",
            domain=EngineeringDomain.PROJECT_STRUCTURE,
            description="Project configuration management",
            priority=70,
            sub_categories=["env_files", "config_files", "secrets", "feature_flags", "environments"],
            tags=["project", "config"],
        ),
    ],
    EngineeringDomain.BUG_PATTERNS: [
        EngineeringCategory(
            name="common_bug_patterns",
            domain=EngineeringDomain.BUG_PATTERNS,
            description="Recurring bug patterns across projects",
            priority=85,
            sub_categories=["null_reference", "race_condition", "resource_leak", "infinite_loop", "boundary_error", "type_confusion"],
            tags=["bug", "pattern"],
        ),
    ],
    EngineeringDomain.ROOT_CAUSES: [
        EngineeringCategory(
            name="root_cause_analysis",
            domain=EngineeringDomain.ROOT_CAUSES,
            description="Root cause analysis techniques and common root causes",
            priority=80,
            sub_categories=["5_whys", "fishbone", "fault_tree", "common_causes", "systemic_issues"],
            tags=["root_cause", "analysis"],
        ),
    ],
    EngineeringDomain.SOLUTIONS: [
        EngineeringCategory(
            name="solution_patterns",
            domain=EngineeringDomain.SOLUTIONS,
            description="Reusable solution patterns for common problems",
            priority=85,
            sub_categories=["retry", "circuit_breaker", "bulkhead", "timeout", "fallback", "cache_aside", "event_sourcing"],
            tags=["solution", "pattern"],
        ),
    ],
    EngineeringDomain.BEST_PRACTICES: [
        EngineeringCategory(
            name="general_best_practices",
            domain=EngineeringDomain.BEST_PRACTICES,
            description="General software engineering best practices",
            priority=90,
            sub_categories=["clean_code", "solid", "dry", "kiss", "yagni", "convention_over_config"],
            tags=["best_practice", "general"],
        ),
        EngineeringCategory(
            name="language_best_practices",
            domain=EngineeringDomain.BEST_PRACTICES,
            description="Language-specific best practices",
            priority=85,
            sub_categories=["python", "javascript", "go", "rust", "java", "csharp"],
            tags=["best_practice", "language"],
        ),
    ],
    EngineeringDomain.ENGINEERING_LESSONS: [
        EngineeringCategory(
            name="lessons_learned",
            domain=EngineeringDomain.ENGINEERING_LESSONS,
            description="Engineering lessons from experience",
            priority=85,
            sub_categories=["success", "failure", "tradeoff", "decision", "anti_pattern"],
            tags=["lesson", "experience"],
        ),
    ],
    EngineeringDomain.ORGANIZATION_STANDARDS: [
        EngineeringCategory(
            name="coding_standards",
            domain=EngineeringDomain.ORGANIZATION_STANDARDS,
            description="Organization coding standards",
            priority=80,
            sub_categories=["style_guide", "naming_conventions", "file_organization", "commenting", "documentation"],
            tags=["standard", "coding"],
        ),
        EngineeringCategory(
            name="process_standards",
            domain=EngineeringDomain.ORGANIZATION_STANDARDS,
            description="Organization engineering processes",
            priority=75,
            sub_categories=["git_workflow", "review_process", "deployment_process", "incident_response", "oncall"],
            tags=["standard", "process"],
        ),
    ],
}


@dataclass
class CategoryRegistry:
    """Registry of engineering knowledge categories.

    Manages the domain taxonomy, allowing categories to be looked up,
    added, and extended. Persists custom categories to disk.
    """

    categories: Dict[str, EngineeringCategory] = field(default_factory=dict)
    storage_path: Optional[Path] = None
    _lock: any = field(default_factory=lambda: __import__('threading').RLock(), repr=False)

    def __post_init__(self):
        """Initialize with default categories."""
        self._load_defaults()
        if self.storage_path:
            self._load_custom()

    def _load_defaults(self) -> None:
        """Load built-in default categories."""
        for domain, cats in DEFAULT_CATEGORIES.items():
            for cat in cats:
                key = f"{domain.value}.{cat.name}"
                self.categories[key] = cat

    def _load_custom(self) -> None:
        """Load custom categories from storage."""
        if not self.storage_path or not self.storage_path.exists():
            return
        try:
            import json
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for cat_data in data.get("categories", []):
                cat = EngineeringCategory.from_dict(cat_data)
                key = f"{cat.domain.value}.{cat.name}"
                # Custom categories override defaults
                self.categories[key] = cat
        except Exception:
            pass

    def save_custom(self) -> None:
        """Save custom (non-default) categories to storage."""
        if not self.storage_path:
            return
        try:
            import json
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            # Only save categories not in defaults
            custom = []
            for key, cat in self.categories.items():
                default = DEFAULT_CATEGORIES.get(cat.domain, [])
                if not any(d.name == cat.name for d in default):
                    custom.append(cat.to_dict())
            data = {"categories": custom, "version": 1}
            temp = self.storage_path.with_suffix(".tmp")
            with open(temp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            temp.replace(self.storage_path)
        except Exception:
            pass

    def get(self, domain: EngineeringDomain, name: str) -> Optional[EngineeringCategory]:
        """Get a category by domain and name."""
        key = f"{domain.value}.{name}"
        return self.categories.get(key)

    def get_by_domain(self, domain: EngineeringDomain) -> List[EngineeringCategory]:
        """Get all categories for a domain."""
        prefix = f"{domain.value}."
        return [c for k, c in self.categories.items() if k.startswith(prefix)]

    def get_all(self) -> List[EngineeringCategory]:
        """Get all categories."""
        return list(self.categories.values())

    def get_all_domains(self) -> List[EngineeringDomain]:
        """Get all domains that have categories."""
        domains = set()
        for cat in self.categories.values():
            domains.add(cat.domain)
        return sorted(domains, key=lambda d: d.value)

    def add(self, category: EngineeringCategory) -> None:
        """Add or update a category."""
        with self._lock:
            key = f"{category.domain.value}.{category.name}"
            self.categories[key] = category
            self.save_custom()

    def remove(self, domain: EngineeringDomain, name: str) -> bool:
        """Remove a custom category (cannot remove defaults)."""
        with self._lock:
            key = f"{domain.value}.{name}"
            if key in self.categories:
                # Check if it's a default
                default = DEFAULT_CATEGORIES.get(domain, [])
                if any(d.name == name for d in default):
                    return False  # Cannot remove built-in
                del self.categories[key]
                self.save_custom()
                return True
            return False

    def search(self, query: str, domain: Optional[EngineeringDomain] = None) -> List[EngineeringCategory]:
        """Search categories by name, description, or tags."""
        query_lower = query.lower()
        results = []
        for cat in self.categories.values():
            if domain and cat.domain != domain:
                continue
            searchable = f"{cat.name} {cat.description} {' '.join(cat.sub_categories)} {' '.join(cat.tags)}".lower()
            if query_lower in searchable:
                results.append(cat)
        # Sort by priority desc
        results.sort(key=lambda c: c.priority, reverse=True)
        return results

    def get_domain_for_category(self, category_name: str) -> Optional[EngineeringDomain]:
        """Find which domain a category belongs to."""
        for cat in self.categories.values():
            if cat.name == category_name:
                return cat.domain
        return None


# Global registry instance
_default_registry: Optional[CategoryRegistry] = None


def get_category_registry(storage_path: Optional[str] = None) -> CategoryRegistry:
    """Get or create the global category registry."""
    global _default_registry
    if _default_registry is None:
        path = Path(storage_path) if storage_path else Path("data/software_engineering_knowledge/categories.json")
        _default_registry = CategoryRegistry(storage_path=path)
    return _default_registry