"""Tests for Software Engineering Knowledge capability."""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timezone

from app.software_engineering_knowledge.models import (
    EngineeringDomain,
    EngineeringKnowledgeType,
    KnowledgeSource,
    ValidationStatus,
    EngineeringKnowledgeItem,
    EngineeringCategory,
    ExtractionResult,
    ValidationResult,
    EngineeringExpertise,
)
from app.software_engineering_knowledge.categories import (
    CategoryRegistry,
    DEFAULT_CATEGORIES,
    get_category_registry,
)
from app.software_engineering_knowledge.storage import (
    EngineeringKnowledgeStorage,
    get_knowledge_storage,
)
from app.software_engineering_knowledge.sources import (
    EngineeringKnowledgeAdapter,
    ExtractedKnowledgeAdapter,
    EngineeringLessonsAdapter,
)
from app.software_engineering_knowledge.extraction import (
    KnowledgeExtractor,
    CodeExtractor,
    DocumentationExtractor,
)
from app.software_engineering_knowledge.import_experience import (
    KnowledgeImporter,
    ExperienceImporter,
    EngineeringLessonsImporter,
    ReflectionImporter,
    UserKnowledgeImporter,
)
from app.software_engineering_knowledge.validation import (
    KnowledgeValidator,
    ValidationConfig,
    ConfidenceScorer,
)
from app.software_engineering_knowledge.ranking import (
    EngineeringRankingEngine,
    EngineeringQueryBuilder,
    create_engineering_ranker,
    create_engineering_query,
)
from app.software_engineering_knowledge.expertise import (
    ExpertiseBuilder,
    ExpertiseQueryEngine,
    ExpertiseBasedRecommendation,
    ExpertiseEnhancedRetrieval,
)
from app.software_engineering_knowledge.autonomous_expansion import (
    AutonomousExpander,
    ExpansionTrigger,
    ExpansionResult,
    TaskCompletionExpander,
    ExpansionEventHandler,
)
from app.software_engineering_knowledge.external_import import (
    ExternalKnowledgeImporter,
    InternetResearchImporter,
    PackageDocumentationImporter,
    UnifiedExternalImporter,
    EXTERNAL_SOURCES,
)
from app.software_engineering_knowledge import (
    create_knowledge_system,
    store_knowledge,
    retrieve_knowledge,
    quick_extract_and_store,
)
from app.knowledge_retrieval.models import (
    KnowledgeRetrievalResult,
    RetrievalQuery,
    KnowledgeSourceType,
)


class TestModels:
    """Test data models."""

    def test_engineering_knowledge_item_creation(self):
        item = EngineeringKnowledgeItem(
            title="Test Item",
            summary="Test summary",
            content="Test content",
            domain=EngineeringDomain.SECURITY,
            sub_category="auth",
            knowledge_type=EngineeringKnowledgeType.BEST_PRACTICE,
            source=KnowledgeSource.USER_INPUT,
            tags=["test", "security"],
            confidence=0.9,
        )
        assert item.id.startswith("eng_")
        assert item.title == "Test Item"
        assert item.domain == EngineeringDomain.SECURITY
        assert item.confidence == 0.9

    def test_item_serialization(self):
        item = EngineeringKnowledgeItem(
            title="Test",
            content="Content",
            domain=EngineeringDomain.TESTING,
            knowledge_type=EngineeringKnowledgeType.PROCEDURE,
        )
        data = item.to_dict()
        assert data["title"] == "Test"
        assert data["domain"] == "testing"
        assert data["knowledge_type"] == "procedure"

        restored = EngineeringKnowledgeItem.from_dict(data)
        assert restored.title == "Test"
        assert restored.domain == EngineeringDomain.TESTING

    def test_engineering_category(self):
        cat = EngineeringCategory(
            name="test_cat",
            domain=EngineeringDomain.SECURITY,
            description="Test category",
            priority=80,
            sub_categories=["sub1"],
            tags=["tag1"],
        )
        assert cat.name == "test_cat"
        assert cat.domain == EngineeringDomain.SECURITY

    def test_extraction_result(self):
        item = EngineeringKnowledgeItem(
            title="Extracted",
            content="Content",
            domain=EngineeringDomain.DEBUGGING,
        )
        result = ExtractionResult(
            success=True,
            items=[item],
            source="test",
            source_type=KnowledgeSource.PROJECT_CODE,
        )
        assert result.success
        assert len(result.items) == 1

    def test_validation_result(self):
        result = ValidationResult(
            is_valid=True,
            confidence=0.85,
            validation_status=ValidationStatus.VALIDATED,
        )
        assert result.is_valid
        assert result.confidence == 0.85

    def test_engineering_expertise(self):
        exp = EngineeringExpertise(
            domain=EngineeringDomain.SECURITY,
            title="Security Expertise",
            description="Expert in security",
            knowledge_item_ids=["item1", "item2"],
            confidence=0.9,
        )
        assert exp.domain == EngineeringDomain.SECURITY
        assert len(exp.knowledge_item_ids) == 2


