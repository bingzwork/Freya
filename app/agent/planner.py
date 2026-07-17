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

        prompt = f"""
You are Freya, an autonomous coding AI.

Create a short execution plan for this task:

{task}

{memory_context}Return ONLY JSON.

Do not use markdown.
Do not use ```.

Format:

{{
    "steps": [
        "step 1",
        "step 2"
    ]
}}
"""

        answer = self.llm.ask(prompt)

        # remove markdown fences if model adds them

        answer = re.sub(
            r"```json|```",
            "",
            answer
        ).strip()


        try:

            plan = json.loads(answer)


        except Exception:

            plan = {
                "steps": [
                    answer
                ]
            }

        # Ensure we have a list of steps
        if isinstance(plan, dict) and isinstance(plan.get("steps"), list):
            # Limit to at most 5 steps to keep the plan concise
            if len(plan["steps"]) > 5:
                plan["steps"] = plan["steps"][:5]
        else:
            # Fallback: wrap the whole response as a single step
            plan = {"steps": [str(plan)]}

        return plan
