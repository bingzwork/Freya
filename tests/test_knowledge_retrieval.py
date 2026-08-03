"""Tests for Knowledge Retrieval capability."""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timezone
from pathlib import Path
import tempfile

from app.knowledge_retrieval import (
    KnowledgeRetrievalResult,
    RetrievalQuery,
    RetrievalResponse,
    RetrievalDecision,
    KnowledgeSourceType,
    RankingSignal,
    RankingFactor,
    RankingConfig,
    UsageEvent,
    RankingEngine,
    AdaptiveRankingEngine,
    create_ranking_engine,
    CalibrationManager,
    UsageAnalytics,
    KnowledgeSourceAdapter,
    SemanticMemoryAdapter,
    VectorSearchAdapter,
    PipelineStats,
    KnowledgeRetrievalPipeline,
    create_pipeline_from_agent,
    retrieve_knowledge,
)


class TestModels:
    """Test data models."""

    def test_knowledge_retrieval_result_creation(self):
        """Test KnowledgeRetrievalResult creation and serialization."""
        obj = KnowledgeRetrievalResult(
            content="Test content",
            title="Test Title",
            summary="Test summary",
            source_type=KnowledgeSourceType.SEMANTIC_MEMORY,
            source_id="test_123",
            raw_confidence=0.8,
            calibrated_confidence=0.85,
            category="best_practice",
            tags=["python", "pattern"],
            language="python",
        )

        assert obj.content == "Test content"
        assert obj.source_type == KnowledgeSourceType.SEMANTIC_MEMORY
        assert obj.raw_confidence == 0.8
        assert obj.calibrated_confidence == 0.85

        # Test serialization
        data = obj.to_dict()
        assert data["content"] == "Test content"
        assert data["source_type"] == "semantic_memory"
        assert data["raw_confidence"] == 0.8

    def test_retrieval_query(self):
        """Test RetrievalQuery creation and defaults."""
        query = RetrievalQuery(query="test query")
        assert query.query == "test query"
        assert query.max_results == 10
        assert query.min_score == 0.1
        assert query.boost_recent is True
        assert query.require_calibration is True

        # Test with custom values
        query2 = RetrievalQuery(
            query="test",
            max_results=5,
            sources=[KnowledgeSourceType.SEMANTIC_MEMORY],
        )
        assert query2.max_results == 5
        assert KnowledgeSourceType.SEMANTIC_MEMORY in query2.sources

    def test_retrieval_response(self):
        """Test RetrievalResponse."""
        result = KnowledgeRetrievalResult(
            content="Test",
            source_type=KnowledgeSourceType.SEMANTIC_MEMORY,
            source_id="1",
        )
        query = RetrievalQuery(query="test")
        response = RetrievalResponse(
            results=[result],
            decision=RetrievalDecision.USE_DIRECTLY,
            decision_reason="High confidence",
            query=query,
            total_candidates=1,
            retrieval_time=0.1,
        )

        assert len(response.results) == 1
        assert response.decision == RetrievalDecision.USE_DIRECTLY
        data = response.to_dict()
        assert data["decision"] == "use_directly"

    def test_ranking_config(self):
        """Test RankingConfig defaults."""
        config = RankingConfig()

        # Check weights sum to approximately 1
        total = sum(config.weights.values())
        assert abs(total - 1.0) < 0.01

        # Check source quality scores
        assert config.source_quality_scores[KnowledgeSourceType.KNOWLEDGE_BASE] == 0.95
        assert config.source_quality_scores[KnowledgeSourceType.UNKNOWN] == 0.50

        # Check thresholds
        assert config.use_directly_threshold == 0.90
        assert config.use_with_caution_threshold == 0.70

    def test_ranking_factor(self):
        """Test RankingFactor weighted value."""
        factor = RankingFactor(
            signal=RankingSignal.RELEVANCE,
            value=0.8,
            weight=0.3,
        )
        assert factor.weighted_value == 0.24

    def test_usage_event(self):
        """Test UsageEvent."""
        event = UsageEvent(
            retrieval_id="retr_123",
            query="test query",
            result_id="res_456",
            source_type=KnowledgeSourceType.SEMANTIC_MEMORY,
            action="selected",
            rank_position=1,
            rank_score=0.9,
        )
        assert event.action == "selected"
        assert event.rank_position == 1

        data = event.to_dict()
        assert data["source_type"] == "semantic_memory"


