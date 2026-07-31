from app.agent.executor import Executor
from app.agent.planner import Planner
from app.brain.state import ConversationState
from app.core.llm import LLM
from app.planner.plan_manager import PlanManager, Plan, TaskCategory
from app.planner.task import Task, TaskStatus
from typing import Optional, Dict, List, Any
from app.core.logger import logger
from app.core.project_index import ProjectIndex
from app.core.symbol_index import SymbolIndex
from app.core.tool_manager import ToolManager
from app.editing.patch_engine import PatchEngine
from app.capabilities.router import route_query
from app.capabilities.formatter import format_capability_result
from app.editing.patch_generator import PatchGenerator
from app.intelligence.context_builder import ContextBuilder
from app.intelligence.dependency_graph import DependencyGraph
from app.intelligence.file_locator import FileLocator
from app.intelligence.lexical_search import LexicalSearch
from app.intent import (
    should_answer_directly,
    classify_intent,
    should_clarify,
    IntentType,
)
from app.memory.episodic_memory import EpisodicMemory, create_episodic_memory
from app.memory.engineering_lessons import EngineeringLessonStorage, LessonSeverity, LessonType
from app.memory.experience_memory import ExperienceMemory
from app.memory.goals import GoalStorage
from app.memory.long_term_memory import LongTermMemory, create_long_term_memory
from app.memory.project_memory import ProjectMemory
from app.memory.semantic_memory import SemanticMemory, create_semantic_memory
from app.memory.task_memory import TaskMemory, create_task_memory
from app.memory.unified_retrieval import create_unified_retrieval
from app.memory.working_memory import WorkingMemory, get_working_memory
from app.conversational_control import ConversationControlHandler, create_conversation_control_handler

# Phase C: Memory Optimization
from app.memory.consolidation import ConsolidationEngine, create_consolidation_engine, ConsolidationTrigger
from app.memory.forgetting import ForgettingEngine, create_forgetting_engine
from app.memory.cross_references import CrossMemoryReferences, create_cross_memory_references
from app.memory.retrieval_ranking import RankingEngine, create_ranking_engine, RankedUnifiedRetrieval
from app.verification.repair_loop import RepairLoop
from app.verification.runner import VerificationRunner
from app.rag import SimpleRetriever

# Decision Management (Phase 1)
from app.decision.manager import DecisionManager, DecisionManagerConfig, decide_planning_strategy
from app.decision.models import (
    DecisionContext,
    DecisionOption,
    DecisionType,
    DecisionCategory,
)

# Phase 1: Failure Recovery
from app.failure_recovery.detector import FailureDetector, FailureEvent
from app.failure_recovery.analyzer import RootCauseAnalyzer
from app.failure_recovery.orchestrator import RecoveryOrchestrator, RecoveryStrategy

# Self-Evaluation
from app.evaluation.manager import EvaluationManager, evaluate_before_delivery
from app.evaluation.models import EvaluationType

try:
    from app.retrieval.enhanced_retriever import EnhancedRetriever
except ImportError:
    EnhancedRetriever = SimpleRetriever # Fallback if enhanced version not available


def _has_sufficient_context(task: str, intent: IntentType) -> bool:
    """
    Check if an engineering task has sufficient context to execute.

    Returns True if the task contains actionable information (file paths, code, errors, etc.),
    False if essential information is missing and user should be asked for it.
    """
    task_lower = task.lower()

    # Patterns that indicate sufficient context is provided
    has_file_path = bool(re.search(r'\b\w+\.(py|js|ts|jsx|tsx|java|cpp|cc|c|h|rs|go|rb|php|cs|kt|swift|scala|r|m|pl|sh|bash|zsh|fish|ps1|bat|cmd|dockerfile|makefile|cmake|gradle|xml|json|yaml|yml|toml|ini|cfg|conf|md|txt|html|css|scss|sass|less|vue|svelte)\b', task_lower))

    has_code_block = '```' in task

    # Repository/project references (e.g., "this repository", "the repo", "my project")
    has_repo_reference = any(phrase in task_lower for phrase in [
        'this repository', 'the repository', 'my repository', 'the repo', 'my repo',
        'this project', 'my project', 'the project', 'this codebase', 'the codebase',
        'this code base', 'the code base', 'entire project', 'whole project', 'full project'
    ])

    # Actual traceback patterns: file paths with line numbers, exception types with details
    has_traceback = bool(re.search(
        r'(traceback \(most recent call last\)|file\s+\".*\",\s+line\s+\d+|'
        r'(syntaxerror|typeerror|valueerror|attributeerror|importerror|modulenotfounderror|keyerror|indexerror|runtimeerror|assertionerror|nameerror|indentationerror|zerodivisionerror):\s+\w+)',
        task_lower
    ))

    # Error message with substantial content (not just the word "error")
    has_error_message = bool(re.search(r'(error|exception|fail|crash|bug)\s*:', task_lower)) and len(task) > 30

    # Colon followed by substantial content (e.g., "Fix this: actual error info")
    has_colon_content = ':' in task and len(task.split(':', 1)[-1].strip()) >= 14

    # Natural language specific action: "by <action>", "to <action>", "for <action>"
    # OR action verb at start with file path: "Upgrade requirements.txt", "Fix bug in app.py"
    has_specific_action = bool(re.search(
        r'\b(by|to|for)\s+(upgrad|add|remov|pin|sync|fix|install|upgrad|refactor|optimiz|implement|creat|build|test|delet|clean)\w*',
        task_lower
    ))
    # Action verb at start followed by file path: "Upgrade requirements.txt", "Fix app.py"
    has_action_with_file = bool(re.search(
        r'^(upgrad|fix|debug|review|explain|optimiz|refactor|implement|creat|build|test|delet|clean|modif|chang|edit)\w*\s+.*\.(py|txt|json|yaml|yml|toml|ini|cfg|conf|md|js|ts|java|cpp|rs|go)\b',
        task_lower
    ))

    # ... rest of function

    # Intent-specific validation
    if intent == IntentType.FILE_OPERATION:
        # File operations need a file path AND specific action for ambiguous verbs
        ambiguous_verbs = ['update', 'modify', 'change', 'edit', 'upgrade']
        if any(verb in task_lower for verb in ambiguous_verbs):
            # "Update requirements.txt" - need specific action (colon content or code or action+file)
            return has_colon_content or has_code_block or has_traceback or has_action_with_file
        # Read/write/delete/create are explicit enough with just a file path
        return has_file_path

    elif intent == IntentType.CODE_TASK:
        # Code tasks need code, file path, or traceback
        # Exception: refactor/analyze on "this repository" is valid
        if 'refactor' in task_lower or 'analyze' in task_lower:
            return (has_file_path or has_code_block or has_traceback or
                    has_colon_content or has_repo_reference)
        return has_file_path or has_code_block or has_traceback or has_colon_content

    elif intent == IntentType.TASK:
        # General tasks: check if it's a fix/debug/review/optimize/update that needs context
        fix_debug_keywords = ['fix', 'debug', 'review', 'explain', 'optimize', 'refactor', 'analyze', 'update', 'upgrade', 'modify', 'change', 'edit']
        if any(kw in task_lower for kw in fix_debug_keywords):
            # These need code, file, or error context with SPECIFIC ACTION
            # A file path alone is not enough (e.g., "Update requirements.txt" is ambiguous)
            # Exception: refactor/analyze on "this repository" is valid
            if 'refactor' in task_lower or 'analyze' in task_lower:
                return (has_file_path or has_code_block or has_traceback or
                        has_colon_content or has_repo_reference)
            # For update/upgrade/modify/change/edit/fix/debug/review/explain/optimize:
            # Need specific action: colon content, code block, traceback, repo reference,
            # OR natural language specific action ("by X", "to X", "for X") WITH a file path,
            # OR action verb at start with file path ("Upgrade requirements.txt")
            return (has_code_block or has_traceback or has_colon_content or has_repo_reference or
                    (has_file_path and has_specific_action) or has_action_with_file)
        # Other tasks (build, run, create, etc.) may not need additional context
        return True

    elif intent == IntentType.TOOL_REQUEST:
        # Tool requests like "run pytest" are self-contained
        return True

    elif intent == IntentType.GIT_OPERATION:
        # Git operations typically don't need additional context
        return True

    # Default: assume sufficient context
    return True


def _get_missing_context_prompt(task: str, intent: IntentType) -> str:
    """Generate a helpful prompt asking for missing context."""
    task_lower = task.lower()

    if 'fix' in task_lower and ('traceback' in task_lower or 'error' in task_lower):
        return "I'd be happy to help fix that. Please paste the complete traceback or error message."

    if 'debug' in task_lower:
        return "I'd be happy to help debug. Please provide the code, error message, or traceback."

    if 'review' in task_lower or 'explain' in task_lower:
        if 'function' in task_lower:
            return "Please provide the function code you'd like me to review or explain."
        return "Please provide the code you'd like me to review or explain."

    if 'optimize' in task_lower:
        return "Please provide the code you'd like me to optimize."

    if 'refactor' in task_lower:
        return "Please provide the code or file path you'd like me to refactor."

    if 'update' in task_lower or 'upgrade' in task_lower or 'modify' in task_lower:
        return "How would you like me to update this? Please specify the change (e.g., upgrade packages, add dependencies, pin versions, sync imports)."

    # Generic fallbacks based on intent
    if intent == IntentType.CODE_TASK:
        return "Please provide the code or file path you'd like me to work with."

    if intent == IntentType.FILE_OPERATION:
        return "Please specify the file path and the specific change you want."

    return "Could you please provide more details (code, file path, error message, etc.)?"


# Rule-based vocabulary for grouping engineering lessons recorded after
# solve() and repair() outcomes. See Priority 2 in SELF_LEARNING.md.
_LESSON_CATEGORIES = ("task", "test", "build", "refactor", "debug", "understand")


