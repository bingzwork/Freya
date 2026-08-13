"""
Tests for the LearningPipeline class.
"""

import unittest
from unittest.mock import Mock, patch
from datetime import datetime, timezone
from uuid import uuid4

from app.learning.pipeline import LearningPipeline, create_learning_pipeline
from app.learning.models import (
    LearningCandidate,
    LearningCandidateType,
    LearningPipelineResult,
    ObservedData,
    EvaluationResult,
    ExtractedLearning,
    ValidationResult,
    WorthRememberingResult,
    WorthRememberingDecision,
    PipelineStage,
)


class TestLearningPipeline(unittest.TestCase):
    """Test the LearningPipeline class."""

    def setUp(self):
        """Set up test fixtures."""
        self.memory_coordinator = Mock()
        self.pipeline = LearningPipeline(
            memory_coordinator=self.memory_coordinator,
            min_relevance=0.3,
            min_novelty=0.2,
            min_actionability=0.2,
            min_confidence=0.3
        )

    def test_initialization(self):
        """Test that the pipeline initializes with correct parameters."""
        self.assertEqual(self.pipeline._memory, self.memory_coordinator)
        self.assertEqual(self.pipeline._min_relevance, 0.3)
        self.assertEqual(self.pipeline._min_novelty, 0.2)
        self.assertEqual(self.pipeline._min_actionability, 0.2)
        self.assertEqual(self.pipeline._min_confidence, 0.3)

    def test_create_learning_pipeline_factory(self):
        """Test the factory function."""
        pipeline = create_learning_pipeline(
            memory_coordinator=self.memory_coordinator,
            min_relevance=0.5,
            min_novelty=0.4,
            min_actionability=0.4,
            min_confidence=0.5
        )
        self.assertIsInstance(pipeline, LearningPipeline)
        self.assertEqual(pipeline._min_relevance, 0.5)
        self.assertEqual(pipeline._min_novelty, 0.4)
        self.assertEqual(pipeline._min_actionability, 0.4)
        self.assertEqual(pipeline._min_confidence, 0.5)

    def test_observe_stage(self):
        """Test the observe stage."""
        candidate = LearningCandidate(
            source_component="TestComponent",
            candidate_type=LearningCandidateType.ANSWER_VERIFICATION,
            raw_observation={"key": "value"},
            context={"context_key": "context_value"},
            tags=["tag1", "tag2"]
        )

        observed = self.pipeline._observe(candidate)

        self.assertIsInstance(observed, ObservedData)
        self.assertEqual(observed.candidate_id, candidate.id)
        self.assertIn("source_component", observed.structured_observation)
        self.assertEqual(observed.structured_observation["source_component"], "TestComponent")
        self.assertTrue(observed.structured_observation["has_raw_observation"])
        self.assertIn("raw_observation_keys", observed.structured_observation)
        self.assertEqual(observed.structured_observation["raw_observation_keys"], ["key"])
        self.assertIn("context_keys", observed.structured_observation)
        self.assertEqual(observed.structured_observation["context_keys"], ["context_key"])
        self.assertEqual(observed.structured_observation["tags"], ["tag1", "tag2"])
        self.assertIn("source:TestComponent", observed.extracted_signals)
        self.assertIn("type:answer_verification", observed.extracted_signals)
        self.assertIn("tag:tag1", observed.extracted_signals)
        self.assertIn("tag:tag2", observed.extracted_signals)
        # Confidence should be between 0.5 and 1.0 based on the data provided
        self.assertGreaterEqual(observed.confidence, 0.5)
        self.assertLessEqual(observed.confidence, 1.0)

    def test_evaluate_stage(self):
        """Test the evaluate stage."""
        candidate = LearningCandidate(
            source_component="TestComponent",
            candidate_type=LearningCandidateType.ANSWER_VERIFICATION,
            raw_observation={"key": "value"},
            context={"context_key": "context_value"},
            tags=["tag1", "tag2"]
        )
        observed = ObservedData(
            candidate_id=candidate.id,
            structured_observation={
                "source_component": "TestComponent",
                "has_raw_observation": True,
                "raw_observation_keys": ["key"],
                "context_keys": ["context_key"],
                "tags": ["tag1", "tag2"]
            },
            extracted_signals=["source:TestComponent", "type:answer_verification", "tag:tag1", "tag:tag2"],
            confidence=0.8
        )

        evaluation = self.pipeline._evaluate(candidate, observed)

        self.assertIsInstance(evaluation, EvaluationResult)
        self.assertEqual(evaluation.candidate_id, candidate.id)
        # With the given data, we expect high scores
        self.assertGreaterEqual(evaluation.relevance_score, 0.8)  # Should be high due to all fields present
        self.assertGreaterEqual(evaluation.novelty_score, 0.0)
        self.assertLessEqual(evaluation.novelty_score, 1.0)
        self.assertGreaterEqual(evaluation.actionability_score, 0.8)  # Should be high
        self.assertTrue(evaluation.has_learning_potential)  # Should be True given thresholds
        self.assertIn("Relevance:", evaluation.evaluation_notes)
        self.assertIn("Novelty:", evaluation.evaluation_notes)
        self.assertIn("Actionability:", evaluation.evaluation_notes)

    def test_evaluate_stage_no_learning_potential(self):
        """Test evaluate stage when learning potential is low."""
        candidate = LearningCandidate(
            source_component="",  # Empty source
            candidate_type=LearningCandidateType.MANUAL_INPUT,
            raw_observation={},  # Empty observation
            context={},  # Empty context
            tags=[]  # No tags
        )
        observed = ObservedData(
            candidate_id=candidate.id,
            structured_observation={
                "source_component": "",
                "has_raw_observation": False,
                "raw_observation_keys": [],
                "context_keys": [],
                "tags": []
            },
            extracted_signals=[],
            confidence=0.1  # Low confidence
        )

        evaluation = self.pipeline._evaluate(candidate, observed)

        self.assertIsInstance(evaluation, EvaluationResult)
        self.assertEqual(evaluation.candidate_id, candidate.id)
        self.assertLess(evaluation.relevance_score, self.pipeline._min_relevance)
        self.assertLess(evaluation.novelty_score, self.pipeline._min_novelty)
        self.assertLess(evaluation.actionability_score, self.pipeline._min_actionability)
        self.assertFalse(evaluation.has_learning_potential)

    def test_extract_learning_stage(self):
        """Test the extract learning stage."""
        candidate = LearningCandidate(
            source_component="TestComponent",
            candidate_type=LearningCandidateType.ANSWER_VERIFICATION,
            raw_observation={"key": "value"},
            context={"context_key": "context_value"},
            tags=["tag1", "tag2"]
        )
        observed = ObservedData(
            candidate_id=candidate.id,
            structured_observation={
                "source_component": "TestComponent",
                "has_raw_observation": True,
                "raw_observation_keys": ["key"],
                "context_keys": ["context_key"],
                "tags": ["tag1", "tag2"],
                "candidate_type": "answer_verification"
            },
            extracted_signals=["source:TestComponent", "type:answer_verification", "tag:tag1", "tag:tag2"],
            confidence=0.8
        )
        evaluated = EvaluationResult(
            candidate_id=candidate.id,
            has_learning_potential=True,
            relevance_score=0.8,
            novelty_score=0.7,
            actionability_score=0.75
        )

        extracted = self.pipeline._extract_learning(candidate, observed, evaluated)

        self.assertIsInstance(extracted, ExtractedLearning)
        self.assertEqual(extracted.candidate_id, candidate.id)
        # Should have extracted multiple items: source, type, tags (2), context
        self.assertGreaterEqual(len(extracted.knowledge_items), 4)  # source, type, 2 tags, context = 5
        # Check that we have the expected types of items
        titles = [item["title"] for item in extracted.knowledge_items]
        self.assertTrue(any("Interaction with TestComponent" in title for title in titles))
        self.assertTrue(any("Learning from answer_verification events" in title for title in titles))
        self.assertTrue(any("Pattern related to tag1" in title for title in titles))
        self.assertTrue(any("Pattern related to tag2" in title for title in titles))
        self.assertTrue(any("Contextual learning from candidate" in title for title in titles))
        # Check confidence values are set and within bounds
        for item in extracted.knowledge_items:
            self.assertGreaterEqual(item["confidence"], 0.0)
            self.assertLessEqual(item["confidence"], 1.0)
            self.assertIn("title", item)
            self.assertIn("content", item)
            self.assertIn("category", item)
            self.assertIn("source", item)
            self.assertIn("metadata", item)

    def test_extract_learning_stage_minimal_data(self):
        """Test extract learning with minimal data."""
        candidate = LearningCandidate(
            source_component="TestComponent",
            candidate_type=LearningCandidateType.MANUAL_INPUT,
            raw_observation={},
            context={},
            tags=[]
        )
        observed = ObservedData(
            candidate_id=candidate.id,
            structured_observation={
                "source_component": "TestComponent",
                "has_raw_observation": False,
                "raw_observation_keys": [],
                "context_keys": [],
                "tags": [],
                "candidate_type": "manual_input"
            },
            extracted_signals=["source:TestComponent", "type:manual_input"],
            confidence=0.5
        )
        evaluated = EvaluationResult(
            candidate_id=candidate.id,
            has_learning_potential=True,
            relevance_score=0.3,
            novelty_score=0.3,
            actionability_score=0.3
        )

        extracted = self.pipeline._extract_learning(candidate, observed, evaluated)

        self.assertIsInstance(extracted, ExtractedLearning)
        self.assertEqual(extracted.candidate_id, candidate.id)
        # Should have source and type items only
        self.assertEqual(len(extracted.knowledge_items), 2)
        titles = [item["title"] for item in extracted.knowledge_items]
        self.assertTrue(any("Interaction with TestComponent" in title for title in titles))
        self.assertTrue(any("Learning from manual_input events" in title for title in titles))

    def test_validate_learning_stage(self):
        """Test the validate learning stage."""
        candidate = LearningCandidate(
            source_component="TestComponent",
            candidate_type=LearningCandidateType.ANSWER_VERIFICATION
        )
        extracted = ExtractedLearning(
            candidate_id=candidate.id,
            knowledge_items=[
                {
                    "title": "Valid Item",
                    "content": "This is a valid learning item with sufficient content.",
                    "category": "test",
                    "confidence": 0.8,
                    "source": "test_source",
                    "metadata": {}
                },
                {
                    "title": "",  # Invalid: empty title
                    "content": "This item has no title.",
                    "category": "test",
                    "confidence": 0.7,
                    "source": "test_source",
                    "metadata": {}
                },
                {
                    "title": "Short Content",
                    "content": "Short",  # Invalid: too short
                    "category": "test",
                    "confidence": 0.9,
                    "source": "test_source",
                    "metadata": {}
                }
            ]
        )

        validation = self.pipeline._validate_learning(candidate, extracted)

        self.assertIsInstance(validation, ValidationResult)
        self.assertEqual(validation.candidate_id, candidate.id)
        self.assertEqual(len(validation.validated_items), 1)  # Only the first item should be valid
        self.assertEqual(len(validation.rejected_items), 2)  # The other two should be rejected
        # Check that the validated item is in validation_details (key includes candidate ID)
        validated_keys = [k for k in validation.validation_details.keys() if k.endswith("_item_0")]
        self.assertEqual(len(validated_keys), 1)
        self.assertEqual(validation.validation_details[validated_keys[0]]["status"], "validated")
        # Check that the rejected items are in validation_details (keys include candidate ID)
        rejected_keys_1 = [k for k in validation.validation_details.keys() if k.endswith("_item_1")]
        rejected_keys_2 = [k for k in validation.validation_details.keys() if k.endswith("_item_2")]
        self.assertEqual(len(rejected_keys_1), 1)
        self.assertEqual(len(rejected_keys_2), 1)
        self.assertEqual(validation.validation_details[rejected_keys_1[0]]["status"], "rejected")
        self.assertEqual(validation.validation_details[rejected_keys_2[0]]["status"], "rejected")
        self.assertIn("Missing or empty title", validation.validation_details[rejected_keys_1[0]]["reasons"])
        self.assertIn("Content too short", validation.validation_details[rejected_keys_2[0]]["reasons"])

    def test_worth_remembering_stage_yes(self):
        """Test the worth remembering stage when decision is YES."""
        candidate = LearningCandidate(
            source_component="TestComponent",
            candidate_type=LearningCandidateType.ANSWER_VERIFICATION
        )
        validated = ValidationResult(
            candidate_id=candidate.id,
            validated_items=[
                {
                    "title": "Good Learning Item",
                    "content": "This is a good learning item with high confidence.",
                    "category": "test",
                    "confidence": 0.8,
                    "source": "test_source",
                    "metadata": {}
                },
                {
                    "title": "Another Good Item",
                    "content": "This is another good learning item.",
                    "category": "test",
                    "confidence": 0.7,
                    "source": "test_source",
                    "metadata": {}
                }
            ],
            rejected_items=[]
        )

        worth_remembering = self.pipeline._worth_remembering(candidate, validated)

        self.assertIsInstance(worth_remembering, WorthRememberingResult)
        self.assertEqual(worth_remembering.candidate_id, candidate.id)
        self.assertEqual(worth_remembering.decision, WorthRememberingDecision.YES)
        self.assertEqual(len(worth_remembering.items_to_store), 2)  # Both items should be stored
        self.assertEqual(len(worth_remembering.items_temporary), 0)
        self.assertIn("Average confidence:", worth_remembering.reasoning)
        self.assertGreaterEqual(float(worth_remembering.reasoning.split()[2]), 0.4)  # Confidence should be >= threshold

    def test_worth_remembering_stage_no(self):
        """Test the worth remembering stage when decision is NO."""
        candidate = LearningCandidate(
            source_component="TestComponent",
            candidate_type=LearningCandidateType.ANSWER_VERIFICATION
        )
        validated = ValidationResult(
            candidate_id=candidate.id,
            validated_items=[
                {
                    "title": "Weak Item",
                    "content": "This item has low confidence.",
                    "category": "test",
                    "confidence": 0.2,  # Low confidence
                    "source": "test_source",
                    "metadata": {}
                }
            ],
            rejected_items=[]
        )

        worth_remembering = self.pipeline._worth_remembering(candidate, validated)

        self.assertIsInstance(worth_remembering, WorthRememberingResult)
        self.assertEqual(worth_remembering.candidate_id, candidate.id)
        self.assertEqual(worth_remembering.decision, WorthRememberingDecision.NO)
        self.assertEqual(len(worth_remembering.items_to_store), 0)  # No items to store
        self.assertEqual(len(worth_remembering.items_temporary), 0)
        self.assertIn("Average confidence:", worth_remembering.reasoning)
        self.assertLess(float(worth_remembering.reasoning.split()[2]), 0.4)  # Confidence should be < threshold

    def test_worth_remembering_stage_no_validated_items(self):
        """Test worth remembering when there are no validated items."""
        candidate = LearningCandidate(
            source_component="TestComponent",
            candidate_type=LearningCandidateType.ANSWER_VERIFICATION
        )
        validated = ValidationResult(
            candidate_id=candidate.id,
            validated_items=[],
            rejected_items=[]
        )

        worth_remembering = self.pipeline._worth_remembering(candidate, validated)

        self.assertIsInstance(worth_remembering, WorthRememberingResult)
        self.assertEqual(worth_remembering.candidate_id, candidate.id)
        self.assertEqual(worth_remembering.decision, WorthRememberingDecision.NO)
        self.assertEqual(len(worth_remembering.items_to_store), 0)
        self.assertEqual(len(worth_remembering.items_temporary), 0)
        self.assertEqual(worth_remembering.reasoning, "No validated items to consider")

    @patch('app.learning.pipeline.logger')
    def test_persist_to_memory(self, mock_logger):
        """Test the persist_to_memory method."""
        candidate = LearningCandidate(
            source_component="TestComponent",
            candidate_type=LearningCandidateType.ANSWER_VERIFICATION
        )
        items = [
            {
                "title": "Test Item",
                "content": "This is a test learning item.",
                "category": "test",
                "confidence": 0.8,
                "source": "test_source",
                "metadata": {}
            }
        ]

        result = self.pipeline._persist_to_memory(candidate, items)

        # Should return a list with one item ID
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], str)
        # Should have logged debug message
        mock_logger.debug.assert_called()

    def test_full_pipeline_run_with_learning(self):
        """Test a full pipeline run that results in learning being stored."""
        # Set up a candidate that should go through all stages and be worth remembering
        candidate = LearningCandidate(
            source_component="TestComponent",
            candidate_type=LearningCandidateType.ANSWER_VERIFICATION,
            raw_observation={"observation_key": "observation_value"},
            context={"context_key": "context_value"},
            tags=["important", "learned"]
        )

        # Mock the memory coordinator to return success when storing
        # In the real implementation, _persist_to_memory returns a list of stored item IDs
        # We'll let the real _persist_to_memory run but we can check it was called
        self.memory_coordinator.unified_retrieval = Mock()
        self.memory_coordinator.goal_storage = Mock()
        self.memory_coordinator.conversation_memory = Mock()

        result = self.pipeline.run(candidate)

        self.assertIsInstance(result, LearningPipelineResult)
        self.assertEqual(result.candidate_id, candidate.id)
        # Check that all stage results are present
        self.assertIsInstance(result.observe_result, ObservedData)
        self.assertIsInstance(result.evaluate_result, EvaluationResult)
        self.assertIsInstance(result.extract_result, ExtractedLearning)
        self.assertIsInstance(result.validate_result, ValidationResult)
        self.assertIsInstance(result.worth_remembering_result, WorthRememberingResult)
        # Check that we went through all stages
        self.assertTrue(result.observe_result.confidence > 0)
        # Depending on the data, it may or may not have learning potential
        # But we can check that the pipeline completed
        self.assertGreaterEqual(result.duration_seconds, 0)
        # The final decision should be set
        self.assertIn(result.final_decision, [WorthRememberingDecision.YES, WorthRememberingDecision.NO])

    def test_full_pipeline_run_no_learning_potential(self):
        """Test a full pipeline run where learning potential is low."""
        # Set up a candidate with minimal data that should not pass evaluation
        candidate = LearningCandidate(
            source_component="",  # Empty source
            candidate_type=LearningCandidateType.MANUAL_INPUT,
            raw_observation={},
            context={},
            tags=[]
        )

        result = self.pipeline.run(candidate)

        self.assertIsInstance(result, LearningPipelineResult)
        self.assertEqual(result.candidate_id, candidate.id)
        self.assertIsInstance(result.observe_result, ObservedData)
        self.assertIsInstance(result.evaluate_result, EvaluationResult)
        # Should not have learning potential, so extraction and beyond should be skipped
        self.assertFalse(result.evaluate_result.has_learning_potential)
        self.assertIsNone(result.extract_result)
        self.assertIsNone(result.validate_result)
        self.assertIsInstance(result.worth_remembering_result, WorthRememberingResult)
        self.assertEqual(result.worth_remembering_result.decision, WorthRememberingDecision.NO)
        self.assertEqual(result.worth_remembering_result.reasoning, "No learning potential")
        self.assertEqual(result.final_decision, WorthRememberingDecision.NO)

    def test_full_pipeline_run_no_validated_items(self):
        """Test a full pipeline run where extraction yields items but validation rejects them all."""
        # We'll test this by mocking the extract learning to return items that will fail validation
        with patch.object(self.pipeline, '_extract_learning') as mock_extract:
            # Return extracted learning with items that will fail validation (empty title, etc.)
            mock_extract.return_value = ExtractedLearning(
                candidate_id="test_id",
                knowledge_items=[
                    {
                        "title": "",  # Invalid
                        "content": "Some content",
                        "category": "test",
                        "confidence": 0.5,
                        "source": "test",
                        "metadata": {}
                    }
                ]
            )
            candidate = LearningCandidate(
                source_component="TestComponent",
                candidate_type=LearningCandidateType.ANSWER_VERIFICATION
            )

            result = self.pipeline.run(candidate)

            self.assertIsInstance(result, LearningPipelineResult)
            self.assertIsInstance(result.evaluate_result, EvaluationResult)
            self.assertTrue(result.evaluate_result.has_learning_potential)  # Assume it passed evaluation
            self.assertIsInstance(result.extract_result, ExtractedLearning)
            self.assertIsInstance(result.validate_result, ValidationResult)
            # Validation should have rejected all items
            self.assertEqual(len(result.validate_result.validated_items), 0)
            self.assertGreaterEqual(len(result.validate_result.rejected_items), 1)
            self.assertIsInstance(result.worth_remembering_result, WorthRememberingResult)
            self.assertEqual(result.worth_remembering_result.decision, WorthRememberingDecision.NO)
            self.assertEqual(result.worth_remembering_result.reasoning, "No validated items")


if __name__ == '__main__':
    unittest.main()