class TestRankingEngine:
    """Test the ranking engine."""

    def test_basic_ranking(self):
        """Test basic ranking functionality."""
        engine = RankingEngine()
        query = RetrievalQuery(query="python singleton pattern")

        results = [
            KnowledgeRetrievalResult(
                content="Singleton pattern implementation in Python",
                title="Singleton Pattern",
                source_type=KnowledgeSourceType.SEMANTIC_MEMORY,
                source_id="1",
                raw_confidence=0.9,
                calibrated_confidence=0.9,
                tags=["python", "pattern", "singleton"],
            ),
            KnowledgeRetrievalResult(
                content="Factory pattern example",
                title="Factory Pattern",
                source_type=KnowledgeSourceType.SEMANTIC_MEMORY,
                source_id="2",
                raw_confidence=0.8,
                calibrated_confidence=0.8,
                tags=["python", "pattern", "factory"],
            ),
            KnowledgeRetrievalResult(
                content="Observer pattern for event handling",
                title="Observer Pattern",
                source_type=KnowledgeSourceType.SEMANTIC_MEMORY,
                source_id="3",
                raw_confidence=0.7,
                calibrated_confidence=0.7,
                tags=["python", "pattern", "observer"],
            ),
        ]

        ranked = engine.rank(results, query)

        # Should be sorted by rank_score descending
        assert len(ranked) == 3
        assert ranked[0].rank_score >= ranked[1].rank_score
        assert ranked[1].rank_score >= ranked[2].rank_score

        # First result should be the singleton one (most relevant)
        assert "singleton" in ranked[0].content.lower()

    def test_ranking_explanation(self):
        """Test ranking explanation generation."""
        engine = RankingEngine()
        query = RetrievalQuery(query="test query")

        result = KnowledgeRetrievalResult(
            content="test content",
            source_type=KnowledgeSourceType.SEMANTIC_MEMORY,
            source_id="1",
            raw_confidence=0.8,
            calibrated_confidence=0.8,
        )

        ranked = engine.rank([result], query)
        assert ranked[0].ranking_explanation is not None
        assert ranked[0].ranking_explanation.total_score > 0

        explanation = ranked[0].ranking_explanation.explain_simple()
        assert "Total score" in explanation

    def test_custom_calculator(self):
        """Test registering custom signal calculator."""
        engine = RankingEngine()

        def custom_calculator(result, query, analytics):
            return 1.0, {"custom": True}

        engine.register_calculator(RankingSignal.RELEVANCE, custom_calculator)

        result = KnowledgeRetrievalResult(
            content="test",
            source_type=KnowledgeSourceType.SEMANTIC_MEMORY,
            source_id="1",
            raw_confidence=0.5,
            calibrated_confidence=0.5,
        )

        ranked = engine.rank([result], RetrievalQuery(query="test"))
        factors = ranked[0].ranking_explanation.factors
        relevance_factor = next(f for f in factors if f.signal == RankingSignal.RELEVANCE)
        assert relevance_factor.value == 1.0
        assert relevance_factor.metadata.get("custom") is True


class TestAdaptiveRankingEngine:
    """Test adaptive ranking engine."""

    def test_adaptation(self):
        """Test weight adaptation from feedback."""
        config = RankingConfig()
        config.adaptation_enabled = True
        config.adaptation_rate = 0.1
        # Use smaller buffer for testing
        engine = AdaptiveRankingEngine(config)
        engine._adaptation_interval = 3

        query = RetrievalQuery(query="test")
        result = KnowledgeRetrievalResult(
            content="test content",
            source_type=KnowledgeSourceType.SEMANTIC_MEMORY,
            source_id="1",
            raw_confidence=0.8,
            calibrated_confidence=0.8,
        )

        # Record positive feedback
        engine.record_feedback(result, query, "positive")
        engine.record_feedback(result, query, "positive")
        engine.record_feedback(result, query, "positive")

        # Weights should have adapted
        assert len(engine._feedback_buffer) == 0  # Cleared after adaptation

    def test_get_weights(self):
        """Test getting current weights."""
        engine = AdaptiveRankingEngine()
        weights = engine.get_weight_history()
        assert isinstance(weights, dict)
        assert "relevance" in weights


