"""Tests for the VectorDB persistent vector database."""

import json
import numpy as np
import pytest
from pathlib import Path

from app.vector_db import (
    VectorDB,
    VectorDBError,
    IndexConfig,
    FAISS_AVAILABLE,
    ensure_faiss_available,
    run_benchmarks,
    BenchmarkResult,
)


@pytest.fixture
def vector_db_path(tmp_path: Path) -> Path:
    """Create a temporary path for vector database testing."""
    db_dir = tmp_path / "vector_db"
    db_dir.mkdir(exist_ok=True)
    return db_dir / "test.faiss"


@pytest.fixture
def sample_vectors():
    """Generate sample vectors for testing (4-dimensional for speed)."""
    return np.array([
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
        [0.5, 0.5, 0.0, 0.0],
        [0.0, 0.5, 0.5, 0.0],
    ], dtype=np.float32)


@pytest.fixture
def sample_metadata():
    """Generate sample metadata for testing."""
    return [
        {"type": "test", "id": 1},
        {"type": "test", "id": 2},
        {"type": "test", "id": 3},
        {"type": "test", "id": 4},
        {"type": "test", "id": 5},
        {"type": "test", "id": 6},
    ]


@pytest.fixture
def large_vectors():
    """Generate a larger set of vectors for testing."""
    np.random.seed(42)
    return np.random.randn(5000, 4).astype(np.float32)


