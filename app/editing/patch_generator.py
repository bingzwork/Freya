"""Ask the model for a constrained, machine-readable patch proposal."""

import json
import re

from app.editing.patch_engine import PatchEngine


class PatchGenerator:
    def __init__(self, llm, patch_engine=None):
        self.llm = llm
        self.patch_engine = patch_engine or PatchEngine()

    def propose(self, task, context):
        prompt = f"""
You are Freya, an AI software engineer. Propose a minimal code patch.

Task:
{task}

Relevant code:
{context}

Return ONLY JSON in this exact form:
{{
  "operations": [
    {{"action": "replace", "path": "relative/file.py", "old_text": "exact existing text", "new_text": "replacement"}},
    {{"action": "create", "path": "relative/new.py", "new_text": "file content"}}
  ]
}}

Allowed actions are create and replace. A replace operation must include text
that occurs exactly once. Do not include markdown fences or terminal commands.
"""
        answer = re.sub(r"```json|```", "", self.llm.ask(prompt)).strip()
        try:
            payload = json.loads(answer)
        except json.JSONDecodeError as error:
            raise ValueError("The model did not return valid patch JSON.") from error
        return self.patch_engine.parse(payload)
