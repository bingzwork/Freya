"""Compact, symbol-level context with local window and imports."""

from __future__ import annotations

from typing import List, Dict, Any, Set

from app.core.performance import BoundedTTLCache


class ContextBuilder:
    def __init__(self, symbol_index, dependency_graph, max_characters=12_000):
        self.symbol_index = symbol_index
        self.dependency_graph = dependency_graph
        self.max_characters = max_characters
        self._cache = BoundedTTLCache(max_size=64, ttl_seconds=30.0)

    def build(self, matches):
        key = (tuple((m.get("file"), m.get("type"), m.get("name"), m.get("line")) for m in matches), self.max_characters)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        sections = []
        included_files = set()

        for match in matches:
            section = self._section_for_match(match)
            if section:
                sections.append(section)
                included_files.add(match["file"])

        for path in list(included_files):
            for dependency in self.dependency_graph.related_files(path):
                if dependency in included_files:
                    continue
                section = self._dependency_section(dependency)
                if section:
                    sections.append(section)
                    included_files.add(dependency)

        context = "\n\n".join(sections)
        result = context[: self.max_characters]
        self._cache.set(key, result)
        return result

    def invalidate_cache(self):
        self._cache.invalidate()

    def _section_for_match(self, match: Dict[str, Any]) -> str:
        """
        Return a context window around the match:
        - Import statements from the file.
        - A span of lines around the matched line (±window_lines).
        For file‑type matches we return the whole file (truncated later).
        """
        path = match["file"]
        source = self.symbol_index.get_file(path)
        if source is None:
            return ""

        lines = source.splitlines()
        total_lines = len(lines)

        if match.get("type") == "file":
            # For a file match we return the whole file (will be truncated by max_chars).
            return f"FILE: {path}\nCODE:\n{source}"

        # Symbol‑type match: show a window around the line.
        line_no = max(0, int(match.get("line", 1)) - 1)  # zero‑based
        window_lines = 8  # lines before and after
        start = max(0, line_no - window_lines)
        end = min(total_lines, line_no + window_lines + 1)

        window = lines[start:end]

        # Collect import lines from the whole file (first 50 lines to keep it cheap).
        import_lines: List[str] = []
        for i, ln in enumerate(lines[:50]):
            stripped = ln.lstrip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                import_lines.append(ln.rstrip())

        # Deduplicate while preserving order.
        seen: Set[str] = set()
        unique_imports = []
        for imp in import_lines:
            if imp not in seen:
                seen.add(imp)
                unique_imports.append(imp)

        parts: List[str] = []
        if unique_imports:
            parts.append("IMPORTS:")
            parts.extend(unique_imports)
            parts.append("")  # blank line

        # Header with file and symbol info.
        parts.append(f"FILE: {path}")
        parts.append(
            f"SYMBOL: {match.get('type', '').upper()} {match.get('name', '')} "
            f"(line {match.get('line', '?')})"
        )
        parts.append("CODE:")
        parts.extend(window)

        return "\n".join(parts)

    def _dependency_section(self, path: str) -> str:
        symbols = self.symbol_index.symbols.get(path, [])
        if not symbols:
            return ""
        symbol = symbols[0]
        source = self.symbol_index.get_symbol_source(path, symbol)
        if source is None:
            return ""
        return (
            f"DEPENDENCY: {path}\n"
            f"SYMBOL: {symbol['type']} {symbol['name']}\n"
            f"CODE:\n{source}"
        )
