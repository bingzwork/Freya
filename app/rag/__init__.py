"""
Simple Retrieval-Augmented Generation (RAG) module for Freya.

Provides a lightweight retrieval mechanism based on keyword matching
over the project's symbol index. This can be used to fetch relevant
code snippets for augmenting LLM prompts.
"""

from __future__ import annotations

from typing import List, Dict, Any
from app.intelligence.lexical_search import LexicalSearch
from app.core.symbol_index import SymbolIndex


class SimpleRetriever:
    """Retrieve relevant code snippets given a query."""

    def __init__(self, symbol_index: SymbolIndex):
        self._lexical = LexicalSearch(symbol_index)

    def retrieve(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Return a list of matching symbols/files ranked by relevance.

        Each result is a dict with keys: file, type, name, line.
        """
        return self._lexical.search(query, limit=limit)

    def retrieve_source(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Retrieve results and include the source snippet for each match.

        Adds a 'source' field containing the relevant lines.
        """
        from app.core.symbol_index import SymbolIndex

        results = self.retrieve(query, limit)
        enriched: List[Dict[str, Any]] = []
        for hit in results:
            file_path = hit["file"]
            source = self._lexical.symbol_index.get_file(file_path)
            if not source:
                continue
            lines = source.splitlines()
            # Determine snippet around the matched line
            line_no = max(0, hit.get("line", 1) - 1)  # zero-indexed
            start = max(0, line_no - 2)
            end = min(len(lines), line_no + 3)
            snippet = "\n".join(lines[start:end])
            hit_copy = hit.copy()
            hit_copy["source"] = snippet
            enriched.append(hit_copy)
        return enriched


# Convenience factory for use with a FreyaAgent instance
def create_retriever(workspace: str = ".") -> SimpleRetriever:
    """Create a Retriever initialized with the workspace's symbol index."""
    from app.agent.core_agent import FreyaAgent

    # We could instantiate a SymbolIndex directly, but reusing the agent's
    # ensures we have the same index as the agent uses.
    agent = FreyaAgent(workspace)
    return SimpleRetriever(agent.symbol_index)

__all__ = ["SimpleRetriever", "create_retriever"]
