import json
import re
from typing import Union, List, Tuple

from app.core.logger import logger
from app.planner.plan_manager import Plan, PlanConfig, PlanManager, Task, TaskPriority, TaskCategory, PlanningHorizon
from app.agent.planner_base import PlannerProtocol


# Rule-based category mapping shared with ``_classify_engineering_category``
# in ``app/agent/core_agent.py``. Kept inline here because the planner module
# sits below ``core_agent`` in the import graph; duplicating the tiny lookup
# avoids introducing a new shared module (see SELF_LEARNING.md Priority 3).
_LESSON_KEYWORDS = {
    "test": ("test", "pytest", "spec"),
    "build": ("build", "compile", "install", "package"),
    "refactor": ("refactor", "rename", "restructure", "cleanup"),
    "debug": ("debug", "fix", "bug", "error", "traceback", "failure"),
    "understand": ("understand", "explain", "describe", "how does", "what does"),
}


def _classify_lesson_category(task: str) -> str:
    """Return the first matching lesson category for a task description."""
    if not task:
        return "task"
    lowered = task.lower()
    for category in ("test", "build", "refactor", "debug", "understand"):
        for keyword in _LESSON_KEYWORDS[category]:
            if keyword in lowered:
                return category
    return "task"


class Planner(PlannerProtocol):
    # Severities the planner surfaces. INFO is intentionally omitted because
    # it adds noise without influencing planning decisions.
    _LESSON_SEVERITY_WHITELIST = ("critical", "important", "recommended")
    _SEVERITY_RANK = {"critical": 0, "important": 1, "recommended": 2}
    _LESSON_SECTION_LIMIT = 3

    # Risk and difficulty weights for plan scoring
    _RISK_WEIGHT = 0.5
    _DIFFICULTY_WEIGHT = 0.5
    _MODEL_PLAN_TIMEOUT_SECONDS = 8.0

    def __init__(self, llm, memory=None, engineering_lessons=None, plan_manager: PlanManager = None):
        self.llm = llm
        self.memory = memory
        self.engineering_lessons = engineering_lessons
        self.plan_manager = plan_manager or PlanManager()
        self._model_fallback_used = False

    def create_plan(
        self,
        task: str,
        name: str = "Generated Plan",
        external_context: str = "",
    ) -> Plan:
        logger.info("[Planner]")
        logger.info("Started")
        self._model_fallback_used = False

        # Classify planning horizon first
        horizon = self._classify_planning_horizon(task)
        max_steps = self._get_max_steps_for_horizon(horizon)
        logger.info(f"[Planner] Planning horizon: {horizon.value} (max steps: {max_steps})")

        # Get relevant memory. UnifiedPlanner supplies the target router
        # preflight context here; legacy callers continue with an empty value.
        memory_context = external_context.strip()
        if memory_context:
            memory_context += "\n\n"
        if self.memory is not None:
            # search for task keywords
            try:
                relevant = self.memory.search(task, limit=3)
                if relevant:
                    mem_lines = ["Relevant past experience:"]
                    for entry in relevant:
                        kind = entry.get('kind', 'unknown')
                        content = entry.get('content', {})
                        # Format content nicely
                        content_str = json.dumps(content, ensure_ascii=False)
                        mem_lines.append(f"- {kind}: {content_str}")
                    memory_context = "\n".join(mem_lines) + "\n\n"
            except Exception:
                # If memory fails, just ignore
                pass

        # Priority 3 (Self-Learning): surface recent Engineering Lessons
        # matching the inferred task category. Reuses the existing
        # ``EngineeringLessonStorage.get_patterns`` retrieval API; ANTI /
        # DECISION / lower-tier severities are filtered and the result is
        # re-sorted by severity (CRITICAL first), with recency as a stable
        # tie-breaker since ``get_patterns`` already returns newest-first.
        lessons_context = self._build_lessons_context(task)

        # Define task-specific templates and examples for ENGINEERING TASKS ONLY
        # ONLY executable engineering actions that map to TOOLS should appear here
        # REASONING steps (analyze, understand, explain, summarize, describe, identify, provide, answer) are NOT executable
        task_samples = """Engineering step patterns (each step names ONE tool action):

- Build: detect project type, restore dependencies, build, fix build errors, report results
- Debug/Fix: read the failing file, read related code, fix the code, run the tests
- Refactor: read the existing code, modify it, run the tests
- Create/Implement: read requirements, write the code, add tests, validate
- Review: read the code, then write feedback / suggestions (no tool action needed for the review itself)
- Test: write tests, run them, fix failures, re-run
- Optimize: profile, change code, run benchmarks, compare

Forbidden verbs as steps (these are LLM reasoning, not tool actions): analyze,
understand, explain, summarize, describe, identify, provide, answer, clarify,
determine, design, locate. Reasoning happens AFTER tools execute.
"""

        # We will generate up to two candidate plans and select the best one
        # based on risk and difficulty scores.
        plans: List[Tuple[Plan, float]] = []  # (plan, score)

        # Generate first plan with the original prompt
        plan1 = self._generate_plan(task, name, horizon, max_steps,
            f"""Plan a SHORT execution for this engineering task: {task}

{task_samples}{memory_context}{lessons_context}Rules:
- Every step must map to one executable tool: read_file, write_file, replace_in_file, list_files, run_terminal, create_file, delete_file, git_*, http_*, format_file.
- Max {max_steps} steps. Keep each step one short imperative ("Read file X", "Run pytest", "Fix the code"). Never describe reasoning.
- If the request is not an engineering task (chat, knowledge, capability, identity, status), return an empty plan: {{"steps": []}}.
- Return ONLY valid JSON. No markdown fences, no prose around it.

Format: {{"steps": ["step 1", "step 2"]}}

Examples:
- "Read app/router.py" -> {{"steps": ["Read app/router.py"]}}
- "Run pytest" -> {{"steps": ["Run pytest"]}}
- "Fix this bug: <traceback>" -> {{"steps": ["Read the error file", "Read relevant code files", "Fix the code", "Run tests"]}}
- "What is Python?" -> {{"steps": []}}
- "Explain this function: <code>" -> {{"steps": []}}
"""
        )
        if plan1:
            score1 = self._score_plan(plan1)
            plans.append((plan1, score1))

        # Generate second plan with a prompt that encourages an alternative approach
        # Only generate a second plan if the task seems complex enough to warrant alternatives.
        # We consider a task complex if the first plan has more than 2 steps or if the task
        # description contains certain keywords that suggest complexity.
        if not self._model_fallback_used and self._should_generate_alternative(task, plan1):
            plan2 = self._generate_plan(task, name + " (Alternative)", horizon, max_steps,
                f"""Plan a SHORT execution for this engineering task: {task}

{task_samples}{memory_context}{lessons_context}Rules:
- Every step must map to one executable tool: read_file, write_file, replace_in_file, list_files, run_terminal, create_file, delete_file, git_*, http_*, format_file.
- Max {max_steps} steps. Keep each step one short imperative ("Read file X", "Run pytest", "Fix the code"). Never describe reasoning.
- If the request is not an engineering task (chat, knowledge, capability, identity, status), return an empty plan: {{"steps": []}}.
- Return ONLY valid JSON. No markdown fences, no prose around it.
- Consider an alternative approach to the one you might typically take.

Format: {{"steps": ["step 1", "step 2"]}}

Examples:
- "Read app/router.py" -> {{"steps": ["Read app/router.py"]}}
- "Run pytest" -> {{"steps": ["Run pytest"]}}
- "Fix this bug: <traceback>" -> {{"steps": ["Read the error file", "Read relevant code files", "Fix the code", "Run tests"]}}
- "What is Python?" -> {{"steps": []}}
- "Explain this function: <code>" -> {{"steps": []}}
"""
            )
            if plan2:
                score2 = self._score_plan(plan2)
                plans.append((plan2, score2))

        # If we have no plans (should not happen), return a default plan
        if not plans:
            # Create a default plan with no tasks
            config = PlanConfig(name=name, description=task, planning_horizon=horizon, max_steps=max_steps)
            plan = self.plan_manager.create_plan(config.name, config.description)
            plan.risk_score = 0.0
            plan.difficulty = 0.0
            plan.planning_horizon = horizon
            return plan

        # Select the plan with the highest score
        best_plan, best_score = max(plans, key=lambda x: x[1])
        logger.info(f"[Planner] Selected plan with score {best_score:.3f}")
        return best_plan

    def _ask_plan(self, prompt: str, task: str) -> str:
        """Return a bounded plan response or a safe original-task fallback."""
        outcome_reader = getattr(self.llm, "ask_outcome", None)
        try:
            if callable(outcome_reader):
                outcome = outcome_reader(
                    prompt, timeout=self._MODEL_PLAN_TIMEOUT_SECONDS
                )
                if not getattr(outcome, "is_success", False):
                    raise RuntimeError(
                        getattr(outcome, "reason", "") or str(getattr(outcome, "kind", "unknown"))
                    )
                return outcome.content or json.dumps({"steps": [task]})
            try:
                return self.llm.ask(
                    prompt, timeout=self._MODEL_PLAN_TIMEOUT_SECONDS
                )
            except TypeError as error:
                if "timeout" not in str(error).lower():
                    raise
                return self.llm.ask(prompt)
        except Exception as error:
            self._model_fallback_used = True
            logger.warning(f"[Planner] Model planning failed; using the original task before safety checks: {error}")
            return json.dumps({"steps": [task]})

    def _generate_plan(self, task: str, name: str, horizon: PlanningHorizon, max_steps: int, prompt: str) -> Plan:
        """Generate a single plan from the given prompt."""
        answer = self._ask_plan(prompt, task)
        # remove markdown fences if model adds them
        answer = re.sub(
            r"```json|```", "", answer
        ).strip()
        try:
            plan_dict = json.loads(answer)
        except Exception:
            self._model_fallback_used = True
            plan_dict = {"steps": [task]}
        # Ensure we have a list of steps
        if isinstance(plan_dict, dict) and isinstance(plan_dict.get("steps"), list):
            # Limit to at most max_steps steps based on planning horizon
            if len(plan_dict["steps"]) > max_steps:
                plan_dict["steps"] = plan_dict["steps"][:max_steps]
        else:
            self._model_fallback_used = True
            plan_dict = {"steps": [task]}

        # Generate rationale for the plan and each step
        step_rationales = self._generate_step_rationales(task, plan_dict.get("steps", []), horizon)
        plan_rationale = self._generate_plan_rationale(task, horizon, plan_dict.get("steps", []))

        # Create a Plan object using PlanManager with horizon config
        config = PlanConfig(name=name, description=task, planning_horizon=horizon, max_steps=max_steps)
        plan = self.plan_manager.create_plan(config.name, config.description)

        # Set plan-level attributes
        plan.planning_horizon = horizon
        plan.rationale = plan_rationale

        # Add tasks from the LLM-generated steps with rationale
        task_ids = []
        steps = plan_dict.get("steps", [])
        for i, step in enumerate(steps):
            if step.strip():
                rationale = step_rationales[i] if i < len(step_rationales) else "Execute this step as part of the solution."
                task = self.plan_manager.add_task(
                    title=step,
                    description="",
                    priority=config.default_priority,
                    category=config.default_category,
                    estimated_hours=config.default_estimated_hours,
                )
                if task:
                    task.rationale = rationale
                    task_ids.append(task.id)

        # Add sequential dependencies: step i+1 depends on step i
        # This creates DependencyEdge objects and establishes parent/child TaskNode relationships
        if len(task_ids) > 1:
            for i in range(1, len(task_ids)):
                self.plan_manager.add_dependency(plan.id, task_ids[i - 1], task_ids[i])

        # Compute and set risk and difficulty scores for the plan
        risk, difficulty = self._assess_plan_risk_and_difficulty(plan)
        plan.risk_score = risk
        plan.difficulty = difficulty

        return plan

    def _should_generate_alternative(self, task: str, plan: Plan) -> bool:
        """Determine whether to generate an alternative plan based on task complexity."""
        # Generate an alternative if the plan has more than 2 steps (non-trivial)
        if len(plan.tasks) > 2:
            return True
        # Also generate an alternative if the task description contains keywords
        # that suggest complexity or multiple possible approaches.
        complex_keywords = [
            "refactor", "optimize", "design", "architect", "implement", "create",
            "build", "deploy", "migrate", "refactor", "restructure", "redesign",
            "analyze", "investigate", "research", "compare", "evaluate"
        ]
        task_lower = task.lower()
        if any(keyword in task_lower for keyword in complex_keywords):
            return True
        return False

    def _assess_plan_risk_and_difficulty(self, plan: Plan) -> tuple[float, float]:
        """Assess the risk and difficulty of a plan.

        Returns:
            tuple (risk, difficulty) where each is a float between 0.0 and 1.0.
        """
        if not plan.tasks:
            return 0.0, 0.0

        # Risk assessment based on task categories
        risk_scores = []
        for task in plan.tasks:
            # Base risk on task category
            category_risk = {
                TaskCategory.IMPLEMENTATION: 0.3,
                TaskCategory.TESTING: 0.2,
                TaskCategory.BUG_FIX: 0.4,
                TaskCategory.REVIEW: 0.1,
                TaskCategory.REFACTORING: 0.4,
                TaskCategory.FEATURE: 0.3,
                TaskCategory.MAINTENANCE: 0.2,
            }.get(task.category, 0.3)

            # Adjust risk based on specific tools implied by the task title
            title_lower = task.title.lower()
            if any(keyword in title_lower for keyword in ["delete", "remove", "drop"]):
                category_risk = min(1.0, category_risk + 0.4)
            elif any(keyword in title_lower for keyword in ["write", "create", "replace"]):
                category_risk = min(1.0, category_risk + 0.2)
            elif any(keyword in title_lower for keyword in ["run", "execute", "terminal"]):
                category_risk = min(1.0, category_risk + 0.3)
            elif any(keyword in title_lower for keyword in ["git", "push", "commit", "pull"]):
                category_risk = min(1.0, category_risk + 0.2)

            risk_scores.append(category_risk)

        # Overall risk is the average of task risks (could also use max)
        risk = sum(risk_scores) / len(risk_scores) if risk_scores else 0.0
        risk = max(0.0, min(1.0, risk))  # Clamp to [0, 1]

        # Difficulty assessment based on number of tasks and estimated hours
        # Normalize by assuming max 5 tasks and 20 hours as high difficulty
        # Adjust for planning horizon - long horizon plans can have more tasks
        max_tasks_for_normalization = {
            PlanningHorizon.SHORT: 3,
            PlanningHorizon.MEDIUM: 8,
            PlanningHorizon.LONG: 15,
        }.get(plan.planning_horizon, 5)
        task_count_factor = min(1.0, len(plan.tasks) / float(max_tasks_for_normalization))
        hours = sum(task.estimated_hours for task in plan.tasks)
        hours_factor = min(1.0, hours / 20.0)

        # Combine factors with weights
        difficulty = 0.6 * task_count_factor + 0.4 * hours_factor
        difficulty = max(0.0, min(1.0, difficulty))

        return risk, difficulty

    def _score_plan(self, plan: Plan) -> float:
        """Score a plan based on risk and difficulty (higher is better).

        Uses a weighted combination: score = 1 - (risk_weight * risk + difficulty_weight * difficulty)
        """
        risk = plan.risk_score
        difficulty = plan.difficulty
        score = 1.0 - (self._RISK_WEIGHT * risk + self._DIFFICULTY_WEIGHT * difficulty)
        # Ensure score is between 0 and 1
        return max(0.0, min(1.0, score))

    # ------------------------------------------------------------------
    # Priority 3 helpers (Self-Learning read-side).
    # ------------------------------------------------------------------

    def _build_lessons_context(self, task: str) -> str:
        """Render a ``Past Engineering Lessons`` block for the planner prompt.

        Reuses ``EngineeringLessonStorage.get_patterns`` for retrieval so the
        underlying storage layer remains unchanged. Returns an empty string
        when no lessons match or the storage raises.
        """
        if self.engineering_lessons is None or not task:
            return ""
        try:
            category = _classify_lesson_category(task)
            # ``get_patterns`` already returns newest-first; we over-fetch and
            # post-filter by severity, then stable-sort by severity rank so
            # CRITICAL > IMPORTANT > RECOMMENDED while preserving recency
            # within each bucket.
            patterns = self.engineering_lessons.get_patterns(
                category=category, limit=20
            )
        except Exception:
            return ""
        eligible = [
            p for p in patterns if p.severity in self._LESSON_SEVERITY_WHITELIST
        ]
        if not eligible:
            return ""
        eligible.sort(key=lambda p: self._SEVERITY_RANK.get(p.severity, 99))
        selected = eligible[: self._LESSON_SECTION_LIMIT]
        lines = ["Past Engineering Lessons:"]
        for lesson in selected:
            description = (lesson.description or "")[:200]
            lines.append(
                f"- [{lesson.severity}] {lesson.title}: {description}"
            )
        return "\n".join(lines) + "\n\n"

    # ------------------------------------------------------------------
    # Planning Horizon Classification
    # ------------------------------------------------------------------

    def _classify_planning_horizon(self, task: str) -> PlanningHorizon:
        """Classify the planning horizon based on task characteristics.

        Uses lightweight heuristics:
        - Estimated steps based on keywords and complexity
        - Task complexity indicators
        - Expected execution time
        - Number of files/tools involved
        """
        task_lower = task.lower()

        # Count complexity indicators
        complexity_score = 0

        # Multiple files/locations mentioned
        file_indicators = len(re.findall(r'\b\w+\.(py|js|ts|java|cpp|rs|go|md|txt|json|yaml|yml|toml|ini|cfg)\b', task_lower))
        if file_indicators >= 3:
            complexity_score += 2
        elif file_indicators >= 1:
            complexity_score += 1

        # Multi-step keywords
        multi_step_keywords = [
            "refactor", "implement", "create", "build", "deploy", "migrate",
            "restructure", "redesign", "architect", "develop", "feature",
            "system", "module", "component", "service", "api", "database",
            "integration", "workflow", "pipeline", "automation"
        ]
        multi_step_count = sum(1 for kw in multi_step_keywords if kw in task_lower)
        if multi_step_count >= 3:
            complexity_score += 2
        elif multi_step_count >= 1:
            complexity_score += 1

        # Phase/multi-stage indicators
        phase_keywords = ["phase", "stage", "step", "milestone", "iterat", "sprint", "epic"]
        if any(kw in task_lower for kw in phase_keywords):
            complexity_score += 2

        # Tool diversity indicators
        tool_keywords = ["test", "lint", "build", "deploy", "docker", "git", "ci", "cd", "benchmark", "profile"]
        tool_count = sum(1 for kw in tool_keywords if kw in task_lower)
        if tool_count >= 3:
            complexity_score += 1

        # Goal hierarchy indicator (if mentioned)
        if "goal" in task_lower or "objective" in task_lower:
            complexity_score += 1

        # Debug/fix with traceback = usually short
        if "traceback" in task_lower or "error" in task_lower:
            if "fix" in task_lower or "debug" in task_lower:
                complexity_score = max(0, complexity_score - 1)

        # Simple question/read-only = short
        if any(kw in task_lower for kw in ["what is", "how to", "explain", "describe", "show me", "list", "find"]):
            complexity_score = min(complexity_score, 1)

        # Classify based on score
        if complexity_score >= 5:
            return PlanningHorizon.LONG
        elif complexity_score >= 2:
            return PlanningHorizon.MEDIUM
        else:
            return PlanningHorizon.SHORT

    def _get_max_steps_for_horizon(self, horizon: PlanningHorizon) -> int:
        """Get the maximum number of steps for a planning horizon."""
        return {
            PlanningHorizon.SHORT: 3,
            PlanningHorizon.MEDIUM: 8,
            PlanningHorizon.LONG: 15,
        }.get(horizon, 5)

    def _generate_plan_rationale(self, task: str, horizon: PlanningHorizon, steps: List[str]) -> str:
        """Generate a plain-English rationale for the overall plan."""
        if not steps:
            return "No engineering steps needed for this request."

        horizon_reasons = {
            PlanningHorizon.SHORT: "This is a focused task that can be completed in a few direct steps.",
            PlanningHorizon.MEDIUM: "This task requires multiple coordinated steps across several files or operations.",
            PlanningHorizon.LONG: "This is a complex, multi-phase task requiring careful planning and execution.",
        }

        base = horizon_reasons.get(horizon, "")
        step_summary = f"The plan has {len(steps)} step(s): " + "; ".join(f"{s}" for s in steps[:3])
        if len(steps) > 3:
            step_summary += f"; and {len(steps) - 3} more"

        return f"{base} {step_summary}."

    def _generate_step_rationales(self, task: str, steps: List[str], horizon: PlanningHorizon) -> List[str]:
        """Generate plain-English rationales for each step."""
        rationales = []
        task_lower = task.lower()

        # Common patterns for rationale
        for i, step in enumerate(steps):
            step_lower = step.lower()

            # First step - usually exploration/reading
            if i == 0:
                if "read" in step_lower or "list" in step_lower or "find" in step_lower or "locate" in step_lower:
                    rationales.append("First, we need to understand the current state by examining relevant files.")
                elif "run" in step_lower and ("test" in step_lower or "pytest" in step_lower):
                    rationales.append("Start by running tests to establish a baseline and see current failures.")
                else:
                    rationales.append("Begin with this step to gather necessary context.")
                continue

            # Last step - usually verification
            if i == len(steps) - 1:
                if "test" in step_lower or "verify" in step_lower or "run" in step_lower:
                    rationales.append("Finally, verify the changes work correctly by running tests.")
                elif "build" in step_lower or "compile" in step_lower:
                    rationales.append("Complete the task by building to ensure everything compiles.")
                else:
                    rationales.append("Final step to complete the task and verify results.")
                continue

            # Middle steps - categorize by action
            if "write" in step_lower or "create" in step_lower or "implement" in step_lower:
                rationales.append("Create the necessary code or files to implement the solution.")
            elif "replace" in step_lower or "modify" in step_lower or "fix" in step_lower or "edit" in step_lower or "update" in step_lower:
                rationales.append("Modify existing code to apply the required changes.")
            elif "read" in step_lower or "examine" in step_lower or "review" in step_lower:
                rationales.append("Examine related code to understand dependencies and impacts.")
            elif "run" in step_lower or "execute" in step_lower:
                if "test" in step_lower:
                    rationales.append("Run tests to verify the changes work correctly.")
                else:
                    rationales.append("Execute a command to apply changes or gather information.")
            elif "git" in step_lower or "commit" in step_lower or "push" in step_lower:
                rationales.append("Save changes to version control.")
            elif "install" in step_lower or "dependency" in step_lower:
                rationales.append("Install required dependencies or packages.")
            else:
                rationales.append("Execute this step as part of the solution.")

        return rationales