class TestCalibrationManager:
    """Test confidence calibration."""

    def test_isotonic_calibration(self):
        """Test isotonic calibration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            calibrator = CalibrationManager(
                method="isotonic",
                storage_path=Path(tmpdir) / "cal.json",
                min_samples=5,
            )

            # Add training data
            for i in range(10):
                pred = 0.5 + i * 0.04  # 0.5 to 0.86
                actual = pred > 0.7  # Better predictions are correct
                calibrator.update(pred, actual)

            # Test calibration
            calibrated = calibrator.calibrate(0.75)
            assert 0 <= calibrated <= 1

    def test_platt_calibration(self):
        """Test Platt scaling calibration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            calibrator = CalibrationManager(
                method="platt",
                storage_path=Path(tmpdir) / "cal.json",
                min_samples=5,
            )

            for i in range(10):
                pred = 0.5 + i * 0.04
                actual = pred > 0.7
                calibrator.update(pred, actual)

            calibrated = calibrator.calibrate(0.75)
            assert 0 <= calibrated <= 1

    def test_temperature_calibration(self):
        """Test temperature scaling calibration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            calibrator = CalibrationManager(
                method="temperature",
                storage_path=Path(tmpdir) / "cal.json",
                min_samples=5,
            )

            for i in range(10):
                pred = 0.5 + i * 0.04
                actual = pred > 0.7
                calibrator.update(pred, actual)

            calibrated = calibrator.calibrate(0.75)
            assert 0 <= calibrated <= 1

    def test_no_op_calibration(self):
        """Test no-op calibration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            calibrator = CalibrationManager(
                method="none",
                storage_path=Path(tmpdir) / "cal.json",
            )

            # Should return raw confidence unchanged
            assert calibrator.calibrate(0.75) == 0.75
            assert calibrator.calibrate(0.2) == 0.2

    def test_persistence(self):
        """Test calibration data persistence."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "cal.json"

            # Create and train
            cal1 = CalibrationManager(method="isotonic", storage_path=path, min_samples=5)
            for i in range(10):
                cal1.update(0.5 + i * 0.04, True)
            cal1.save()

            # Load in new instance
            cal2 = CalibrationManager(method="isotonic", storage_path=path, min_samples=5)
            assert len(cal2.calibrator._global_data.predictions) == 10


class TestUsageAnalytics:
    """Test usage analytics."""

    def test_basic_analytics(self):
        """Test basic analytics recording."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analytics = UsageAnalytics(storage_path=Path(tmpdir) / "analytics.json")

            # Record retrieval
            session_id = analytics.record_retrieval(
                query="test query",
                results=[
                    {"result_id": "1", "source_type": "semantic_memory", "rank_position": 1, "rank_score": 0.9},
                    {"result_id": "2", "source_type": "semantic_memory", "rank_position": 2, "rank_score": 0.7},
                ],
            )

            assert session_id is not None

            # Record selection
            analytics.record_selection("1", KnowledgeSourceType.SEMANTIC_MEMORY, 1, 0.9, "test query")

            # Record feedback
            analytics.record_feedback("1", KnowledgeSourceType.SEMANTIC_MEMORY, True, "test query")

            # Record task outcome
            analytics.record_task_outcome("1", KnowledgeSourceType.SEMANTIC_MEMORY, True)

            # Get stats
            stats = analytics.get_result_usage_stats("1", KnowledgeSourceType.SEMANTIC_MEMORY)
            assert stats is not None
            assert stats["total_retrievals"] == 1
            assert stats["total_selections"] == 1
            assert stats["positive_feedback"] == 1
            assert stats["task_successes"] == 1

    def test_usefulness_score(self):
        """Test usefulness score calculation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analytics = UsageAnalytics(storage_path=Path(tmpdir) / "analytics.json")

            analytics.record_retrieval(
                query="test",
                results=[{"result_id": "1", "source_type": "semantic_memory", "rank_position": 1, "rank_score": 0.9}],
            )

            # Good result: selected, positive feedback, task success
            analytics.record_selection("1", KnowledgeSourceType.SEMANTIC_MEMORY, 1, 0.9)
            analytics.record_feedback("1", KnowledgeSourceType.SEMANTIC_MEMORY, True)
            analytics.record_task_outcome("1", KnowledgeSourceType.SEMANTIC_MEMORY, True)

            usefulness = analytics.get_result_usefulness("1", KnowledgeSourceType.SEMANTIC_MEMORY)
            assert usefulness is not None
            assert usefulness > 0.5  # Should be high

    def test_source_stats(self):
        """Test source-level statistics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analytics = UsageAnalytics(storage_path=Path(tmpdir) / "analytics.json")

            analytics.record_retrieval(
                query="test",
                results=[{"result_id": "1", "source_type": "semantic_memory", "rank_position": 1, "rank_score": 0.9}],
            )

            stats = analytics.get_source_stats(KnowledgeSourceType.SEMANTIC_MEMORY)
            assert stats is not None
            assert stats["total_queries"] == 1
            assert stats["total_results_retrieved"] == 1

    def test_query_analytics(self):
        """Test query analytics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analytics = UsageAnalytics(storage_path=Path(tmpdir) / "analytics.json")

            analytics.record_retrieval(
                query="python test",
                results=[{"result_id": "1", "source_type": "semantic_memory", "rank_position": 1, "rank_score": 0.9}],
            )
            analytics.record_retrieval(
                query="javascript test",
                results=[{"result_id": "2", "source_type": "semantic_memory", "rank_position": 1, "rank_score": 0.8}],
            )

            query_analytics = analytics.get_query_analytics(query="python")
            assert query_analytics["total_events"] > 0


class TestPipeline:
    """Test the main retrieval pipeline."""

    def test_empty_pipeline(self):
        """Test pipeline with no adapters."""
        pipeline = KnowledgeRetrievalPipeline()
        response = pipeline.retrieve("test query")

        assert response.results == []
        assert response.decision == RetrievalDecision.NO_KNOWLEDGE

    def test_pipeline_with_mock_adapter(self):
        """Test pipeline with a mock adapter."""
        # Create mock adapter
        mock_adapter = Mock(spec=KnowledgeSourceAdapter)
        mock_adapter.source_type = KnowledgeSourceType.SEMANTIC_MEMORY
        mock_adapter.is_available.return_value = True
        mock_adapter.retrieve_candidates.return_value = [
            KnowledgeRetrievalResult(
                content="Test content about singleton pattern",
                title="Singleton",
                source_type=KnowledgeSourceType.SEMANTIC_MEMORY,
                source_id="1",
                raw_confidence=0.9,
                calibrated_confidence=0.9,
                tags=["python", "singleton"],
            ),
            KnowledgeRetrievalResult(
                content="Factory pattern content",
                title="Factory",
                source_type=KnowledgeSourceType.SEMANTIC_MEMORY,
                source_id="2",
                raw_confidence=0.8,
                calibrated_confidence=0.8,
                tags=["python", "factory"],
            ),
        ]
        mock_adapter.get_source_quality.return_value = 0.9

        pipeline = KnowledgeRetrievalPipeline()
        pipeline.register_adapter(mock_adapter)

        response = pipeline.retrieve(RetrievalQuery(query="singleton pattern"))

        assert len(response.results) == 2
        assert response.decision in [RetrievalDecision.USE_DIRECTLY, RetrievalDecision.USE_WITH_CAUTION]
        assert "singleton" in response.results[0].content.lower()

    def test_pipeline_with_string_query(self):
        """Test pipeline with simple string query."""
        mock_adapter = Mock(spec=KnowledgeSourceAdapter)
        mock_adapter.source_type = KnowledgeSourceType.SEMANTIC_MEMORY
        mock_adapter.is_available.return_value = True
        mock_adapter.retrieve_candidates.return_value = [
            KnowledgeRetrievalResult(
                content="Test content",
                source_type=KnowledgeSourceType.SEMANTIC_MEMORY,
                source_id="1",
                raw_confidence=0.9,
                calibrated_confidence=0.9,
            ),
        ]
        mock_adapter.get_source_quality.return_value = 0.9

        pipeline = KnowledgeRetrievalPipeline()
        pipeline.register_adapter(mock_adapter)

        response = pipeline.retrieve("test query")
        assert len(response.results) == 1

    def test_pipeline_stats(self):
        """Test pipeline statistics."""
        mock_adapter = Mock(spec=KnowledgeSourceAdapter)
        mock_adapter.source_type = KnowledgeSourceType.SEMANTIC_MEMORY
        mock_adapter.is_available.return_value = True
        mock_adapter.retrieve_candidates.return_value = [
            KnowledgeRetrievalResult(
                content="Test",
                source_type=KnowledgeSourceType.SEMANTIC_MEMORY,
                source_id="1",
                raw_confidence=0.9,
                calibrated_confidence=0.9,
            ),
        ]
        mock_adapter.get_source_quality.return_value = 0.9

        pipeline = KnowledgeRetrievalPipeline()
        pipeline.register_adapter(mock_adapter)

        pipeline.retrieve("test 1")
        pipeline.retrieve("test 2")

        stats = pipeline.get_stats()
        assert stats["total_queries"] == 2
        assert stats["successful_queries"] == 2
        assert stats["avg_results_per_query"] == 1.0

    def test_calibration_in_pipeline(self):
        """Test calibration is applied in pipeline."""
        mock_adapter = Mock(spec=KnowledgeSourceAdapter)
        mock_adapter.source_type = KnowledgeSourceType.SEMANTIC_MEMORY
        mock_adapter.is_available.return_value = True
        mock_adapter.retrieve_candidates.return_value = [
            KnowledgeRetrievalResult(
                content="Test content",
                source_type=KnowledgeSourceType.SEMANTIC_MEMORY,
                source_id="1",
                raw_confidence=0.9,
                calibrated_confidence=0.9,  # Will be overwritten by calibration
            ),
        ]
        mock_adapter.get_source_quality.return_value = 0.9

        # Create pipeline with calibration
        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = KnowledgeRetrievalPipeline(
                calibration_method="temperature",
                calibration_storage=Path(tmpdir) / "cal.json",
            )
            pipeline.register_adapter(mock_adapter)

            # Train calibration
            for i in range(10):
                pipeline.calibration.update(0.5 + i * 0.04, True)

            response = pipeline.retrieve("test query")
            assert response.results[0].calibration_metadata is not None
            assert "calibrated_confidence" in response.results[0].calibration_metadata


class TestSourceAdapters:
    """Test knowledge source adapters."""

    def test_semantic_memory_adapter(self):
        """Test semantic memory adapter with mock."""
        mock_memory = Mock()
        mock_memory.is_empty.return_value = False
        mock_memory.search.return_value = [
            Mock(
                entry_id="1",
                category="best_practice",
                title="Test Entry",
                content="Test content about singleton",
                language="python",
                tags=["python", "pattern"],
                confidence=0.9,
                source="training",
                examples=[],
                related_concepts=[],
                prerequisites=[],
                created_at=datetime.now(timezone.utc).isoformat(),
                updated_at=datetime.now(timezone.utc).isoformat(),
                access_count=5,
                last_accessed=datetime.now(timezone.utc).isoformat(),
            )
        ]

        adapter = SemanticMemoryAdapter(mock_memory)
        assert adapter.is_available()

        results = adapter.retrieve_candidates(RetrievalQuery(query="singleton"))
        assert len(results) == 1
        assert results[0].source_type == KnowledgeSourceType.SEMANTIC_MEMORY
        assert "singleton" in results[0].content.lower()

    def test_vector_search_adapter(self):
        """Test vector search adapter with mock."""
        mock_vector_db = Mock()
        mock_vector_db.is_empty.return_value = False
        mock_vector_db.embedding_dim = 128
        mock_vector_db.search.return_value = [
            (1, 0.9, {"content": "Test content", "title": "Test Title"}),
        ]

        adapter = VectorSearchAdapter(vector_db=mock_vector_db)
        assert adapter.is_available()

        results = adapter.retrieve_candidates(RetrievalQuery(query="test"))
        assert len(results) == 1
        assert results[0].source_type == KnowledgeSourceType.VECTOR_SEARCH
        assert results[0].content == "Test content"
        assert results[0].title == "Test Title"
        assert results[0].raw_confidence == 0.9

        # Test when vector_db is empty
        mock_vector_db.is_empty.return_value = True
        assert not adapter.is_available()
        assert adapter.retrieve_candidates(RetrievalQuery(query="test")) == []


class TestConvenienceFunctions:
    """Test convenience functions."""

    def test_create_pipeline_from_agent(self):
        """Test creating pipeline from agent."""
        mock_agent = Mock()
        mock_agent.semantic_memory = Mock()
        mock_agent.semantic_memory.is_empty.return_value = False

        pipeline = create_pipeline_from_agent(mock_agent)
        assert isinstance(pipeline, KnowledgeRetrievalPipeline)
        assert len(pipeline._adapters) >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])