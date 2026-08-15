from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.core.performance import BoundedTTLCache


class ProjectIndex:
    IGNORE = {".git", ".venv", "__pycache__", "node_modules", ".pytest_cache", ".mypy_cache", ".idea", ".vscode"}
    EXTENSIONS = {".py", ".json", ".md", ".txt", ".toml", ".yaml", ".yml", ".ini"}

    def __init__(self, workspace, metadata_path=None, observability=None):
        self.workspace = Path(workspace)
        self.files: dict[str, str] = {}
        self.metadata_path = Path(metadata_path) if metadata_path else self.workspace / ".freya-index.json"
        self.metadata: dict[str, dict[str, Any]] = {}
        self.cache = BoundedTTLCache(max_size=128, ttl_seconds=300)
        self.observability = observability
        self.last_update = {"added": [], "modified": [], "deleted": [], "unchanged": [], "errors": []}
        self._load_metadata()

    def _load_metadata(self):
        try:
            if self.metadata_path.exists():
                data = json.loads(self.metadata_path.read_text(encoding="utf-8"))
                self.metadata = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            self.metadata = {}

    def _save_metadata(self):
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.metadata_path.with_suffix(self.metadata_path.suffix + ".tmp")
        temp.write_text(json.dumps(self.metadata, sort_keys=True), encoding="utf-8")
        temp.replace(self.metadata_path)

    def _eligible(self, path: Path) -> bool:
        return (path.is_file() and path.name != self.metadata_path.name
                and not any(part in self.IGNORE for part in path.parts)
                and path.suffix.lower() in self.EXTENSIONS)

    def _signature(self, path: Path) -> dict[str, Any]:
        stat = path.stat()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return {"mtime_ns": stat.st_mtime_ns, "size": stat.st_size, "sha256": digest}

    def update(self, *, force: bool = False) -> dict[str, list[str]]:
        added, modified, deleted, unchanged, errors = [], [], [], [], []
        discovered: dict[str, Path] = {}
        for path in self.workspace.rglob("*"):
            if self._eligible(path):
                discovered[str(path.relative_to(self.workspace))] = path
        for relative, path in discovered.items():
            try:
                sig = self._signature(path)
                old = self.metadata.get(relative)
                if not force and old and old.get("signature") == sig and relative in self.files:
                    unchanged.append(relative)
                    continue
                content = path.read_text(encoding="utf-8", errors="ignore")
                was_present = relative in self.metadata
                self.files[relative] = content
                self.metadata[relative] = {"signature": sig, "content_length": len(content)}
                (modified if was_present else added).append(relative)
                self.cache.invalidate(relative)
            except (OSError, UnicodeError) as exc:
                errors.append(f"{relative}: {exc}")
        for relative in list(self.metadata):
            if relative not in discovered:
                self.metadata.pop(relative, None)
                self.files.pop(relative, None)
                self.cache.invalidate(relative)
                deleted.append(relative)
        self._save_metadata()
        self.last_update = {"added": added, "modified": modified, "deleted": deleted, "unchanged": unchanged, "errors": errors}
        if self.observability:
            self.observability.record_metric("project_index.files", float(len(self.files)))
            self.observability.record_metric("project_index.changes", float(len(added) + len(modified) + len(deleted)))
        return self.last_update

    def build(self):
        self.update(force=True)
        return self.files

    def summary(self):
        return "\n".join(self.files.keys())

    def get(self, path):
        return self.files.get(path, "")

    def remove(self, path: str) -> bool:
        existed = path in self.files or path in self.metadata
        self.files.pop(path, None)
        self.metadata.pop(path, None)
        self.cache.invalidate(path)
        self._save_metadata()
        return existed
