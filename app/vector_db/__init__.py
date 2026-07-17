"""Persistent vector database for embedding storage and similarity search.

This module provides a FAISS-based vector database with disk persistence,
enabling efficient similarity search across embeddings that persist between
sessions.

Features:
- FAISS index for fast similarity search
- Disk persistence of both index and metadata
- Automatic index rebuilding from disk
- Support for batch insertions and queries
- Configurable similarity threshold
- Adaptive index selection (Flat for small, IVF for large datasets)
- Efficient deletion using tombstone tracking with lazy compaction
- Automatic FAISS installation if missing
- Built-in benchmarking capabilities

Index Selection Policy:
- Small datasets (<=10,000 vectors): IndexFlatIP (exact search)
- Medium datasets (<=100,000 vectors): IndexIVFFlat with nlist=100
- Larger datasets (<=500,000 vectors): IndexIVFFlat with nlist=400
- Very large datasets (>500,000 vectors): IndexIVFFlat with nlist=800

These thresholds are configurable via IndexConfig.

Deletion Strategy:
Uses tombstone tracking with lazy compaction. Deleted vectors are marked
as deleted and filtered from search results. Periodic compaction removes
deleted vectors and rebuilds the index. Compaction triggers at configurable
thresholds (default: 10% deletion ratio, 60s minimum interval).

The implementation maintains:
- A FAISS index for vector storage and similarity search
- A metadata list where each entry corresponds to a physical position in FAISS
- A set of tombstoned (deleted) physical positions
- A next_id counter for assigning new logical IDs

Benchmarking:
- benchmark_build(): Measures index build time
- benchmark_search(): Measures search latency
- benchmark_delete(): Measures deletion performance
- run_benchmarks(): Runs full benchmark suite with statistics
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

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


@dataclass
class IndexConfig:
    """Configuration for vector database index selection and behavior.

    Attributes:
        flat_threshold: Maximum vectors for Flat index (default: 10,000)
        medium_threshold: Maximum vectors for medium IVF (default: 100,000)
        small_nlist: nlist for small IVF indexes (default: 100)
        medium_nlist: nlist for medium IVF indexes (default: 400)
        large_nlist: nlist for large IVF indexes (default: 800)
        nprobe: Number of probe clusters for IVF search (default: 10)
        auto_install: Whether to auto-install FAISS if missing (default: True)
        lazy_deletion: Use lazy deletion instead of immediate rebuild (default: True)
        compaction_threshold: Delete threshold before compaction (default: 0.1 = 10%)
        compaction_interval: Minimum seconds between compactions (default: 60)
    """
    # Thresholds for adaptive index selection
    flat_threshold: int = 10_000
    medium_threshold: int = 100_000

    # IVF configuration
    small_nlist: int = 100
    medium_nlist: int = 400
    large_nlist: int = 800
    nprobe: int = 10

    # Deletion strategy
    lazy_deletion: bool = True
    compaction_threshold: float = 0.1  # 10% deleted vectors triggers compaction
    compaction_interval: float = 60.0  # Minimum seconds between compactions

    # Auto-install
    auto_install: bool = True

    # Index metadata storage
    store_index_metadata: bool = True


# Default configuration
DEFAULT_CONFIG = IndexConfig()


def _attempt_install_faiss() -> bool:
    """Attempt to install FAISS automatically.

    Returns:
        True if installation succeeded, False otherwise
    """
    try:
        # Check if pip is available
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "faiss-cpu", "-q"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode == 0:
            # Re-import faiss
            import importlib
            import faiss as faiss_module
            global faiss, FAISS_AVAILABLE
            faiss = faiss_module
            FAISS_AVAILABLE = True
            return True
        else:
            warnings.warn(
                f"Failed to auto-install faiss-cpu: {result.stderr}"
            )
            return False
    except subprocess.TimeoutExpired:
        warnings.warn("Timeout while attempting to install faiss-cpu")
        return False
    except Exception as e:
        warnings.warn(f"Error attempting to install faiss-cpu: {e}")
        return False


def ensure_faiss_available(auto_install: bool = True) -> bool:
    """Ensure FAISS is available, optionally auto-installing if missing.

    Args:
        auto_install: Whether to attempt auto-installation if FAISS is missing

    Returns:
        True if FAISS is available, False otherwise
    """
    global FAISS_AVAILABLE, faiss

    if FAISS_AVAILABLE:
        return True

    if auto_install:
        return _attempt_install_faiss()

    return False


@dataclass
class BenchmarkResult:
    """Result of a benchmarking operation.

    Attributes:
        operation: Name of the operation benchmarked
        duration_seconds: Time taken in seconds
        details: Additional details about the benchmark
    """
    operation: str
    duration_seconds: float
    details: Dict[str, Any] = field(default_factory=dict)


class VectorDB:
    """
    Persistent vector database using FAISS for efficient similarity search.

    Features:
    - FAISS index for fast similarity search
    - Disk persistence of both index and metadata
    - Automatic index rebuilding from disk
    - Support for batch insertions and queries
    - Configurable similarity threshold
    - Adaptive index selection based on dataset size
    - Efficient deletion using tombstone tracking with lazy compaction
    - Automatic FAISS installation if missing

    Note on IDs:
    This implementation uses sequential integer IDs (0, 1, 2, ...) that correspond
    to positions in the FAISS index. When vectors are deleted, they are marked as
    tombstones and filtered from search results. Compaction rebuilds the index
    without tombstoned vectors.

    Example:
        >>> db = VectorDB("data/vectors.faiss", embedding_dim=384)
        >>> db.add(vector, {"type": "embedding"})
        >>> results = db.search(query_vector, limit=5)
    """

    # Default embedding dimension for all-MiniLM-L6-v2
    DEFAULT_EMBEDDING_DIM = 384

    def __init__(
        self,
        index_path: str | Path,
        embedding_dim: int = DEFAULT_EMBEDDING_DIM,
        normalize: bool = True,
        create_if_missing: bool = True,
        config: Optional[IndexConfig] = None,
        auto_install: bool = True,
    ):
        """
        Initialize the vector database.

        Args:
            index_path: Path to the FAISS index file (without extension)
            embedding_dim: Dimension of the embeddings
            normalize: Whether to normalize vectors for cosine similarity
            create_if_missing: Create index if it doesn't exist
            config: Index configuration (defaults to DEFAULT_CONFIG)
            auto_install: Whether to auto-install FAISS if missing

        Raises:
            VectorDBError: If FAISS cannot be made available
        """
        self.index_path = Path(index_path)
        self.embedding_dim = embedding_dim
        self.normalize = normalize
        self.config = config or IndexConfig(auto_install=auto_install)

        # Initialize FAISS if needed
        if not FAISS_AVAILABLE:
            if self.config.auto_install or auto_install:
                if not _attempt_install_faiss():
                    raise VectorDBError(
                        "FAISS is not available and auto-install failed. "
                        "Install manually with: pip install faiss-cpu"
                    )
            else:
                raise VectorDBError(
                    "FAISS is not available. Install with: pip install faiss-cpu"
                )

        self._index = None

        # Metadata: list where index corresponds to FAISS position
        self._metadata: List[Dict[str, Any]] = []
        self._metadata_path = self.index_path.with_suffix(".metadata.json")

        # Tombstones: set of physical positions that have been deleted
        self._tombstones: Set[int] = set()
        self._tombstones_path = self.index_path.with_suffix(".tombstones.json")

        # Index metadata for persistence
        self._index_config_path = self.index_path.with_suffix(".config.json")
        self._index_config: Dict[str, Any] = {}

        # Timing for compaction
        self._last_compaction_time: float = time.time()

        # Create parent directory if needed
        if create_if_missing:
            self.index_path.parent.mkdir(parents=True, exist_ok=True)

        # Load or create index
        self._load_or_create_index()

    def _get_index_type_for_size(self, size: int) -> str:
        """Determine the appropriate index type for a given dataset size.

        Args:
            size: Number of active vectors in the dataset

        Returns:
            Index type string: 'Flat', 'IVF_Small', 'IVF_Medium', 'IVF_Large'
        """
        if size <= self.config.flat_threshold:
            return "Flat"
        elif size <= self.config.medium_threshold:
            return "IVF_Small"
        else:
            return "IVF_Large"

    def _get_nlist_for_index(self, index_type: str) -> int:
        """Get the nlist value for a given IVF index type.

        Args:
            index_type: Index type string

        Returns:
            nlist value for IVF indexes
        """
        if index_type == "IVF_Small":
            return self.config.small_nlist
        elif index_type == "IVF_Medium":
            return self.config.medium_nlist
        else:
            return self.config.large_nlist

    def _create_flat_index(self) -> None:
        """Create a Flat index for exact search."""
        if self.normalize:
            self._index = faiss.IndexFlatIP(self.embedding_dim)
        else:
            self._index = faiss.IndexFlatL2(self.embedding_dim)
        self._index_config["type"] = "Flat"

    def _create_ivf_index(self, nlist: int) -> None:
        """Create an IVF index with specified nlist.

        Args:
            nlist: Number of clusters for IVF
        """
        if self.normalize:
            quantizer = faiss.IndexFlatIP(self.embedding_dim)
            self._index = faiss.IndexIVFFlat(
                quantizer, self.embedding_dim, nlist, faiss.METRIC_INNER_PRODUCT
            )
        else:
            quantizer = faiss.IndexFlatL2(self.embedding_dim)
            self._index = faiss.IndexIVFFlat(
                quantizer, self.embedding_dim, nlist, faiss.METRIC_L2
            )

        self._index_config["type"] = "IVF"
        self._index_config["nlist"] = nlist
        self._index_config["nprobe"] = self.config.nprobe
        self._index_config["trained"] = False

    def _train_index_if_needed(self) -> None:
        """Train the IVF index if it needs training and we have enough vectors."""
        if self._index is None:
            return

        if self._index_config.get("type") != "IVF":
            return

        if self._index_config.get("trained", False):
            return

        nlist = self._index_config.get("nlist", 100)
        active_size = self.size()

        # Need at least nlist vectors to train properly
        if active_size >= nlist:
            # Use actual vectors for training
            active_phys_ids = [i for i in range(len(self._metadata)) if i not in self._tombstones]
            if len(active_phys_ids) >= nlist:
                vectors = self._index.reconstruct_batch(active_phys_ids[:nlist])
            else:
                # Generate dummy vectors
                vectors = np.random.randn(nlist, self.embedding_dim).astype(np.float32)
                if self.normalize:
                    vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)

            self._index.train(vectors)
            self._index_config["trained"] = True
            self._save_index_config()

    def _create_index(self, index_type: Optional[str] = None) -> None:
        """Create a new FAISS index of the specified type.

        Args:
            index_type: Type of index to create (None for auto-selection based on current size)
        """
        active_size = self.size()
        if index_type is None:
            index_type = self._get_index_type_for_size(active_size)

        if index_type == "Flat":
            self._create_flat_index()
        else:
            nlist = self._get_nlist_for_index(index_type)
            self._create_ivf_index(nlist)

    def _should_reindex(self) -> bool:
        """Check if the index should be rebuilt due to size changes.

        Returns:
            True if the index type should change based on active vector count
        """
        current_type = self._index_config.get("type", "Flat")
        active_size = self.size()

        if current_type == "Flat":
            return active_size > self.config.flat_threshold
        elif current_type == "IVF":
            nlist = self._index_config.get("nlist", 100)
            if nlist == self.config.small_nlist:
                return active_size > self.config.medium_threshold
            # For medium/large, don't downgrade
            return False
        return False

    def _rebuild_index(self) -> None:
        """Rebuild the index from active vectors."""
        # Collect active vectors (non-tombstoned)
        active_phys_ids = [i for i in range(len(self._metadata)) if i not in self._tombstones]

        if not active_phys_ids:
            # No active vectors, just reset
            self._metadata = []
            self._tombstones = set()
            self._create_index()
            return

        # Get active metadata
        active_metadata = [self._metadata[i] for i in active_phys_ids]

        # Get active vectors from FAISS
        vectors = self._index.reconstruct_batch(active_phys_ids)

        # Determine new index type and create
        new_type = self._get_index_type_for_size(len(active_phys_ids))
        self._create_index(new_type)

        # Normalize if needed
        if self.normalize:
            vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)

        # Add to new index
        self._index.add(vectors)

        # Update state
        self._metadata = active_metadata
        self._tombstones = set()

        # Update index config
        self._index_config["type"] = new_type
        if new_type != "Flat":
            self._index_config["nlist"] = self._get_nlist_for_index(new_type)
            self._index_config["trained"] = False

        # Train if needed (will be done on next add if not enough vectors)
        self._train_index_if_needed()

        # Save
        self._save_index()

    def _load_index_config(self) -> None:
        """Load index configuration from disk."""
        if self._index_config_path.exists():
            try:
                with open(self._index_config_path, 'r', encoding='utf-8') as f:
                    self._index_config = json.load(f)
            except (OSError, json.JSONDecodeError):
                self._index_config = {}

    def _save_index_config(self) -> None:
        """Save index configuration to disk."""
        if not self.config.store_index_metadata:
            return
        try:
            with open(self._index_config_path, 'w', encoding='utf-8') as f:
                json.dump(self._index_config, f, indent=2)
        except Exception:
            pass

    def _load_tombstones(self) -> None:
        """Load tombstones from disk."""
        if self._tombstones_path.exists():
            try:
                with open(self._tombstones_path, 'r', encoding='utf-8') as f:
                    self._tombstones = set(json.load(f))
            except (OSError, json.JSONDecodeError):
                self._tombstones = set()

    def _save_tombstones(self) -> None:
        """Save tombstones to disk."""
        try:
            with open(self._tombstones_path, 'w', encoding='utf-8') as f:
                json.dump(list(self._tombstones), f)
        except Exception:
            pass

    def _load_or_create_index(self) -> None:
        """Load index from disk or create a new one."""
        index_file = str(self.index_path)

        # Load index config first
        self._load_index_config()

        if self.index_path.exists():
            try:
                # Load FAISS index
                self._index = faiss.read_index(index_file)

                # Load metadata
                if self._metadata_path.exists():
                    with open(self._metadata_path, 'r', encoding='utf-8') as f:
                        self._metadata = json.load(f)

                # Load tombstones
                self._load_tombstones()

                # Verify embedding dimension matches
                if hasattr(self._index, 'd') and self._index.d != self.embedding_dim:
                    raise VectorDBError(
                        f"Index dimension {self._index.d} doesn't match "
                        f"expected dimension {self.embedding_dim}"
                    )

                # Re-apply normalize to index config
                if self.normalize:
                    self._index_config["normalize"] = True

                # Check if we need to rebuild due to size changes
                if self._should_reindex():
                    self._rebuild_index()
                else:
                    # Ensure IVF is trained
                    self._train_index_if_needed()

            except Exception as e:
                # If loading fails, create a new index
                self._metadata = []
                self._tombstones = set()
                self._create_index()
        else:
            self._metadata = []
            self._tombstones = set()
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

    def _should_compact(self) -> bool:
        """Check if compaction should be performed."""
        if not self.config.lazy_deletion:
            return False

        total_positions = len(self._metadata)
        if total_positions == 0:
            return False

        deleted_ratio = len(self._tombstones) / total_positions
        time_since_compaction = time.time() - self._last_compaction_time

        return (
            deleted_ratio >= self.config.compaction_threshold
            and time_since_compaction >= self.config.compaction_interval
        )

    def _compact(self) -> None:
        """Perform compaction to remove deleted vectors."""
        if not self._should_compact():
            return

        self._rebuild_index()
        self._last_compaction_time = time.time()

    def physical_size(self) -> int:
        """Return the physical number of vectors in the FAISS index."""
        if self._index is not None:
            return int(self._index.ntotal)
        return 0

    def size(self) -> int:
        """Return the logical number of active vectors (excluding deleted)."""
        return len(self._metadata) - len(self._tombstones)

    def is_empty(self) -> bool:
        """Check if the database is empty."""
        return self.size() == 0

    def get_deleted_count(self) -> int:
        """Return the number of deleted but not yet compacted vectors."""
        return len(self._tombstones)

    def add(
        self,
        vector: np.ndarray | list,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Add a single vector to the database.

        Args:
            vector: The embedding vector to add. Can be a numpy array or list.
            metadata: Optional metadata dictionary to associate with the vector.
                     If None, an empty dict is used.

        Returns:
            The physical position (ID) where the vector was added in the FAISS index.
            This ID can be used with get_metadata(), update_metadata(), and remove().

        Raises:
            VectorDBError: If the vector cannot be added
        """
        vector = self._get_vector_shape(vector)

        if self._index is None:
            raise VectorDBError("Index not initialized")

        # Normalize if required
        if self.normalize:
            vector = vector / np.linalg.norm(vector, axis=1, keepdims=True)

        # Add to FAISS index
        self._index.add(vector)

        # Store metadata
        metadata = metadata or {}
        self._metadata.append(metadata)

        # The new physical position is len(metadata) - 1
        phys_id = len(self._metadata) - 1

        # Train IVF if needed
        self._train_index_if_needed()

        # Save to disk
        self._save_index()

        # Check if we need to rebuild due to size growth
        if self._should_reindex():
            self._rebuild_index()

        return phys_id

    def add_batch(
        self,
        vectors: List[np.ndarray] | np.ndarray,
        metadata: Optional[List[Dict[str, Any]]] = None,
    ) -> List[int]:
        """
        Add multiple vectors to the database.

        Args:
            vectors: List of embedding vectors to add. Can be a numpy array or list of arrays.
            metadata: Optional list of metadata dictionaries, one for each vector.
                     If None or shorter than vectors, empty dicts are used for missing entries.

        Returns:
            List of physical positions (IDs) where each vector was added.

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

        # Add to FAISS index
        self._index.add(vectors)

        # Store metadata
        num_vectors = len(vectors)
        if metadata:
            # Extend with empty dicts if metadata is shorter
            metadata = list(metadata)
            while len(metadata) < num_vectors:
                metadata.append({})
            self._metadata.extend(metadata)
        else:
            self._metadata.extend([{} for _ in range(num_vectors)])

        # Train IVF if needed
        self._train_index_if_needed()

        # Save to disk
        self._save_index()

        # Check if we need to rebuild due to size growth
        if self._should_reindex():
            self._rebuild_index()

        # Return physical IDs
        start_id = len(self._metadata) - num_vectors
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
            query_vector: The query embedding vector. Can be a numpy array or list.
            limit: Maximum number of results to return.
            threshold: Optional minimum similarity score (0-1) to include.
                      Results below this threshold are filtered out.

        Returns:
            List of tuples (id, score, metadata) sorted by similarity (descending).
            The 'id' is the physical position in the FAISS index.
            The 'score' is the similarity score (0-1 for normalized vectors).
            The 'metadata' is the metadata dictionary associated with the vector.

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

        # Set nprobe for IVF
        if self._index_config.get("type") == "IVF" and hasattr(self._index, "nprobe"):
            self._index.nprobe = self._index_config.get("nprobe", self.config.nprobe)

        # Search FAISS (returns physical positions)
        limit = min(limit, self.physical_size())
        scores, phys_indices = self._index.search(query_vector, limit)

        # Process results - filter out tombstoned physical positions
        results = []
        for i in range(len(phys_indices[0])):
            phys_id = int(phys_indices[0][i])
            score = float(scores[0][i])

            # Skip if physical ID is out of range or tombstoned
            if phys_id < 0 or phys_id >= len(self._metadata) or phys_id in self._tombstones:
                continue

            # Calculate similarity
            if self.normalize:
                similarity = score
            else:
                # For L2 distance, convert to similarity (0-1 range)
                similarity = 1.0 / (1.0 + score)

            if threshold is not None and similarity < threshold:
                continue

            result_metadata = self._metadata[phys_id].copy()
            results.append((phys_id, similarity, result_metadata))

        # Sort by similarity descending (FAISS returns results sorted by distance)
        # But we need to re-sort after filtering out tombstones
        results.sort(key=lambda x: x[1], reverse=True)

        return results[:limit]

    def get_metadata(self, id: int) -> Optional[Dict[str, Any]]:
        """Get metadata for a specific vector by physical ID.

        Args:
            id: The physical ID (position) of the vector in the FAISS index.

        Returns:
            Metadata dictionary or None if the ID is invalid or the vector was deleted.
        """
        if id < 0 or id >= len(self._metadata):
            return None
        if id in self._tombstones:
            return None
        return self._metadata[id].copy()

    def update_metadata(self, id: int, metadata: Dict[str, Any]) -> bool:
        """
        Update metadata for a specific vector.

        Args:
            id: The physical ID to update
            metadata: New metadata dictionary

        Returns:
            True if update was successful, False if ID is invalid or deleted
        """
        if id < 0 or id >= len(self._metadata):
            return False
        if id in self._tombstones:
            return False

        self._metadata[id] = metadata.copy()
        self._save_metadata()
        return True

    def remove(self, id: int) -> bool:
        """
        Remove a vector from the database.

        Uses tombstone marking with lazy compaction for efficiency.
        The vector is marked as deleted and will be filtered from search results.
        Actual removal happens during compaction.

        Args:
            id: The physical ID to remove

        Returns:
            True if removal was successful, False if ID is invalid or already deleted
        """
        if id < 0 or id >= len(self._metadata):
            return False

        if id in self._tombstones:
            return False  # Already deleted

        self._tombstones.add(id)

        # Save tombstones
        self._save_tombstones()

        # Trigger compaction if threshold reached
        if self._should_compact():
            self._compact()

        return True

    def force_compact(self) -> None:
        """Force immediate compaction to remove all deleted vectors."""
        if len(self._tombstones) == 0:
            return
        self._last_compaction_time = 0  # Force compaction
        self._compact()

    def clear(self) -> None:
        """Clear all vectors and metadata from the database."""
        self._metadata = []
        self._tombstones = set()
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

                # Save tombstones
                self._save_tombstones()

                # Save index config
                self._save_index_config()
            except Exception:
                # Log error but don't fail
                pass

    def _save_metadata(self) -> None:
        """Save only metadata to disk."""
        try:
            with open(self._metadata_path, 'w', encoding='utf-8') as f:
                json.dump(self._metadata, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def get_config(self) -> IndexConfig:
        """Get the current configuration."""
        return self.config

    def get_index_info(self) -> Dict[str, Any]:
        """Get information about the current index.

        Returns:
            Dictionary with index type, size, dimension, and other info
        """
        info = {
            "type": self._index_config.get("type", "Unknown"),
            "size": self.size(),
            "physical_size": self.physical_size(),
            "deleted_count": self.get_deleted_count(),
            "embedding_dim": self.embedding_dim,
            "normalize": self.normalize,
            "index_path": str(self.index_path),
        }

        if self._index_config.get("type") == "IVF":
            info["nlist"] = self._index_config.get("nlist", "Unknown")
            info["nprobe"] = self._index_config.get("nprobe", self.config.nprobe)
            info["is_trained"] = self._index_config.get("trained", False)

        if self._index is not None and hasattr(self._index, "is_trained"):
            info["faiss_is_trained"] = self._index.is_trained

        return info

    def benchmark_build(self, num_vectors: int = 10000) -> BenchmarkResult:
        """Benchmark index build performance.

        Args:
            num_vectors: Number of vectors to generate for benchmarking

        Returns:
            BenchmarkResult with timing information
        """
        import time

        vectors = np.random.randn(num_vectors, self.embedding_dim).astype(np.float32)
        if self.normalize:
            vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)

        # Save old state
        old_metadata = self._metadata.copy()
        old_tombstones = self._tombstones.copy()

        start = time.time()
        self.clear()
        self.add_batch(vectors)
        end = time.time()

        # Restore old state
        self.clear()
        self._metadata = old_metadata
        self._tombstones = old_tombstones

        return BenchmarkResult(
            operation="build",
            duration_seconds=end - start,
            details={
                "num_vectors": num_vectors,
                "index_type": self._index_config.get("type", "Unknown"),
            }
        )

    def benchmark_search(self, num_queries: int = 100) -> BenchmarkResult:
        """Benchmark search performance.

        Args:
            num_queries: Number of search queries to perform

        Returns:
            BenchmarkResult with timing information
        """
        import time

        if self.is_empty():
            raise VectorDBError("Cannot benchmark search on empty database")

        query_vectors = np.random.randn(num_queries, self.embedding_dim).astype(np.float32)
        if self.normalize:
            query_vectors = query_vectors / np.linalg.norm(query_vectors, axis=1, keepdims=True)

        start = time.time()
        for i in range(num_queries):
            self.search(query_vectors[i], limit=10)
        end = time.time()

        return BenchmarkResult(
            operation="search",
            duration_seconds=end - start,
            details={
                "num_queries": num_queries,
                "database_size": self.size(),
                "avg_latency_ms": (end - start) / num_queries * 1000,
            }
        )

    def benchmark_delete(self, num_deletes: int = 100) -> BenchmarkResult:
        """Benchmark deletion performance.

        Args:
            num_deletes: Number of deletion operations to benchmark

        Returns:
            BenchmarkResult with timing information
        """
        import time

        active_ids = [i for i in range(len(self._metadata)) if i not in self._tombstones]
        if len(active_ids) < num_deletes:
            raise VectorDBError(
                f"Cannot benchmark delete: need at least {num_deletes} active vectors "
                f"but have {len(active_ids)}"
            )

        ids_to_delete = active_ids[:num_deletes]

        start = time.time()
        for id in ids_to_delete:
            self.remove(id)
        end = time.time()

        # Restore by removing from tombstones
        for id in ids_to_delete:
            self._tombstones.discard(id)
        self._save_tombstones()

        return BenchmarkResult(
            operation="delete",
            duration_seconds=end - start,
            details={
                "num_deletes": num_deletes,
                "strategy": "lazy" if self.config.lazy_deletion else "immediate",
                "avg_latency_ms": (end - start) / num_deletes * 1000,
            }
        )

    def __len__(self) -> int:
        """Return the number of active vectors in the database."""
        return self.size()

    def __repr__(self) -> str:
        return (
            f"VectorDB(index_path={self.index_path!r}, "
            f"size={self.size()}, "
            f"embedding_dim={self.embedding_dim}, "
            f"index_type={self._index_config.get('type', 'Unknown')!r})"
        )


def get_vector_db(
    name: str = "default",
    workspace: Optional[str | Path] = None,
    embedding_dim: int = VectorDB.DEFAULT_EMBEDDING_DIM,
    config: Optional[IndexConfig] = None,
) -> Optional[VectorDB]:
    """
    Get or create a named vector database in the workspace.

    Args:
        name: Name of the vector database
        workspace: Workspace directory (defaults to current directory)
        embedding_dim: Embedding dimension
        config: Optional index configuration

    Returns:
        VectorDB instance or None if FAISS cannot be made available
    """
    if not FAISS_AVAILABLE:
        # Try auto-install
        if config is None:
            config = IndexConfig(auto_install=True)
        elif not config.auto_install:
            return None

        if not _attempt_install_faiss():
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
            config=config,
        )
    except Exception:
        return None


def run_benchmarks(
    db: VectorDB,
    sizes: List[int] = [100, 1000, 10000],
) -> Dict[str, Any]:
    """Run comprehensive benchmarks on a VectorDB instance.

    Args:
        db: VectorDB instance to benchmark
        sizes: List of dataset sizes to benchmark

    Returns:
        Dictionary with benchmark results
    """
    import numpy as np

    results = {
        "build": {},
        "search": {},
        "delete": {},
    }

    for size in sizes:
        # Benchmark build
        try:
            result = db.benchmark_build(size)
            results["build"][str(size)] = {
                "duration_seconds": result.duration_seconds,
                "details": result.details,
            }
        except Exception as e:
            results["build"][str(size)] = {"error": str(e)}

        # Benchmark search - need to add vectors first
        if size > 0:
            try:
                # Add vectors for search
                db.clear()
                db.add_batch(np.random.randn(size, db.embedding_dim).astype(np.float32))
                result = db.benchmark_search(min(100, size))
                results["search"][str(size)] = {
                    "duration_seconds": result.duration_seconds,
                    "details": result.details,
                }
            except Exception as e:
                results["search"][str(size)] = {"error": str(e)}

        # Benchmark delete
        if size > 0:
            # First add some vectors
            db.clear()
            db.add_batch(np.random.randn(size, db.embedding_dim).astype(np.float32))

            try:
                result = db.benchmark_delete(min(10, size))
                results["delete"][str(size)] = {
                    "duration_seconds": result.duration_seconds,
                    "details": result.details,
                }
            except Exception as e:
                results["delete"][str(size)] = {"error": str(e)}

    return results
