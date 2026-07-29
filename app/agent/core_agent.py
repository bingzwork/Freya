from app.agent.executor import Executor
from app.agent.planner import Planner
from app.brain.state import ConversationState
from app.core.llm import LLM
from app.planner.plan_manager import PlanManager, Plan
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
from app.memory.project_memory import ProjectMemory
from app.memory.experience_memory import ExperienceMemory
from app.memory.engineering_lessons import EngineeringLessonStorage, LessonSeverity, LessonType
from app.memory.goals import GoalStorage
from app.verification.repair_loop import RepairLoop
from app.verification.runner import VerificationRunner
from app.rag import SimpleRetriever
import re
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
        self.conversation = ConversationState(max_history=max_conversation_history, persistence_path=conversation_persistence_path)

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
        logger.info("Freya Agent initialized")

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
        classification = classify_intent(task)

        # Conversational control short-circuits all routing and bypasses the LLM.
        if classification.is_control:
            result = route_query(
                task, intent_type=classification.intent.value
            )
            if result is not None:
                answer = format_capability_result(result)
                self.conversation.add_message("user", task)
                self.conversation.add_message("assistant", answer)
                if self.conversation._persistence_path:
                    self.conversation.save()
                return answer

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
            self.conversation.add_message("assistant", answer)
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
            self.conversation.add_message("assistant", answer)
            if self.conversation._persistence_path:
                self.conversation.save()
            return answer

        # Validate that engineering tasks have sufficient context
        if not _has_sufficient_context(task, classification.intent):
            # Missing essential information - ask user instead of inventing fake plans
            prompt = _get_missing_context_prompt(task, classification.intent)
            answer = self.llm.ask(prompt)
            self.memory.record("task", {"request": task, "outcome": answer[:500]})
            self.conversation.add_message("user", task)
            self.conversation.add_message("assistant", answer)
            if self.conversation._persistence_path:
                self.conversation.save()
            return answer

        # Engineering tasks -> full planning and execution pipeline
        context = self.build_context(task)
        memory_context = self.memory.context()
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
        # Execute using the Plan object (Executor now accepts Plan or dict)
        results = self.executor.execute_plan(plan, allowed_tools)

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
        self.conversation.add_message("assistant", answer)
        if self.conversation._persistence_path:
            self.conversation.save()
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
        """Attempt to autonomously solve a task via iterative planning, patching, and verification.

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
            }
        """
        if not allow_mutations:
            raise PermissionError("Autonomous solving requires allow_mutations=True.")
        context = self.build_context(task)
        history = []
        for it in range(1, max_iterations + 1):
            # 1. Plan
            plan = self.planner.create_plan(task)
            # 2. Propose patch based on plan (we treat the plan steps as the sub-task)
            plan_steps = plan.tasks if hasattr(plan, 'tasks') else plan.get("steps", [])
            sub_task = "\n".join(plan_steps) if plan_steps else task
            try:
                proposal = self.patch_generator.propose(sub_task, context)
            except Exception as e:
                # If proposal fails, record and continue
                history.append({"iteration": it, "plan": plan, "error": str(e)})
                continue
            # 3. Apply and verify
            result = self.patch_engine.apply_and_verify(
                self.tools, proposal["operations"], self.verifier
            )
            # 4. Record outcome
            hist_entry = {
                "iteration": it,
                "plan": plan,
                "proposal": proposal,
                "verification": result["verification"],
                "rolled_back": result.get("rolled_back", False),
                "changes": result.get("changes", []),
            }
            history.append(hist_entry)
            # 5. Check success condition
            verified_success = result["verification"].success
            if success_condition is not None:
                try:
                    success = success_condition(task, it, result["verification"], history)
                except Exception:
                    success = False
            else:
                success = verified_success
            if success:
                # Success! Record a decision for learning
                self.memory.record(
                    "solved_task",
                    {
                        "task": task,
                        "iterations": it,
                        "solution_summary": f"Solved in {it} iterations.",
                        "trajectory": history,
                    },
                )
                # Priority 2: capture an Engineering Lesson pattern so future
                # work can reuse this trajectory. See SELF_LEARNING.md.
                summary = f"Solved in {it} iterations."
                category = _classify_engineering_category(task)
                self.engineering_lessons.store(
                    title=task[:60],
                    description=f"Solved in {it} iterations: {summary}",
                    lesson_type=LessonType.PATTERN,
                    category=category,
                    severity=LessonSeverity.RECOMMENDED,
                    tags=[category],
                    rationale=f"Solved after {it} iterations; captured for future reference.",
                )
                # Priority 4: capture a parallel ExperienceMemory entry so the
                # ExperienceMemory reader can surface it on the next run.
                self.experience_memory.store(
                    title=task[:60],
                    description=f"Solved in {it} iterations: {summary}",
                    category=category,
                    tags=[category],
                    outcome="positive",
                    confidence=0.8,
                    metadata={"iterations": it, "kind": "solve"},
                )
                return {
                    "success": True,
                    "iterations": it,
                    "history": history,
                }
        # Exhausted iterations
        self.memory.record(
            "unsolved_task",
            {
                "task": task,
                "max_iterations": max_iterations,
                "last_attempt": history[-1] if history else None,
                "trajectory": history,
            },
        )
        # Priority 2: capture an Engineering Lesson anti-pattern so future
        # runs can avoid the same trajectory. The final verification reason
        # (truncated) is preserved in `examples` for diagnostic reuse.
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
            description=f"Failed to solve after {max_iterations} iterations.",
            lesson_type=LessonType.ANTI_PATTERN,
            category=_classify_engineering_category(task),
            severity=LessonSeverity.IMPORTANT,
            tags=[_classify_engineering_category(task)],
            examples=[failure_reason] if failure_reason else [],
            rationale="Exhausted repair iterations without a verified fix.",
        )
        # Priority 4: parallel ExperienceMemory capture (negative outcome).
        failed_category = _classify_engineering_category(task)
        self.experience_memory.store(
            title=task[:60],
            description=f"Failed to solve after {max_iterations} iterations.",
            category=failed_category,
            tags=[failed_category],
            outcome="negative",
            confidence=0.6,
            metadata={"iterations": max_iterations, "kind": "solve"},
        )
        return {
            "success": False,
            "iterations": max_iterations,
            "history": history,
        }

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
        """Execute the active goal (or a specific goal) through the planning pipeline.

        Workflow:
            Active Goal → Planner → Task Plan → Tool Selection → Execution
            → Memory Update → Goal Update → Repeat (if goal not complete)

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
        """
        from app.core.logger import logger

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

        for iteration in range(1, max_iterations + 1):
            iterations = iteration

            # Build task description from goal
            task_description = goal.description or goal.name

            # 1. Plan
            logger.info(f"[Goal Execution] Iteration {iteration}: Planning...")
            context = self.build_context(task_description)
            memory_context = self.memory.context()

            plan = self.planner.create_plan(task_description)

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
                    "plan_steps": plan.get("steps", []),
                    "outcome": outcome_summary,
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

        result = {
            "goal_id": goal.id,
            "goal_name": goal.name,
            "completed": is_completed,
            "iterations": iterations,
            "history": history,
            "progress": final_progress,
        }

        logger.info(f"[Goal Execution] Finished: {goal.name} — completed={is_completed}, "
                    f"progress={final_progress['percentage']:.1f}%")
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