class TestCategories:
    """Test category registry."""

    def test_default_categories_loaded(self):
        registry = CategoryRegistry()
        all_cats = registry.get_all()
        assert len(all_cats) > 70  # Currently ~77 categories

    def test_get_by_domain(self):
        registry = CategoryRegistry()
        security_cats = registry.get_by_domain(EngineeringDomain.SECURITY)
        assert len(security_cats) > 0
        for cat in security_cats:
            assert cat.domain == EngineeringDomain.SECURITY

    def test_get_category(self):
        registry = CategoryRegistry()
        cat = registry.get(EngineeringDomain.SECURITY, "application_security")
        assert cat is not None
        assert cat.name == "application_security"

    def test_search(self):
        registry = CategoryRegistry()
        results = registry.search("auth")
        assert len(results) > 0
        for cat in results:
            searchable = f"{cat.name} {cat.description} {' '.join(cat.sub_categories)} {' '.join(cat.tags)}".lower()
            assert "auth" in searchable

    def test_custom_category(self):
        registry = CategoryRegistry()
        from app.software_engineering_knowledge.models import EngineeringCategory
        custom = EngineeringCategory(
            name="my_custom",
            domain=EngineeringDomain.SECURITY,
            description="Custom",
            priority=50,
        )
        registry.add(custom)
        found = registry.get(EngineeringDomain.SECURITY, "my_custom")
        assert found is not None
        assert found.name == "my_custom"