def _classify_engineering_category(task: str) -> str:
    """Return the first matching lesson category for a task description.

    The lookup is intentionally simple: a fixed set of keyword groups matched
    in priority order. Anything that does not match falls back to ``"task"``.
    No external calls, no LLM usage.
    """
    if not task:
        return "task"
    lowered = task.lower()
    keyword_map = {
        "test": ("test", "pytest", "spec"),
        "build": ("build", "compile", "install", "package"),
        "refactor": ("refactor", "rename", "restructure", "cleanup"),
        "debug": ("debug", "fix", "bug", "error", "traceback", "failure"),
        "understand": ("understand", "explain", "describe", "how does", "what does"),
    }
    # "task" acts as the catch-all below
    for category in ("test", "build", "refactor", "debug", "understand"):
        for keyword in keyword_map[category]:
            if keyword in lowered:
                return category
    return "task"


class FreyaAgent:
    def __init__(self, workspace=".", max_conversation_history=20, conversation_persistence_path: Optional[str] = None):
        self.workspace = workspace
        self.llm = LLM()
        self.tools = ToolManager(workspace)
        self.memory = ProjectMemory(workspace)
        self.experience_memory = ExperienceMemory(workspace)
        self.engineering_lessons = EngineeringLessonStorage(workspace)
        self.goal_storage = GoalStorage(workspace)
        self.plan_manager = PlanManager(workspace)
        self.executor = Executor(self.llm, self.tools, engineering_lessons=self.engineering_lessons)
        self.patch_engine = PatchEngine()
        self.patch_generator = PatchGenerator(self.llm, self.patch_engine)
        self.verifier = VerificationRunner(workspace)
        self.planner = Planner(self.llm, self.memory, engineering_lessons=self.engineering_lessons)

        # Conversation Memory - using ConversationState for backward compatibility
        self.conversation = ConversationState(
            max_history=max_conversation_history,
            persistence_path=conversation_persistence_path,
            workspace=workspace,
        )

        # Working Memory - scratchpad for active task execution
        self.working_memory = get_working_memory()

        # Phase B: Extended Memory Systems
        # Task Memory - persistent storage for active task execution state
        self.task_memory = create_task_memory(workspace)

        # Long-Term Memory - user preferences, permanent facts, cross-project knowledge
        self.long_term_memory = create_long_term_memory(workspace)

        # Episodic Memory - append-only event log for "what happened when"
        self.episodic_memory = create_episodic_memory(workspace)

        # Semantic Memory - general programming knowledge base
        self.semantic_memory = create_semantic_memory(workspace)

        # Unified Retrieval Layer - single interface for all memories
        self.unified_retrieval = create_unified_retrieval(self)

        # Phase C: Memory Optimization
        # Consolidation Engine - promotes high-value experiences/lessons to long-term memory
        self.consolidation_engine = create_consolidation_engine(
            experience_memory=self.experience_memory,
            engineering_lessons=self.engineering_lessons,
            long_term_memory=self.long_term_memory,
            project_memory=self.memory,
        )

        # Forgetting Engine - controlled TTL-based expiration and archival
        self.forgetting_engine = create_forgetting_engine(
            experience_memory=self.experience_memory,
            engineering_lessons=self.engineering_lessons,
            project_memory=self.memory,
            task_memory=self.task_memory,
            episodic_memory=self.episodic_memory,
            semantic_memory=self.semantic_memory,
            long_term_memory=self.long_term_memory,
            working_memory=self.working_memory,
        )

        # Cross-Memory References - traceability between memory types
        self.cross_references = create_cross_memory_references()

        # Ranking Engine - advanced relevance ranking for unified retrieval
        self.ranking_engine = create_ranking_engine(
            vector_db=None,  # Could be enhanced with vector DB later
            long_term_memory=self.long_term_memory,
        )
        self.ranked_retrieval = RankedUnifiedRetrieval(self.unified_retrieval, self.ranking_engine)

        # Phase 1: Decision Management
        # Central decision orchestrator integrating confidence, risk, goals, planning, memory
        self.decision_manager = DecisionManager(
            workspace=workspace,
            config=DecisionManagerConfig(
                min_confidence_for_auto_execute=0.6,
                min_confidence_for_recommendation=0.4,
                max_risk_for_auto_execute="medium",
                require_approval_above_risk="high",
                enable_explainable_decisions=True,
                enable_human_oversight=True,
                record_all_decisions=True,
                calibrate_confidence_from_outcomes=True,
                use_confidence_scoring=True,
                use_risk_assessment=True,
                use_goal_scheduling=True,
                use_memory_retrieval=True,
                use_intent_classification=True,
            ),
            goal_storage=self.goal_storage,
            unified_retrieval=self.unified_retrieval,
            intent_classifier=classify_intent,
            planner=self.planner,
            plan_manager=self.plan_manager,
        )

        # Phase 1: Failure Recovery
        # Unified failure detection, root cause analysis, and recovery orchestration
        self.failure_detector = FailureDetector(workspace=workspace)
        self.root_cause_analyzer = RootCauseAnalyzer()
        self.recovery_orchestrator = RecoveryOrchestrator(
            failure_detector=self.failure_detector,
            root_cause_analyzer=self.root_cause_analyzer,
            decision_manager=self.decision_manager,
            verification_callback=lambda: self.verifier.dry_run_verify(),
            max_recovery_attempts=3,
            workspace=workspace,
        )

        # Self-Evaluation - runs before declaring task completion
        self.evaluation_manager = EvaluationManager(
            workspace=workspace,
            agent=self,
            decision_manager=self.decision_manager,
            verifier=self.verifier,
        )

        # Progress tracking - stores the last execution's progress snapshot
        self.last_execution_progress: Optional[Dict[str, Any]] = None

        self.project_index = ProjectIndex(workspace)
        self.symbol_index = SymbolIndex(workspace)
        logger.info("Building project index...")
        self.project_index.build()
        logger.info("Building symbol index...")
        self.symbol_index.build()

        self.file_locator = FileLocator(self.symbol_index)
        self.lexical_search = LexicalSearch(self.symbol_index)
        self.dependency_graph = DependencyGraph(self.symbol_index)
        self.dependency_graph.build()
        self.context_builder = ContextBuilder(self.symbol_index, self.dependency_graph)
        self.retriever = EnhancedRetriever(self.symbol_index)
        logger.info(f"Indexed {len(self.project_index.files)} files.")
        logger.info(f"Indexed {len(self.symbol_index.symbols)} Python files.")

        # Initialize centralized conversational control handler
        self.conversation_control = create_conversation_control_handler(
            plan_manager=self.plan_manager,
            executor=self.executor,
            conversation_memory=self.conversation._memory if hasattr(self.conversation, '_memory') else None,
        )
        # Register execution callback for interruption
        self.conversation_control.register_execution_callback(self._request_execution_stop)

        logger.info("Freya Agent initialized")

    def _request_execution_stop(self) -> None:
        """Callback to request execution stop from conversation control."""
        # This will be checked by the executor via conversation_control.check_stop_requested()
        logger.info("[FreyaAgent] Execution stop requested via conversation control")

    def build_context(self, task):
        matches = self.file_locator.locate(task)
        if not matches:
            for word in task.replace(",", " ").replace(".", " ").split():
                matches.extend(self.file_locator.locate(word))

        matches.extend(self.lexical_search.search(task, limit=5))
        matches.extend(self.retriever.retrieve(task, limit=5))
        unique = []
        seen = set()
        for match in matches:
            key = (match["file"], match["type"], match["name"], match["line"])
            if key not in seen:
                seen.add(key)
                unique.append(match)
        return self.context_builder.build(unique[:5]) if unique else ""

    def run(self, task, allow_mutations=True):
        """Plan, execute bounded workspace actions, and summarize the result. Mutating tools will prompt for confirmation before each use."""
        classification = classify_intent(
            task,
            context={
                "last_intent": self.conversation.get_last_intent() if hasattr(self.conversation, 'get_last_intent') else None,
            }
        )

        # Conversational control and system status short-circuit all routing and bypass the LLM.
        if classification.is_control or classification.intent == IntentType.SYSTEM_STATUS:
            result = route_query(
                task, intent_type=classification.intent.value
            )
            if result is not None:
                answer = format_capability_result(result)
                self.conversation.add_message("user", task)
                self.conversation.add_message("assistant", answer, classification.intent.value)
                if self.conversation._persistence_path:
                    self.conversation.save()
                return answer
            # If no capability matched, fall through to LLM (but this shouldn't happen for SYSTEM_STATUS)

        # Mid-band confidence: ask a paraphrased clarifying question.
        if should_clarify(classification):
            clarifying_prompt = (
                "I'm not quite sure what the user wants yet. "
                "Ask a short, friendly clarifying question rather than guessing. "
                f"The user said: {task}"
            )
            answer = self.llm.ask(clarifying_prompt)
            self.memory.record(
                "clarification",
                {"request": task, "intent": classification.intent.value,
                 "confidence": classification.confidence, "outcome": answer[:500]},
            )
            self.conversation.add_message("user", task)
            self.conversation.add_message("assistant", answer, classification.intent.value)
            if self.conversation._persistence_path:
                self.conversation.save()
            return answer

        # Classify intent to determine if we need the engineering pipeline
        if should_answer_directly(task):
            # Chat, knowledge questions, and system status -> direct LLM response.
            # Low-confidence inputs are still routed here, but flagged for the LLM.
            conversation_history = self.conversation.get_history_text()
            low_confidence_block = ""
            if classification.is_low_confidence:
                low_confidence_block = (
                    "\n\nNote: The user's request is a bit unclear. "
                    "If you're not sure what they're asking for, ask a short, "
                    "friendly clarifying question rather than guessing.\n"
                )
            prompt = f"""{conversation_history}

User: {task}
{low_confidence_block}
Answer the user's request directly."""
            answer = self.llm.ask(prompt)
            self.memory.record("task", {"request": task, "outcome": answer[:500]})
            self.conversation.add_message("user", task)
            self.conversation.add_message("assistant", answer, classification.intent.value)
            if self.conversation._persistence_path:
                self.conversation.save()
            return answer

        # Validate that engineering tasks have sufficient context using Decision Manager
        from app.decision.manager import decide_context_sufficiency

        built_context = self.build_context(task)
        unified_context = self.unified_retrieval.retrieve_for_planner(task, {"phase": "planning"})
        memory_context = self.memory.context()
        if unified_context:
            combined_context = unified_context + "\n\n" + memory_context
        else:
            combined_context = memory_context

        context_sufficiency = decide_context_sufficiency(
            self.decision_manager,
            task=task,
            current_context=built_context + "\n\n" + combined_context,
            intent_type=classification.intent.value,
        )

        if not context_sufficiency.should_execute or context_sufficiency.requires_approval:
            # Missing essential information - ask user instead of inventing fake plans
            prompt = _get_missing_context_prompt(task, classification.intent)
            answer = self.llm.ask(prompt)
            self.memory.record("task", {"request": task, "outcome": answer[:500]})
            self.conversation.add_message("user", task)
            self.conversation.add_message("assistant", answer, classification.intent.value)
            if self.conversation._persistence_path:
                self.conversation.save()
            return answer

        # Engineering tasks -> full planning and execution pipeline
        context = built_context

        plan = self.planner.create_plan(task)
        # Priority 4 (Self-Learning): retrieve relevant Engineering Lessons and
        # ExperienceMemory hits immediately before execution so the post-
        # execute LLM prompt can use them. The retrieval uses the same APIs
        # exposed to the Planner (Priority 3) and the existing
        # ExperienceMemory.search() helper. Both calls are best-effort.
        lessons_block = self._build_run_lessons_block(task)
        experience_block = self._build_run_experience_block(task)
        allowed_tools = set(Executor.READ_ONLY_TOOLS)
        if allow_mutations:
            allowed_tools.update(Executor.MUTATING_TOOLS)

        # Start conversation control tracking for this execution
        self.conversation_control.start_execution(plan)
        # Pass conversation control to executor for stop/pause checking
        self.executor.set_conversation_control(self.conversation_control)

        # Human Plan Review Flow - allow user to review and modify plan before execution
        reviewed_plan = self._review_plan_with_user(plan, task)
        if reviewed_plan is None:
            # User rejected/cancelled the plan
            self.conversation.add_message("user", task)
            self.conversation.add_message("assistant", "Plan cancelled. Let me know if you'd like to try a different approach.", "plan_review")
            if self.conversation._persistence_path:
                self.conversation.save()
            return "Plan cancelled. Let me know if you'd like to try a different approach."

        # Execute using the Plan object (Executor now accepts Plan or dict)
        results = self.executor.execute_plan(reviewed_plan, allowed_tools)

        # Finish conversation control tracking
        success = True  # Assume success unless exception was raised
        self.conversation_control.finish_execution(success)

        # Capture progress tracking data from the plan's ProgressTracker
        if isinstance(plan, Plan):
            snapshot = plan._tracker.get_current_snapshot()
            self.last_execution_progress = {
                "plan_id": plan.id,
                "plan_name": plan.config.name,
                "total_tasks": snapshot.total_tasks,
                "completed_tasks": snapshot.completed_tasks,
                "in_progress_tasks": snapshot.in_progress_tasks,
                "pending_tasks": snapshot.pending_tasks,
                "blocked_tasks": snapshot.blocked_tasks,
                "overall_progress": snapshot.overall_progress,
                "tasks_by_status": snapshot.tasks_by_status,
                "tasks_by_priority": snapshot.tasks_by_priority,
                "tasks_by_category": snapshot.tasks_by_category,
                "snapshots_count": len(plan._tracker.get_snapshots()),
                "state_history": plan._tracker.get_state_history(),
            }

        # For the LLM prompt, use the plan's steps
        plan_steps = plan.tasks if hasattr(plan, 'tasks') else plan.get("steps", [])
        conversation_history = self.conversation.get_history_text()
        prompt = f"""{conversation_history}

User request:
{task}

Relevant project code:
{context}

Recent project memory:
{memory_context}

Execution plan:
{plan_steps}

Tool results:
{results}

{lessons_block}{experience_block}Answer the user's request using the relevant code above. Quote code only when it is the actual answer; otherwise summarize."""
        answer = self.llm.ask(prompt)
        self.memory.record("task", {"request": task, "outcome": answer[:500]})
        self.conversation.add_message("user", task)
        self.conversation.add_message("assistant", answer, classification.intent.value)
        if self.conversation._persistence_path:
            self.conversation.save()

        # Self-Evaluation for engineering tasks run through run()
        eval_result = self.evaluation_manager.evaluate_task_completion(
            task_description=task,
            original_request=task,
            task_id=f"run_{task[:30]}",
            plan_id=plan.id if isinstance(plan, Plan) else None,
            evaluation_type=EvaluationType.COMPREHENSIVE,
        )
        logger.info(f"[Self-Evaluation] {eval_result.summary}")

        if eval_result.requires_rework:
            logger.warning(f"[Self-Evaluation] Rework recommended: {eval_result.rework_reasons}")
        if eval_result.requires_human_review:
            logger.warning(f"[Self-Evaluation] Human review recommended (confidence: {eval_result.overall_confidence:.0%})")

        return answer

    def propose_patch(self, task):
        """Return a reviewable patch proposal without changing any files."""
        operations = self.patch_generator.propose(task, self.build_context(task))
        return {"operations": operations, "preview": self.patch_engine.preview(operations)}

    def apply_patch(self, proposal, allow_mutations=False):
        if not allow_mutations:
            raise PermissionError("Patch application requires allow_mutations=True.")
        return self.patch_engine.apply(self.tools, proposal["operations"])

    def verify(self):
        """Run automated tests without giving the model a shell."""
        return self.verifier.run_tests()

    def apply_patch_and_verify(self, proposal, allow_mutations=False):
        if not allow_mutations:
            raise PermissionError("Patch application requires allow_mutations=True.")
        result = self.patch_engine.apply_and_verify(
            self.tools, proposal["operations"], self.verifier
        )
        self.memory.record(
            "patch_verification",
            {
                "preview": proposal.get("preview", ""),
                "success": result["verification"].success,
                "rolled_back": result["rolled_back"],
            },
        )
        return result

    def solve(self, task, max_iterations=5, allow_mutations=False, success_condition=None):
        """Attempt to autonomously solve a task via adaptive replanning.

        This replaces the old restart-from-scratch loop with a cycle that:
        1. Creates a Plan on first iteration
        2. Executes the plan (or remaining incomplete tasks)
        3. On failure, marks failed tasks, generates new replacement tasks, and continues
        4. Preserves COMPLETED tasks across iterations

        Args:
            task (str): Description of the goal.
            max_iterations (int): Maximum number of propose-apply cycles.
            allow_mutations (bool): If True, allows the agent to modify files.
            success_condition (callable, optional): A function that takes (task, iteration,
                verification_result, history) and returns True if the task is considered
                successfully completed. If not provided, success is determined by verification.

        Returns:
            dict: {
                'success': bool,
                'iterations': int,
                'history': list of dicts per iteration containing plan, proposal, verification result,
                'replanning_count': int,
            }
        """
        if not allow_mutations:
            raise PermissionError("Autonomous solving requires allow_mutations=True.")
        context = self.build_context(task)

        # Initialize working memory for this solve() execution
        self.working_memory.start_task(f"solve_{task[:30]}")
        history = []
        plan = None
        replanning_count = 0

        for it in range(1, max_iterations + 1):
            # On first iteration, create a new plan. On subsequent iterations, reuse and adapt existing plan.
            if plan is None:
                # Use Decision Manager for initial planning decision
                plan_decision = decide_planning_strategy(
                    manager=self.decision_manager,
                    task=task,
                    context=context,
                    iteration=1,
                )
                plan = self.planner.create_plan(task)
            else:
                # Adaptive replanning: update the existing plan based on failures
                replanning_count += 1
                plan = self._replan_after_failure(plan, task, history)

            # Execute the plan (or remaining incomplete tasks)
            plan_steps = plan.tasks if hasattr(plan, 'tasks') else plan.get("steps", [])
            sub_task = "\n".join([t.title if hasattr(t, 'title') else str(t) for t in plan_steps]) if plan_steps else task
            try:
                proposal = self.patch_generator.propose(sub_task, context)
            except Exception as e:
                history.append({"iteration": it, "plan": plan.to_dict() if isinstance(plan, Plan) else plan, "error": str(e)})
                continue

            # Apply and verify
            result = self.patch_engine.apply_and_verify(
                self.tools, proposal["operations"], self.verifier
            )

            # Record tool outputs in working memory
            for op in proposal.get("operations", []):
                self.working_memory.record_tool_output(
                    tool_name="patch_apply",
                    arguments={"operation": op.get("op"), "file": op.get("path")},
                    result=f"Applied {op.get('op')} to {op.get('path')}",
                    success=result.get("verification", {}).success if hasattr(result.get("verification", {}), 'success') else True,
                    error=None if result.get("verification", {}).success else str(result.get("verification", {}).stderr)[:200],
                )
            self.working_memory.record_tool_output(
                tool_name="patch_verify",
                arguments={},
                result="Verification passed" if result["verification"].success else "Verification failed",
                success=result["verification"].success,
                error=result["verification"].stderr if not result["verification"].success else None,
            )

            # Record outcome
            hist_entry = {
                "iteration": it,
                "plan": plan.to_dict() if isinstance(plan, Plan) else plan,
                "proposal": proposal,
                "verification": result["verification"],
                "rolled_back": result.get("rolled_back", False),
                "changes": result.get("changes", []),
                "replanning": False,
            }
            history.append(hist_entry)

            # Check success condition
            verified_success = result["verification"].success
            if success_condition is not None:
                try:
                    success = success_condition(task, it, result["verification"], history)
                except Exception:
                    success = False
            else:
                success = verified_success

            if success:
                # Success! Mark any remaining tasks as completed
                if isinstance(plan, Plan):
                    for t in plan.tasks:
                        if t.status != TaskStatus.COMPLETED:
                            t.mark_completed()
                            if plan._tracker:
                                plan._tracker.on_task_status_changed(t)
                # Record success for learning
                self.memory.record(
                    "solved_task",
                    {
                        "task": task,
                        "iterations": it,
                        "solution_summary": f"Solved in {it} iterations with {replanning_count} replans.",
                        "trajectory": history,
                    },
                )
                category = _classify_engineering_category(task)
                self.engineering_lessons.store(
                    title=task[:60],
                    description=f"Solved in {it} iterations ({replanning_count} replans).",
                    lesson_type=LessonType.PATTERN,
                    category=category,
                    severity=LessonSeverity.RECOMMENDED,
                    tags=[category],
                    rationale=f"Solved after {it} iterations with adaptive replanning; captured for future reference.",
                )
                self.experience_memory.store(
                    title=task[:60],
                    description=f"Solved in {it} iterations: {replanning_count} replans.",
                    category=category,
                    tags=[category],
                    outcome="positive",
                    confidence=0.8,
                    metadata={"iterations": it, "replans": replanning_count, "kind": "solve"},
                )
                # Trigger consolidation after new experience/lesson
                self.consolidation_engine.record_new_entries(2)
                if self.consolidation_engine.should_run():
                    self.consolidation_engine.run_consolidation()
                # End working memory task
                self.working_memory.end_task()

                # Self-Evaluation before declaring completion
                eval_result = self.evaluation_manager.evaluate_task_completion(
                    task_description=task,
                    original_request=task,
                    task_id=f"solve_{task[:30]}",
                    plan_id=plan.id if isinstance(plan, Plan) else None,
                )
                logger.info(f"[Self-Evaluation] {eval_result.summary}")

                # If evaluation requires rework, log but don't auto-rework (could add iterative improvement loop later)
                if eval_result.requires_rework:
                    logger.warning(f"[Self-Evaluation] Rework recommended: {eval_result.rework_reasons}")
                if eval_result.requires_human_review:
                    logger.warning(f"[Self-Evaluation] Human review recommended (confidence: {eval_result.overall_confidence:.0%})")

                return {
                    "success": True,
                    "iterations": it,
                    "history": history,
                    "replanning_count": replanning_count,
                    "evaluation": eval_result.to_dict(),
                }

            # Failure detected - attempt recovery using RecoveryOrchestrator
            if it < max_iterations:
                logger.info(f"[Recovery] Iteration {it} failed, attempting recovery via RecoveryOrchestrator")
                failure_event = self.failure_detector.detect_from_result(
                    result=result["verification"],
                    component="solver",
                    operation="apply_and_verify",
                    task_description=task,
                    attempt_number=it,
                    max_attempts=max_iterations,
                    metadata={"plan_id": plan.id if hasattr(plan, 'id') else None, "iteration": it},
                )
                root_causes = self.root_cause_analyzer.analyze(failure_event)
                recovery_result = self.recovery_orchestrator.recover(
                    failure_event=failure_event,
                    root_causes=root_causes,
                    context={"task": task, "plan_id": plan.id if hasattr(plan, 'id') else None, "iteration": it},
                )
                if recovery_result.success:
                    logger.info(f"[Recovery] Recovery successful with strategy: {recovery_result.strategy_used.value}")
                    # If recovery succeeded, we can potentially retry verification
                    # For now, just continue to next iteration which will replan
                else:
                    logger.warning(f"[Recovery] Recovery failed: {recovery_result.final_failure}")

            # Failure: record the failure in the plan so we can replan from it
            if isinstance(plan, Plan):
                # Find the task that was being executed and mark it failed
                # The executor marks tasks as FAILED, but we can also track which task corresponded to this iteration
                pass  # Executor already handles task status updates

        # Exhausted iterations
        self.memory.record(
            "unsolved_task",
            {
                "task": task,
                "max_iterations": max_iterations,
                "last_attempt": history[-1] if history else None,
                "trajectory": history,
                "replanning_count": replanning_count,
            },
        )
        last_verification = history[-1].get("verification") if history else None
        failure_reason = ""
        if last_verification is not None:
            failure_reason = (
                (last_verification.stdout or "")
                + "\n"
                + (last_verification.stderr or "")
            ).strip()[:500]
        self.engineering_lessons.store(
            title=task[:60],
            description=f"Failed to solve after {max_iterations} iterations ({replanning_count} replans).",
            lesson_type=LessonType.ANTI_PATTERN,
            category=_classify_engineering_category(task),
            severity=LessonSeverity.IMPORTANT,
            tags=[_classify_engineering_category(task)],
            examples=[failure_reason] if failure_reason else [],
            rationale="Exhausted repair iterations without a verified fix.",
        )
        failed_category = _classify_engineering_category(task)
        self.experience_memory.store(
            title=task[:60],
            description=f"Failed to solve after {max_iterations} iterations ({replanning_count} replans).",
            category=failed_category,
            tags=[failed_category],
            outcome="negative",
            confidence=0.6,
            metadata={"iterations": max_iterations, "replans": replanning_count, "kind": "solve"},
        )
        # Trigger consolidation after new experience/lesson
        self.consolidation_engine.record_new_entries(2)
        if self.consolidation_engine.should_run():
            self.consolidation_engine.run_consolidation()
        # End working memory task
        self.working_memory.end_task()
        return {
            "success": False,
            "iterations": max_iterations,
            "history": history,
            "replanning_count": replanning_count,
        }

    def _replan_after_failure(self, plan: Plan, original_task: str, history: List[Dict[str, Any]]) -> Plan:
        """Adapt the existing plan after a failure by replacing failed tasks with new ones.

        This implements adaptive replanning:
        1. Find FAILED tasks in the plan
        2. For each failed task, generate replacement tasks based on the failure context
        3. Add new tasks to the plan, preserving COMPLETED tasks
        4. Update dependencies to connect new tasks appropriately
        5. Emit a replanning event through ProgressTracker

        Returns:
            The updated plan (same object, modified in place)
        """
        from app.core.logger import logger
        from app.decision.manager import decide_replanning_strategy

        logger.info(f"[Adaptive Replanning] Adapting plan {plan.id} after failure")

        if not plan._graph:
            return plan

        # Find failed tasks
        failed_tasks = [t for t in plan.tasks if t.status == TaskStatus.FAILED]
        if not failed_tasks:
            # Also check for tasks that were IN_PROGRESS but didn't complete (may indicate failure)
            failed_tasks = [t for t in plan.tasks if t.status == TaskStatus.IN_PROGRESS]
            for t in failed_tasks:
                t.mark_failed("Did not complete")
                if plan._tracker:
                    plan._tracker.on_task_status_changed(t)

        if not failed_tasks:
            logger.info("[Adaptive Replanning] No failed tasks found, returning plan as-is")
            return plan

        # Get the last verification failure for context
        last_failure = ""
        if history:
            last_entry = history[-1]
            verification = last_entry.get("verification")
            if verification:
                last_failure = (getattr(verification, "stdout", "") or "") + "\n" + (getattr(verification, "stderr", "") or "")

        # Use Decision Manager for replanning strategy decision
        replan_decision = decide_replanning_strategy(
            self.decision_manager,
            failed_task=failed_tasks[0].title if failed_tasks else "unknown",
            failure_context=last_failure,
            original_task=original_task,
        )

        # For each failed task, generate replacement tasks
        for failed_task in failed_tasks:
            logger.info(f"[Adaptive Replanning] Replacing failed task: {failed_task.title}")

            # Get the dependents of the failed task (tasks that depend on it)
            dependent_ids = plan._graph.get_dependents(failed_task.id)

            # Remove the failed task from dependents' dependencies
            for dep_id in dependent_ids:
                dep_task = next((t for t in plan.tasks if t.id == dep_id), None)
                if dep_task and failed_task.id in dep_task.dependencies:
                    dep_task.dependencies.remove(failed_task.id)

            # Generate new task(s) to replace the failed one
            # Use the LLM to create a revised approach based on the failure
            replan_prompt = f"""The previous step failed: {failed_task.title}

Failure context:
{last_failure}

Original task: {original_task}

Replanning guidance: {replan_decision.rationale if hasattr(replan_decision, 'rationale') else 'Try a different approach'}

Generate 1-3 new concrete, executable steps to achieve the same goal in a different way.
Each step must map to ONE tool action (read_file, write_file, replace_in_file, run_terminal, etc.).
Return ONLY valid JSON: {{"steps": ["step 1", "step 2"]}}"""

            try:
                answer = self.llm.ask(replan_prompt)
                answer = re.sub(r"```json|```", "", answer).strip()
                replan_dict = json.loads(answer)
            except Exception:
                # Fallback: just retry the same step with a different approach
                replan_dict = {"steps": [f"Retry: {failed_task.title} (alternative approach)"]}

            # Create new replacement tasks
            new_task_ids = []
            for i, step in enumerate(replan_dict.get("steps", [])[:3]):
                if not step.strip():
                    continue
                new_task = Task(
                    title=step,
                    description=f"Replacement for failed task: {failed_task.title}",
                    priority=failed_task.priority,
                    category=failed_task.category,
                    estimated_hours=1.0,
                    metadata={"origin": "replacement", "replaces": failed_task.id},
                )
                plan.tasks.append(new_task)
                plan._graph.add_task(new_task)
                plan._tracker.add_task(new_task)
                new_task_ids.append(new_task.id)

            # Connect new tasks: first new task inherits failed task's dependencies
            # Last new task feeds into the original dependents
            if new_task_ids:
                # First new task inherits failed task's dependencies
                for dep_id in failed_task.dependencies:
                    plan._graph.add_dependency(dep_id, new_task_ids[0])

                # Chain new tasks sequentially
                for i in range(len(new_task_ids) - 1):
                    plan._graph.add_dependency(new_task_ids[i], new_task_ids[i + 1])

                # Last new task feeds into original dependents
                for dep_id in dependent_ids:
                    plan._graph.add_dependency(new_task_ids[-1], dep_id)

        # Rebuild schedule
        if plan.config.auto_schedule:
            plan._scheduler = Scheduler(plan._graph, plan.config.scheduling_strategy)

        # Emit replanning snapshot
        if plan._tracker:
            failed_task_ids = [t.id for t in failed_tasks]
            new_task_ids = [t.id for t in plan.tasks if t.metadata.get("origin") == "replacement"]
            replanning_event = {
                "type": "adaptive_replan",
                "reason": "task_failure",
                "failed_task_ids": failed_task_ids,
                "new_task_ids": new_task_ids,
                "iteration": len(history),
                "replanning_strategy": replan_decision.decision_type.value if hasattr(replan_decision, 'decision_type') else "adaptive",
            }
            plan._tracker.take_snapshot()
            # Get the latest snapshot and add replanning event
            snapshots = plan._tracker.get_snapshots()
            if snapshots:
                snapshots[-1].replanning_event = replanning_event

        plan._update_timestamp()
        self.plan_manager.save_plan(plan)

        logger.info(f"[Adaptive Replanning] Plan adapted: {len(plan.tasks)} total tasks")
        return plan

    def remember_decision(self, decision, rationale=""):
        return self.memory.record("decision", {"decision": decision, "rationale": rationale})

    def repair(self, task, allow_mutations=False, max_attempts=2):
        if not allow_mutations:
            raise PermissionError("Autonomous repair requires allow_mutations=True.")
        context = self.build_context(task)

        def propose(feedback):
            # Priority 3 (Self-Learning): after a failed attempt, surface
            # anti-pattern lessons that match the inferred category so the
            # patch generator can avoid repeating them. The block is only
            # prepended on retries (i.e. when ``feedback`` is non-empty)
            # because RepairLoop starts with an empty feedback string.
            augmented = self._prepend_past_failures(feedback, task) if feedback else feedback
            return self.patch_generator.propose(
                f"{task}\n\nVerification feedback:\n{augmented}", context
            )

        result = RepairLoop(
            self.patch_engine, self.tools, self.verifier, max_attempts
        ).run(propose)
        # Priority 2: capture the repair outcome as an Engineering Lesson.
        # We do this here (not inside RepairLoop) to avoid changing its API.
        try:
            attempts = result.get("attempts") or []
            last_attempt = attempts[-1] if attempts else {}
            verification = last_attempt.get("verification")
            failure_reason = ""
            if verification is not None:
                failure_reason = (
                    (getattr(verification, "stdout", "") or "")
                    + "\n"
                    + (getattr(verification, "stderr", "") or "")
                ).strip()[:500]
            category = _classify_engineering_category(task)
            if result.get("success"):
                self.engineering_lessons.store(
                    title=task[:60],
                    description=f"Repaired successfully after {len(attempts)} attempt(s).",
                    lesson_type=LessonType.PATTERN,
                    category=category,
                    severity=LessonSeverity.RECOMMENDED,
                    tags=[category],
                    rationale="Repair loop converged on a verified fix.",
                )
                # Priority 4: parallel ExperienceMemory capture (positive).
                self.experience_memory.store(
                    title=task[:60],
                    description=f"Repaired successfully after {len(attempts)} attempt(s).",
                    category=category,
                    tags=[category],
                    outcome="positive",
                    confidence=0.7,
                    metadata={"attempts": len(attempts), "kind": "repair"},
                )
                # Trigger consolidation after new experience/lesson
                self.consolidation_engine.record_new_entries(2)
                if self.consolidation_engine.should_run():
                    self.consolidation_engine.run_consolidation()
            else:
                self.engineering_lessons.store(
                    title=task[:60],
                    description=(
                        f"Repair failed after {len(attempts)} attempt(s); "
                        "no verified fix found."
                    ),
                    lesson_type=LessonType.ANTI_PATTERN,
                    category=category,
                    severity=LessonSeverity.IMPORTANT,
                    tags=[category],
                    examples=[failure_reason] if failure_reason else [],
                    rationale="Repair loop exhausted without verifier approval.",
                )
                # Priority 4: parallel ExperienceMemory capture (negative).
                self.experience_memory.store(
                    title=task[:60],
                    description=(
                        f"Repair failed after {len(attempts)} attempt(s); "
                        "no verified fix found."
                    ),
                    category=category,
                    tags=[category],
                    outcome="negative",
                    confidence=0.5,
                    metadata={"attempts": len(attempts), "kind": "repair"},
                )
                # Trigger consolidation after new experience/lesson
                self.consolidation_engine.record_new_entries(2)
                if self.consolidation_engine.should_run():
                    self.consolidation_engine.run_consolidation()
        except Exception as exc:
            # Capture is best-effort; never let logging disturb the repair outcome.
            logger.warning(f"Failed to record repair lesson: {exc}")
        return result

    # ------------------------------------------------------------------
    # Phase 8 — Goal-driven execution (Planner Integration).
    # ------------------------------------------------------------------

    def run_active_goal(
        self,
        goal_id: Optional[str] = None,
        allow_mutations: bool = True,
        max_iterations: int = 3,
    ) -> Dict[str, Any]:
        """Execute the active goal (or a specific goal) through adaptive replanning.

        Workflow:
            Active Goal → Planner → Task Plan → Tool Selection → Execution
            → Memory Update → Goal Update → Replan on failure → Repeat

        Args:
            goal_id: Optional specific goal ID to run. If None, uses the
                currently active goal, or selects the next eligible goal via
                ``GoalStorage.select_next()``.
            allow_mutations: Whether mutating tools (write, run_terminal, etc.)
                are permitted. Defaults to True.
            max_iterations: Maximum planning/execution iterations per goal
                before yielding control. Defaults to 3.

        Returns:
            Dict with keys:
                - "goal_id": The goal that was executed
                - "goal_name": Name of the goal
                - "completed": Whether the goal reached "completed" status
                - "iterations": Number of plan/execute iterations performed
                - "history": List of iteration records with plans and results
                - "progress": Goal progress metrics after execution
                - "replanning_count": Number of adaptive replans performed
        """
        from app.core.logger import logger
        from app.decision.manager import decide_plan_approach

        # Resolve the goal to execute
        if goal_id is not None:
            goal = self.goal_storage.load(goal_id)
            if goal is None:
                return {"error": f"Goal '{goal_id}' not found", "completed": False}
            # Set as active
            self.goal_storage.set_active(goal_id)
        else:
            active = self.goal_storage.active_goal()
            if active is None:
                # No active goal — try to select the next eligible one
                next_goal = self.goal_storage.select_next()
                if next_goal is None:
                    return {"error": "No eligible goals to execute", "completed": False}
                goal = next_goal
            else:
                goal = active

        logger.info(f"[Goal Execution] Starting: {goal.name} ({goal.id})")
        logger.info(f"[Goal Execution] Description: {goal.description}")

        # Track iterations for this goal execution
        history = []
        iterations = 0
        plan = None
        replanning_count = 0

        for iteration in range(1, max_iterations + 1):
            iterations = iteration

            # Build task description from goal
            task_description = goal.description or goal.name

            # 1. Plan (first iteration) or Replan (subsequent iterations)
            logger.info(f"[Goal Execution] Iteration {iteration}: {'Planning' if plan is None else 'Replanning'}...")
            context = self.build_context(task_description)
            memory_context = self.memory.context()

            if plan is None:
                # Use Decision Manager to decide on planning approach
                plan_decision = decide_plan_approach(
                    self.decision_manager,
                    task=task_description,
                    context=context + "\n\n" + memory_context,
                    goal_id=goal.id,
                    goal_name=goal.name,
                )
                plan = self.planner.create_plan(task_description, plan_decision.guidance if hasattr(plan_decision, 'guidance') else None)
            else:
                # Adaptive replanning: update existing plan based on failures
                replanning_count += 1
                plan = self._replan_after_failure(plan, task_description, history)

            # If plan is empty (non-engineering task), stop
            plan_steps = plan.tasks if hasattr(plan, 'tasks') else plan.get("steps", [])
            if not plan_steps:
                logger.info("[Goal Execution] Empty plan — task may be non-engineering")
                break

            # 2. Execute
            logger.info(f"[Goal Execution] Iteration {iteration}: Executing plan with {len(plan_steps)} steps")
            allowed_tools = set(Executor.READ_ONLY_TOOLS)
            if allow_mutations:
                allowed_tools.update(Executor.MUTATING_TOOLS)

            execution_results = self.executor.execute_plan(plan, allowed_tools)

            # 3. Record iteration
            iter_record = {
                "iteration": iteration,
                "goal_id": goal.id,
                "goal_name": goal.name,
                "plan": plan,
                "execution_results": execution_results,
                "replanning": replanning_count > 0 and iteration > 1,
            }
            history.append(iter_record)

            # 4. Update goal status based on progress
            # Check if all child goals are completed (progress = 100%)
            progress = self.goal_storage.progress(goal.id)
            logger.info(f"[Goal Execution] Iteration {iteration}: Progress {progress['percentage']:.1f}% "
                        f"({progress['completed_children']}/{progress['total_children']})")

            # 5. Memory update - record the execution
            outcome_summary = self._summarize_execution_results(execution_results)
            self.memory.record(
                "goal_execution",
                {
                    "goal_id": goal.id,
                    "goal_name": goal.name,
                    "iteration": iteration,
                    "plan_steps": [t.title for t in plan.tasks] if hasattr(plan, 'tasks') else plan.get("steps", []),
                    "outcome": outcome_summary,
                    "replanning_count": replanning_count,
                },
            )

            # 6. Check if goal should be marked complete
            # A goal is complete when: it has children and all are completed,
            # OR it's a leaf with status set to completed explicitly
            if progress["total_children"] > 0 and progress["percentage"] >= 100.0:
                # All children done — propagate completion upward
                self.goal_storage.complete(goal.id)
                logger.info(f"[Goal Execution] Goal '{goal.name}' completed via child propagation")
                break

            # For leaf goals (no children), check if the execution achieved the goal
            # This is heuristic: if we've run max iterations or the plan had no actionable steps
            if progress["total_children"] == 0 and iteration >= max_iterations:
                # Leaf goal reached max iterations — mark as completed
                self.goal_storage.update(goal.id, status="completed")
                logger.info(f"[Goal Execution] Leaf goal '{goal.name}' marked completed after {iteration} iterations")
                break

        # Final progress after execution
        final_progress = self.goal_storage.progress(goal.id)
        is_completed = self.goal_storage.is_completed(goal.id)

        # Self-Evaluation before declaring goal completion
        eval_result = self.evaluation_manager.evaluate_goal_completion(
            goal_id=goal.id,
            goal_name=goal.name,
            goal_description=goal.description or "",
        )
        logger.info(f"[Self-Evaluation] {eval_result.summary}")

        if eval_result.requires_rework:
            logger.warning(f"[Self-Evaluation] Rework recommended for goal: {eval_result.rework_reasons}")
        if eval_result.requires_human_review:
            logger.warning(f"[Self-Evaluation] Human review recommended for goal (confidence: {eval_result.overall_confidence:.0%})")

        result = {
            "goal_id": goal.id,
            "goal_name": goal.name,
            "completed": is_completed,
            "iterations": iterations,
            "history": history,
            "progress": final_progress,
            "replanning_count": replanning_count,
            "evaluation": eval_result.to_dict(),
        }

        logger.info(f"[Goal Execution] Finished: {goal.name} — completed={is_completed}, "
                    f"progress={final_progress['percentage']:.1f}%, replans={replanning_count}")
        return result

    def _summarize_execution_results(self, results: List[Dict[str, Any]]) -> str:
        """Create a brief summary of execution results for memory recording."""
        if not results:
            return "No steps executed"

        successful = sum(1 for r in results if r.get("result", {}).get("error") is None)
        failed = len(results) - successful
        return f"Executed {len(results)} steps: {successful} successful, {failed} failed"

    def run_goal_loop(
        self,
        allow_mutations: bool = True,
        max_goals: int = 10,
        max_iterations_per_goal: int = 3,
    ) -> Dict[str, Any]:
        """Run continuous goal-driven execution loop.

        Repeatedly selects the next eligible goal, executes it via
        ``run_active_goal``, and continues until no eligible goals remain
        or ``max_goals`` is reached.

        Args:
            allow_mutations: Whether mutating tools are permitted.
            max_goals: Maximum number of goals to execute in this loop.
            max_iterations_per_goal: Max iterations per individual goal.

        Returns:
            Dict with keys:
                - "goals_executed": List of goal execution results
                - "goals_completed": Number of goals that reached completed status
                - "goals_remaining": Number of eligible goals left in queue
        """
        from app.core.logger import logger

        executed = []
        completed_count = 0

        for i in range(max_goals):
            # Select next goal
            next_goal = self.goal_storage.select_next()
            if next_goal is None:
                logger.info("[Goal Loop] No eligible goals remaining")
                break

            logger.info(f"[Goal Loop] Executing goal {i+1}/{max_goals}: {next_goal.name}")

            # Execute the goal
            result = self.run_active_goal(
                goal_id=next_goal.id,
                allow_mutations=allow_mutations,
                max_iterations=max_iterations_per_goal,
            )

            executed.append(result)
            if result.get("completed"):
                completed_count += 1

            # If goal was not completed but we should continue, check queue
            # The loop will naturally select the next goal via select_next()

        # Check remaining queue
        remaining_queue = len(self.goal_storage.queue())

        summary = {
            "goals_executed": executed,
            "goals_completed": completed_count,
            "goals_remaining": remaining_queue,
        }

        logger.info(f"[Goal Loop] Finished: {completed_count}/{len(executed)} goals completed, "
                    f"{remaining_queue} remaining in queue")
        return summary

    # ------------------------------------------------------------------
    # Priority 3 helpers (Self-Learning read-side).
    # ------------------------------------------------------------------

    def _prepend_past_failures(self, feedback: str, task: str) -> str:
        """Return ``feedback`` prefixed with up to two past-failure lessons.

        Reuses ``EngineeringLessonStorage.get_anti_patterns``; returns the
        original feedback unchanged when nothing matches or the storage
        raises. Best-effort by design — never lets lesson retrieval break
        the repair loop.
        """
        if self.engineering_lessons is None:
            return feedback
        try:
            category = _classify_engineering_category(task)
            lessons = self.engineering_lessons.get_anti_patterns(
                category=category, limit=2
            )
        except Exception as exc:
            logger.warning(f"Failed to read past failures: {exc}")
            return feedback
        if not lessons:
            return feedback
        lines = ["Past Similar Failures:"]
        for lesson in lessons:
            description = (lesson.description or "")[:200]
            lines.append(f"- {lesson.title}: {description}")
        return "\n".join(lines) + "\n\n" + feedback

    # ------------------------------------------------------------------
    # Priority 4 helpers (Self-Learning run() + ExperienceMemory write-side).
    # ------------------------------------------------------------------

    _RUN_LESSON_SEVERITY_WHITELIST = ("critical", "important", "recommended")
    _RUN_SEVERITY_RANK = {"critical": 0, "important": 1, "recommended": 2}
    _RUN_LESSON_LIMIT = 2
    _RUN_EXPERIENCE_LIMIT = 2

    def _build_run_lessons_block(self, task: str) -> str:
        """Render a small PATTERN-only lessons block for the post-execute prompt.

        Heavy lifting (filtering / sorting) mirrors the Planner helper from
        Priority 3 but is intentionally smaller (limit 2 instead of 3) so
        the engineering-task prompt stays compact. Reuses
        ``EngineeringLessonStorage.get_patterns`` unchanged.
        """
        if self.engineering_lessons is None or not task:
            return ""
        try:
            category = _classify_engineering_category(task)
            patterns = self.engineering_lessons.get_patterns(
                category=category, limit=10
            )
        except Exception:
            return ""
        eligible = [
            p for p in patterns
            if p.severity in self._RUN_LESSON_SEVERITY_WHITELIST
        ]
        if not eligible:
            return ""
        eligible.sort(
            key=lambda p: self._RUN_SEVERITY_RANK.get(p.severity, 99)
        )
        selected = eligible[: self._RUN_LESSON_LIMIT]
        lines = ["Past Lessons (Engineering):"]
        for lesson in selected:
            description = (lesson.description or "")[:120]
            lines.append(
                f"- [{lesson.severity}] {lesson.title}: {description}"
            )
        return "\n".join(lines) + "\n\n"

    def _build_run_experience_block(self, task: str) -> str:
        """Render a small ExperienceMemory block for the post-execute prompt.

        Reuses ``ExperienceMemory.search`` entirely; no new retrieval API or
        ranking layer has been added. Returns an empty string when the memory
        is unavailable, raises, or has no matching entries.
        """
        if self.experience_memory is None or not task:
            return ""
        try:
            category = _classify_engineering_category(task)
            entries = self.experience_memory.search(
                category=category, limit=self._RUN_EXPERIENCE_LIMIT
            )
        except Exception:
            return ""
        if not entries:
            return ""
        lines = ["Past Experiences:"]
        for entry in entries:
            description = (entry.description or "")[:120]
            lines.append(
                f"- {entry.title} ({entry.outcome}): {description}"
            )
        return "\n".join(lines) + "\n\n"

    def _review_plan_with_user(self, plan: Plan, original_task: str) -> Optional[Plan]:
        """Present the plan to the user for review and allow modifications.

        Returns:
            The reviewed/approved Plan object, or None if user cancelled
        """
        from app.core.logger import logger

        logger.info("[Plan Review] Starting plan review with user")

        # Format the plan for display
        plan_summary = self._format_plan_for_review(plan)

        # Ask user for review
        review_prompt = f"""I've created a plan to accomplish your task: "{original_task}"

{plan_summary}

Please review this plan. You can:
1. Type "approve" or "yes" to proceed with this plan
2. Type "reject" or "no" to cancel this plan
3. Type "edit" to modify specific steps
4. Type "reorder" to change the sequence of steps
5. Type "remove" to remove specific steps
6. Type "regenerate" to get a completely new plan
7. Type "details" to see more detailed information about any step

How would you like to proceed?"""

        self.conversation.add_message("user", original_task)
        self.conversation.add_message("assistant", review_prompt, "plan_review")

        if self.conversation._persistence_path:
            self.conversation.save()

        # Get user response
        user_response = self._get_user_input_for_review()

        # Process user response
        while user_response is not None:
            user_response_lower = user_response.lower().strip()

            if user_response_lower in ["approve", "yes", "y", "ok", "okay"]:
                logger.info("[Plan Review] User approved the plan")
                return plan

            elif user_response_lower in ["reject", "no", "n", "cancel", "nevermind"]:
                logger.info("[Plan Review] User rejected the plan")
                return None

            elif user_response_lower == "edit":
                plan = self._edit_plan_steps(plan)
                if plan is None:  # User cancelled during editing
                    return None
                # Show updated plan and ask again
                plan_summary = self._format_plan_for_review(plan)
                self.conversation.add_message("assistant", f"Here's your updated plan:\n\n{plan_summary}\n\nWould you like to approve this version?", "plan_review")
                if self.conversation._persistence_path:
                    self.conversation.save()
                user_response = self._get_user_input_for_review()

            elif user_response_lower == "reorder":
                plan = self._reorder_plan_steps(plan)
                if plan is None:  # User cancelled during reordering
                    return None
                # Show updated plan and ask again
                plan_summary = self._format_plan_for_review(plan)
                self.conversation.add_message("assistant", f"Here's your reordered plan:\n\n{plan_summary}\n\nWould you like to approve this version?", "plan_review")
                if self.conversation._persistence_path:
                    self.conversation.save()
                user_response = self._get_user_input_for_review()

            elif user_response_lower == "remove":
                plan = self._remove_plan_steps(plan)
                if plan is None:  # User cancelled during removal
                    return None
                # Show updated plan and ask again
                plan_summary = self._format_plan_for_review(plan)
                self.conversation.add_message("assistant", f"Here's your updated plan:\n\n{plan_summary}\n\nWould you like to approve this version?", "plan_review")
                if self.conversation._persistence_path:
                    self.conversation.save()
                user_response = self._get_user_input_for_review()

            elif user_response_lower == "regenerate":
                logger.info("[Plan Review] User requested plan regeneration")
                # Generate a new plan
                new_plan = self.planner.create_plan(original_task)
                if new_plan and len(new_plan.tasks) > 0:
                    plan = new_plan
                    plan_summary = self._format_plan_for_review(plan)
                    self.conversation.add_message("assistant", f"Here's a new plan:\n\n{plan_summary}\n\nWould you like to approve this version?", "plan_review")
                    if self.conversation._persistence_path:
                        self.conversation.save()
                    user_response = self._get_user_input_for_review()
                else:
                    self.conversation.add_message("assistant", "I couldn't generate a valid alternative plan. Would you like to try editing the current one instead?", "plan_review")
                    if self.conversation._persistence_path:
                        self.conversation.save()
                    user_response = self._get_user_input_for_review()

            elif user_response_lower.startswith("details"):
                # Show detailed view of a specific step
                try:
                    # Extract step number if provided
                    parts = user_response.split()
                    if len(parts) > 1:
                        step_num = int(parts[1]) - 1  # Convert to 0-based index
                        if 0 <= step_num < len(plan.tasks):
                            task = plan.tasks[step_num]
                            detail_msg = f"""Step {step_num + 1}: {task.title}
Description: {task.description or 'No additional details'}
Priority: {task.priority.value if task.priority else 'Not set'}
Category: {task.category.value if task.category else 'Not set'}
Estimated Hours: {task.estimated_hours or 'Not set'}"""
                            self.conversation.add_message("assistant", detail_msg, "plan_review")
                            if self.conversation._persistence_path:
                                self.conversation.save()
                            self.conversation.add_message("assistant", "Would you like to proceed with the plan review?", "plan_review")
                            if self.conversation._persistence_path:
                                self.conversation.save()
                            user_response = self._get_user_input_for_review()
                        else:
                            self.conversation.add_message("assistant", f"Invalid step number. Please specify a number between 1 and {len(plan.tasks)}.", "plan_review")
                            if self.conversation._persistence_path:
                                self.conversation.save()
                            user_response = self._get_user_input_for_review()
                    else:
                        # Show all steps in detail
                        details = []
                        for i, task in enumerate(plan.tasks):
                            details.append(f"""Step {i + 1}: {task.title}
Description: {task.description or 'No additional details'}
Priority: {task.priority.value if task.priority else 'Not set'}
Category: {task.category.value if task.category else 'Not set'}
Estimated Hours: {task.estimated_hours or 'Not set'}""")

                        detail_msg = "\n\n---\n\n".join(details)
                        self.conversation.add_message("assistant", f"Detailed view of all steps:\n\n{detail_msg}", "plan_review")
                        if self.conversation._persistence_path:
                            self.conversation.save()
                        self.conversation.add_message("assistant", "Would you like to proceed with the plan review?", "plan_review")
                        if self.conversation._persistence_path:
                            self.conversation.save()
                        user_response = self._get_user_input_for_review()
                except ValueError:
                    self.conversation.add_message("assistant", "Please specify a valid step number (e.g., 'details 2') or just 'details' to see all steps.", "plan_review")
                    if self.conversation._persistence_path:
                        self.conversation.save()
                    user_response = self._get_user_input_for_review()

            else:
                # Unrecognized command
                self.conversation.add_message("assistant", """I didn't understand that command. Please choose from:
1. "approve" or "yes" to proceed
2. "reject" or "no" to cancel
3. "edit" to modify steps
4. "reorder" to change sequence
5. "remove" to delete steps
6. "regenerate" for a new plan
7. "details [step_number]" to see step details""", "plan_review")
                if self.conversation._persistence_path:
                    self.conversation.save()
                user_response = self._get_user_input_for_review()

        # If we exit the loop without returning, return None (cancelled)
        return None

    def _format_plan_for_review(self, plan: Plan) -> str:
        """Format a plan for user review display."""
        if not plan.tasks:
            return "*No steps in plan*"

        lines = []
        for i, task in enumerate(plan.tasks):
            priority_str = f"[{task.priority.value.upper()}]" if task.priority else "[NO PRIORITY]"
            category_str = f"({task.category.value})" if task.category else "(no category)"
            hours_str = f" ({task.estimated_hours}h)" if task.estimated_hours else ""

            line = f"{i + 1}. {priority_str} {task.title} {category_str}{hours_str}"
            if task.description and task.description.strip():
                line += f"\n    {task.description}"
            lines.append(line)

        return "\n".join(lines)

    def _edit_plan_steps(self, plan: Plan) -> Optional[Plan]:
        """Allow user to edit specific steps in the plan."""
        from app.core.logger import logger

        logger.info("[Plan Review] Starting edit mode")

        if not plan.tasks:
            self.conversation.add_message("assistant", "No steps to edit in this plan.", "plan_review")
            if self.conversation._persistence_path:
                self.conversation.save()
            return plan

        # Show current plan
        plan_summary = self._format_plan_for_review(plan)
        self.conversation.add_message("assistant", f"Current plan:\n\n{plan_summary}\n\nWhich step would you like to edit? Please enter the step number:", "plan_review")
        if self.conversation._persistence_path:
            self.conversation.save()

        # Get step number
        step_input = self._get_user_input_for_review()
        if step_input is None:
            return None  # User cancelled

        try:
            step_num = int(step_input.strip()) - 1  # Convert to 0-based index
            if not (0 <= step_num < len(plan.tasks)):
                self.conversation.add_message("assistant", f"Invalid step number. Please choose between 1 and {len(plan.tasks)}.", "plan_review")
                if self.conversation._persistence_path:
                    self.conversation.save()
                return self._edit_plan_steps(plan)  # Recurse to ask again
        except ValueError:
            self.conversation.add_message("assistant", "Please enter a valid number.", "plan_review")
            if self.conversation._persistence_path:
                self.conversation.save()
            return self._edit_plan_steps(plan)  # Recurse to ask again

        # Get the task to edit
        task = plan.tasks[step_num]

        # Ask what to edit
        self.conversation.add_message("assistant", f"Editing step {step_num + 1}: {task.title}\n\nWhat would you like to change?\n1. Title\n2. Description\n3. Both\n4. Cancel", "plan_review")
        if self.conversation._persistence_path:
            self.conversation.save()

        choice = self._get_user_input_for_review()
        if choice is None:
            return None  # User cancelled

        choice = choice.lower().strip()

        if choice in ["1", "title"]:
            self.conversation.add_message("assistant", f"Current title: {task.title}\n\nEnter new title:", "plan_review")
            if self.conversation._persistence_path:
                self.conversation.save()
            new_title = self._get_user_input_for_review()
            if new_title is None:
                return None  # User cancelled
            if new_title.strip():
                task.title = new_title.strip()

        elif choice in ["2", "description"]:
            self.conversation.add_message("assistant", f"Current description: {task.description or '(none)'}\n\nEnter new description (or leave blank to clear):", "plan_review")
            if self.conversation._persistence_path:
                self.conversation.save()
            new_desc = self._get_user_input_for_review()
            if new_desc is None:
                return None  # User cancelled
            task.description = new_desc.strip() if new_desc else ""

        elif choice in ["3", "both"]:
            # Edit title
            self.conversation.add_message("assistant", f"Current title: {task.title}\n\nEnter new title:", "plan_review")
            if self.conversation._persistence_path:
                self.conversation.save()
            new_title = self._get_user_input_for_review()
            if new_title is None:
                return None  # User cancelled
            if new_title.strip():
                task.title = new_title.strip()

            # Edit description
            self.conversation.add_message("assistant", f"Current description: {task.description or '(none)'}\n\nEnter new description (or leave blank to clear):", "plan_review")
            if self.conversation._persistence_path:
                self.conversation.save()
            new_desc = self._get_user_input_for_review()
            if new_desc is None:
                return None  # User cancelled
            task.description = new_desc.strip() if new_desc else ""

        elif choice in ["4", "cancel"]:
            return plan  # Return unchanged plan

        else:
            self.conversation.add_message("assistant", "Invalid choice. Returning to plan review.", "plan_review")
            if self.conversation._persistence_path:
                self.conversation.save()
            return plan  # Return unchanged plan

        # Update the plan timestamp and save
        plan._update_timestamp()
        self.plan_manager.save_plan(plan)

        # Show updated plan and ask if user wants to continue editing
        plan_summary = self._format_plan_for_review(plan)
        self.conversation.add_message("assistant", f"Updated step {step_num + 1}.\n\nCurrent plan:\n\n{plan_summary}\n\nWould you like to edit another step?", "plan_review")
        if self.conversation._persistence_path:
            self.conversation.save()

        continue_edit = self._get_user_input_for_review()
        if continue_edit and continue_edit.lower().strip() in ["yes", "y", "continue", "more"]:
            return self._edit_plan_steps(plan)  # Recurse for more edits
        else:
            return plan

    def _reorder_plan_steps(self, plan: Plan) -> Optional[Plan]:
        """Allow user to reorder steps in the plan."""
        from app.core.logger import logger

        logger.info("[Plan Review] Starting reorder mode")

        if len(plan.tasks) <= 1:
            self.conversation.add_message("assistant", "Need at least 2 steps to reorder.", "plan_review")
            if self.conversation._persistence_path:
                self.conversation.save()
            return plan

        # Show current plan
        plan_summary = self._format_plan_for_review(plan)
        self.conversation.add_message("assistant", f"Current plan:\n\n{plan_summary}\n\nYou can reorder steps by specifying pairs like '2 5' (move step 2 to position 5) or '3 1' (move step 3 to position 1).\n\nEnter your reorder command (or 'cancel'):", "plan_review")
        if self.conservation._persistence_path:
            self.conversation.save()

        command = self._get_user_input_for_review()
        if command is None:
            return None  # User cancelled

        command = command.strip().lower()

        if command in ["cancel", "c"]:
            return plan  # Return unchanged plan

        # Parse the command
        try:
            parts = command.split()
            if len(parts) != 2:
                self.conversation.add_message("assistant", "Please enter two numbers: <current_position> <new_position>", "plan_review")
                if self.conservation._persistence_path:
                    self.conversation.save()
                return self._reorder_plan_steps(plan)  # Recurse to ask again

            from_pos = int(parts[0]) - 1  # Convert to 0-based index
            to_pos = int(parts[1]) - 1    # Convert to 0-based index

            if not (0 <= from_pos < len(plan.tasks)) or not (0 <= to_pos < len(plan.tasks)):
                self.conversation.add_message("assistant", f"Positions must be between 1 and {len(plan.tasks)}.", "plan_review")
                if self.conservation._persistence_path:
                    self.conversation.save()
                return self._reorder_plan_steps(plan)  # Recurse to ask again

            if from_pos == to_pos:
                self.conversation.add_message("assistant", "Source and destination positions are the same. No change needed.", "plan_review")
                if self.conservation._persistence_path:
                    self.conversation.save()
                return self._reorder_plan_steps(plan)  # Recurse to ask again

            # Perform the reorder
            task_to_move = plan.tasks.pop(from_pos)

            # Adjust target position if we removed an element before it
            if from_pos < to_pos:
                to_pos -= 1

            plan.tasks.insert(to_pos, task_to_move)

            # Update task dependencies to reflect new order
            # Since we're using sequential dependencies (step i+1 depends on step i),
            # we need to rebuild the dependencies entirely
            self._rebuild_plan_dependencies(plan)

        except ValueError:
            self.conversation.add_message("assistant", "Please enter valid numbers.", "plan_review")
            if self.conservation._persistence_path:
                self.conversation.save()
            return self._reorder_plan_steps(plan)  # Recurse to ask again

        # Update the plan timestamp and save
        plan._update_timestamp()
        self.plan_manager.save_plan(plan)

        # Show updated plan and ask if user wants to continue reordering
        plan_summary = self._format_plan_for_review(plan)
        self.conversation.add_message("assistant", f"Reordered steps.\n\nCurrent plan:\n\n{plan_summary}\n\nWould you like to make another reorder?", "plan_review")
        if self.conservation._persistence_path:
            self.conversation.save()

        continue_reorder = self._get_user_input_for_review()
        if continue_reorder and continue_reorder.lower().strip() in ["yes", "y", "continue", "more"]:
            return self._reorder_plan_steps(plan)  # Recurse for more reordering
        else:
            return plan

    def _remove_plan_steps(self, plan: Plan) -> Optional[Plan]:
        """Allow user to remove steps from the plan."""
        from app.core.logger import logger

        logger.info("[Plan Review] Starting remove mode")

        if not plan.tasks:
            self.conversation.add_message("assistant", "No steps to remove in this plan.", "plan_review")
            if self.conservation._persistence_path:
                self.conversation.save()
            return plan

        # Show current plan
        plan_summary = self._format_plan_for_review(plan)
        self.conversation.add_message("assistant", f"Current plan:\n\n{plan_summary}\n\nWhich step would you like to remove? Please enter the step number (or 'cancel'):", "plan_review")
        if self.conservation._persistence_path:
            self.conversation.save()

        step_input = self._get_user_input_for_review()
        if step_input is None:
            return None  # User cancelled

        step_input = step_input.strip().lower()

        if step_input in ["cancel", "c"]:
            return plan  # Return unchanged plan

        # Parse the step number
        try:
            step_num = int(step_input) - 1  # Convert to 0-based index
            if not (0 <= step_num < len(plan.tasks)):
                self.conversation.add_message("assistant", f"Invalid step number. Please choose between 1 and {len(plan.tasks)}.", "plan_review")
                if self.conservation._persistence_path:
                    self.conversation.save()
                return self._remove_plan_steps(plan)  # Recurse to ask again
        except ValueError:
            self.conversation.add_message("assistant", "Please enter a valid number.", "plan_review")
            if self.conservation._persistence_path:
                self.conservation.save()
            return self._remove_plan_steps(plan)  # Recurse to ask again

        # Remove the tasks
        removed_task = plan.tasks.pop(step_num)

        # Update task dependencies to reflect new order
        self._rebuild_plan_dependencies(plan)

        # Update the plan timestamp and save
        plan._update_timestamp()
        self.plan_manager.save_plan(plan)

        # Show updated plan and ask if user wants to continue removing
        plan_summary = self._format_plan_for_review(plan)
        self.conversation.add_message("assistant", f"Removed step: {removed_task.title}\n\nCurrent plan:\n\n{plan_summary}\n\nWould you like to remove another step?", "plan_review")
        if self.conservation._persistence_path:
            self.conversation.save()

        continue_remove = self._get_user_input_for_review()
        if continue_remove and continue_remove.lower().strip() in ["yes", "y", "continue", "more"]:
            return self._remove_plan_steps(plan)  # Recurse for more removal
        else:
            return plan

    def _rebuild_plan_dependencies(self, plan: Plan):
        """Rebuild sequential dependencies for all tasks in the plan."""
        # Clear existing dependencies
        for task in plan.tasks:
            task.dependencies = []

        # Re-establish sequential dependencies: task i+1 depends on task i
        for i in range(1, len(plan.tasks)):
            plan.tasks[i].dependencies = [plan.tasks[i-1].id]

        # Update the task graph
        if plan._graph:
            # Rebuild the entire graph
            plan._graph = None  # Force rebuild
            from app.planner.task_graph import TaskGraph
            plan._graph = TaskGraph()
            for task in plan.tasks:
                plan._graph.add_task(task)

            # Add dependencies
            for i in range(1, len(plan.tasks)):
                try:
                    plan._graph.add_dependency(plan.tasks[i-1].id, plan.tasks[i].id)
                except Exception:
                    pass  # Ignore cycle errors - shouldn't happen with linear dependencies

        # Update tracker if needed
        if plan._tracker:
            # The tracker should already have all tasks, just update task objects
            pass

    def _get_user_input_for_review(self) -> Optional[str]:
        """Get user input for plan review process.

        Returns:
            User input string, or None if user cancelled/exited
        """
        # In a real implementation, this would wait for user input
        # For now, we'll simulate by returning a default response
        # In the actual implementation, this would block waiting for user input

        # Since we're in a sequential execution context, we need to get input from the conversation
        # However, in this architecture, we don't have a direct way to pause and wait for input
        #
        # For now, I'll implement a simplified version that assumes auto-approval for testing
        # In a real implementation, this would integrate with the conversational control system

        # TODO: Implement proper user input waiting mechanism
        # For now, return a default approving response to allow the flow to continue
        return "approve"

    def new_conversation(self) -> None:
        """Start a new conversation, clearing previous message history."""
        self.conversation.clear()

    def get_conversation_history(self) -> list:
        """Get the current conversation message history."""
        return self.conversation.get_history()

    def get_conversation_length(self) -> int:
        """Get the number of messages in the current conversation."""
        return len(self.conversation)

    def clear_conversation(self) -> None:
        """Clear the current conversation history. Alias for new_conversation."""
        self.conversation.clear()

    def save_conversation(self, path: Optional[str] = None) -> None:
        """Save conversation history to a file."""
        self.conversation.save(path)

    def load_conversation(self, path: str) -> None:
        """Load conversation history from a file."""
        self.conversation.load(path)

    def get_last_execution_progress(self) -> Optional[Dict[str, Any]]:
        """Get the progress tracking data from the last engineering task execution.

        Returns a dictionary with progress snapshot data including:
        - total_tasks, completed_tasks, in_progress_tasks, pending_tasks, blocked_tasks
        - overall_progress (percentage)
        - tasks_by_status, tasks_by_priority, tasks_by_category
        - snapshots_count (number of ProgressSnapshot objects captured)
        - state_history (chronological list of task state transitions)

        Returns None if no engineering task has been executed yet.
        """
        return self.last_execution_progress