"""Semantic work item extraction and decomposition logic for goals."""

import hashlib
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Set, Tuple

from app.memory.goals.models import (
    Goal,
    GoalComplexity,
    ComplexityLevel,
    TaskType,
    Milestone,
    SubtaskSuggestion,
    WorkItem,
    DecompositionCacheEntry,
    HierarchicalDecompositionResult,
    DecompositionFeedback,
    DecompositionStrategyType,
    EnhancedDecompositionStrategy,
)


class _DecompositionMixin:
    """Mixin providing enhanced decomposition capabilities for GoalStorage.

    This mixin is composed into GoalStorage to provide:
    - Semantic work item extraction from goal descriptions
    - Duplicate/redundancy detection
    - Deterministic caching
    - Content-aware milestone generation
    - Dependency-aware topological ordering
    - Hierarchical recursive decomposition
    - Reusable decomposition strategies
    - Feedback collection for continuous improvement
    """

    # Maximum cache entries per goal (prevents unbounded growth)
    _MAX_CACHE_ENTRIES = 10
    # Default cache TTL in seconds (1 week)
    _CACHE_TTL_SECONDS = 7 * 24 * 3600

    # Complexity indicators inspected by ``assess_complexity``.
    _COMPLEXITY_SIGNAL_WEIGHTS: Dict[str, float] = {
        "has_dependencies": 0.15,
        "has_children": 0.2,
        "long_description": 0.1,
        "deep_hierarchy": 0.15,
        "critical_priority": 0.1,
        "broad_scope_keywords": 0.15,
        "cross_cutting": 0.15,
    }

    _SCOPE_KEYWORDS: Tuple[str, ...] = (
        "architecture", "system", "pipeline", "framework", "platform",
        "multi", "distributed", "scalable", "enterprise", "orchestrator",
        "integration", "migration", "refactor",
    )

    # Original Phase 6 decomposition phases (template-based approach)
    _DECOMPOSE_PHASES = (
        ("Plan", "Plan and break down the work for the parent goal."),
        ("Implement", "Implement the core functionality of the parent goal."),
        ("Test", "Verify behaviour end-to-end against the parent goal."),
        ("Document", "Document the changes delivered for the parent goal."),
        ("Review", "Review and finalize the work for the parent goal."),
    )

    # Work item extraction patterns — maps keywords to work categories
    _WORK_ITEM_PATTERNS: Dict[str, List[Tuple[str, List[str]]]] = {
        "research": [
            ("research", ["research", "investigate", "explore", "survey", "analyze", "evaluate", "assess", "study"]),
            ("design", ["design", "architect", "plan", "specify", "model", "draft"]),
            ("prototype", ["prototype", "proof of concept", "spike", "experiment", "poc"]),
        ],
        "implement": [
            ("implement", ["implement", "build", "create", "develop", "code", "write", "construct", "add"]),
            ("refactor", ["refactor", "restructure", "reorganize", "clean up", "cleanup", "modernize"]),
            ("integrate", ["integrate", "connect", "wire", "bridge", "hook", "link"]),
            ("configure", ["configure", "setup", "set up", "install", "provision", "deploy config"]),
        ],
        "test": [
            ("test", ["test", "verify", "validate", "check", "assert", "unit test", "integration test"]),
            ("debug", ["debug", "fix", "troubleshoot", "resolve", "patch", "repair"]),
            ("benchmark", ["benchmark", "profile", "measure", "performance", "optimize"]),
        ],
        "document": [
            ("document", ["document", "documentation", "readme", "wiki", "guide", "tutorial", "comments"]),
            ("changelog", ["changelog", "release notes", "migration guide", "upgrade guide"]),
        ],
        "verify": [
            ("review", ["review", "audit", "inspect", "validate", "approve", "sign off"]),
            ("release", ["release", "ship", "publish", "deploy", "launch", "deliver"]),
        ],
    }

    # Category ordering for execution sequence
    _CATEGORY_ORDER = {
        "research": 0,
        "design": 1,
        "prototype": 2,
        "implement": 3,
        "refactor": 4,
        "integrate": 5,
        "configure": 6,
        "test": 7,
        "debug": 8,
        "benchmark": 9,
        "document": 10,
        "changelog": 11,
        "review": 12,
        "release": 13,
    }

    def __init__(self):
        """Initialize decomposition capabilities."""
        # Registered decomposition strategies
        self._decomposition_strategies: Dict[str, EnhancedDecompositionStrategy] = {}
        self._register_default_strategies()

        # Feedback storage
        self._decomposition_feedback: List[DecompositionFeedback] = []

    def _estimate_subtask_duration(self, goal: Goal, suggestion: SubtaskSuggestion) -> float:
        """Estimate duration for a subtask suggestion using the planner's DurationEstimator.

        This method should be called after the GoalStorage has initialized _duration_estimator.
        Returns estimated hours.
        """
        if not hasattr(self, '_duration_estimator') or self._duration_estimator is None:
            # Fallback to estimated_hours or default
            return suggestion.estimated_hours or 1.0

        from app.planner.task import Task, TaskCategory, TaskPriority

        # Map planner_category string to TaskCategory
        category_map = {
            "research": TaskCategory.RESEARCH,
            "design": TaskCategory.FEATURE,
            "prototype": TaskCategory.FEATURE,
            "implement": TaskCategory.IMPLEMENTATION,
            "refactor": TaskCategory.REFACTORING,
            "integrate": TaskCategory.FEATURE,
            "configure": TaskCategory.MAINTENANCE,
            "test": TaskCategory.TESTING,
            "debug": TaskCategory.BUG_FIX,
            "benchmark": TaskCategory.TESTING,
            "document": TaskCategory.DOCUMENTATION,
            "changelog": TaskCategory.DOCUMENTATION,
            "review": TaskCategory.REVIEW,
            "release": TaskCategory.MAINTENANCE,
            "plan": TaskCategory.FEATURE,
            "execute": TaskCategory.IMPLEMENTATION,
            "verify": TaskCategory.TESTING,
            "prepare": TaskCategory.MAINTENANCE,
            "deploy": TaskCategory.MAINTENANCE,
            "assess": TaskCategory.RESEARCH,
            "update": TaskCategory.MAINTENANCE,
            "outline": TaskCategory.DOCUMENTATION,
            "write": TaskCategory.DOCUMENTATION,
            "epic": TaskCategory.FEATURE,
            "user_story": TaskCategory.FEATURE,
            "planning": TaskCategory.FEATURE,
            "retrospective": TaskCategory.REVIEW,
            "requirements": TaskCategory.FEATURE,
            "implementation": TaskCategory.IMPLEMENTATION,
            "testing": TaskCategory.TESTING,
            "deployment": TaskCategory.MAINTENANCE,
            "maintenance": TaskCategory.MAINTENANCE,
        }

        category = category_map.get(suggestion.planner_category, TaskCategory.OTHER)
        priority_map = {"critical": TaskPriority.CRITICAL, "high": TaskPriority.HIGH,
                       "medium": TaskPriority.MEDIUM, "low": TaskPriority.LOW, "optional": TaskPriority.LOW}
        priority = priority_map.get(suggestion.priority, TaskPriority.MEDIUM)

        temp_task = Task(
            id=f"subtask_{suggestion.name}",
            title=suggestion.name,
            description=suggestion.description,
            category=category,
            priority=priority,
        )

        estimate = self._duration_estimator.estimate_task_duration(temp_task)
        return round(estimate.estimated_seconds / 3600, 1)

    def _register_default_strategies(self) -> None:
        """Register the built-in decomposition strategies."""
        # Template-based strategy (original Phase 6 approach)
        self.register_strategy(EnhancedDecompositionStrategy(
            name="template",
            description="Fixed phase-based decomposition (Plan, Implement, Test, Document, Review)",
            strategy_type=DecompositionStrategyType.TEMPLATE,
            applicable_types=list(TaskType),
            min_complexity=ComplexityLevel.SIMPLE,
            generator=self._template_decomposition_generator,
            weight=1.0,
        ))

        # Semantic work-item based decomposition
        self.register_strategy(EnhancedDecompositionStrategy(
            name="semantic",
            description="Keyword-based work item extraction with dependency ordering",
            strategy_type=DecompositionStrategyType.SEMANTIC,
            applicable_types=list(TaskType),
            min_complexity=ComplexityLevel.MODERATE,
            generator=self._semantic_decomposition_generator,
            weight=1.5,
        ))

        # Hierarchical recursive decomposition
        self.register_strategy(EnhancedDecompositionStrategy(
            name="hierarchical",
            description="Multi-level recursive decomposition for complex goals",
            strategy_type=DecompositionStrategyType.HIERARCHICAL,
            applicable_types=[TaskType.IMPLEMENTATION, TaskType.INTEGRATION, TaskType.REFACTORING],
            min_complexity=ComplexityLevel.COMPLEX,
            generator=self._hierarchical_decomposition_generator,
            weight=2.0,
        ))

        # Agile sprint-oriented decomposition
        self.register_strategy(EnhancedDecompositionStrategy(
            name="agile",
            description="Sprint-oriented decomposition with user stories and tasks",
            strategy_type=DecompositionStrategyType.AGILE,
            applicable_types=[TaskType.IMPLEMENTATION, TaskType.FEATURE, TaskType.MAINTENANCE],
            min_complexity=ComplexityLevel.MODERATE,
            generator=self._agile_decomposition_generator,
            weight=1.2,
        ))

        # Waterfall sequential decomposition
        self.register_strategy(EnhancedDecompositionStrategy(
            name="waterfall",
            description="Sequential phase decomposition (Requirements, Design, Implementation, Verification, Maintenance)",
            strategy_type=DecompositionStrategyType.WATERFALL,
            applicable_types=[TaskType.IMPLEMENTATION, TaskType.DEPLOYMENT, TaskType.INTEGRATION],
            min_complexity=ComplexityLevel.MODERATE,
            generator=self._waterfall_decomposition_generator,
            weight=1.0,
        ))

        # Hybrid adaptive decomposition
        self.register_strategy(EnhancedDecompositionStrategy(
            name="hybrid",
            description="Adaptive combination of strategies based on goal characteristics",
            strategy_type=DecompositionStrategyType.HYBRID,
            applicable_types=list(TaskType),
            min_complexity=ComplexityLevel.SIMPLE,
            generator=self._hybrid_decomposition_generator,
            weight=2.5,
        ))

    def register_strategy(self, strategy: EnhancedDecompositionStrategy) -> None:
        """Register a new decomposition strategy."""
        self._decomposition_strategies[strategy.name] = strategy

    def unregister_strategy(self, name: str) -> bool:
        """Unregister a decomposition strategy."""
        if name in self._decomposition_strategies:
            del self._decomposition_strategies[name]
            return True
        return False

    def get_strategy(self, name: str) -> Optional[EnhancedDecompositionStrategy]:
        """Get a decomposition strategy by name."""
        return self._decomposition_strategies.get(name)

    def list_strategies(self) -> List[EnhancedDecompositionStrategy]:
        """List all registered decomposition strategies."""
        return list(self._decomposition_strategies.values())

    def get_applicable_strategies(self, goal: Goal) -> List[EnhancedDecompositionStrategy]:
        """Get strategies applicable to a goal based on its type and complexity."""
        complexity = self.assess_complexity(goal.id)
        if not complexity:
            return []
        task_type = self._infer_task_type(goal)
        applicable = []
        for strategy in self._decomposition_strategies.values():
            if (strategy.min_complexity.value <= complexity.level.value or
                    complexity.level == strategy.min_complexity) and \
                    (task_type in strategy.applicable_types or TaskType.UNKNOWN in strategy.applicable_types):
                applicable.append(strategy)
        # Sort by weight (higher = more preferred)
        applicable.sort(key=lambda s: s.weight, reverse=True)
        return applicable

    def _now(self) -> str:
        """Get current UTC timestamp as ISO string."""
        return datetime.now(timezone.utc).isoformat()

    def _template_decomposition_generator(
        self,
        goal: Goal,
        max_subtasks: int,
        parameters: Optional[Dict[str, Any]] = None
    ) -> List[SubtaskSuggestion]:
        """Template-based decomposition generator (Phase 6 approach)."""
        suggestions = []
        phase_count = min(max_subtasks, len(self._DECOMPOSE_PHASES))
        for index in range(phase_count):
            phase_name, phase_desc = self._DECOMPOSE_PHASES[index]
            suggestions.append(SubtaskSuggestion(
                name=f"{phase_name}: {goal.name}",
                description=phase_desc,
                priority=goal.priority,
            ))
        if suggestions and goal.description:
            suggestions[0].description = f"{suggestions[0].description}\n\nParent goal context: {goal.description}"
        return suggestions

    def _semantic_decomposition_generator(
        self,
        goal: Goal,
        max_subtasks: int,
        parameters: Optional[Dict[str, Any]] = None
    ) -> List[SubtaskSuggestion]:
        """Semantic decomposition generator (uses work item extraction)."""
        return self.decompose_semantic(goal.id, max_subtasks, use_cache=False)

    def _hierarchical_decomposition_generator(
        self,
        goal: Goal,
        max_subtasks: int,
        parameters: Optional[Dict[str, Any]] = None
    ) -> List[SubtaskSuggestion]:
        """Hierarchical decomposition generator - returns top-level suggestions only."""
        result = self.decompose_hierarchical(goal.id, max_depth=parameters.get("max_depth", 3) if parameters else 3)
        return result.suggestions

    def _agile_decomposition_generator(
        self,
        goal: Goal,
        max_subtasks: int,
        parameters: Optional[Dict[str, Any]] = None
    ) -> List[SubtaskSuggestion]:
        """Agile sprint-oriented decomposition generator."""
        return self.decompose_agile(goal.id, max_subtasks)

    def _waterfall_decomposition_generator(
        self,
        goal: Goal,
        max_subtasks: int,
        parameters: Optional[Dict[str, Any]] = None
    ) -> List[SubtaskSuggestion]:
        """Waterfall sequential decomposition generator."""
        return self.decompose_waterfall(goal.id, max_subtasks)

    def _hybrid_decomposition_generator(
        self,
        goal: Goal,
        max_subtasks: int,
        parameters: Optional[Dict[str, Any]] = None
    ) -> List[SubtaskSuggestion]:
        """Hybrid adaptive decomposition generator."""
        return self.decompose_hybrid(goal.id, max_subtasks)

    def _compute_decomposition_cache_key(self, goal: Goal) -> str:
        """Compute a deterministic cache key for a goal's content."""
        content = f"{goal.name}|{goal.description}|{goal.priority}"
        # Include parent context for hierarchical goals
        if goal.parent_goal_id:
            parent = self._goals.get(goal.parent_goal_id)
            if parent:
                content += f"|parent:{parent.name}|{parent.description}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _get_cached_decomposition(self, goal_id: str, cache_key: str) -> Optional[DecompositionCacheEntry]:
        """Retrieve a valid cached decomposition entry."""
        with self._lock:
            goal = self._goals.get(goal_id)
            if not goal:
                return None
            cache = goal.metadata.get("decomposition_cache", [])
            for entry_data in cache:
                if entry_data.get("cache_key") == cache_key:
                    entry = DecompositionCacheEntry.from_dict(entry_data)
                    # Check TTL
                    created = datetime.fromisoformat(entry.created_at.replace("Z", "+00:00"))
                    age = (datetime.now(timezone.utc) - created).total_seconds()
                    if age < self._CACHE_TTL_SECONDS:
                        entry.access_count += 1
                        return entry
        return None

    def _store_decomposition_cache(
        self,
        goal_id: str,
        cache_key: str,
        suggestions: List["SubtaskSuggestion"],
        milestones: List[Milestone],
        complexity_level: "ComplexityLevel",
    ) -> None:
        """Store a decomposition result in the goal's cache."""
        with self._lock:
            goal = self._goals.get(goal_id)
            if not goal:
                return
            cache = goal.metadata.get("decomposition_cache", [])
            # Remove existing entry with same key
            cache = [e for e in cache if e.get("cache_key") != cache_key]
            # Add new entry
            entry = DecompositionCacheEntry(
                goal_id=goal_id,
                cache_key=cache_key,
                suggestions=suggestions,
                milestones=milestones,
                complexity_level=complexity_level,
                created_at=self._now(),
            )
            cache.append(entry.to_dict())
            # Trim cache
            if len(cache) > self._MAX_CACHE_ENTRIES:
                # Keep most recently accessed
                entries = [DecompositionCacheEntry.from_dict(e) for e in cache]
                entries.sort(key=lambda e: e.access_count, reverse=True)
                cache = [e.to_dict() for e in entries[:self._MAX_CACHE_ENTRIES]]
            goal.metadata["decomposition_cache"] = cache
            goal.updated_at = self._now()
            self._save_file()

    def extract_work_items(self, goal_id: str) -> List[WorkItem]:
        """Extract logical work items from a goal's name and description.

        Uses keyword-based semantic analysis to identify atomic units of work.
        Returns a list of WorkItem objects with categories, dependencies,
        and effort estimates.
        """
        with self._lock:
            goal = self._goals.get(goal_id)
            if not goal:
                return []

        text = f"{goal.name} {goal.description}".lower()
        work_items: List[WorkItem] = []
        item_counter = 0

        # Extract work items from each category
        for category, patterns in self._WORK_ITEM_PATTERNS.items():
            for subcategory, keywords in patterns:
                for keyword in keywords:
                    if keyword in text:
                        # Find context around the keyword for better description
                        idx = text.find(keyword)
                        context_start = max(0, idx - 50)
                        context_end = min(len(text), idx + len(keyword) + 100)
                        context = text[context_start:context_end].strip()

                        item = WorkItem(
                            id=f"wi_{goal_id}_{item_counter}",
                            title=f"{subcategory.title()}: {goal.name}",
                            description=f"Work item for '{keyword}': {context}",
                            category=subcategory,
                            estimated_effort=self._estimate_effort(subcategory),
                            signals=[f"keyword: {keyword}", f"category: {category}"],
                        )
                        work_items.append(item)
                        item_counter += 1

        # If no specific items found, create generic ones based on task type
        if not work_items:
            task_type = self._infer_task_type(goal)
            generic_items = self._get_generic_work_items(task_type, goal)
            work_items.extend(generic_items)

        # Deduplicate similar items
        work_items = self._deduplicate_work_items(work_items)

        # Infer dependencies between work items
        work_items = self._infer_work_item_dependencies(work_items)

        return work_items

    def _get_generic_work_items(self, task_type: TaskType, goal: Goal) -> List[WorkItem]:
        """Get default work items for a task type when no keywords match."""
        generic_map: Dict[TaskType, List[Tuple[str, str, float]]] = {
            TaskType.RESEARCH: [
                ("Research", "Gather information and analyze options", 1.5),
                ("Analyze", "Synthesize findings and draw conclusions", 1.0),
                ("Document", "Record research results and recommendations", 0.5),
            ],
            TaskType.IMPLEMENTATION: [
                ("Design", "Plan the implementation approach", 1.0),
                ("Implement", "Build the core functionality", 3.0),
                ("Test", "Verify the implementation works correctly", 1.5),
                ("Document", "Document the changes", 0.5),
            ],
            TaskType.DEBUGGING: [
                ("Reproduce", "Capture reproduction steps", 1.0),
                ("Isolate", "Narrow down root cause", 1.5),
                ("Fix", "Apply targeted corrective change", 1.0),
                ("Verify", "Run regression tests", 1.0),
            ],
            TaskType.REFACTORING: [
                ("Audit", "Identify improvement targets", 1.0),
                ("Extract", "Extract shared abstractions", 1.5),
                ("Refactor", "Apply transformations", 2.0),
                ("Verify", "Run full test suite", 1.5),
            ],
            TaskType.INTEGRATION: [
                ("Design Contract", "Define integration interface", 1.0),
                ("Build Adapters", "Build adapters on both sides", 2.0),
                ("Integrate", "Wire together with validation", 1.5),
                ("Test", "Run integration tests", 1.0),
            ],
            TaskType.DOCUMENTATION: [
                ("Outline", "Plan documentation structure", 0.5),
                ("Write", "Create documentation content", 1.5),
                ("Review", "Review for accuracy and completeness", 0.5),
            ],
            TaskType.TESTING: [
                ("Plan", "Design test strategy and cases", 1.0),
                ("Implement", "Write test code", 2.0),
                ("Execute", "Run tests and collect results", 1.0),
                ("Report", "Document test results", 0.5),
            ],
            TaskType.DEPLOYMENT: [
                ("Prepare", "Prepare deployment artifacts", 1.0),
                ("Deploy", "Execute deployment", 1.0),
                ("Verify", "Validate deployment success", 0.5),
                ("Rollback Plan", "Document rollback procedure", 0.5),
            ],
            TaskType.MAINTENANCE: [
                ("Assess", "Evaluate current state and needs", 0.5),
                ("Update", "Apply updates/patches", 1.0),
                ("Verify", "Confirm system health", 0.5),
            ],
        }
        items = generic_map.get(task_type, generic_map[TaskType.UNKNOWN])
        return [
            WorkItem(
                id=f"wi_{goal.id}_{i}",
                title=f"{title}: {goal.name}",
                description=desc,
                category=title.lower().split()[0],
                estimated_effort=effort,
                signals=[f"task_type: {task_type.value}"],
            )
            for i, (title, desc, effort) in enumerate(items)
        ]

    def _estimate_effort(self, subcategory: str) -> float:
        """Estimate relative effort for a work subcategory."""
        effort_map = {
            "research": 1.5, "design": 1.0, "prototype": 2.0,
            "implement": 3.0, "refactor": 2.0, "integrate": 1.5,
            "configure": 0.5, "test": 1.5, "debug": 1.5,
            "benchmark": 1.0, "document": 0.5, "changelog": 0.3,
            "review": 0.5, "release": 1.0, "outline": 0.3,
            "write": 1.5, "plan": 1.0, "execute": 1.0,
            "report": 0.5, "prepare": 1.0, "deploy": 1.0,
            "verify": 0.5, "assess": 0.5, "update": 1.0,
            "reproduce": 1.0, "isolate": 1.5, "fix": 1.0,
            "audit": 1.0, "extract": 1.5,
        }
        return effort_map.get(subcategory.lower(), 1.0)

    def _deduplicate_work_items(self, items: List[WorkItem]) -> List[WorkItem]:
        """Remove duplicate or highly similar work items."""
        seen_titles: Set[str] = set()
        unique_items: List[WorkItem] = []
        for item in items:
            # Normalize title for comparison
            norm_title = item.title.lower().strip()
            # Extract core action (first word before colon)
            core = norm_title.split(":")[0].strip()
            if core not in seen_titles:
                seen_titles.add(core)
                unique_items.append(item)
        return unique_items

    def _infer_work_item_dependencies(self, items: List[WorkItem]) -> List[WorkItem]:
        """Infer logical dependencies between work items based on categories."""
        # Define category precedence (must come before)
        precedes: Dict[str, List[str]] = {
            "research": ["design", "prototype", "implement", "refactor", "integrate"],
            "design": ["prototype", "implement", "refactor", "integrate"],
            "prototype": ["implement", "integrate"],
            "audit": ["extract", "refactor"],
            "extract": ["refactor"],
            "implement": ["test", "debug", "benchmark", "integrate", "document", "verify", "release"],
            "refactor": ["test", "verify"],
            "integrate": ["test", "verify"],
            "configure": ["test", "verify", "deploy"],
            "test": ["document", "review", "release"],
            "debug": ["test", "verify", "release"],
            "benchmark": ["document", "review"],
            "document": ["review", "release"],
            "changelog": ["release"],
            "review": ["release"],
            "plan": ["implement", "execute", "test"],
            "execute": ["test", "verify"],
        }

        for i, item in enumerate(items):
            for j, other in enumerate(items):
                if i == j:
                    continue
                if other.category in precedes.get(item.category, []):
                    if other.id not in item.dependencies:
                        item.dependencies.append(other.id)
        return items

    def decompose_semantic(
        self,
        goal_id: str,
        max_subtasks: Optional[int] = None,
        use_cache: bool = True,
    ) -> List["SubtaskSuggestion"]:
        """Semantic decomposition based on work item extraction.

        This is the main enhanced decomposition method that:
        1. Extracts logical work items from the goal description
        2. Orders them by dependency and category precedence
        3. Groups into milestones for complex goals
        4. Uses deterministic caching

        Returns a list of SubtaskSuggestion objects ready for apply_decomposition.
        """
        with self._lock:
            goal = self._goals.get(goal_id)
            if not goal:
                return []

        # Check cache first
        if use_cache:
            cache_key = self._compute_decomposition_cache_key(goal)
            cached = self._get_cached_decomposition(goal_id, cache_key)
            if cached:
                return cached.suggestions

        # Extract work items
        work_items = self.extract_work_items(goal_id)
        if not work_items:
            # Fall back to adaptive decomposition
            return self.decompose_adaptive(goal_id, max_subtasks)

        # Topologically sort by dependencies
        ordered_items = self._topological_sort_work_items(work_items)

        # Apply max_subtasks limit
        if max_subtasks is not None and max_subtasks > 0:
            ordered_items = ordered_items[:max_subtasks]

        # Convert to SubtaskSuggestion objects
        suggestions: List["SubtaskSuggestion"] = []
        for i, item in enumerate(ordered_items):
            # Generate a clean name without the work item ID prefix
            clean_name = f"{item.category.title()}: {goal.name}"
            description = item.description
            if i == 0 and goal.description:
                description = f"{description}\n\nParent context: {goal.description}"

            suggestion = SubtaskSuggestion(
                name=clean_name,
                description=description,
                priority=goal.priority,
                planner_category=item.category,
                estimated_hours=item.estimated_effort,
            )

            # Add duration estimate using planner's estimator
            estimated_hours = self._estimate_subtask_duration(goal, suggestion)
            suggestion.estimated_hours = estimated_hours

            suggestions.append(suggestion)

        # Generate milestones for complex goals
        milestones: List[Milestone] = []
        complexity = self.assess_complexity(goal_id)
        if complexity and complexity.level in (ComplexityLevel.COMPLEX, ComplexityLevel.VERY_COMPLEX):
            milestones = self._generate_semantic_milestones(goal_id, work_items, suggestions)

        # Cache the result
        if use_cache:
            self._store_decomposition_cache(goal_id, cache_key, suggestions, milestones, complexity.level if complexity else ComplexityLevel.SIMPLE)

        return suggestions

    def _topological_sort_work_items(self, items: List[WorkItem]) -> List[WorkItem]:
        """Sort work items by dependencies and category precedence.

        Uses Kahn's algorithm for topological sorting, with category order
        as tiebreaker.
        """
        # Build adjacency list and in-degree count
        id_to_item = {item.id: item for item in items}
        adj: Dict[str, List[str]] = {item.id: [] for item in items}
        in_degree: Dict[str, int] = {item.id: 0 for item in items}

        for item in items:
            for dep_id in item.dependencies:
                if dep_id in id_to_item:
                    adj[dep_id].append(item.id)
                    in_degree[item.id] += 1

        # Kahn's algorithm
        queue = [item_id for item_id, deg in in_degree.items() if deg == 0]
        # Sort queue by category order for deterministic tiebreaking
        queue.sort(key=lambda x: (self._CATEGORY_ORDER.get(id_to_item[x].category, 99), x))

        result: List[WorkItem] = []
        while queue:
            current_id = queue.pop(0)
            current = id_to_item[current_id]
            result.append(current)
            for neighbor_id in adj[current_id]:
                in_degree[neighbor_id] -= 1
                if in_degree[neighbor_id] == 0:
                    queue.append(neighbor_id)
            # Re-sort queue for deterministic ordering
            queue.sort(key=lambda x: (self._CATEGORY_ORDER.get(id_to_item[x].category, 99), x))

        # If there are remaining items (cycles), append them
        remaining = [item for item in items if item.id not in {r.id for r in result}]
        remaining.sort(key=lambda x: (self._CATEGORY_ORDER.get(x.category, 99), x.id))
        result.extend(remaining)

        return result

    def _generate_semantic_milestones(
        self,
        goal_id: str,
        work_items: List[WorkItem],
        suggestions: List["SubtaskSuggestion"],
    ) -> List[Milestone]:
        """Generate meaningful milestones based on work item categories.

        Groups work items into logical phases (research -> design -> implement -> verify).
        """
        with self._lock:
            goal = self._goals.get(goal_id)
            if not goal:
                return []

        # Group items by semantic phase
        phase_groups: Dict[str, List[WorkItem]] = defaultdict(list)
        phase_order = ["research", "design", "prototype", "audit", "extract",
                       "implement", "refactor", "integrate", "configure",
                       "test", "debug", "benchmark",
                       "document", "changelog",
                       "review", "release", "plan", "execute", "verify", "prepare", "deploy", "assess", "update", "outline", "write"]

        for item in work_items:
            phase = item.category
            if phase not in phase_order:
                phase = "implement"  # default
            phase_groups[phase].append(item)

        # Create milestones for phases that have items, in order
        milestones: List[Milestone] = []
        phase_names = {
            "research": "Research & Analysis",
            "design": "Design & Planning",
            "prototype": "Prototyping",
            "audit": "Code Audit",
            "extract": "Abstraction Extraction",
            "implement": "Core Implementation",
            "refactor": "Refactoring",
            "integrate": "Integration",
            "configure": "Configuration",
            "test": "Testing",
            "debug": "Debugging",
            "benchmark": "Benchmarking",
            "document": "Documentation",
            "changelog": "Release Documentation",
            "review": "Review & Approval",
            "release": "Release & Deployment",
            "plan": "Planning",
            "execute": "Execution",
            "verify": "Verification",
            "prepare": "Preparation",
            "deploy": "Deployment",
            "assess": "Assessment",
            "update": "Updates",
            "outline": "Outlining",
            "write": "Writing",
        }

        for phase in phase_order:
            items = phase_groups.get(phase, [])
            if not items:
                continue
            # Get corresponding suggestions - matching by category
            suggestion_indices = []
            for i, s in enumerate(suggestions):
                for item in items:
                    if s.name.startswith(f"{item.category.title()}:"):
                        suggestion_indices.append(i)
                        break
            if not suggestion_indices:
                # Fallback: map first N suggestions
                suggestion_indices = list(range(min(len(items), len(suggestions))))

            milestone = Milestone(
                id=f"ms_{goal_id}_{uuid.uuid4().hex[:8]}",
                name=f"Milestone {len(milestones) + 1}: {phase_names.get(phase, phase.title())}",
                description=f"Complete {phase} phase: {', '.join([suggestions[i].name for i in suggestion_indices if i < len(suggestions)])}",
                order=len(milestones) + 1,
                subtask_ids=[suggestions[i].name for i in suggestion_indices if i < len(suggestions)],
                completed=False,
            )
            milestones.append(milestone)

        # Persist milestones
        if milestones:
            goal.metadata["milestones"] = [m.to_dict() for m in milestones]
            goal.metadata["has_milestones"] = True
            goal.updated_at = self._now()
            self._save_file()

        return milestones

    # --- complexity assessment ---

    def _infer_task_type(self, goal: Goal) -> TaskType:
        """Infer a goal's task type from its name and description."""
        text = f"{goal.name} {goal.description}".lower()
        type_patterns: List[Tuple[List[str], TaskType]] = [
            (["debug", "fix", "bug", "repair", "troubleshoot", "fix the"], TaskType.DEBUGGING),
            (["refactor", "rewrite", "restructure", "clean up", "cleanup"], TaskType.REFACTORING),
            (["research", "investigate", "explore", "survey", "study"], TaskType.RESEARCH),
            (["document", "documentation", "readme", "tutorial", "guide"], TaskType.DOCUMENTATION),
            (["test", "testing", "qa", "verify", "validate", "acceptance"], TaskType.TESTING),
            (["integrat", "connect", "wire", "bridge", "adaptor", "adapter"], TaskType.INTEGRATION),
            (["deploy", "release", "publish", "ship", "launch"], TaskType.DEPLOYMENT),
            (["maintain", "maintenance", "patch", "upgrade", "update dependency"], TaskType.MAINTENANCE),
            (["implement", "build", "create", "develop", "add", "code", "write"], TaskType.IMPLEMENTATION),
        ]
        for keywords, task_type in type_patterns:
            if any(kw in text for kw in keywords):
                return task_type
        return TaskType.UNKNOWN

    def assess_complexity(self, goal_id: str) -> Optional["GoalComplexity"]:
        """Assess goal complexity using deterministic signals.

        Inspects description length, keyword presence, dependency count,
        child count, priority, and hierarchy depth.  Returns a
        ``GoalComplexity`` with numeric score, level enum, suggested
        depth, and suggested subtask count.

        Returns ``None`` when ``goal_id`` is unknown.
        """
        with self._lock:
            goal = self._goals.get(goal_id)
            if goal is None:
                return None
            desc = goal.description or ""
            signals: List[str] = []
            score = 0.0

            if goal.depends_on_ids:
                score += self._COMPLEXITY_SIGNAL_WEIGHTS["has_dependencies"]
                signals.append(f"has {len(goal.depends_on_ids)} dependency(s)")

            child_ids = self._children_ids_of(goal_id)
            if child_ids:
                score += self._COMPLEXITY_SIGNAL_WEIGHTS["has_children"]
                signals.append(f"already has {len(child_ids)} child goal(s)")

            depth = 0
            current = goal
            while current.parent_goal_id and self._goals.get(current.parent_goal_id):
                depth += 1
                current = self._goals[current.parent_goal_id]
            if depth >= 2:
                score += self._COMPLEXITY_SIGNAL_WEIGHTS["deep_hierarchy"]
                signals.append(f"nested {depth} level(s) deep")

            if len(desc) > 300:
                score += self._COMPLEXITY_SIGNAL_WEIGHTS["long_description"]
                signals.append("long description")

            if goal.priority == "critical":
                score += self._COMPLEXITY_SIGNAL_WEIGHTS["critical_priority"]
                signals.append("critical priority")

            desc_lower = desc.lower()
            keyword_hits = [kw for kw in self._SCOPE_KEYWORDS if kw in desc_lower]
            if keyword_hits:
                score += self._COMPLEXITY_SIGNAL_WEIGHTS["broad_scope_keywords"]
                signals.append(f"scope keywords: {', '.join(keyword_hits)}")

            score = min(1.0, round(score, 3))

            if score <= 0.05:
                level = ComplexityLevel.TRIVIAL
                depth_sug = 1
                subtask = 0
            elif score <= 0.2:
                level = ComplexityLevel.SIMPLE
                depth_sug = 1
                subtask = 1
            elif score <= 0.45:
                level = ComplexityLevel.MODERATE
                depth_sug = 2
                subtask = 3
            elif score <= 0.75:
                level = ComplexityLevel.COMPLEX
                depth_sug = 3
                subtask = 6
            else:
                level = ComplexityLevel.VERY_COMPLEX
                depth_sug = 4
                subtask = 10

            return GoalComplexity(
                level=level,
                score=score,
                suggested_depth=depth_sug,
                suggested_subtask_count=subtask,
                signals=signals,
            )

    def decompose_deterministic(
        self,
        goal_id: str,
        max_subtasks: Optional[int] = None,
    ) -> List["SubtaskSuggestion"]:
        """Deterministic decomposition that always produces the same output for the same goal.

        This method combines semantic decomposition with caching to ensure
        repeatable results. It's the recommended entry point for production use.
        """
        return self.decompose_semantic(goal_id, max_subtasks, use_cache=True)

    def get_decomposition_cache_info(self, goal_id: str) -> Dict[str, Any]:
        """Get information about cached decompositions for a goal."""
        with self._lock:
            goal = self._goals.get(goal_id)
            if not goal:
                return {"entries": 0, "cache_keys": []}
            cache = goal.metadata.get("decomposition_cache", [])
            return {
                "entries": len(cache),
                "cache_keys": [e.get("cache_key") for e in cache],
                "entries_detail": [
                    {
                        "cache_key": e.get("cache_key"),
                        "suggestion_count": len(e.get("suggestions", [])),
                        "milestone_count": len(e.get("milestones", [])),
                        "complexity_level": e.get("complexity_level"),
                        "created_at": e.get("created_at"),
                        "access_count": e.get("access_count", 0),
                    }
                    for e in cache
                ],
            }

    def clear_decomposition_cache(self, goal_id: str) -> bool:
        """Clear all cached decompositions for a goal."""
        with self._lock:
            goal = self._goals.get(goal_id)
            if not goal:
                return False
            goal.metadata.pop("decomposition_cache", None)
            goal.updated_at = self._now()
            self._save_file()
            return True

    def decompose_goal(
        self,
        goal_id: str,
        max_subtasks: int = 5,
    ) -> List["SubtaskSuggestion"]:
        """Return suggested child-goal drafts for ``goal_id``.

        This is the **non-mutating** read-side of Phase 6: callers receive
        a list of ``SubtaskSuggestion`` objects representing candidate
        child goals but **nothing is written to disk**. Use
        ``apply_decomposition`` to materialise approved suggestions.

        Returns an empty list when ``goal_id`` does not exist. The number
        of returned suggestions is ``min(max_subtasks, len(_DECOMPOSE_PHASES))``
        and is capped at ``0`` when ``max_subtasks`` is non-positive.
        Subtask priorities default to the parent goal's priority so the
        scheduler (Phase 5) treats them as a coherent group until the user
        edits them.
        """
        with self._lock:
            parent = self._goals.get(goal_id)
            if parent is None:
                return []
            inherited_priority = parent.priority
            parent_name = parent.name
            parent_description = parent.description

        if max_subtasks <= 0:
            return []
        phase_count = min(max_subtasks, len(self._DECOMPOSE_PHASES))
        suggestions: List["SubtaskSuggestion"] = []
        for index in range(phase_count):
            phase_name, phase_desc = self._DECOMPOSE_PHASES[index]
            suggestions.append(
                SubtaskSuggestion(
                    name=f"{phase_name}: {parent_name}",
                    description=phase_desc,
                    priority=inherited_priority,
                )
            )
        # Attach parent context to the first suggestion so reviewers can
        # surface the linkage without re-resolving the parent goal.
        if suggestions and parent_description:
            suggestions[0].description = (
                f"{suggestions[0].description}\n\n"
                f"Parent goal context: {parent_description}"
            )
        return suggestions

    def apply_decomposition(
        self,
        goal_id: str,
        suggestions: List["SubtaskSuggestion"],
        plan_manager: Optional[Any] = None,
    ) -> List[Goal]:
        """Persist ``suggestions`` as child goals of ``goal_id``.

        This is the **mutating** write-side of Phase 6 — the explicit
        manual-approval step. Each suggestion produces a child ``Goal``
        via the existing ``create(..., parent_goal_id=...)`` path, so the
        standard hierarchy invariants (Phase 3) apply automatically.

        When ``plan_manager`` is supplied, each accepted suggestion is
        also mirrored as a ``Task`` in the manager's active plan via the
        existing ``PlanManager.add_task(...)`` surface (no new planner
        surface is added in Phase 6 — the goal side is the source of
        truth and the planner side is a parallel projection). This is
        the **Planner integration** hook for Phase 6.

        ``suggestions`` referencing unknown parent id (``None`` /
        invalid / empty list) are ignored — the call returns ``[]`` rather
        than raising. Suggestions are applied in order, so callers that
        want ``depends_on_ids`` between siblings can post-edit the created
        goals via the Phase 1 ``update()`` verb after approval.
        """
        if not suggestions:
            return []
        with self._lock:
            if goal_id not in self._goals:
                return []
            created: List[Goal] = []
            for suggestion in suggestions:
                child = self.create(
                    name=suggestion.name,
                    description=suggestion.description,
                    priority=suggestion.priority,
                    parent_goal_id=goal_id,
                )
                created.append(child)

        # Planner integration happens after the goal-side persistence so
        # a planner failure can't roll back the goal tree. Errors are
        # swallowed (logged via the standard logger) — the goal side
        # remains the source of truth and surviving child count is
        # returned either way.
        if plan_manager is not None:
            try:
                for suggestion in suggestions:
                    kwargs = {}
                    if suggestion.planner_category is not None:
                        kwargs["category"] = suggestion.planner_category
                    if suggestion.estimated_hours is not None:
                        kwargs["estimated_hours"] = suggestion.estimated_hours
                    plan_manager.add_task(
                        title=suggestion.name,
                        description=suggestion.description,
                        **kwargs,
                    )
            except Exception as exc:  # noqa: BLE001
                from app.core.logger import logger
                logger.warning(
                    "[goals] planner side of decomposition failed: %s", exc
                )

        return created

    # --- hierarchical decomposition ---

    def decompose_hierarchical(
        self,
        goal_id: str,
        max_depth: int = 3,
        max_subtasks_per_level: int = 5,
    ) -> "HierarchicalDecompositionResult":
        """Perform multi-level recursive hierarchical decomposition.

        This recursively decomposes a goal into multiple levels of subtasks,
        building a decomposition tree. Each level uses semantic decomposition
        appropriate for the complexity of that sub-goal.

        Args:
            goal_id: The root goal to decompose
            max_depth: Maximum recursion depth (1 = single level)
            max_subtasks_per_level: Maximum subtasks at each level

        Returns:
            HierarchicalDecompositionResult containing the full tree
        """
        with self._lock:
            root_goal = self._goals.get(goal_id)
            if not root_goal:
                return HierarchicalDecompositionResult(
                    root_goal_id=goal_id,
                    suggestions=[],
                    strategy_used="hierarchical",
                )

        # Assess root complexity
        complexity = self.assess_complexity(goal_id)
        if not complexity:
            complexity = GoalComplexity(
                level=ComplexityLevel.SIMPLE,
                score=0.2,
                suggested_depth=1,
                suggested_subtask_count=max_subtasks_per_level,
            )

        # Determine actual depth based on complexity
        actual_depth = min(max_depth, complexity.suggested_depth)

        # Level 1 decomposition
        level1_suggestions = self._decompose_level(root_goal, max_subtasks_per_level, 1, actual_depth)

        # Recursively decompose children for deeper levels
        child_decompositions = {}
        total_hours = 0.0

        for suggestion in level1_suggestions:
            # Create a temporary child goal to recursively decompose
            child_goal = Goal(
                id=f"temp_{uuid.uuid4().hex[:12]}",
                name=suggestion.name,
                description=suggestion.description,
                priority=suggestion.priority,
                parent_goal_id=goal_id,
            )

            # Recursively decompose if depth allows
            if actual_depth > 1:
                child_result = self.decompose_hierarchical(
                    child_goal.id,
                    max_depth=actual_depth - 1,
                    max_subtasks_per_level=max(2, max_subtasks_per_level - 1),
                )
                child_decompositions[suggestion.name] = child_result
                total_hours += child_result.total_estimated_hours

            # Add estimated hours from this suggestion
            if suggestion.estimated_hours:
                total_hours += suggestion.estimated_hours

        # Generate milestones for the overall decomposition
        milestones = self._generate_semantic_milestones(
            goal_id,
            self.extract_work_items(goal_id),
            level1_suggestions,
        )

        return HierarchicalDecompositionResult(
            root_goal_id=goal_id,
            suggestions=level1_suggestions,
            child_decompositions=child_decompositions,
            milestones=milestones,
            complexity_assessment=complexity,
            strategy_used="hierarchical",
            total_estimated_hours=round(total_hours, 1),
            decomposition_depth=actual_depth,
        )

    def _decompose_level(
        self,
        goal: Goal,
        max_subtasks: int,
        current_depth: int,
        max_depth: int,
    ) -> List["SubtaskSuggestion"]:
        """Decompose a single level, choosing strategy based on depth and complexity."""
        # At deeper levels, prefer simpler strategies
        if current_depth >= max_depth:
            return self._template_decomposition_generator(goal, max_subtasks)

        complexity = self.assess_complexity(goal.id) if goal.id in self._goals else None
        if not complexity:
            # Create temporary assessment
            complexity = GoalComplexity(
                level=ComplexityLevel.MODERATE,
                score=0.3,
                suggested_depth=max_depth - current_depth + 1,
                suggested_subtask_count=max_subtasks,
            )

        # Choose strategy based on complexity and depth
        if complexity.level in (ComplexityLevel.COMPLEX, ComplexityLevel.VERY_COMPLEX):
            return self._semantic_decomposition_generator(goal, max_subtasks)
        else:
            return self._template_decomposition_generator(goal, max_subtasks)

    # --- agile decomposition ---

    def decompose_agile(
        self,
        goal_id: str,
        max_subtasks: int = 10,
        sprint_length_days: int = 14,
    ) -> List["SubtaskSuggestion"]:
        """Sprint-oriented decomposition with user stories and tasks.

        Creates decomposition following agile methodology:
        - Epics -> User Stories -> Tasks
        - Story points estimation
        - Sprint-ready groupings

        Args:
            goal_id: The goal to decompose
            max_subtasks: Maximum number of suggestions
            sprint_length_days: Sprint length for capacity planning

        Returns:
            List of SubtaskSuggestion representing user stories/tasks
        """
        with self._lock:
            goal = self._goals.get(goal_id)
            if not goal:
                return []

        # Extract work items as base
        work_items = self.extract_work_items(goal_id)
        if not work_items:
            return self._template_decomposition_generator(goal, max_subtasks)

        # Group into "epics" (major feature areas)
        epic_groups: Dict[str, List[WorkItem]] = defaultdict(list)
        for item in work_items:
            # Group by high-level category
            if item.category in ("research", "design", "prototype"):
                epic = "Discovery"
            elif item.category in ("implement", "refactor", "integrate"):
                epic = "Development"
            elif item.category in ("test", "debug", "benchmark"):
                epic = "Quality Assurance"
            elif item.category in ("document", "changelog", "review"):
                epic = "Documentation & Review"
            elif item.category in ("release", "deploy", "configure"):
                epic = "Delivery"
            else:
                epic = "Other"
            epic_groups[epic].append(item)

        suggestions: List["SubtaskSuggestion"] = []
        story_counter = 0

        # Create user stories from epics
        for epic_name, items in epic_groups.items():
            if story_counter >= max_subtasks:
                break

            # Create high-level user story (epic)
            epic_story = SubtaskSuggestion(
                name=f"Epic: {epic_name} - {goal.name}",
                description=f"Epic covering {epic_name.lower()} for: {goal.description or goal.name}",
                priority=goal.priority,
                planner_category="epic",
                estimated_hours=sum(i.estimated_effort for i in items) * 0.5,  # Epic is larger
            )
            suggestions.append(epic_story)
            story_counter += 1

            # Create user stories from work items
            for item in items:
                if story_counter >= max_subtasks:
                    break
                story = SubtaskSuggestion(
                    name=f"Story: {item.category.title()} - {goal.name}",
                    description=f"As a developer, I want to {item.category} so that {goal.name.lower()}. {item.description}",
                    priority=goal.priority,
                    planner_category="user_story",
                    estimated_hours=item.estimated_effort,
                )
                suggestions.append(story)
                story_counter += 1

        # If we have room, add sprint planning/meta tasks
        if story_counter < max_subtasks:
            planning = SubtaskSuggestion(
                name=f"Sprint Planning: {goal.name}",
                description=f"Plan sprint(s) for {sprint_length_days}-day iterations covering this goal",
                priority=goal.priority,
                planner_category="planning",
                estimated_hours=1.0,
            )
            suggestions.append(planning)
            story_counter += 1

        if story_counter < max_subtasks:
            retrospective = SubtaskSuggestion(
                name=f"Retrospective: {goal.name}",
                description="Review sprint outcomes and identify improvements",
                priority=goal.priority,
                planner_category="retrospective",
                estimated_hours=0.5,
            )
            suggestions.append(retrospective)

        return suggestions[:max_subtasks]

    # --- waterfall decomposition ---

    def decompose_waterfall(
        self,
        goal_id: str,
        max_subtasks: int = 7,
    ) -> List["SubtaskSuggestion"]:
        """Sequential phase decomposition (Waterfall model).

        Creates a linear sequence of phases:
        1. Requirements Analysis
        2. System Design
        3. Implementation
        4. Integration & Testing
        5. Deployment
        6. Maintenance

        Args:
            goal_id: The goal to decompose
            max_subtasks: Maximum number of phases (capped at 6)

        Returns:
            List of SubtaskSuggestion representing waterfall phases
        """
        with self._lock:
            goal = self._goals.get(goal_id)
            if not goal:
                return []

        # Define waterfall phases with descriptions
        waterfall_phases = [
            ("Requirements Analysis", "Gather, analyze, and document functional and non-functional requirements", "requirements"),
            ("System Design", "Create high-level and detailed design specifications", "design"),
            ("Implementation", "Build the system according to design specifications", "implementation"),
            ("Integration & Testing", "Integrate components and perform system/integration testing", "testing"),
            ("Deployment", "Deploy to production environment", "deployment"),
            ("Maintenance & Operations", "Monitor, maintain, and support the system", "maintenance"),
        ]

        # Adjust phases based on task type
        task_type = self._infer_task_type(goal)
        if task_type == TaskType.RESEARCH:
            waterfall_phases = [
                ("Literature Review", "Survey existing research and approaches", "research"),
                ("Hypothesis Formation", "Define research questions and hypotheses", "design"),
                ("Experimentation", "Conduct experiments and collect data", "implementation"),
                ("Analysis", "Analyze results and validate hypotheses", "testing"),
                ("Documentation", "Document findings and conclusions", "documentation"),
            ]
        elif task_type == TaskType.DEBUGGING:
            waterfall_phases = [
                ("Reproduction", "Capture and isolate reproduction steps", "requirements"),
                ("Root Cause Analysis", "Identify the underlying cause", "design"),
                ("Fix Implementation", "Apply targeted corrective change", "implementation"),
                ("Verification", "Run regression and confirm fix", "testing"),
                ("Documentation", "Record findings and preventive measures", "documentation"),
            ]
        elif task_type == TaskType.DOCUMENTATION:
            waterfall_phases = [
                ("Planning", "Define scope, audience, and structure", "requirements"),
                ("Outlining", "Create detailed content outline", "design"),
                ("Writing", "Produce documentation content", "implementation"),
                ("Review", "Technical and editorial review", "testing"),
                ("Publishing", "Publish and distribute documentation", "deployment"),
            ]

        suggestions: List["SubtaskSuggestion"] = []
        phase_count = min(max_subtasks, len(waterfall_phases))

        for i in range(phase_count):
            phase_name, phase_desc, category = waterfall_phases[i]
            # Waterfall is strictly sequential - each phase depends on previous
            suggestion = SubtaskSuggestion(
                name=f"Phase {i+1}: {phase_name} - {goal.name}",
                description=f"{phase_desc} for: {goal.name}. {goal.description}",
                priority=goal.priority,
                planner_category=category,
                estimated_hours=self._estimate_waterfall_phase_hours(category, i, phase_count),
            )
            suggestions.append(suggestion)

        return suggestions

    def _estimate_waterfall_phase_hours(self, category: str, phase_index: int, total_phases: int) -> float:
        """Estimate hours for waterfall phase based on typical distribution."""
        # Typical waterfall effort distribution (percentages)
        phase_weights = {
            "requirements": 0.10,
            "design": 0.15,
            "implementation": 0.40,
            "testing": 0.20,
            "deployment": 0.10,
            "maintenance": 0.05,
            "research": 0.25,
            "documentation": 0.15,
        }
        weight = phase_weights.get(category, 1.0 / total_phases)
        base_hours = 40.0  # Assume ~1 week base
        return round(base_hours * weight, 1)

    # --- hybrid decomposition ---

    def decompose_hybrid(
        self,
        goal_id: str,
        max_subtasks: int = 8,
    ) -> List["SubtaskSuggestion"]:
        """Adaptive combination of strategies based on goal characteristics.

        Analyzes the goal and selects the best combination of:
        - Template for simple, well-understood goals
        - Semantic for goals with clear work items
        - Hierarchical for complex multi-level goals
        - Agile for iterative/feature work
        - Waterfall for sequential/regulated work

        Args:
            goal_id: The goal to decompose
            max_subtasks: Maximum number of suggestions

        Returns:
            List of SubtaskSuggestion from the best-fit strategy
        """
        with self._lock:
            goal = self._goals.get(goal_id)
            if not goal:
                return []

        # Assess characteristics
        complexity = self.assess_complexity(goal_id)
        task_type = self._infer_task_type(goal)
        work_items = self.extract_work_items(goal_id)
        has_children = bool(self._children_ids_of(goal_id))
        dep_count = len(goal.depends_on_ids)

        # Decision logic for strategy selection
        use_hierarchical = (
            complexity and complexity.level in (ComplexityLevel.COMPLEX, ComplexityLevel.VERY_COMPLEX)
            and not has_children  # Don't re-decompose if already has children
        )
        use_agile = (
            task_type in (TaskType.IMPLEMENTATION, TaskType.FEATURE, TaskType.MAINTENANCE)
            and complexity and complexity.level in (ComplexityLevel.MODERATE, ComplexityLevel.COMPLEX)
        )
        use_waterfall = (
            task_type in (TaskType.DEPLOYMENT, TaskType.INTEGRATION)
            or (dep_count > 3)  # Many dependencies suggests sequential
        )
        use_semantic = len(work_items) > 3

        # Strategy selection priority
        if use_hierarchical:
            # For complex goals, use hierarchical but return top level only
            result = self.decompose_hierarchical(goal_id, max_depth=2, max_subtasks_per_level=max_subtasks)
            return result.suggestions
        elif use_agile:
            return self.decompose_agile(goal_id, max_subtasks)
        elif use_waterfall:
            return self.decompose_waterfall(goal_id, max_subtasks)
        elif use_semantic:
            return self.decompose_semantic(goal_id, max_subtasks)
        else:
            # Default to template
            return self.decompose_deterministic(goal_id, max_subtasks)

    # --- adaptive decomposition (fallback) ---

    def decompose_adaptive(
        self,
        goal_id: str,
        max_subtasks: Optional[int] = None,
    ) -> List["SubtaskSuggestion"]:
        """Adaptive decomposition that automatically selects the best strategy.

        This is the main entry point for automatic decomposition. It:
        1. Assesses goal complexity and type
        2. Selects the best registered strategy
        3. Executes the strategy
        4. Returns suggestions

        Args:
            goal_id: The goal to decompose
            max_subtasks: Maximum suggestions (None = use strategy default)

        Returns:
            List of SubtaskSuggestion
        """
        with self._lock:
            goal = self._goals.get(goal_id)
            if not goal:
                return []

        # Get applicable strategies
        strategies = self.get_applicable_strategies(goal)
        if not strategies:
            # Fallback to template
            return self._template_decomposition_generator(goal, max_subtasks or 5)

        # Use highest-weighted strategy
        best_strategy = strategies[0]

        # Execute strategy generator
        params = {"max_subtasks": max_subtasks or 5}
        try:
            suggestions = best_strategy.generator(goal, max_subtasks or 5, params)
            return suggestions
        except Exception:
            # Fallback on error
            return self._template_decomposition_generator(goal, max_subtasks or 5)

    # --- feedback collection ---

    def submit_decomposition_feedback(self, feedback: "DecompositionFeedback") -> bool:
        """Submit feedback on a decomposition for continuous improvement.

        Args:
            feedback: DecompositionFeedback object with rating and details

        Returns:
            True if feedback was stored
        """
        self._decomposition_feedback.append(feedback)
        # Also persist to goal metadata
        with self._lock:
            goal = self._goals.get(feedback.goal_id)
            if goal:
                fb_list = goal.metadata.get("decomposition_feedback", [])
                fb_list.append(feedback.to_dict())
                goal.metadata["decomposition_feedback"] = fb_list
                goal.updated_at = self._now()
                self._save_file()
        return True

    def get_decomposition_feedback(self, goal_id: Optional[str] = None) -> List["DecompositionFeedback"]:
        """Get decomposition feedback, optionally filtered by goal."""
        if goal_id:
            return [f for f in self._decomposition_feedback if f.goal_id == goal_id]
        return list(self._decomposition_feedback)

    def get_strategy_performance(self, strategy_name: str) -> Dict[str, Any]:
        """Get performance metrics for a decomposition strategy."""
        feedback = [
            f for f in self._decomposition_feedback
            if f.decomposition_cache_key  # Has cache key means it was from a strategy
        ]
        if not feedback:
            return {"strategy": strategy_name, "ratings": [], "avg_rating": 0.0, "count": 0}

        ratings = [f.rating for f in feedback]
        return {
            "strategy": strategy_name,
            "ratings": ratings,
            "avg_rating": round(sum(ratings) / len(ratings), 2),
            "count": len(ratings),
            "successful_items": sum(len(f.successful_suggestions) for f in feedback),
            "failed_items": sum(len(f.failed_suggestions) for f in feedback),
        }