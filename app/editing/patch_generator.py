"""Ask the model for a constrained, machine-readable patch proposal."""

import json
import re

from app.editing.patch_engine import PatchEngine


class PatchGenerator:
    def __init__(self, llm, patch_engine=None):
        self.llm = llm
        self.patch_engine = patch_engine or PatchEngine()

    def propose(self, task, context):
        prompt = f"""Propose the minimal patch for this task.

Task:
{task}

Relevant code:
{context}

Return ONLY this JSON (no markdown, no commentary):
{{
  "operations": [
    {{"action": "replace", "path": "relative/file.py", "old_text": "exact existing text", "new_text": "replacement"}},
    {{"action": "create", "path": "relative/new.py", "new_text": "file content"}}
  ]
}}

Rules:
- Only "create" or "replace" actions.
- Each "replace" old_text must occur exactly once in the file.
- No terminal commands, no extra keys.
- Prefer one operation that solves the task; add more only when needed."""
        answer = re.sub(r"```json|```", "", self.llm.ask(prompt)).strip()
        try:
            payload = json.loads(answer)
        except json.JSONDecodeError as error:
            raise ValueError("The model did not return valid patch JSON.") from error
        return self.patch_engine.parse(payload)
