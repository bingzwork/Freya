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

        # Define task-specific templates and examples
        task_samples = """Task Type Examples (use these as patterns):
- Build tasks: Detect project type, Restore dependencies if required, Build the project, Analyze build errors, Fix build errors if possible, Rebuild, Report results
- Debug/Fix tasks: Analyze the error/symptoms, Locate relevant code/files, Identify root cause, Implement a fix, Run validation/tests, Report results
- Refactor tasks: Analyze existing implementation and dependencies, Design refactoring approach, Implement changes incrementally, Preserve existing behavior, Run tests/validation, Report results
- Create/Implement tasks: Analyze requirements/project structure, Design solution/architecture, Implement the feature/module/API, Add tests if applicable, Validate functionality, Report results
- Explain tasks: Analyze the code/function/module, Identify key components and logic, Provide clear explanation with examples if helpful, Answer follow-up questions
- Review tasks: Examine the code/changes, Identify issues or improvements, Provide specific feedback, Suggest fixes or enhancements
- Test tasks: Design test cases, Implement test code, Run tests, Analyze results, Fix issues if found, Re-run tests
- Optimize tasks: Profile current performance, Identify bottlenecks, Design optimizations, Implement improvements, Validate results, Compare before/after metrics
"""

        prompt = f"""You are Freya, an autonomous coding AI. Create a short execution plan for this task: {task}

{task_samples}

{memory_context}Guidelines:
- Create a plan that is SPECIFIC to the type of task requested
- For "Build my project": include steps like detecting project type, restoring dependencies, building, analyzing errors
- For "Fix this Python error": include analyzing the error, locating code, implementing fix, validating
- For "Refactor this function": include analyzing current implementation, designing refactoring, implementing changes, testing
- For "Create a REST API": include analyzing structure, designing endpoints, implementing API, testing, validating
- For "Explain this function": include analyzing code, identifying key logic, providing clear explanation
- Do NOT generate generic software development workflows
- Each step must directly contribute to completing the specific request
- Keep steps concise and high-level
- Limit to 3-5 practical steps
- Return ONLY JSON. Do not use markdown. Do not use ```. 
Format: {{"steps": ["step 1", "step 2"]}}"""

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