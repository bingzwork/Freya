"""Small, local, durable memory for Freya project sessions."""

import json
from datetime import datetime, timezone
from pathlib import Path


class ProjectMemory:
    def __init__(self, workspace, relative_path="data/memory/freya_memory.json", limit=200):
        self.workspace = Path(workspace).resolve()
        self.path = self.workspace / relative_path
        self.limit = limit

    def record(self, kind, content):
        if not isinstance(content, dict):
            raise TypeError("Memory content must be a dictionary.")
        entries = self._load()
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            "content": content,
        }
        entries.append(entry)
        self._save(entries[-self.limit :])
        return entry

    def record_edit(self, task, operation_type, file_path, diff_summary=""):
        """Record an edit operation performed on a file."""
        content = {
            "task": task,
            "operation_type": operation_type,  # e.g., "replace", "create"
            "file": file_path,
            "diff_summary": diff_summary,
        }
        return self.record("edit", content)

    def recent(self, limit=5):
        return self._load()[-limit:]

    def recent_edits(self, limit=5):
        """Return the most recent edit records."""
        all_entries = self._load()
        edits = [e for e in all_entries if e.get("kind") == "edit"]
        return edits[-limit:]

    def context(self, limit=5, max_characters=2_000):
        lines = [
            f"- {entry['kind']}: {json.dumps(entry['content'], ensure_ascii=False)}"
            for entry in self.recent(limit)
        ]
        return "\n".join(lines)[:max_characters]

    def search(self, keyword, limit=10):
        """Return entries whose content contains the keyword (case-insensitive)."""
        keyword_lower = keyword.lower()
        matches = []
        for entry in self._load():
            content_str = json.dumps(entry["content"], ensure_ascii=False).lower()
            if keyword_lower in content_str:
                matches.append(entry)
        return matches[-limit:] if limit else matches

    def _load(self):
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return data if isinstance(data, list) else []

    def _save(self, entries):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.path)