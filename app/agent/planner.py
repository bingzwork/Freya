import json
import re

class Planner:
    def __init__(self, llm, memory=None):
        self.llm = llm
        self.memory = memory

    def create_plan(self, task):
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

{task_samples}{memory_context}Rules:
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
            plan = json.loads(answer)
        except Exception:
            plan = { "steps": [ answer ] }
        # Ensure we have a list of steps
        if isinstance(plan, dict) and isinstance(plan.get("steps"), list):
            # Limit to at most 5 steps to keep the plan concise
            if len(plan["steps"]) > 5:
                plan["steps"] = plan["steps"][:5]
        else:
            # Fallback: wrap the whole response as a single step
            plan = {"steps": [str(plan)]}
        return plan