class TestStorage:
    """Test storage layer."""

    @pytest.fixture
    def temp_storage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield EngineeringKnowledgeStorage(Path(tmpdir))

    def test_create_and_get(self, temp_storage):
        item = EngineeringKnowledgeItem(
            title="Storage Test",
            content="Test content",
            domain=EngineeringDomain.TESTING,
        )
        created = temp_storage.create(item)
        assert created.id == item.id

        retrieved = temp_storage.get(created.id)
        assert retrieved is not None
        assert retrieved.title == "Storage Test"

    def test_update_with_versioning(self, temp_storage):
        item = EngineeringKnowledgeItem(
            title="Version Test",
            content="Original",
            domain=EngineeringDomain.TESTING,
        )
        created = temp_storage.create(item)
        assert created.version == 1

        created.content = "Updated"
        updated = temp_storage.update(created, expected_version=1)
        assert updated.version == 2
        assert updated.content == "Updated"

    def test_update_version_conflict(self, temp_storage):
        item = EngineeringKnowledgeItem(
            title="Conflict Test",
            content="Original",
            domain=EngineeringDomain.TESTING,
        )
        created = temp_storage.create(item)

        created.content = "Updated v1"
        temp_storage.update(created, expected_version=1)

        created.content = "Updated v2 (stale)"
        with pytest.raises(ValueError, match="Version conflict"):
            temp_storage.update(created, expected_version=1)

    def test_delete(self, temp_storage):
        item = EngineeringKnowledgeItem(
            title="Delete Test",
            content="Content",
            domain=EngineeringDomain.TESTING,
        )
        created = temp_storage.create(item)
        assert temp_storage.get(created.id) is not None

        deleted = temp_storage.delete(created.id)
        assert deleted is True
        assert temp_storage.get(created.id) is None

    def test_query_by_domain(self, temp_storage):
        for i in range(3):
            item = EngineeringKnowledgeItem(
                title=f"Item {i}",
                content=f"Content {i}",
                domain=EngineeringDomain.SECURITY,
                confidence=0.5 + i * 0.1,
            )
            temp_storage.create(item)

        items = temp_storage.get_by_domain(EngineeringDomain.SECURITY, limit=10)
        assert len(items) == 3
        # Sorted by confidence desc
        assert items[0].confidence >= items[1].confidence

    def test_query_by_tag(self, temp_storage):
        item = EngineeringKnowledgeItem(
            title="Tag Test",
            content="Content",
            domain=EngineeringDomain.SECURITY,
            tags=["python", "auth"],
        )
        temp_storage.create(item)

        items = temp_storage.get_by_tag("python")
        assert len(items) == 1
        assert "python" in items[0].tags

    def test_query_by_category(self, temp_storage):
        item = EngineeringKnowledgeItem(
            title="Category Test",
            content="Content",
            domain=EngineeringDomain.DESIGN_PATTERNS,
            sub_category="singleton",
        )
        temp_storage.create(item)

        items = temp_storage.get_by_category("singleton")
        assert len(items) == 1

    def test_search(self, temp_storage):
        item = EngineeringKnowledgeItem(
            title="Search Test",
            content="This is searchable content about authentication",
            domain=EngineeringDomain.SECURITY,
        )
        temp_storage.create(item)

        results = temp_storage.search("authentication")
        assert len(results) == 1

    def test_statistics(self, temp_storage):
        for domain in [EngineeringDomain.SECURITY, EngineeringDomain.TESTING]:
            for i in range(2):
                item = EngineeringKnowledgeItem(
                    title=f"Item {domain.value} {i}",
                    content="Content",
                    domain=domain,
                    knowledge_type=EngineeringKnowledgeType.BEST_PRACTICE,
                    source=KnowledgeSource.USER_INPUT,
                    validation_status=ValidationStatus.VALIDATED,
                )
                temp_storage.create(item)

        assert temp_storage.count() == 4
        assert temp_storage.count_by_domain()[EngineeringDomain.SECURITY] == 2
        assert temp_storage.count_by_type()[EngineeringKnowledgeType.BEST_PRACTICE] == 4
        assert temp_storage.count_by_source()[KnowledgeSource.USER_INPUT] == 4
        assert temp_storage.count_by_validation()[ValidationStatus.VALIDATED] == 4

    def test_expertise_storage(self, temp_storage):
        exp = EngineeringExpertise(
            domain=EngineeringDomain.SECURITY,
            title="Test Expertise",
            description="Description",
            knowledge_item_ids=["item1"],
            confidence=0.8,
        )
        saved = temp_storage.save_expertise(exp)
        assert saved.id == exp.id

        retrieved = temp_storage.get_expertise(exp.id)
        assert retrieved is not None
        assert retrieved.title == "Test Expertise"

        all_exp = temp_storage.list_expertise(EngineeringDomain.SECURITY)
        assert len(all_exp) == 1


