"""Persistent vector database for embedding storage and similarity search.

This module provides a FAISS-based vector database with disk persistence,
enabling efficient similarity search across embeddings that persist between
sessions.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import numpy as np

if TYPE_CHECKING:
    pass

# Try to import FAISS
try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False
    faiss = None


class VectorDBError(Exception):
    """Exception raised when vector database operations fail."""
    pass


class VectorDB:
    """
    Persistent vector database using FAISS for efficient similarity search.

    Features:
    - FAISS index for fast similarity search
    - Disk persistence of both index and metadata
    - Automatic index rebuilding from disk
    - Support for batch insertions and queries
    - Configurable similarity threshold
    """

    # Default embedding dimension for all-MiniLM-L6-v2
    DEFAULT_EMBEDDING_DIM = 384

    def __init__(
        self,
        index_path: str | Path,
        embedding_dim: int = DEFAULT_EMBEDDING_DIM,
        index_type: str = "Flat",
        normalize: bool = True,
        create_if_missing: bool = True,
    ):
        """
        Initialize the vector database.

        Args:
            index_path: Path to the FAISS index file (without extension)
            embedding_dim: Dimension of the embeddings
            index_type: Type of FAISS index ('Flat' or 'IVF')
            normalize: Whether to normalize vectors for cosine similarity
            create_if_missing: Create index if it doesn't exist

        Raises:
            VectorDBError: If FAISS is not available
        """
        if not FAISS_AVAILABLE:
            raise VectorDBError(
                "FAISS is not available. Install with: pip install faiss-cpu"
            )

        self.index_path = Path(index_path)
        self.embedding_dim = embedding_dim
        self.index_type = index_type
        self.normalize = normalize
        self._index = None
        self._metadata: List[Dict[str, Any]] = []
        self._metadata_path = self.index_path.with_suffix(".metadata.json")

        # Create parent directory if needed
        if create_if_missing:
            self.index_path.parent.mkdir(parents=True, exist_ok=True)

        # Load or create index
        self._load_or_create_index()

    def _create_index(self) -> None:
        """Create a new FAISS index."""
        if self.index_type == "IVF":
            # Use inverted file for larger datasets
            nlist = 100
            quantizer = faiss.IndexFlatIP(self.embedding_dim)
            self._index = faiss.IndexIVFFlat(
                quantizer, self.embedding_dim, nlist, faiss.METRIC_INNER_PRODUCT
            )
        else:
            # Default: Flat index (exact search)
            if self.normalize:
                # For cosine similarity with normalized vectors, use Inner Product
                self._index = faiss.IndexFlatIP(self.embedding_dim)
            else:
                self._index = faiss.IndexFlatL2(self.embedding_dim)

        # Mark as not trained (for IVF)
        if self.index_type == "IVF":
            self._index.train(np.array([]).reshape(0, self.embedding_dim))

    def _load_or_create_index(self) -> None:
        """Load index from disk or create a new one."""
        index_file = str(self.index_path)

        if self.index_path.exists():
            try:
                # Load FAISS index
                self._index = faiss.read_index(index_file)

                # Load metadata
                if self._metadata_path.exists():
                    with open(self._metadata_path, 'r', encoding='utf-8') as f:
                        self._metadata = json.load(f)

                # Verify embedding dimension matches
                if hasattr(self._index, 'd') and self._index.d != self.embedding_dim:
                    raise VectorDBError(
                        f"Index dimension {self._index.d} doesn't match "
                        f"expected dimension {self.embedding_dim}"
                    )

            except Exception as e:
                # If loading fails, create a new index
                # This can happen if the index was created with different parameters
                self._metadata = []
                self._create_index()
        else:
            self._metadata = []
            self._create_index()

    def _get_vector_shape(self, vector: Any) -> np.ndarray:
        """Convert input to numpy array and validate shape."""
        if isinstance(vector, list):
            vector = np.array(vector, dtype=np.float32)
        elif isinstance(vector, np.ndarray):
            vector = vector.astype(np.float32)
        else:
            raise TypeError(f"Unsupported vector type: {type(vector)}")

        if vector.ndim == 1:
            vector = vector.reshape(1, -1)

        if vector.shape[1] != self.embedding_dim:
            raise ValueError(
                f"Vector dimension {vector.shape[1]} doesn't match "
                f"expected dimension {self.embedding_dim}"
            )

        return vector

    def size(self) -> int:
        """Return the number of vectors in the database."""
        if self._index is not None:
            return int(self._index.ntotal)
        return 0

    def is_empty(self) -> bool:
        """Check if the database is empty."""
        return self.size() == 0

    def add(
        self,
        vector: np.ndarray | list,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Add a single vector to the database.

        Args:
            vector: The embedding vector to add
            metadata: Optional metadata dictionary to associate with the vector

        Returns:
            The index (ID) of the added vector

        Raises:
            VectorDBError: If the vector cannot be added
        """
        vector = self._get_vector_shape(vector)

        if self._index is None:
            raise VectorDBError("Index not initialized")

        # Normalize if required
        if self.normalize:
            vector = vector / np.linalg.norm(vector, axis=1, keepdims=True)

        # Add to index
        self._index.add(vector)

        # Store metadata
        metadata = metadata or {}
        self._metadata.append(metadata)

        # Save to disk
        self._save_index()

        # Return the ID (last added)
        return len(self._metadata) - 1

    def add_batch(
        self,
        vectors: List[np.ndarray] | np.ndarray,
        metadata: Optional[List[Dict[str, Any]]] = None,
    ) -> List[int]:
        """
        Add multiple vectors to the database.

        Args:
            vectors: List of embedding vectors to add
            metadata: Optional list of metadata dictionaries

        Returns:
            List of IDs for the added vectors

        Raises:
            VectorDBError: If vectors cannot be added
        """
        if isinstance(vectors, list):
            vectors = np.array(vectors, dtype=np.float32)
        elif isinstance(vectors, np.ndarray):
            vectors = vectors.astype(np.float32)
        else:
            raise TypeError(f"Unsupported vectors type: {type(vectors)}")

        if vectors.shape[1] != self.embedding_dim:
            raise ValueError(
                f"Vector dimension {vectors.shape[1]} doesn't match "
                f"expected dimension {self.embedding_dim}"
            )

        if self._index is None:
            raise VectorDBError("Index not initialized")

        # Normalize if required
        if self.normalize:
            vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)

        # Add to index
        self._index.add(vectors)

        # Store metadata
        if metadata:
            self._metadata.extend(metadata)
        else:
            self._metadata.extend([{} for _ in range(len(vectors))])

        # Save to disk
        self._save_index()

        # Return IDs
        start_id = len(self._metadata) - len(vectors)
        return list(range(start_id, len(self._metadata)))

    def search(
        self,
        query_vector: np.ndarray | list,
        limit: int = 5,
        threshold: Optional[float] = None,
    ) -> List[Tuple[int, float, Dict[str, Any]]]:
        """
        Search for similar vectors.

        Args:
            query_vector: The query embedding vector
            limit: Maximum number of results to return
            threshold: Optional minimum similarity score (for filtered results)

        Returns:
            List of tuples (id, score, metadata) sorted by similarity (descending)

        Raises:
            VectorDBError: If search cannot be performed
        """
        if self._index is None:
            raise VectorDBError("Index not initialized")

        if self.is_empty():
            return []

        query_vector = self._get_vector_shape(query_vector)

        # Normalize if required
        if self.normalize:
            query_vector = query_vector / np.linalg.norm(query_vector, axis=1, keepdims=True)

        # Search
        limit = min(limit, self.size())
        scores, indices = self._index.search(query_vector, limit)

        # Process results
        results = []
        for i, (idx, score) in enumerate(zip(indices[0], scores[0])):
            if idx < 0 or idx >= len(self._metadata):
                continue

            # For IVF index, scores might need adjustment
            if self.index_type == "IVF" and self.normalize:
                # For normalized vectors with Inner Product, score is already cosine similarity
                similarity = float(score)
            elif self.normalize:
                # For normalized vectors with Inner Product, score is cosine similarity
                similarity = float(score)
            else:
                # For L2 distance, convert to similarity (0-1 range)
                # Use a simple inversion heuristic
                similarity = 1.0 / (1.0 + float(score))

            if threshold is not None and similarity < threshold:
                continue

            results.append((int(idx), similarity, self._metadata[idx].copy()))

        # Sort by similarity descending (search results are already sorted)
        return results

    def get_metadata(self, id: int) -> Optional[Dict[str, Any]]:
        """Get metadata for a specific vector by ID."""
        if 0 <= id < len(self._metadata):
            return self._metadata[id].copy()
        return None

    def update_metadata(self, id: int, metadata: Dict[str, Any]) -> bool:
        """
        Update metadata for a specific vector.

        Args:
            id: The vector ID to update
            metadata: New metadata dictionary

        Returns:
            True if update was successful
        """
        if 0 <= id < len(self._metadata):
            self._metadata[id] = metadata.copy()
            self._save_metadata()
            return True
        return False

    def remove(self, id: int) -> bool:
        """
        Remove a vector from the database.

        Note: FAISS doesn't support efficient removal, so this reconstructs
        the index without the removed vector.

        Args:
            id: The vector ID to remove

        Returns:
            True if removal was successful
        """
        if id < 0 or id >= len(self._metadata):
            return False

        # Get all vectors except the one to remove
        if self._index is not None and self.size() > 0:
            # Reconstruct index without the removed vector
            # This is not efficient but FAISS doesn't support removal well
            # For production use, consider using a different approach
            remaining_ids = [i for i in range(len(self._metadata)) if i != id]
            if not remaining_ids:
                # Clear the index
                self._create_index()
                self._metadata = []
                self._save_index()
                return True

            # Rebuild index with remaining vectors
            vectors = []
            for i in remaining_ids:
                if i < self.size():
                    vec = self._index.reconstruct(i)
                    if vec is not None:
                        vectors.append(vec)

            if vectors:
                vectors = np.array(vectors, dtype=np.float32)
                if self.normalize:
                    vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
                self._create_index()
                self._index.add(vectors)

            # Remove metadata
            new_metadata = []
            for i in remaining_ids:
                if i < len(self._metadata):
                    new_metadata.append(self._metadata[i])
            self._metadata = new_metadata

            self._save_index()
            return True

        return False

    def clear(self) -> None:
        """Clear all vectors and metadata from the database."""
        self._metadata = []
        self._create_index()
        self._save_index()

    def _save_index(self) -> None:
        """Save the FAISS index and metadata to disk."""
        if self._index is not None:
            try:
                # Save FAISS index
                faiss.write_index(self._index, str(self.index_path))

                # Save metadata
                with open(self._metadata_path, 'w', encoding='utf-8') as f:
                    json.dump(self._metadata, f, indent=2, ensure_ascii=False)
            except Exception as e:
                # Log error but don't fail
                pass

    def _save_metadata(self) -> None:
        """Save only metadata to disk."""
        try:
            with open(self._metadata_path, 'w', encoding='utf-8') as f:
                json.dump(self._metadata, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def __len__(self) -> int:
        """Return the number of vectors in the database."""
        return self.size()

    def __repr__(self) -> str:
        return (
            f"VectorDB(index_path={self.index_path!r}, "
            f"size={self.size()}, "
            f"embedding_dim={self.embedding_dim}, "
            f"index_type={self.index_type!r})"
        )


def get_vector_db(
    name: str = "default",
    workspace: Optional[str | Path] = None,
    embedding_dim: int = VectorDB.DEFAULT_EMBEDDING_DIM,
) -> Optional[VectorDB]:
    """
    Get or create a named vector database in the workspace.

    Args:
        name: Name of the vector database
        workspace: Workspace directory (defaults to current directory)
        embedding_dim: Embedding dimension

    Returns:
        VectorDB instance or None if FAISS is not available
    """
    if not FAISS_AVAILABLE:
        return None

    if workspace is None:
        workspace = Path.cwd()
    else:
        workspace = Path(workspace)

    index_path = workspace / "data" / "vector_db" / f"{name}.faiss"

    try:
        return VectorDB(
            index_path=index_path,
            embedding_dim=embedding_dim,
        )
    except Exception:
        return None

