import json
import re
from typing import Union

from app.core.logger import logger
from app.planner.plan_manager import Plan, PlanConfig, PlanManager, Task, TaskPriority, TaskCategory


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


class Planner:
    # Severities the planner surfaces. INFO is intentionally omitted because
    # it adds noise without influencing planning decisions.
    _LESSON_SEVERITY_WHITELIST = ("critical", "important", "recommended")
    _SEVERITY_RANK = {"critical": 0, "important": 1, "recommended": 2}
    _LESSON_SECTION_LIMIT = 3

    def __init__(self, llm, memory=None, engineering_lessons=None, plan_manager: PlanManager = None):
        self.llm = llm
        self.memory = memory
        self.engineering_lessons = engineering_lessons
        self.plan_manager = plan_manager or PlanManager()

    def create_plan(self, task: str, name: str = "Generated Plan") -> Plan:
        logger.info("[Planner]")
        logger.info("Started")

        # Get relevant memory
        memory_context = ""
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
        # ``EngineeringLessonStorage.get_patterns()`` retrieval API; ANTI /
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

        prompt = f"""Plan a SHORT execution for this engineering task: {task}

{task_samples}{memory_context}{lessons_context}Rules:
- Every step must map to one executable tool: read_file, write_file, replace_in_file, list_files, run_terminal, create_file, delete_file, git_*, http_*, format_file.
- Max 5 steps. Keep each step one short imperative ("Read file X", "Run pytest", "Fix the code"). Never describe reasoning.
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

        answer = self.llm.ask(prompt)
        # remove markdown fences if model adds them
        answer = re.sub(
            r"```json|```", "", answer
        ).strip()
        try:
            plan_dict = json.loads(answer)
        except Exception:
            plan_dict = {"steps": [answer]}
        # Ensure we have a list of steps
        if isinstance(plan_dict, dict) and isinstance(plan_dict.get("steps"), list):
            # Limit to at most 5 steps to keep the plan concise
            if len(plan_dict["steps"]) > 5:
                plan_dict["steps"] = plan_dict["steps"][:5]
        else:
            # Fallback: wrap the whole response as a single step
            plan_dict = {"steps": [str(plan_dict)]}

        logger.info("[Planner]")
        logger.info("Finished")

        # Create a Plan object using PlanManager
        config = PlanConfig(name=name, description=task)
        plan = self.plan_manager.create_plan(config.name, config.description)

        # Add tasks from the LLM-generated steps
        for i, step in enumerate(plan_dict.get("steps", [])):
            if step.strip():
                self.plan_manager.add_task(
                    title=step,
                    description="",
                    priority=config.default_priority,
                    category=config.default_category,
                    estimated_hours=config.default_estimated_hours,
                )

        return plan

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