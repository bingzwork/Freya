"""Test Knowledge Validation implementation."""

import tempfile
import shutil
from pathlib import Path

from app.memory.validation import (
    KnowledgeValidator,
    ValidationConfig,
    ValidationSource,
    ValidationSourceType,
    ConflictType,
    ValidationStatus,
    StorageDecision,
    ConfidenceThresholds,
    create_knowledge_validator,
    create_source_from_documentation,
    create_source_from_code,
    create_source_from_user,
    create_source_from_community,
    create_source_from_llm,
)
from app.memory.semantic_memory import SemanticMemory, create_semantic_memory
from app.memory.experience_memory import ExperienceMemory
from app.memory.engineering_lessons import EngineeringLessonStorage
from app.memory.long_term_memory import LongTermMemory, create_long_term_memory
from app.memory.cross_references import CrossMemoryReferences, create_cross_memory_references


def test_basic_validation():
    """Test basic validation flow."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Setup memory systems
        semantic = create_semantic_memory(tmpdir)
        experience = ExperienceMemory(tmpdir, f"{tmpdir}/experience.json")
        lessons = EngineeringLessonStorage(tmpdir, f"{tmpdir}/lessons.json")
        ltm = create_long_term_memory(tmpdir, f"{tmpdir}/ltm.json", max_entries=1000)
        cross_refs = create_cross_memory_references(f"{tmpdir}/cross_refs.json")

        # Add some existing knowledge
        semantic.set(
            category="best_practice",
            title="Use context managers for file I/O",
            content="Always use 'with' statements for file I/O operations to ensure proper resource cleanup and exception safety.",
            confidence=0.9,
            source="documentation",
        )

        # Create validator
        validator = create_knowledge_validator(
            semantic_memory=semantic,
            experience_memory=experience,
            engineering_lessons=lessons,
            long_term_memory=ltm,
            cross_refs=cross_refs,
        )

        # Create sources
        sources = [
            create_source_from_documentation(
                "https://docs.python.org/3/library/stdtypes.html#context-manager-types",
                "Python's context managers provide a way to allocate and release resources precisely. Always use 'with' statements for file I/O operations to ensure proper resource cleanup and exception safety.",
            ),
            create_source_from_code(
                "/path/to/example.py",
                "with open('file.txt') as f:\n    content = f.read()\n# Always use with statements for file I/O operations to ensure proper resource cleanup and exception safety",
            ),
        ]

        # Validate
        result = validator.validate(
            knowledge_id="test_001",
            title="Use context managers for file I/O",
            content="Always use 'with' statements for file I/O operations to ensure proper resource cleanup and exception safety.",
            category="best_practice",
            sources=sources,
        )

        print(f"Validation ID: {result.validation_id}")
        print(f"Title: {result.title}")
        print(f"Overall Confidence: {result.overall_confidence:.2%}")
        print(f"Validation Status: {result.validation_status.value}")
        print(f"Storage Decision: {result.storage_decision.value}")
        print(f"Sources: {len(result.sources)}")
        print(f"Cross-refs: {len(result.cross_references)}")
        print(f"Conflicts: {len(result.conflicts)}")
        print(f"Source Reliability: {result.source_reliability_score:.2f}")
        print(f"Agreement Score: {result.agreement_score:.2f}")
        print(f"Freshness Score: {result.freshness_score:.2f}")
        print(f"KB Consistency: {result.kb_consistency_score:.2f}")
        print(f"\nNotes:\n{result.validation_notes}")

        # Assertions
        assert result.overall_confidence > 0.8, f"Expected high confidence, got {result.overall_confidence}"
        assert result.validation_status in [ValidationStatus.VALIDATED, ValidationStatus.HIGH_CONFIDENCE]
        assert result.storage_decision == StorageDecision.AUTO_STORE
        assert len(result.cross_references) > 0, "Should cross-reference existing semantic memory"

        print("\n== Basic validation test passed!")
        return True


def test_conflict_detection():
    """Test conflict detection between sources."""
    with tempfile.TemporaryDirectory() as tmpdir:
        semantic = create_semantic_memory(tmpdir)
        experience = ExperienceMemory(tmpdir, f"{tmpdir}/experience.json")
        lessons = EngineeringLessonStorage(tmpdir, f"{tmpdir}/lessons.json")
        ltm = create_long_term_memory(tmpdir, f"{tmpdir}/ltm.json", max_entries=1000)
        cross_refs = create_cross_memory_references(f"{tmpdir}/cross_refs.json")

        validator = create_knowledge_validator(
            semantic_memory=semantic,
            experience_memory=experience,
            engineering_lessons=lessons,
            long_term_memory=ltm,
            cross_refs=cross_refs,
        )

        # Two sources that disagree on the same topic - make first 100 chars nearly identical
        # but overall content different enough
        sources = [
            create_source_from_documentation(
                "https://old-docs.example.com/python-style",
                "Python indentation style guide: The official recommendation is 2 spaces for indentation based on historical conventions. This older style guide emphasizes compact code layout.",
            ),
            create_source_from_code(
                "/path/to/test.py",
                "Python indentation style guide: The official recommendation is 4 spaces for indentation per PEP 8 standard. PEP 8 explicitly states 4 spaces as the standard for all Python code.",
            ),
        ]

        result = validator.validate(
            knowledge_id="test_002",
            title="Python indentation style",
            content="Python uses 4 spaces for indentation per PEP 8.",
            category="language_rule",
            sources=sources,
        )

        print(f"\nConflict Detection Test:")
        print(f"Overall Confidence: {result.overall_confidence:.2%}")
        print(f"Validation Status: {result.validation_status.value}")
        print(f"Storage Decision: {result.storage_decision.value}")
        print(f"Conflicts: {len(result.conflicts)}")
        for c in result.conflicts:
            print(f"  - {c.conflict_type.value}: {c.description} (severity: {c.severity:.2f})")

        assert len(result.conflicts) > 0, "Should detect conflict between 2-space and 4-space sources"
        # Accept either SOURCES_DISAGREE or DOCS_VS_SOURCE_CODE as valid conflict detection
        assert any(c.conflict_type in [ConflictType.SOURCES_DISAGREE, ConflictType.DOCS_VS_SOURCE_CODE] for c in result.conflicts)
        assert result.storage_decision in [StorageDecision.MANUAL_REVIEW, StorageDecision.REJECT]

        print("== Conflict detection test passed!")
        return True


def test_single_low_confidence_source():
    """Test validation with single low-confidence source."""
    with tempfile.TemporaryDirectory() as tmpdir:
        semantic = create_semantic_memory(tmpdir)
        experience = ExperienceMemory(tmpdir, f"{tmpdir}/experience.json")
        lessons = EngineeringLessonStorage(tmpdir, f"{tmpdir}/lessons.json")
        ltm = create_long_term_memory(tmpdir, f"{tmpdir}/ltm.json", max_entries=1000)
        cross_refs = create_cross_memory_references(f"{tmpdir}/cross_refs.json")

        validator = create_knowledge_validator(
            semantic_memory=semantic,
            experience_memory=experience,
            engineering_lessons=lessons,
            long_term_memory=ltm,
            cross_refs=cross_refs,
        )

        # Single blog article source
        sources = [
            ValidationSource(
                source_type=ValidationSourceType.SINGLE_ARTICLE_BLOG,
                identifier="https://blog.example.com/python-tips",
                content="Python's new pattern matching feature makes switch statements obsolete. Pattern matching in Python 3.10+ replaces traditional switch statements.",
                confidence=0.6,
            ),
        ]

        result = validator.validate(
            knowledge_id="test_003",
            title="Python pattern matching vs switch",
            content="Python 3.10+ pattern matching replaces traditional switch statements.",
            category="language_rule",
            sources=sources,
        )

        print(f"\nLow Confidence Source Test:")
        print(f"Overall Confidence: {result.overall_confidence:.2%}")
        print(f"Validation Status: {result.validation_status.value}")
        print(f"Storage Decision: {result.storage_decision.value}")

        assert result.overall_confidence < 0.7, "Should have low confidence from single blog source"
        assert result.storage_decision in [StorageDecision.DELAY_STORE, StorageDecision.MANUAL_REVIEW, StorageDecision.REJECT]

        print("== Low confidence source test passed!")
        return True


def test_user_provided_high_confidence():
    """Test user-provided knowledge gets high confidence."""
    with tempfile.TemporaryDirectory() as tmpdir:
        semantic = create_semantic_memory(tmpdir)
        experience = ExperienceMemory(tmpdir, f"{tmpdir}/experience.json")
        lessons = EngineeringLessonStorage(tmpdir, f"{tmpdir}/lessons.json")
        ltm = create_long_term_memory(tmpdir, f"{tmpdir}/ltm.json", max_entries=1000)
        cross_refs = create_cross_memory_references(f"{tmpdir}/cross_refs.json")

        validator = create_knowledge_validator(
            semantic_memory=semantic,
            experience_memory=experience,
            engineering_lessons=lessons,
            long_term_memory=ltm,
            cross_refs=cross_refs,
        )

        # Use multiple user sources to boost agreement
        sources = [
            create_source_from_user("Our team uses 4-space indentation and type hints everywhere."),
            create_source_from_user("Team standard: 4-space indentation, mandatory type hints for all functions."),
        ]

        result = validator.validate(
            knowledge_id="test_004",
            title="Team coding standards",
            content="Team standard: 4-space indentation, mandatory type hints for all functions.",
            category="convention",
            sources=sources,
        )

        print(f"\nUser Provided Test:")
        print(f"Overall Confidence: {result.overall_confidence:.2%}")
        print(f"Validation Status: {result.validation_status.value}")
        print(f"Storage Decision: {result.storage_decision.value}")

        assert result.overall_confidence > 0.8, "User-provided should have high confidence"
        assert result.storage_decision == StorageDecision.AUTO_STORE

        print("== User provided high confidence test passed!")
        return True


def test_kb_consistency():
    """Test consistency checking with existing knowledge base."""
    with tempfile.TemporaryDirectory() as tmpdir:
        semantic = create_semantic_memory(tmpdir)
        experience = ExperienceMemory(tmpdir, f"{tmpdir}/experience.json")
        lessons = EngineeringLessonStorage(tmpdir, f"{tmpdir}/lessons.json")
        ltm = create_long_term_memory(tmpdir, f"{tmpdir}/ltm.json", max_entries=1000)
        cross_refs = create_cross_memory_references(f"{tmpdir}/cross_refs.json")

        # Add existing knowledge that contradicts new info
        # The entry will get an ID like "best_practice.always_use_async_await"
        existing_entry = semantic.set(
            category="best_practice",
            title="Always use async/await for I/O",
            content="All I/O operations must use async/await for better concurrency. Synchronous I/O should be avoided.",
            confidence=0.9,
            source="documentation",
        )

        validator = create_knowledge_validator(
            semantic_memory=semantic,
            experience_memory=experience,
            engineering_lessons=lessons,
            long_term_memory=ltm,
            cross_refs=cross_refs,
        )

        # New knowledge that contradicts
        sources = [
            create_source_from_documentation(
                "https://new-docs.example.com",
                "Synchronous I/O is preferred for simplicity in most cases. Use async only when concurrency is required. Avoid async/await for simple I/O.",
            ),
        ]

        result = validator.validate(
            knowledge_id="test_005",
            title="Always use async/await for I/O",
            content="Synchronous I/O is simpler and preferred for most use cases. Only use async when concurrency is required. Avoid async/await for simple I/O.",
            category="best_practice",
            sources=sources,
        )

        print(f"\nKB Consistency Test:")
        print(f"Overall Confidence: {result.overall_confidence:.2%}")
        print(f"KB Consistency Score: {result.kb_consistency_score:.2f}")
        print(f"Validation Status: {result.validation_status.value}")
        print(f"Conflicts: {len(result.conflicts)}")
        for c in result.conflicts:
            print(f"  - {c.conflict_type.value}: {c.description}")

        assert result.kb_consistency_score < 1.0, "Should detect inconsistency with KB"
        assert len(result.conflicts) > 0, "Should flag KB contradiction"

        print("== KB consistency test passed!")
        return True


def test_validation_metadata_persistence():
    """Test that validation results are persisted."""
    with tempfile.TemporaryDirectory() as tmpdir:
        semantic = create_semantic_memory(tmpdir)
        experience = ExperienceMemory(tmpdir, f"{tmpdir}/experience.json")
        lessons = EngineeringLessonStorage(tmpdir, f"{tmpdir}/lessons.json")
        ltm = create_long_term_memory(tmpdir, f"{tmpdir}/ltm.json", max_entries=1000)
        cross_refs = create_cross_memory_references(f"{tmpdir}/cross_refs.json")

        validator1 = create_knowledge_validator(
            semantic_memory=semantic,
            experience_memory=experience,
            engineering_lessons=lessons,
            long_term_memory=ltm,
            cross_refs=cross_refs,
        )

        sources = [create_source_from_user("Test knowledge for persistence.")]
        result = validator1.validate(
            knowledge_id="test_006",
            title="Persistence Test",
            content="This knowledge should persist across validator instances.",
            category="fact",
            sources=sources,
        )
        validation_id = result.validation_id

        # Create new validator instance (simulates restart)
        validator2 = create_knowledge_validator(
            semantic_memory=semantic,
            experience_memory=experience,
            engineering_lessons=lessons,
            long_term_memory=ltm,
            cross_refs=cross_refs,
        )

        loaded = validator2.get_validation_result(validation_id)
        assert loaded is not None, "Validation result should be persisted"
        assert loaded.knowledge_item_id == "test_006"
        assert loaded.title == "Persistence Test"

        print("== Validation metadata persistence test passed!")
        return True


def test_approval_workflow():
    """Test manual review approval workflow."""
    with tempfile.TemporaryDirectory() as tmpdir:
        semantic = create_semantic_memory(tmpdir)
        experience = ExperienceMemory(tmpdir, f"{tmpdir}/experience.json")
        lessons = EngineeringLessonStorage(tmpdir, f"{tmpdir}/lessons.json")
        ltm = create_long_term_memory(tmpdir, f"{tmpdir}/ltm.json", max_entries=1000)
        cross_refs = create_cross_memory_references(f"{tmpdir}/cross_refs.json")

        validator = create_knowledge_validator(
            semantic_memory=semantic,
            experience_memory=experience,
            engineering_lessons=lessons,
            long_term_memory=ltm,
            cross_refs=cross_refs,
        )

        # Create validation that requires manual review (medium confidence ~0.75)
        sources = [
            create_source_from_llm(
                "Claude-3-Opus",
                "This approach works but has edge cases that need careful handling.",
                confidence=0.8,
            ),
        ]

        result = validator.validate(
            knowledge_id="test_007",
            title="Edge case handling",
            content="Handle edge cases with try/except blocks around the main logic.",
            category="error_handling",
            sources=sources,
        )

        print(f"\nBefore approval: {result.storage_decision.value}, {result.validation_status.value}")
        assert result.storage_decision == StorageDecision.MANUAL_REVIEW

        # Approve
        success = validator.approve_validation(result.validation_id, "test_user")
        assert success

        approved = validator.get_validation_result(result.validation_id)
        print(f"After approval: {approved.storage_decision.value}, {approved.validation_status.value}")
        assert approved.storage_decision == StorageDecision.AUTO_STORE
        assert approved.validation_status == ValidationStatus.VALIDATED
        assert approved.reviewer == "test_user"

        print("== Approval workflow test passed!")
        return True


def run_all_tests():
    """Run all validation tests."""
    print("=" * 60)
    print("Running Knowledge Validation Tests")
    print("=" * 60)

    tests = [
        test_basic_validation,
        test_conflict_detection,
        test_single_low_confidence_source,
        test_user_provided_high_confidence,
        test_kb_consistency,
        test_validation_metadata_persistence,
        test_approval_workflow,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"\nXX {test.__name__} FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)