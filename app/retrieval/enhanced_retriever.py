"""Enhanced retriever combining lexical and semantic search."""

from __future__ import annotations

from typing import List, Dict, Any, Optional
import os

try:
    from sentence_transformers import SentenceTransformer
    SEMANTIC_SEARCH_AVAILABLE = True
except ImportError:
    SEMANTIC_SEARCH_AVAILABLE = False

from app.rag import SimpleRetriever
from app.core.symbol_index import SymbolIndex


if SEMANTIC_SEARCH_AVAILABLE:
    # Import semantic search only if available
    try:
        from app.semantic.search import SemanticSearch
    except ImportError:
        SEMANTIC_SEARCH_AVAILABLE = False


class EnhancedRetriever:
    """
    Retriever that combines lexical (keyword) and semantic (embedding-based) search.
    
    Provides better relevance ranking by leveraging both exact matches and 
    semantic similarity.
    """

    def __init__(self, symbol_index: SymbolIndex, enable_semantic: bool = True):
        """
        Initialize the enhanced retriever.
        
        Args:
            symbol_index: The symbol index to search over
            enable_semantic: Whether to use semantic search if available
        """
        self.lexical = SimpleRetriever(symbol_index)
        self.semantic: Optional[SemanticSearch] = None
        
        if enable_semantic and SEMANTIC_SEARCH_AVAILABLE:
            try:
                self.semantic = SemanticSearch(symbol_index)
            except Exception:
                # If semantic search fails to initialize, continue with lexical only
                self.semantic = None

    def retrieve(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Retrieve relevant code snippets using both lexical and semantic search.
        
        Results are combined and deduplicated, with scores combined for ranking.
        
        Args:
            query: The search query
            limit: Maximum number of results to return
            
        Returns:
            List of matching symbols/files ranked by combined relevance
        """
        # Get results from both search methods
        lexical_results = self.lexical.retrieve(query, limit=limit * 2)  # Get extra for merging
        
        semantic_results: List[Dict[str, Any]] = []
        if self.semantic is not None:
            try:
                semantic_results = self.semantic.search(query, limit=limit * 2)
            except Exception:
                # If semantic search fails, continue with lexical only
                pass
        
        # Combine and deduplicate results
        # We'll use a scoring system that combines both signals
        scored_results: Dict[str, Dict[str, Any]] = {}
        
        # Process lexical results
        for i, result in enumerate(lexical_results):
            key = self._make_result_key(result)
            # Score: higher for earlier results (1.0, 0.8, 0.6, ...)
            lexical_score = 1.0 - (i * 0.2)
            if key not in scored_results:
                scored_results[key] = {
                    **result,
                    "lexical_score": lexical_score,
                    "semantic_score": 0.0,
                    "combined_score": lexical_score * 0.6,  # Weight lexical at 60%
                }
            else:
                # Update existing entry
                existing = scored_results[key]
                existing["lexical_score"] = max(existing["lexical_score"], lexical_score)
                existing["combined_score"] = max(
                    existing["combined_score"],
                    lexical_score * 0.6
                )

        # Process semantic results
        for i, result in enumerate(semantic_results):
            key = self._make_result_key(result)
            # Score: higher for earlier results
            semantic_score = 1.0 - (i * 0.2)
            if key not in scored_results:
                scored_results[key] = {
                    **result,
                    "lexical_score": 0.0,
                    "semantic_score": semantic_score,
                    "combined_score": semantic_score * 0.4,  # Weight semantic at 40%
                }
            else:
                # Update existing entry
                existing = scored_results[key]
                existing["semantic_score"] = max(existing["semantic_score"], semantic_score)
                # Combined score: weighted average
                lexical_contrib = existing["lexical_score"] * 0.6
                semantic_contrib = existing["semantic_score"] * 0.4
                existing["combined_score"] = max(
                    existing["combined_score"],
                    lexical_contrib + semantic_contrib
                )

        # Convert to list and sort by combined score
        results_list = list(scored_results.values())
        results_list.sort(key=lambda x: x["combined_score"], reverse=True)
        
        # Return top results, removing the internal scoring fields
        final_results = []
        for result in results_list[:limit]:
            # Return only the standard fields expected by the rest of the system
            final_results.append({
                "file": result["file"],
                "type": result["type"],
                "name": result["name"],
                "line": result["line"],
            })
            
        return final_results

    def _make_result_key(self, result: Dict[str, Any]) -> str:
        """Create a unique key for deduplication."""
        return f"{result['file']}:{result['type']}:{result['name']}:{result['line']}"

    def retrieve_source(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Retrieve results and include source snippets.
        
        Args:
            query: The search query
            limit: Maximum number of results to return
            
        Returns:
            List of results with added 'source' field containing code snippets
        """
        # Get the basic results first
        results = self.retrieve(query, limit=limit)
        
        # Then enrich with source using the lexical retriever's method
        # This ensures we get proper source snippets
        enhanced: List[Dict[str, Any]] = []
        for hit in results:
            # We need to get the source snippet - reuse lexical's method
            # But we only have the basic hit info, so we'll do a simple lookup
            file_path = hit["file"]
            source = self.lexical._lexical.symbol_index.get_file(file_path)
            if not source:
                continue
            lines = source.splitlines()
            line_no = max(0, hit.get("line", 1) - 1)  # zero-indexed
            start = max(0, line_no - 2)
            end = min(len(lines), line_no + 3)
            snippet = "\n".join(lines[start:end])
            hit_copy = hit.copy()
            hit_copy["source"] = snippet
            enhanced.append(hit_copy)
        return enhanced