@pytest.mark.skipif(not FAISS_AVAILABLE, reason="FAISS not available")
class TestVectorDBBasic:
    """Test basic VectorDB operations."""

    def test_db_creation(self, vector_db_path: Path) -> None:
        """Test creating a new VectorDB."""
        db = VectorDB(vector_db_path, embedding_dim=4)
        assert db.size() == 0
        assert db.is_empty()
        assert len(db) == 0

    def test_add_single_vector(self, vector_db_path: Path, sample_vectors) -> None:
        """Test adding a single vector."""
        db = VectorDB(vector_db_path, embedding_dim=4)

        vector = sample_vectors[0]
        metadata = {"test": "vector1"}

        id = db.add(vector, metadata)

        assert id == 0
        assert db.size() == 1
        assert not db.is_empty()

        # Verify metadata
        retrieved_metadata = db.get_metadata(0)
        assert retrieved_metadata == metadata

    def test_add_batch_vectors(self, vector_db_path: Path, sample_vectors, sample_metadata) -> None:
        """Test adding multiple vectors at once."""
        db = VectorDB(vector_db_path, embedding_dim=4)

        ids = db.add_batch(sample_vectors, sample_metadata)

        assert len(ids) == len(sample_vectors)
        # IDs should be sequential starting from 0
        assert ids == list(range(len(sample_vectors)))
        assert db.size() == len(sample_vectors)

        # Verify metadata
        for i, expected_meta in enumerate(sample_metadata):
            retrieved = db.get_metadata(i)
            assert retrieved == expected_meta

    def test_search(self, vector_db_path: Path, sample_vectors) -> None:
        """Test similarity search."""
        db = VectorDB(vector_db_path, embedding_dim=4, normalize=False)

        # Add vectors
        db.add_batch(sample_vectors)

        # Search for vector similar to [1, 0, 0, 0]
        query = np.array([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32)
        results = db.search(query, limit=3)

        assert len(results) > 0
        # First result should be the first vector (exact match)
        assert results[0][0] == 0
        assert results[0][1] >= 0.9  # High similarity

    def test_search_with_threshold(self, vector_db_path: Path, sample_vectors) -> None:
        """Test search with similarity threshold."""
        db = VectorDB(vector_db_path, embedding_dim=4)

        # Add vectors
        db.add_batch(sample_vectors)

        # Search with high threshold
        query = np.array([[0.1, 0.1, 0.1, 0.1]], dtype=np.float32)
        results = db.search(query, limit=5, threshold=0.5)

        # Only highly similar results should be returned
        for _, score, _ in results:
            assert score >= 0.5

    def test_update_metadata(self, vector_db_path: Path) -> None:
        """Test updating metadata for a vector."""
        db = VectorDB(vector_db_path, embedding_dim=4)

        vector = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        db.add(vector, {"old": "value"})

        # Update metadata
        assert db.update_metadata(0, {"new": "value"})

        # Verify update
        metadata = db.get_metadata(0)
        assert metadata == {"new": "value"}

    def test_update_deleted_metadata_fails(self, vector_db_path: Path, sample_vectors) -> None:
        """Test that updating deleted metadata fails."""
        db = VectorDB(vector_db_path, embedding_dim=4)

        db.add_batch(sample_vectors)
        db.remove(0)

        # Should fail to update deleted vector
        assert db.update_metadata(0, {"new": "value"}) is False

    def test_get_deleted_metadata_returns_none(self, vector_db_path: Path, sample_vectors) -> None:
        """Test that getting deleted metadata returns None."""
        db = VectorDB(vector_db_path, embedding_dim=4)

        db.add_batch(sample_vectors)
        db.remove(0)

        assert db.get_metadata(0) is None

    def test_clear(self, vector_db_path: Path, sample_vectors) -> None:
        """Test clearing the database."""
        db = VectorDB(vector_db_path, embedding_dim=4)

        # Add vectors
        db.add_batch(sample_vectors)
        assert db.size() > 0

        # Clear
        db.clear()

        assert db.size() == 0
        assert db.is_empty()
        assert db.get_metadata(0) is None

    def test_repr(self, vector_db_path: Path) -> None:
        """Test string representation."""
        db = VectorDB(vector_db_path, embedding_dim=4)
        repr_str = repr(db)

        assert "VectorDB" in repr_str
        assert "test.faiss" in repr_str
        assert "embedding_dim=4" in repr_str


@pytest.mark.skipif(not FAISS_AVAILABLE, reason="FAISS not available")
class TestVectorDBPersistence:
    """Test VectorDB persistence across sessions."""

    def test_persist_and_reload(self, tmp_path: Path, sample_vectors, sample_metadata) -> None:
        """Test that database persists to disk and can be reloaded."""
        db_path = tmp_path / "persistent.faiss"

        # Create and populate database
        db1 = VectorDB(db_path, embedding_dim=4)
        ids = db1.add_batch(sample_vectors, sample_metadata)

        # Verify it was saved
        assert db_path.exists()

        # Create a new instance pointing to the same path
        db2 = VectorDB(db_path, embedding_dim=4)

        # Verify data was restored
        assert db2.size() == len(sample_vectors)

        # Verify metadata was restored
        for i in range(len(sample_metadata)):
            assert db2.get_metadata(i) == sample_metadata[i]

    def test_metadata_file_created(self, vector_db_path: Path, sample_vectors, sample_metadata) -> None:
        """Test that metadata file is created alongside index."""
        db = VectorDB(vector_db_path, embedding_dim=4)
        db.add_batch(sample_vectors, sample_metadata)

        # Check metadata file exists
        metadata_path = vector_db_path.with_suffix(".metadata.json")
        assert metadata_path.exists()

        # Verify metadata content
        with open(metadata_path, 'r') as f:
            saved_metadata = json.load(f)

        assert len(saved_metadata) == len(sample_metadata)


@pytest.mark.skipif(not FAISS_AVAILABLE, reason="FAISS not available")
class TestVectorDBNormalization:
    """Test VectorDB with normalized vectors."""

    def test_normalized_search(self, vector_db_path: Path) -> None:
        """Test search with normalized vectors."""
        db = VectorDB(vector_db_path, embedding_dim=4, normalize=True)

        # Add normalized vectors
        vectors = np.array([
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
        ], dtype=np.float32)
        db.add_batch(vectors)

        # Search with normalized query
        query = np.array([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32)
        results = db.search(query, limit=1)

        assert len(results) > 0
        assert results[0][0] == 0


@pytest.mark.skipif(not FAISS_AVAILABLE, reason="FAISS not available")
class TestVectorDBErrorHandling:
    """Test VectorDB error handling."""

    def test_wrong_dimension(self, vector_db_path: Path) -> None:
        """Test error when adding vector with wrong dimension."""
        db = VectorDB(vector_db_path, embedding_dim=4)

        # Try to add 3-dimensional vector to 4D database
        wrong_vector = np.array([1.0, 2.0, 3.0], dtype=np.float32)

        with pytest.raises(ValueError, match="dimension"):
            db.add(wrong_vector)

    def test_invalid_vector_type(self, vector_db_path: Path) -> None:
        """Test error when providing invalid vector type."""
        db = VectorDB(vector_db_path, embedding_dim=4)

        with pytest.raises(TypeError, match="type"):
            db.add("not a vector")

    def test_get_metadata_invalid_id(self, vector_db_path: Path) -> None:
        """Test getting metadata with invalid ID."""
        db = VectorDB(vector_db_path, embedding_dim=4)

        assert db.get_metadata(0) is None
        assert db.get_metadata(-1) is None
        assert db.get_metadata(100) is None


@pytest.mark.skipif(not FAISS_AVAILABLE, reason="FAISS not available")
class TestGetVectorDB:
    """Test the get_vector_db helper function."""

    def test_get_vector_db(self, tmp_path: Path) -> None:
        """Test getting a named vector database."""
        from app.vector_db import get_vector_db

        db = get_vector_db("test", workspace=str(tmp_path))

        assert db is not None
        assert db.size() == 0
        assert "test.faiss" in str(db.index_path)

    def test_get_vector_db_default(self, tmp_path: Path, monkeypatch) -> None:
        """Test getting the default vector database."""
        from app.vector_db import get_vector_db

        monkeypatch.chdir(tmp_path)
        db = get_vector_db()

        assert db is not None
        assert "default.faiss" in str(db.index_path)


@pytest.mark.skipif(not FAISS_AVAILABLE, reason="FAISS not available")
class TestVectorDBConfig:
    """Test VectorDB configuration."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        from app.vector_db import DEFAULT_CONFIG

        assert DEFAULT_CONFIG.flat_threshold == 10_000
        assert DEFAULT_CONFIG.medium_threshold == 100_000
        assert DEFAULT_CONFIG.small_nlist == 100
        assert DEFAULT_CONFIG.lazy_deletion is True

    def test_custom_config(self, vector_db_path: Path) -> None:
        """Test custom configuration."""
        config = IndexConfig(
            flat_threshold=100,
            medium_threshold=1000,
            lazy_deletion=False,
        )

        db = VectorDB(vector_db_path, embedding_dim=4, config=config)

        assert db.config.flat_threshold == 100
        assert db.config.medium_threshold == 1000
        assert db.config.lazy_deletion is False


@pytest.mark.skipif(not FAISS_AVAILABLE, reason="FAISS not available")
class TestVectorDBAdaptiveIndex:
    """Test adaptive index selection."""

    def test_flat_index_for_small_data(self, vector_db_path: Path) -> None:
        """Test that Flat index is used for small datasets."""
        config = IndexConfig(
            flat_threshold=1000,
            medium_threshold=10000,
        )

        db = VectorDB(vector_db_path, embedding_dim=4, config=config)

        # Check initial index type
        info = db.get_index_info()
        assert info["type"] == "Flat"

    def test_index_info(self, vector_db_path: Path) -> None:
        """Test get_index_info returns correct information."""
        db = VectorDB(vector_db_path, embedding_dim=4)

        info = db.get_index_info()

        assert "type" in info
        assert "size" in info
        assert "embedding_dim" in info
        assert info["embedding_dim"] == 4
        assert info["size"] == 0


@pytest.mark.skipif(not FAISS_AVAILABLE, reason="FAISS not available")
class TestVectorDBLazyDeletion:
    """Test lazy deletion functionality."""

    def test_remove_marks_for_deletion(self, vector_db_path: Path, sample_vectors, sample_metadata) -> None:
        """Test that remove marks vectors as deleted."""
        config = IndexConfig(lazy_deletion=True)
        db = VectorDB(vector_db_path, embedding_dim=4, config=config)

        db.add_batch(sample_vectors, sample_metadata)
        initial_size = db.size()

        # Remove a vector
        assert db.remove(0)

        # Size should decrease
        assert db.size() == initial_size - 1

        # Metadata should be None for deleted vector
        assert db.get_metadata(0) is None

    def test_deleted_vectors_excluded_from_search(self, vector_db_path: Path, sample_vectors) -> None:
        """Test that deleted vectors are excluded from search results."""
        config = IndexConfig(lazy_deletion=True)
        db = VectorDB(vector_db_path, embedding_dim=4, config=config)

        db.add_batch(sample_vectors)

        # Remove first vector
        db.remove(0)

        # Search should not return the deleted vector
        query = np.array([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32)
        results = db.search(query, limit=5)

        # First vector (index 0) should not be in results
        for id, _, _ in results:
            assert id != 0

    def test_force_compact(self, vector_db_path: Path, sample_vectors, sample_metadata) -> None:
        """Test force compaction."""
        config = IndexConfig(lazy_deletion=True, compaction_threshold=0.5)
        db = VectorDB(vector_db_path, embedding_dim=4, config=config)

        db.add_batch(sample_vectors, sample_metadata)
        initial_physical = db.physical_size()

        # Remove half the vectors
        for i in range(len(sample_vectors) // 2):
            db.remove(i)

        # Physical size should still be the same (tombstones are marked)
        assert db.physical_size() == initial_physical
        # But logical size should be half
        assert db.size() == len(sample_vectors) - len(sample_vectors) // 2

        # Force compaction
        db.force_compact()

        # Physical size should be reduced after compaction
        assert db.physical_size() < initial_physical
        # Logical size should be the same
        assert db.size() == len(sample_vectors) - len(sample_vectors) // 2

    def test_get_deleted_count(self, vector_db_path: Path, sample_vectors) -> None:
        """Test get_deleted_count."""
        config = IndexConfig(lazy_deletion=True)
        db = VectorDB(vector_db_path, embedding_dim=4, config=config)

        db.add_batch(sample_vectors)

        # Initially no deleted vectors
        assert db.get_deleted_count() == 0

        # Remove some vectors
        db.remove(0)
        db.remove(1)

        # Should have 2 deleted vectors
        assert db.get_deleted_count() == 2

    def test_remove_nonexistent_id(self, vector_db_path: Path) -> None:
        """Test removing a non-existent ID."""
        db = VectorDB(vector_db_path, embedding_dim=4)

        # Try to remove from empty database
        assert db.remove(0) is False

    def test_remove_already_deleted(self, vector_db_path: Path, sample_vectors) -> None:
        """Test removing an already deleted vector."""
        db = VectorDB(vector_db_path, embedding_dim=4)

        db.add_batch(sample_vectors)

        # Remove twice
        assert db.remove(0) is True
        assert db.remove(0) is False


@pytest.mark.skipif(not FAISS_AVAILABLE, reason="FAISS not available")
class TestVectorDBPersistenceWithDeletion:
    """Test persistence with lazy deletion."""

    def test_deleted_ids_persist(self, tmp_path: Path, sample_vectors, sample_metadata) -> None:
        """Test that deleted IDs are persisted to disk."""
        db_path = tmp_path / "deletion_test.faiss"
        config = IndexConfig(lazy_deletion=True, compaction_threshold=0.1)

        # Create and populate
        db1 = VectorDB(db_path, embedding_dim=4, config=config)
        db1.add_batch(sample_vectors, sample_metadata)
        db1.remove(0)
        db1.remove(2)

        # Reload
        db2 = VectorDB(db_path, embedding_dim=4, config=config)

        # Check that deleted IDs are restored
        assert db2.get_deleted_count() == 2
        assert db2.get_metadata(0) is None
        assert db2.get_metadata(1) is not None
        assert db2.get_metadata(2) is None


@pytest.mark.skipif(not FAISS_AVAILABLE, reason="FAISS not available")
class TestVectorDBEdgeCases:
    """Test edge cases for VectorDB."""

    def test_empty_database_search(self, vector_db_path: Path) -> None:
        """Test searching on empty database."""
        db = VectorDB(vector_db_path, embedding_dim=4)

        query = np.array([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32)
        results = db.search(query, limit=5)

        assert results == []

    def test_single_vector_database(self, vector_db_path: Path) -> None:
        """Test operations on single-vector database."""
        db = VectorDB(vector_db_path, embedding_dim=4)

        vector = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        db.add(vector, {"test": "single"})

        assert db.size() == 1
        assert not db.is_empty()

        # Search
        results = db.search(vector, limit=1)
        assert len(results) == 1
        assert results[0][0] == 0

    def test_duplicate_vectors(self, vector_db_path: Path) -> None:
        """Test adding duplicate vectors."""
        db = VectorDB(vector_db_path, embedding_dim=4)

        vector = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)

        db.add(vector, {"id": 1})
        db.add(vector, {"id": 2})

        assert db.size() == 2

        # Both should be retrievable
        assert db.get_metadata(0)["id"] == 1
        assert db.get_metadata(1)["id"] == 2

    def test_large_batch_add(self, vector_db_path: Path, large_vectors) -> None:
        """Test adding a large batch of vectors."""
        db = VectorDB(vector_db_path, embedding_dim=4)

        ids = db.add_batch(large_vectors)

        assert len(ids) == len(large_vectors)
        assert db.size() == len(large_vectors)


@pytest.mark.skipif(not FAISS_AVAILABLE, reason="FAISS not available")
class TestVectorDBCorruptedRecovery:
    """Test recovery from corrupted index files."""

    def test_recover_from_corrupted_index(self, tmp_path: Path, sample_vectors) -> None:
        """Test that database can recover from corrupted index file."""
        db_path = tmp_path / "corrupted.faiss"

        # Create valid database
        db1 = VectorDB(db_path, embedding_dim=4)
        db1.add_batch(sample_vectors)

        # Corrupt the index file
        with open(db_path, 'wb') as f:
            f.write(b"corrupted data")

        # Should still be able to create new instance (will rebuild)
        db2 = VectorDB(db_path, embedding_dim=4)

        # Should be empty (rebuilt)
        assert db2.size() == 0


@pytest.mark.skipif(not FAISS_AVAILABLE, reason="FAISS not available")
class TestVectorDBIndexMetadata:
    """Test index metadata storage."""

    def test_index_config_saved(self, vector_db_path: Path) -> None:
        """Test that index config is saved to disk."""
        db = VectorDB(vector_db_path, embedding_dim=4)
        db.add(np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32))

        # Check config file exists
        config_path = vector_db_path.with_suffix(".config.json")
        assert config_path.exists()


@pytest.mark.skipif(not FAISS_AVAILABLE, reason="FAISS not available")
class TestVectorDBBenchmarking:
    """Test benchmarking functionality."""

    def test_benchmark_build(self, vector_db_path: Path) -> None:
        """Test build benchmarking."""
        db = VectorDB(vector_db_path, embedding_dim=4)

        result = db.benchmark_build(num_vectors=100)

        assert isinstance(result, BenchmarkResult)
        assert result.operation == "build"
        assert result.duration_seconds > 0
        assert result.details["num_vectors"] == 100

    def test_benchmark_search(self, vector_db_path: Path, sample_vectors) -> None:
        """Test search benchmarking."""
        db = VectorDB(vector_db_path, embedding_dim=4)
        db.add_batch(sample_vectors)

        result = db.benchmark_search(num_queries=10)

        assert isinstance(result, BenchmarkResult)
        assert result.operation == "search"
        # Duration might be 0 for very fast operations
        assert result.duration_seconds >= 0
        assert "avg_latency_ms" in result.details

    def test_benchmark_delete(self, vector_db_path: Path, sample_vectors) -> None:
        """Test delete benchmarking."""
        db = VectorDB(vector_db_path, embedding_dim=4)
        db.add_batch(sample_vectors)

        result = db.benchmark_delete(num_deletes=3)

        assert isinstance(result, BenchmarkResult)
        assert result.operation == "delete"
        # Duration might be 0 for very fast operations
        assert result.duration_seconds >= 0

    def test_run_benchmarks(self, vector_db_path: Path) -> None:
        """Test comprehensive benchmarking."""
        db = VectorDB(vector_db_path, embedding_dim=4)

        results = run_benchmarks(db, sizes=[10, 100])

        assert "build" in results
        assert "search" in results
        assert "delete" in results

        # Check that benchmarks ran
        assert len(results["build"]) > 0


@pytest.mark.skipif(not FAISS_AVAILABLE, reason="FAISS not available")
class TestEnsureFAISS:
    """Test FAISS availability checking."""

    def test_ensure_faiss_available_true(self) -> None:
        """Test ensure_faiss_available when FAISS is available."""
        result = ensure_faiss_available(auto_install=False)
        assert result is True

    def test_ensure_faiss_available_no_auto_install(self, monkeypatch) -> None:
        """Test ensure_faiss_available with no auto-install."""
        # Temporarily hide FAISS
        import app.vector_db as vdb_module
        original_faiss = vdb_module.FAISS_AVAILABLE
        vdb_module.FAISS_AVAILABLE = False

        try:
            result = ensure_faiss_available(auto_install=False)
            assert result is False
        finally:
            vdb_module.FAISS_AVAILABLE = original_faiss
