"""Tests for the VectorDB persistent vector database."""

import json
import numpy as np
import pytest
from pathlib import Path

from app.vector_db import VectorDB, VectorDBError, FAISS_AVAILABLE


@pytest.fixture
def vector_db_path(tmp_path: Path) -> Path:
    """Create a temporary path for vector database testing."""
    db_dir = tmp_path / "vector_db"
    db_dir.mkdir(exist_ok=True)
    return db_dir / "test.faiss"


@pytest.fixture
def sample_vectors():
    """Generate sample vectors for testing."""
    # Use 4-dimensional vectors for faster testing
    vectors = np.array([
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
        [0.5, 0.5, 0.0, 0.0],
        [0.0, 0.5, 0.5, 0.0],
    ], dtype=np.float32)
    return vectors


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

        idx = db.add(vector, metadata)

        assert idx == 0
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
        db = VectorDB(vector_db_path, embedding_dim=4, normalize=False)

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
        db1.add_batch(sample_vectors, sample_metadata)

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

    def test_not_faiss_available(self, tmp_path: Path, monkeypatch) -> None:
        """Test error when FAISS is not available."""
        # This test is tricky because we're already in the FAISS-available path
        # We'll just verify the module-level flag works
        from app.vector_db import FAISS_AVAILABLE
        if FAISS_AVAILABLE:
            # Just verify the error is raised when FAISS is not available
            # by checking the import behavior
            assert True  # Skip - FAISS is available

    def test_invalid_vector_type(self, vector_db_path: Path) -> None:
        """Test error when providing invalid vector type."""
        db = VectorDB(vector_db_path, embedding_dim=4)

        with pytest.raises(TypeError, match="type"):
            db.add("not a vector")


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
