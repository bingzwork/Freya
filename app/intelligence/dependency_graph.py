"""Lightweight local Python import graph for context expansion."""

import ast
from pathlib import PurePosixPath


class DependencyGraph:
    def __init__(self, symbol_index):
        self.symbol_index = symbol_index
        self.dependencies = {}

    def build(self):
        self.dependencies = {
            path: self._dependencies_for(path, source)
            for path, source in self.symbol_index.files.items()
        }
        return self.dependencies

    def related_files(self, path, limit=3):
        return self.dependencies.get(path, [])[:limit]

    def _dependencies_for(self, path, source):
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []

        dependencies = []
        for node in ast.walk(tree):
            module = None
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module = alias.name
                    resolved = self._resolve_module(path, module)
                    if resolved:
                        dependencies.append(resolved)
            elif isinstance(node, ast.ImportFrom) and node.module:
                resolved = self._resolve_module(path, node.module, node.level)
                if resolved:
                    dependencies.append(resolved)

        return list(dict.fromkeys(dependencies))

    def _resolve_module(self, source_path, module, level=0):
        parent = PurePosixPath(source_path).parent
        if level:
            for _ in range(level - 1):
                parent = parent.parent
            base = parent / PurePosixPath(module.replace(".", "/"))
        else:
            base = PurePosixPath(module.replace(".", "/"))

        candidates = (f"{base}.py", f"{base}/__init__.py")
        return next((item for item in candidates if item in self.symbol_index.files), None)
