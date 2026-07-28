from app.agent.executor import Executor
from app.agent.planner import Planner
from app.brain.state import ConversationState
from app.core.llm import LLM
from typing import Optional
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
        self.executor = Executor(self.llm, self.tools)
        self.patch_engine = PatchEngine()
        self.patch_generator = PatchGenerator(self.llm, self.patch_engine)
        self.verifier = VerificationRunner(workspace)
        self.planner = Planner(self.llm, self.memory)
        self.conversation = ConversationState(max_history=max_conversation_history, persistence_path=conversation_persistence_path)

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
        allowed_tools = set(Executor.READ_ONLY_TOOLS)
        if allow_mutations:
            allowed_tools.update(Executor.MUTATING_TOOLS)
        results = self.executor.execute_plan(plan, allowed_tools)
        conversation_history = self.conversation.get_history_text()
        prompt = f"""{conversation_history}

User request:
{task}

Relevant project code:
{context}

Recent project memory:
{memory_context}

Execution plan:
{plan}

Tool results:
{results}

Answer the user's request using the relevant code above. Quote code only when it is the actual answer; otherwise summarize."""
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
            plan_steps = plan.get("steps", [])
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
                self.engineering_lessons.store(
                    title=task[:60],
                    description=f"Solved in {it} iterations: {summary}",
                    lesson_type=LessonType.PATTERN,
                    category=_classify_engineering_category(task),
                    severity=LessonSeverity.RECOMMENDED,
                    tags=[_classify_engineering_category(task)],
                    rationale=f"Solved after {it} iterations; captured for future reference.",
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
            return self.patch_generator.propose(
                f"{task}\n\nVerification feedback:\n{feedback}", context
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
        except Exception as exc:
            # Capture is best-effort; never let logging disturb the repair outcome.
            logger.warning(f"Failed to record repair lesson: {exc}")
        return result

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