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
        task_samples = """Engineering Task Examples (ONLY executable tool actions):

- Build tasks: Detect project type, Restore dependencies, Build project, Run build command, Fix build errors, Rebuild, Report results
- Debug/Fix tasks: Read error file, Read code files, Locate relevant code, Fix the code, Run validation tests, Report results
- Refactor tasks: Read existing implementation, Modify code files, Run tests, Report results
- Create/Implement tasks: Read requirements, Write implementation files, Add tests, Run validation, Report results
- Review tasks: Read code files, Write feedback, Suggest fixes
- Test tasks: Write test files, Run tests, Fix issues, Re-run tests
- Optimize tasks: Profile performance, Implement optimizations, Run benchmarks, Compare results

FORBIDDEN STEPS (these are LLM REASONING, not executable tool actions):
- Analyze, Understand, Explain, Summarize, Describe, Identify, Provide, Answer, Clarify, Determine, Design, Locate
- These happen AFTER tools execute, NOT as plan steps
"""

        prompt = f"""You are Freya, an autonomous coding AI. Create a SHORT EXECUTION PLAN for this ENGINEERING task: {task}

{task_samples}

{memory_context}CRITICAL RULES:
- ONLY generate steps that map to EXECUTABLE TOOLS: read_file, write_file, replace_in_file, list_files, run_terminal, create_file, delete_file, git_*, http_*, format_file
- NEVER include reasoning steps: NO "analyze", "understand", "explain", "summarize", "describe", "identify", "provide", "answer", "clarify", "determine"
- If the request is NOT an engineering task (knowledge question, capability question, identity, status), return {{"steps": []}} - empty plan
- Each step MUST be a concrete TOOL ACTION: "Read file X", "Run command Y", "Write file Z", "List directory"
- Max 5 steps. Keep steps concise.
- Return ONLY JSON. No markdown. No explanations.
Format: {{"steps": ["step 1", "step 2"]}}

EXAMPLES:
- "Read app/router.py" -> {{"steps": ["Read app/router.py"]}}
- "Run pytest" -> {{"steps": ["Run pytest"]}}
- "Fix this bug: <traceback>" -> {{"steps": ["Read error file", "Read relevant code files", "Fix the code", "Run tests"]}}
- "What is Python?" -> {{"steps": []}}  (not engineering - empty plan)
- "Explain this function: <code>" -> {{"steps": []}}  (not engineering - empty plan)
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