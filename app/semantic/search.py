"""Semantic search using sentence transformers for code retrieval."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import numpy as np

try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False


class SemanticSearch:
    """
    Semantic search over code symbols using sentence transformers.
    
    Encodes code snippets and descriptions to enable semantic similarity search.
    """

    def __init__(
        self,
        symbol_index,
        model_name: str = "all-MiniLM-L6-v2",
        cache_dir: Optional[str] = None,
        enable_caching: bool = True,
    ):
        """
        Initialize semantic search.
        
        Args:
            symbol_index: The symbol index to search over
            model_name: Name of the sentence-transformers model to use
            cache_dir: Directory to cache embeddings (defaults to .semantic_cache)
            enable_caching: Whether to cache embeddings to disk
        """
        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            raise ImportError(
                "sentence-transformers is required for semantic search. "
                "Install with: pip install sentence-transformers"
            )
        
        self.symbol_index = symbol_index
        self.model_name = model_name
        self.enable_caching = enable_caching
        
        # Set up cache directory
        if cache_dir is None:
            cache_dir = str(Path.cwd() / ".semantic_cache")
        self.cache_dir = Path(cache_dir)
        if self.enable_caching:
            self.cache_dir.mkdir(exist_ok=True)
        
        # Load model
        self.model = SentenceTransformer(model_name)
        
        # Cache for embeddings
        self._embeddings_cache: Dict[str, np.ndarray] = {}
        self._texts_cache: List[str] = []
        self._metadata_cache: List[Dict[str, Any]] = []
        
        # Initialize by encoding all symbols
        self._build_index()

    def _get_cache_key(self) -> str:
        """Generate a cache key based on model and symbol index content."""
        # Hash the model name and a summary of the symbol index
        hash_input = f"{self.model_name}:"
        # Include symbol count and modification times if possible
        hash_input += f"symbols:{len(self.symbol_index.symbols)}:"
        # For simplicity, we'll just use a fixed cache filename per model
        # In production, you might want to hash the actual symbol content
        return hashlib.md5(hash_input.encode()).hexdigest()

    def _get_cache_paths(self) -> tuple[Path, Path]:
        """Get paths for embeddings and metadata cache files."""
        cache_key = self._get_cache_key()
        embeddings_path = self.cache_dir / f"embeddings_{cache_key}.npy"
        metadata_path = self.cache_dir / f"metadata_{cache_key}.json"
        return embeddings_path, metadata_path

    def _load_from_cache(self) -> bool:
        """Load embeddings and metadata from cache if available."""
        if not self.enable_caching:
            return False
            
        embeddings_path, metadata_path = self._get_cache_paths()
        if not (embeddings_path.exists() and metadata_path.exists()):
            return False
            
        try:
            # Load metadata
            with open(metadata_path, 'r') as f:
                cache_data = json.load(f)
            
            # Verify cache is still valid (simple check)
            if cache_data.get("model_name") != self.model_name:
                return False
                
            self._texts_cache = cache_data["texts"]
            self._metadata_cache = cache_data["metadata"]
            
            # Load embeddings
            self._embeddings_cache["all"] = np.load(embeddings_path)
            
            return True
        except Exception:
            # If cache is corrupted or unreadable, rebuild
            return False

    def _save_to_cache(self):
        """Save embeddings and metadata to cache."""
        if not self.enable_caching:
            return
            
        embeddings_path, metadata_path = self._get_cache_paths()
        
        try:
            # Save metadata
            cache_data = {
                "model_name": self.model_name,
                "texts": self._texts_cache,
                "metadata": self._metadata_cache,
            }
            with open(metadata_path, 'w') as f:
                json.dump(cache_data, f)
            
            # Save embeddings
            if "all" in self._embeddings_cache:
                np.save(embeddings_path, self._embeddings_cache["all"])
        except Exception:
            # Fail silently - caching is optimization only
            pass

    def _extract_symbol_text(self, symbol: Dict[str, Any]) -> str:
        """
        Extract searchable text from a symbol.
        
        Combines name, type, and context for better semantic matching.
        """
        parts = [
            symbol.get("name", ""),
            symbol.get("type", ""),
        ]
        
        # Add file path context
        file_path = symbol.get("file", "")
        if file_path:
            # Get just the filename and parent directory for context
            path_obj = Path(file_path)
            parts.append(path_obj.name)
            parts.append(path_obj.parent.name)
        
        # Join and clean
        text = " ".join(filter(None, parts))
        return text.strip()

    def _get_symbol_source_snippet(self, symbol: Dict[str, Any]) -> str:
        """Get a code snippet for a symbol if available."""
        file_path = symbol.get("file")
        if not file_path:
            return ""
            
        source = self.symbol_index.get_file(file_path)
        if not source:
            return ""
            
        lines = source.splitlines()
        line_num = symbol.get("line", 1)
        # Get context around the line (2 lines before, 2 after)
        start_idx = max(0, line_num - 3)
        end_idx = min(len(lines), line_num + 2)
        
        snippet_lines = []
        for i in range(start_idx, end_idx):
            prefix = "> " if i == line_num - 1 else "  "
            snippet_lines.append(f"{prefix}{i+1:3}: {lines[i]}")
            
        return "\n".join(snippet_lines)

    def _build_index(self):
        """Build or load the search index from symbols."""
        # Try to load from cache first
        if self._load_from_cache():
            return
            
        # Build index from scratch
        texts = []
        metadata = []
        
        # Process all symbols in the index
        for file_path, symbols in self.symbol_index.symbols.items():
            for symbol in symbols:
                # Create searchable text representation
                text = self._extract_symbol_text(symbol)
                if not text:
                    continue
                    
                texts.append(text)
                metadata.append({
                    "file": file_path,
                    "name": symbol.get("name", ""),
                    "type": symbol.get("type", ""),
                    "line": symbol.get("line", 1),
                    "symbol": symbol,  # Keep original for reference
                })
        
        self._texts_cache = texts
        self._metadata_cache = metadata
        
        # Generate embeddings
        if texts:
            print(f"Encoding {len(texts)} symbols for semantic search...")
            embeddings = self.model.encode(
                texts,
                show_progress_bar=True,
                convert_to_numpy=True,
                normalize_embeddings=True  # Normalize for cosine similarity
            )
            self._embeddings_cache["all"] = embeddings
        else:
            self._embeddings_cache["all"] = np.array([]).reshape(0, 384)  # Default dim for MiniLM
        
        # Save to cache
        self._save_to_cache()

    def search(
        self,
        query: str,
        limit: int = 5,
        threshold: float = 0.3
    ) -> List[Dict[str, Any]]:
        """
        Search for semantically similar symbols.
        
        Args:
            query: The search query text
            limit: Maximum number of results to return
            threshold: Minimum similarity score (0-1) to include
            
        Returns:
            List of matching symbols with metadata, sorted by relevance
        """
        if not self._texts_cache:
            return []
            
        # Encode the query
        query_embedding = self.model.encode(
            [query],
            convert_to_numpy=True,
            normalize_embeddings=True
        )[0]
        
        # Compute cosine similarity (dot product of normalized vectors)
        if len(self._embeddings_cache["all"]) == 0:
            similarities = np.array([])
        else:
            similarities = np.dot(self._embeddings_cache["all"], query_embedding)
        
        # Get top results above threshold
        if len(similarities) == 0:
            return []
            
        # Get indices of top k results
        top_indices = np.argsort(similarities)[::-1][:limit * 2]  # Get extra to filter by threshold
        
        results = []
        for idx in top_indices:
            if idx >= len(similarities):
                continue
                
            score = float(similarities[idx])
            if score < threshold:
                continue
                
            meta = self._metadata_cache[idx].copy()
            result = {
                "file": meta["file"],
                "type": meta["type"],
                "name": meta["name"],
                "line": meta["line"],
                "score": score,
                "source": self._get_symbol_source_snippet(meta["symbol"]),
            }
            results.append(result)
            
            if len(results) >= limit:
                break
                
        return results

    def search_by_example(
        self,
        example_code: str,
        limit: int = 5,
        threshold: float = 0.3
    ) -> List[Dict[str, Any]]:
        """
        Find symbols semantically similar to a code example.
        
        Args:
            example_code: Code snippet to match against
            limit: Maximum number of results
            threshold: Minimum similarity score
            
        Returns:
            List of matching symbols
        """
        # For code examples, we might want to preprocess
        # For now, just use the raw code as query
        return self.search(example_code, limit=limit, threshold=threshold)