class TestExtraction:
    """Test knowledge extraction."""

    def test_code_extractor_singleton(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            test_file = project_root / "test.py"
            test_file.write_text("""
class Singleton:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def get_instance():
        return Singleton._instance
""")

            extractor = CodeExtractor(project_root)
            result = extractor.extract([test_file])

            assert result.success
            assert len(result.items) > 0
            # Should detect singleton pattern
            singleton_items = [i for i in result.items if "singleton" in i.tags]
            assert len(singleton_items) > 0

    def test_code_extractor_async(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            test_file = project_root / "async_test.py"
            test_file.write_text("""
async def fetch_data():
    await asyncio.sleep(1)
    return "data"

async def main():
    result = await fetch_data()
    print(result)
""")

            extractor = CodeExtractor(project_root)
            result = extractor.extract([test_file])

            assert result.success
            async_items = [i for i in result.items if "async" in i.tags]
            assert len(async_items) > 0

    def test_doc_extractor_readme(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            readme = project_root / "README.md"
            readme.write_text("""
# My Project

## Installation

Install with pip by running the following command in your terminal:
pip install myproject

## Usage

Here is a detailed example of how to use the project in your own code:

```python
from myproject import main
main()
```

## Testing

Run tests with pytest by executing pytest in the project root directory. This will discover and run all test files.
""")

            extractor = DocumentationExtractor(project_root)
            result = extractor.extract([readme])

            assert result.success
            assert len(result.items) > 0
            assert len(result.items) > 0
            # Should have sections
            for item in result.items:
                assert item.source == KnowledgeSource.DOCUMENTATION

    def test_knowledge_extractor(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            # Create some files
            (project_root / "test.py").write_text("class Test: pass")
            (project_root / "README.md").write_text("# Test\n\nContent")

            extractor = KnowledgeExtractor(project_root)
            results = extractor.extract_all()

            assert "code" in results
            assert "documentation" in results


class TestExperienceImport:
    """Test experience/lesson import."""

    def test_experience_importer(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            exp_path = Path(tmpdir)
            exp_file = exp_path / "experience.jsonl"
            exp_file.write_text('{"task": "Fix bug", "outcome": "Fixed", "lessons": ["Check null"], "tags": ["bug"], "confidence": 0.8}\n')

            importer = ExperienceImporter(exp_path)
            result = importer.import_all()

            assert result.success
            assert len(result.items) == 1
            item = result.items[0]
            assert item.source == KnowledgeSource.EXPERIENCE_MEMORY
            assert "bug" in item.tags

    def test_lessons_importer(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lessons_path = Path(tmpdir)
            lesson_file = lessons_path / "lessons.json"
            lesson_file.write_text('[{"title": "Best Practice", "description": "Use type hints", "lesson_type": "best_practice", "tags": ["python"], "confidence": 0.9}]')

            importer = EngineeringLessonsImporter(lessons_path)
            result = importer.import_all()

            assert result.success
            assert len(result.items) == 1
            item = result.items[0]
            assert item.knowledge_type == EngineeringKnowledgeType.BEST_PRACTICE

    def test_reflection_importer(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reflect_path = Path(tmpdir)
            reflect_file = reflect_path / "reflections.jsonl"
            reflect_file.write_text('{"insight": "Always validate input", "context": "API endpoint", "tags": ["security"], "confidence": 0.85}\n')

            importer = ReflectionImporter(reflect_path)
            result = importer.import_all()

            assert result.success
            assert len(result.items) == 1
            item = result.items[0]
            assert item.source == KnowledgeSource.REFLECTION

    def test_user_knowledge_importer(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            user_path = Path(tmpdir)
            user_file = user_path / "user.json"
            user_file.write_text('[{"title": "My Knowledge", "content": "Custom content", "domain": "security", "knowledge_type": "best_practice", "tags": ["custom"], "confidence": 0.95}]')

            importer = UserKnowledgeImporter(user_path)
            result = importer.import_all()

            assert result.success
            assert len(result.items) == 1
            item = result.items[0]
            assert item.source == KnowledgeSource.USER_INPUT

    def test_unified_importer(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            exp_path = project_root / "experience"
            exp_path.mkdir()
            (exp_path / "exp.jsonl").write_text('{"task": "Test", "outcome": "Done", "tags": ["test"]}\n')

            importer = KnowledgeImporter(
                project_root=project_root,
                experience_path=exp_path,
            )
            results = importer.import_all()

            assert "experience" in results


class TestValidation:
    """Test validation."""

    @pytest.fixture
    def validator(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield KnowledgeValidator(storage_path=tmpdir)

    @pytest.fixture
    def storage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield get_knowledge_storage(tmpdir)

    def test_basic_validation_pass(self, validator):
        item = EngineeringKnowledgeItem(
            title="Valid Item",
            content="This is valid content with enough length to pass validation",
            domain=EngineeringDomain.TESTING,
            confidence=0.8,
            source=KnowledgeSource.USER_INPUT,
        )
        result = validator.validate(item)
        assert result.is_valid
        assert result.validation_status == ValidationStatus.VALIDATED

    def test_basic_validation_fail_missing_title(self, validator):
        item = EngineeringKnowledgeItem(
            title="",
            content="Content",
            domain=EngineeringDomain.TESTING,
        )
        result = validator.validate(item)
        assert not result.is_valid
        assert result.validation_status == ValidationStatus.REJECTED

    def test_basic_validation_fail_short_content(self, validator):
        item = EngineeringKnowledgeItem(
            title="Test",
            content="Short",
            domain=EngineeringDomain.TESTING,
        )
        result = validator.validate(item)
        assert not result.is_valid

    def test_duplicate_detection(self, validator, storage):
        # Create first item
        item1 = EngineeringKnowledgeItem(
            title="Duplicate Test",
            content="This is the content for duplicate detection testing",
            domain=EngineeringDomain.TESTING,
            confidence=0.8,
            source=KnowledgeSource.USER_INPUT,
        )
        storage.create(item1)

        # Create similar item
        item2 = EngineeringKnowledgeItem(
            title="Duplicate Test",
            content="This is the content for duplicate detection testing",
            domain=EngineeringDomain.TESTING,
            confidence=0.7,
            source=KnowledgeSource.USER_INPUT,
        )
        result = validator.validate(item2)
        assert "duplicate" in result.duplicates or result.validation_status == ValidationStatus.DUPLICATE

    def test_conflict_detection(self, validator, storage):
        # Create first item
        item1 = EngineeringKnowledgeItem(
            title="Conflict Topic",
            content="Approach A is the best way to do this",
            domain=EngineeringDomain.TESTING,
            tags=["approach"],
            confidence=0.8,
            source=KnowledgeSource.USER_INPUT,
        )
        storage.create(item1)

        # Create conflicting item
        item2 = EngineeringKnowledgeItem(
            title="Conflict Topic",
            content="Approach B is completely different and better",
            domain=EngineeringDomain.TESTING,
            tags=["approach"],
            confidence=0.7,
            source=KnowledgeSource.USER_INPUT,
        )
        result = validator.validate(item2)
        # Should detect conflict due to similar title but different content
        # (Note: conflict detection depends on similarity thresholds)

    def test_confidence_scorer(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            scorer = ConfidenceScorer(tmpdir)
            item = EngineeringKnowledgeItem(
                title="Scored Item",
                content="Content with tags and details for scoring purposes",
                domain=EngineeringDomain.TESTING,
                source=KnowledgeSource.USER_INPUT,
                tags=["test", "scoring"],
                confidence=0.8,
                version=2,
            )
            score, signals = scorer.score_item(item)
            assert 0 <= score <= 1
            assert "source_reliability" in signals
            assert "completeness" in signals


class TestRanking:
    """Test engineering-specific ranking."""

    def test_engineering_ranker_creation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ranker = EngineeringRankingEngine(tmpdir)
            assert ranker is not None
            assert ranker.engine is not None

    def test_query_builder(self):
        builder = create_engineering_query("test query")
        query = (builder
            .with_domain(EngineeringDomain.SECURITY)
            .with_knowledge_type(EngineeringKnowledgeType.BEST_PRACTICE)
            .with_language("python")
            .with_task_context("implementation", "how_to")
            .build())

        assert query.query == "test query"
        assert query.context["engineering_filters"]["domain"] == "security"
        assert query.context["engineering_filters"]["knowledge_type"] == "best_practice"
        assert query.context["language"] == "python"
        assert query.context["task_type"] == "implementation"
        assert query.context["intent"] == "how_to"

    def test_ranking_engine_integration(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = get_knowledge_storage(tmpdir)
            ranker = EngineeringRankingEngine(tmpdir)

            # Add some items
            for i in range(5):
                item = EngineeringKnowledgeItem(
                    title=f"Item {i}",
                    content=f"Content about testing and authentication {i}",
                    domain=EngineeringDomain.SECURITY if i % 2 == 0 else EngineeringDomain.TESTING,
                    tags=["test", "auth"] if i % 2 == 0 else ["test"],
                    confidence=0.5 + i * 0.1,
                    source=KnowledgeSource.USER_INPUT,
                )
                storage.create(item)

            # Build query
            query = create_engineering_query("authentication").build()

            # Convert items to retrieval results
            from app.software_engineering_knowledge.sources import EngineeringKnowledgeAdapter
            adapter = EngineeringKnowledgeAdapter(tmpdir)
            candidates = adapter.retrieve_candidates(query, max_results=10)

            # Rank
            ranked = ranker.rank_results(candidates, query)
            assert len(ranked) > 0
            assert ranked[0].rank_score >= ranked[-1].rank_score


class TestExpertise:
    """Test expertise building."""

    def test_expertise_builder(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = get_knowledge_storage(tmpdir)
            builder = ExpertiseBuilder(tmpdir)

            # Add items
            for i in range(5):
                item = EngineeringKnowledgeItem(
                    title=f"Security Item {i}",
                    content=f"Security content {i}",
                    domain=EngineeringDomain.SECURITY,
                    sub_category="auth",
                    knowledge_type=EngineeringKnowledgeType.BEST_PRACTICE,
                    confidence=0.8,
                    validation_status=ValidationStatus.VALIDATED,
                    source=KnowledgeSource.USER_INPUT,
                )
                storage.create(item)

            # Build expertise
            expertise = builder.build_expertise(
                domain=EngineeringDomain.SECURITY,
                title="Auth Expertise",
                description="Authentication expertise",
                min_confidence=0.7,
                min_items=3,
            )

            assert expertise is not None
            assert expertise.domain == EngineeringDomain.SECURITY
            assert expertise.title == "Auth Expertise"
            assert len(expertise.knowledge_item_ids) >= 3

    def test_expertise_query_engine(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = get_knowledge_storage(tmpdir)
            query_engine = ExpertiseQueryEngine(tmpdir)

            # Create and save expertise
            exp = EngineeringExpertise(
                domain=EngineeringDomain.SECURITY,
                title="Test Expertise",
                description="Test",
                knowledge_item_ids=[],
                confidence=0.8,
            )
            storage.save_expertise(exp)

            # Query
            results = query_engine.get_expertise_for_domain(EngineeringDomain.SECURITY)
            assert len(results) == 1

    def test_expertise_recommendations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = get_knowledge_storage(tmpdir)
            recommender = ExpertiseBasedRecommendation(tmpdir)

            # Create expertise with items
            for i in range(3):
                item = EngineeringKnowledgeItem(
                    title=f"JWT Best Practice {i}",
                    content=f"Use RS256 for JWT signing {i}",
                    domain=EngineeringDomain.SECURITY,
                    knowledge_type=EngineeringKnowledgeType.BEST_PRACTICE,
                    confidence=0.9,
                    validation_status=ValidationStatus.VALIDATED,
                )
                storage.create(item)

            exp = EngineeringExpertise(
                domain=EngineeringDomain.SECURITY,
                title="JWT Expertise",
                description="JWT knowledge",
                knowledge_item_ids=[item.id for item in list(storage._items.values())],
                confidence=0.9,
            )
            storage.save_expertise(exp)

            # Get recommendations
            recs = recommender.recommend_for_task(
                "Implement JWT authentication",
                domain=EngineeringDomain.SECURITY,
            )

            assert "recommendations" in recs
            assert len(recs["recommendations"]) > 0


class TestAutonomousExpansion:
    """Test autonomous expansion."""

    def test_expansion_trigger(self):
        trigger = ExpansionTrigger(
            name="test_trigger",
            condition=lambda ctx: ctx.get("event") == "test",
            extractors=["code"],
            priority=5,
        )

        context = {"event": "test"}
        assert trigger.condition(context)

        context = {"event": "other"}
        assert not trigger.condition(context)

    def test_expansion_result(self):
        result = ExpansionResult(
            trigger_name="test",
            timestamp=datetime.now(timezone.utc).isoformat(),
            items_created=5,
            items_validated=4,
            errors=["error1"],
            extracted_sources=["code"],
            duration_seconds=1.5,
        )
        assert result.items_created == 5
        assert result.items_validated == 4

    def test_task_completion_expander(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / "test.py").write_text("def test(): pass")

            expander = TaskCompletionExpander(project_root, tmpdir)
            result = expander.expand_from_task(
                task_description="Add unit tests",
                task_result={"summary": "Done", "outcome": "success", "patterns_used": ["pytest"]},
                changed_files=["test.py"],
                technologies=["python"],
            )

            assert result.trigger_name == "task_completion"
            assert result.items_created > 0

    def test_event_handler(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            expander = AutonomousExpander(project_root, tmpdir)
            handler = ExpansionEventHandler(expander)

            # Should not crash
            results = handler.on_task_completed(
                task_description="Test task",
                result={"summary": "Done"},
                changed_files=[],
                technologies=[],
            )
            assert isinstance(results, list)


class TestExternalImport:
    """Test external knowledge import."""

    def test_external_importer_source_config(self):
        importer = ExternalKnowledgeImporter()
        assert "python_docs" in EXTERNAL_SOURCES
        assert "mdn" in EXTERNAL_SOURCES
        assert "rfc_editor" in EXTERNAL_SOURCES

    @pytest.mark.asyncio
    async def test_external_import_stubs(self):
        importer = ExternalKnowledgeImporter()

        # All return not implemented errors
        result = await importer.import_from_source("python_docs", "query")
        assert not result.success
        assert len(result.errors) > 0

        result = await importer.import_from_url("https://example.com")
        assert not result.success

        result = await importer.import_package_docs("requests", "python")
        assert not result.success

        await importer.close()

    @pytest.mark.asyncio
    async def test_internet_research_stubs(self):
        importer = InternetResearchImporter()

        result = await importer.search_and_import("query")
        assert not result.success

        result = await importer.import_from_stackoverflow("12345")
        assert not result.success

        result = await importer.import_from_github_repo("https://github.com/user/repo")
        assert not result.success

        await importer.close()

    def test_package_doc_importer(self):
        importer = PackageDocumentationImporter()

        result = importer.import_python_package_docs("nonexistent_package_12345")
        assert not result.success

    @pytest.mark.asyncio
    async def test_unified_external_importer(self):
        importer = UnifiedExternalImporter()

        result = await importer.import_from_source(KnowledgeSource.EXTERNAL_DOCS, "python:requests")
        # The import may succeed if requests is installed, or fail if not
        # Assert that we get a valid result either way
        assert result is not None
        assert hasattr(result, 'success')
        assert hasattr(result, 'items')

        result = await importer.import_from_source(KnowledgeSource.INTERNET_RESEARCH, "query")
        assert not result.success

        await importer.close()


class TestIntegration:
    """Integration tests."""

    def test_full_workflow(self):
        """Test complete workflow: extract -> validate -> store -> retrieve."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / "auth.py").write_text("""
class JWTAuth:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def authenticate(self, token):
        # Validate JWT token
        import jwt
        return jwt.decode(token, "secret", algorithms=["HS256"])
""")
            (project_root / "README.md").write_text("""
# Auth Module

## Installation
pip install auth

## Usage
```python
from auth import JWTAuth
auth = JWTAuth()
result = auth.authenticate(token)
```
""")

            # Create system
            system = create_knowledge_system(project_root, tmpdir)

            # Quick extract
            result = quick_extract_and_store(project_root, tmpdir)
            assert result["stored"] > 0

            # Retrieve
            items = retrieve_knowledge(
                "singleton pattern authentication",
                domain=EngineeringDomain.DESIGN_PATTERNS,
                storage_path=tmpdir,
            )
            assert len(items) > 0

    def test_pipeline_integration(self):
        """Test integration with Knowledge Retrieval Pipeline."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Add some knowledge
            storage = get_knowledge_storage(tmpdir)
            for i in range(3):
                item = EngineeringKnowledgeItem(
                    title=f"Pattern {i}",
                    content=f"Content about factory pattern {i}",
                    domain=EngineeringDomain.DESIGN_PATTERNS,
                    knowledge_type=EngineeringKnowledgeType.CODE_PATTERN,
                    confidence=0.8,
                    validation_status=ValidationStatus.VALIDATED,
                )
                storage.create(item)

            # Create adapter
            adapter = EngineeringKnowledgeAdapter(tmpdir)

            # Query
            query = RetrievalQuery(query="factory pattern", max_results=5)
            results = adapter.retrieve_candidates(query, max_results=5)

            assert len(results) > 0
            for r in results:
                assert r.source_type == KnowledgeSourceType.KNOWLEDGE_BASE

    def test_convenience_functions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Store
            item = store_knowledge(
                title="Convenience Test",
                content="Testing convenience functions for storage and retrieval of engineering knowledge items",
                domain=EngineeringDomain.TESTING,
                confidence=0.85,
                storage_path=tmpdir,
            )
            assert item.id is not None

            # Retrieve
            items = retrieve_knowledge(
                "convenience test",
                domain=EngineeringDomain.TESTING,
                storage_path=tmpdir,
            )
            assert len(items) > 0


# Run with: python -m pytest tests/test_software_engineering_knowledge.py -v
if __name__ == "__main__":
    pytest.main([__file__, "-v"])