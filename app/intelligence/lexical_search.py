"""Dependency-free relevance ranking for local source code."""

import re
from pathlib import Path


class LexicalSearch:
    STOP_WORDS = {
        "a", "an", "and", "are", "can", "code", "do", "for", "from", "how",
        "i", "in", "is", "it", "of", "on", "please", "the", "this", "to", "with",
    }

    def __init__(self, symbol_index):
        self.symbol_index = symbol_index

    def search(self, query, limit=5):
        terms = self._terms(query)
        if not terms:
            return []

        results = []
        for path, source in self.symbol_index.files.items():
            score = self._score_file(path, source, terms)
            for symbol in self.symbol_index.symbols.get(path, []):
                symbol_score = score + self._score_text(symbol["name"], terms) * 8
                if symbol_score:
                    results.append((symbol_score, {"file": path, **symbol}))
            if score:
                results.append(
                    (score, {"file": path, "type": "file", "name": Path(path).name, "line": 1})
                )

        results.sort(key=lambda item: (-item[0], item[1]["file"], item[1]["line"]))
        unique = []
        seen = set()
        for _, match in results:
            key = (match["file"], match["type"], match["name"], match["line"])
            if key not in seen:
                seen.add(key)
                unique.append(match)
            if len(unique) >= limit:
                break
        return unique

    def _score_file(self, path, source, terms):
        return self._score_text(Path(path).stem, terms) * 5 + self._score_text(source, terms)

    @classmethod
    def _terms(cls, text):
        expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text).replace("_", " ")
        return {term.lower() for term in re.findall(r"[A-Za-z][A-Za-z0-9]*", expanded) if term.lower() not in cls.STOP_WORDS}

    @classmethod
    def _score_text(cls, text, terms):
        words = cls._terms(text)
        return sum(1 for term in terms if term in words)
