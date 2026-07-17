"""Semantic search using sentence transformers for code retrieval.

This module provides semantic search capabilities over code symbols using
sentence transformers. It supports both in-memory caching and persistent
vector database storage via FAISS.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, List, Dict, Any, Optional, Tuple
import numpy as np

try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False

# Try to import VectorDB
try:
    from app.vector_db import VectorDB, FAISS_AVAILABLE as VECTOR_DB_AVAILABLE
except ImportError:
    VECTOR_DB_AVAILABLE = False
    VectorDB = None

if TYPE_CHECKING:
    pass


class SemanticSearch:
    """
    Semantic search over code symbols using sentence transformers.

    Encodes code snippets and descriptions to enable semantic similarity search.
    Supports persistent vector database storage for efficient retrieval across
    sessions.
    """

    def __init__(
        self,
        symbol_index,
        model_name: str = "all-MiniLM-L6-v2",
        cache_dir: Optional[str] = None,
        enable_caching: bool = True,
        use_vector_db: bool = True,
        vector_db_path: Optional[str] = None,
    ):
        """
        Initialize semantic search.

        Args:
            symbol_index: The symbol index to search over
            model_name: Name of the sentence-transformers model to use
            cache_dir: Directory to cache embeddings (defaults to .semantic_cache)
            enable_caching: Whether to cache embeddings to disk (numpy format)
            use_vector_db: Whether to use persistent vector database (FAISS)
            vector_db_path: Path to the FAISS index file (defaults to cache_dir/vector.faiss)
        """
        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            raise ImportError(
                "sentence-transformers is required for semantic search. "
                "Install with: pip install sentence-transformers"
            )

        self.symbol_index = symbol_index
        self.model_name = model_name
        self.enable_caching = enable_caching
        self.use_vector_db = use_vector_db and VECTOR_DB_AVAILABLE

        # Set up cache directory
        if cache_dir is None:
            cache_dir = str(Path.cwd() / ".semantic_cache")
        self.cache_dir = Path(cache_dir)
        if self.enable_caching:
            self.cache_dir.mkdir(exist_ok=True)

        # Set up vector DB path
        if vector_db_path is None and self.use_vector_db:
            vector_db_path = str(self.cache_dir / "symbols.faiss")
        self.vector_db_path = vector_db_path

        # Load model
        self.model = SentenceTransformer(model_name)
        self._embedding_dimension = self.model.get_sentence_embedding_dimension()

        # Initialize vector database
        self._vector_db = None
        if self.use_vector_db and self.vector_db_path:
            try:
                self._vector_db = VectorDB(
                    index_path=self.vector_db_path,
                    embedding_dim=self._embedding_dimension,
                    normalize=True,
                )
            except Exception:
                # Fall back to in-memory if vector DB fails
                self._vector_db = None

        # In-memory cache for embeddings (fallback when vector DB not used)
        # These are kept for backward compatibility
        self._embeddings_cache: Dict[str, np.ndarray] = {}
        self._texts_cache: List[str] = []
        self._metadata_cache: List[Dict[str, Any]] = []

        # Build or load the search index
        self._build_index()

    def _get_cache_key(self) -> str:
        """Generate a cache key based on model and symbol index content."""
        hash_input = f"{self.model_name}:"
        hash_input += f"symbols:{len(self.symbol_index.symbols)}:"
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

            # Verify cache is still valid
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
            prefix = "> " if i == line_num - 1 else " "
            snippet_lines.append(f"{prefix}{i+1:3}: {lines[i]}")

        return "\n".join(snippet_lines)

    def _rebuild_vector_db(self):
        """Rebuild the vector database from the symbol index."""
        if self._vector_db is None:
            return

        # Clear existing vectors
        self._vector_db.clear()

        # Build texts and metadata from symbols
        texts = []
        metadata = []

        for file_path, symbols in self.symbol_index.symbols.items():
            for symbol in symbols:
                text = self._extract_symbol_text(symbol)
                if not text:
                    continue
                texts.append(text)
                metadata.append({
                    "file": file_path,
                    "name": symbol.get("name", ""),
                    "type": symbol.get("type", ""),
                    "line": symbol.get("line", 1),
                    "symbol": symbol,
                })

        if not texts:
            return

        # Generate embeddings
        embeddings = self.model.encode(
            texts,
            show_progress_bar=True,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )

        # Add to vector DB
        self._vector_db.add_batch(embeddings, metadata)

        # Also update in-memory cache for backward compatibility
        self._texts_cache = texts
        self._metadata_cache = metadata
        self._embeddings_cache["all"] = embeddings

    def _should_rebuild_index(self) -> bool:
        """Check if the index needs to be rebuilt."""
        # If using vector DB, check if it's populated
        if self._vector_db is not None:
            if self._vector_db.is_empty():
                return True
            # Check if symbol count changed
            total_symbols = sum(len(s) for s in self.symbol_index.symbols.values())
            if self._vector_db.size() != total_symbols:
                return True
        return False

    def _build_index(self):
        """Build or load the search index from symbols."""
        # Check if we need to rebuild
        if self._vector_db is not None and not self._should_rebuild_index():
            # Vector DB is already populated
            # Try to load metadata cache for backward compatibility
            if self.enable_caching:
                self._load_from_cache()
            return

        # Try to load from old-style cache first (for backward compatibility)
        if self._vector_db is None and self._load_from_cache():
            return

        # Meed to (re)build index from scratch
        texts = []
        metadata = []

        # Process all symbols in the index
        for file_path, symbols in self.symbol_index.symbols.items():
            for symbol in symbols:
                text = self._extract_symbol_text(symbol)
                if not text:
                    continue

                texts.append(text)
                metadata.append({
                    "file": file_path,
                    "name": symbol.get("name", ""),
                    "type": symbol.get("type", ""),
                    "line": symbol.get("line", 1),
                    "symbol": symbol,
                })

        self._texts_cache = texts
        self._metadata_cache = metadata

        # Generate embeddings
        if texts:
            embeddings = self.model.encode(
                texts,
                show_progress_bar=True,
                convert_to_numpy=True,
                normalize_embeddings=True,
            )
            self._embeddings_cache["all"] = embeddings

            # Also populate vector DB if available
            if self._vector_db is not None:
                self._vector_db.clear()
                self._vector_db.add_batch(embeddings, metadata)
        else:
            self._embeddings_cache["all"] = np.array([]).reshape(0, 384)
            if self._vector_db is not None:
                self._vector_db.clear()

        # Save to cache
        if self.enable_caching:
            self._save_to_cache()

    def _sync_vector_db(self):
        """Ensure vector DB is in sync with current symbols."""
        if self._vector_db is not None and self._should_rebuild_index():
            self._rebuild_vector_db()

    def search(
        self,
        query: str,
        limit: int = 5,
        threshold: float = 0.3,
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
        # Sync vector DB if needed
        self._sync_vector_db()

        # Use vector DB if available
        if self._vector_db is not None and not self._vector_db.is_empty():
            query_embedding = self.model.encode(
                [query],
                convert_to_numpy=True,
                normalize_embeddings=True,
            )[0]

            results = self._vector_db.search(query_embedding, limit=limit * 2, threshold=threshold)

            formatted_results = []
            for id, score, metadata in results:
                result = {
                    "file": metadata["file"],
                    "type": metadata["type"],
                    "name": metadata["name"],
                    "line": metadata["line"],
                    "score": score,
                    "source": self._get_symbol_source_snippet(metadata["symbol"]),
                }
                formatted_results.append(result)

            return formatted_results[:limit]

        # Fallback to in-memory search
        if not self._texts_cache:
            return []

        query_embedding = self.model.encode(
            [query],
            convert_to_numpy=True,
            normalize_embeddings=True,
        )[0]

        # Compute cosine similarity (dot product of normalized vectors)
        if len(self._embeddings_cache["all"]) == 0:
            similarities = np.array([])
        else:
            similarities = np.dot(self._embeddings_cache["all"], query_embedding)

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
        threshold: float = 0.3,
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

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the semantic search index."""
        total_symbols = sum(len(s) for s in self.symbol_index.symbols.values())
        vector_db_size = self._vector_db.size() if self._vector_db else 0
        cache_size = len(self._texts_cache) if "all" in self._embeddings_cache else 0

        return {
            "total_symbols": total_symbols,
            "vector_db_enabled": self.use_vector_db,
            "vector_db_size": vector_db_size,
            "cache_enabled": self.enable_caching,
            "cache_size": cache_size,
            "model_name": self.model_name,
            "embedding_dimension": self._embedding_dimension,
        }
