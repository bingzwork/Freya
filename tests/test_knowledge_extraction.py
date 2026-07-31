"""Tests for Knowledge Extraction capability."""

import tempfile
from pathlib import Path

import pytest

from app.knowledge_extraction import (
    KnowledgeObject,
    SourceType,
    KnowledgeCategory,
    KnowledgeExtractionResult,
    ExtractionError,
    KnowledgeExtractionPipeline,
    ExtractorRegistry,
    LLMExtractor,
    DocumentExtractor,
    pipeline,
    registry,
)


class TestModels:
    """Test data models."""

    def test_knowledge_object_creation(self):
        """Test KnowledgeObject creation and serialization."""
        obj = KnowledgeObject(
            title="Test Knowledge",
            summary="A test summary",
            content="Full content here",
            source="test_source",
            source_type=SourceType.LLM_RESPONSE,
            category=KnowledgeCategory.FACT,
            confidence=0.8,
            tags=["test", "fact"],
            language="en",
        )

        assert obj.id.startswith("kobj_")
        assert obj.title == "Test Knowledge"
        assert obj.source_type == SourceType.LLM_RESPONSE
        assert obj.category == KnowledgeCategory.FACT

        # Test serialization
        data = obj.to_dict()
        assert data["title"] == "Test Knowledge"
        assert data["source_type"] == "llm_response"
        assert data["category"] == "fact"

        # Test deserialization
        obj2 = KnowledgeObject.from_dict(data)
        assert obj2.title == obj.title
        assert obj2.source_type == obj.source_type
        assert obj2.category == obj.category

    def test_extraction_error(self):
        """Test ExtractionError creation."""
        error = ExtractionError(
            message="Test error",
            source_type=SourceType.DOCUMENTATION,
            source="/path/to/file.md",
            details={"line": 42},
        )

        assert "documentation" in str(error).lower()
        assert "test error" in str(error).lower()

    def test_extraction_result_success(self):
        """Test successful extraction result."""
        obj = KnowledgeObject(title="Test", content="Content", source="src")
        result = KnowledgeExtractionResult.success_result(
            knowledge_objects=[obj],
            source="src",
            source_type=SourceType.LLM_RESPONSE,
            extraction_time=0.5,
            metadata={"key": "value"},
        )

        assert result.success is True
        assert len(result.knowledge_objects) == 1
        assert result.extraction_time == 0.5
        assert result.metadata["key"] == "value"

        data = result.to_dict()
        assert data["success"] is True
        assert len(data["knowledge_objects"]) == 1
        assert data["metadata"]["key"] == "value"

    def test_extraction_result_error(self):
        """Test error extraction result."""
        error = ExtractionError("Failed", SourceType.DOCUMENTATION, "file.md")
        result = KnowledgeExtractionResult.error_result(
            error=error,
            source="file.md",
            source_type=SourceType.DOCUMENTATION,
            extraction_time=0.1,
        )

        assert result.success is False
        assert result.error is not None
        assert result.error.message == "Failed"

        data = result.to_dict()
        assert data["success"] is False
        assert data["error"]["message"] == "Failed"


class TestLLMExtractor:
    """Test LLM response extractor."""

    @pytest.fixture
    def extractor(self):
        return LLMExtractor()

    def test_extract_facts(self, extractor):
        """Test extraction of facts from LLM response."""
        content = """
        Here is an explanation of how it works.

        Fact: Python uses indentation for code blocks instead of braces.
        This is a known fact about Python syntax that is important to understand.

        Best practice: Always use 4 spaces for indentation in Python code.
        """
        result = extractor.extract(content, "test_conv_1")

        assert result.success is True
        assert len(result.knowledge_objects) > 0

        # Check for fact
        facts = [o for o in result.knowledge_objects if o.category == KnowledgeCategory.FACT]
        assert len(facts) > 0
        assert "indentation" in facts[0].content.lower()

        # Check for best practice
        practices = [o for o in result.knowledge_objects if o.category == KnowledgeCategory.BEST_PRACTICE]
        assert len(practices) > 0

    def test_extract_code_blocks(self, extractor):
        """Test extraction of code blocks."""
        content = """
        Here's an example:

        ```python
        def hello():
            print("Hello, World!")
        ```

        And another:

        ```javascript
        console.log("Hello");
        ```
        """
        result = extractor.extract(content, "test_conv_2")

        assert result.success is True
        code_objects = [o for o in result.knowledge_objects if o.category == KnowledgeCategory.ALGORITHM]
        assert len(code_objects) >= 1

        python_code = [o for o in code_objects if o.language == "python"]
        assert len(python_code) == 1
        assert "def hello" in python_code[0].content

    def test_extract_procedures(self, extractor):
        """Test extraction of procedures/steps."""
        content = """
        To install the package:

        Steps:
        1. First, run pip install package with the correct version
        2. Then, verify with pip list to confirm installation
        3. Finally, import in your code and test functionality
        """
        result = extractor.extract(content, "test_conv_3")

        assert result.success is True
        procedures = [o for o in result.knowledge_objects if o.category == KnowledgeCategory.PROCEDURE]
        assert len(procedures) > 0

    def test_extract_warnings(self, extractor):
        """Test extraction of warnings."""
        content = """
        Warning: Do not use eval() on user input as it can execute arbitrary code.
        This can lead to code injection vulnerabilities in your application.

        Caution: Always validate input before processing to prevent security issues.
        """
        result = extractor.extract(content, "test_conv_4")

        assert result.success is True
        warnings = [o for o in result.knowledge_objects if o.category == KnowledgeCategory.WARNING]
        assert len(warnings) > 0
        assert "eval" in warnings[0].content.lower()

    def test_ignore_filler(self, extractor):
        """Test that conversational filler is ignored."""
        content = """
        Hello! I'm happy to help you with that.

        Here is the answer:
        Fact: Python is a programming language that uses indentation for code blocks.

        Let me know if you need anything else!
        """
        result = extractor.extract(content, "test_conv_5")

        assert result.success is True
        # Should only have the fact, not the filler
        facts = [o for o in result.knowledge_objects if o.category == KnowledgeCategory.FACT]
        assert len(facts) == 1

        # Check filler not extracted
        all_content = " ".join(o.content for o in result.knowledge_objects)
        assert "happy to help" not in all_content.lower()
        assert "hello" not in all_content.lower()

    def test_empty_content(self, extractor):
        """Test handling of empty content."""
        result = extractor.extract("", "test_empty")
        assert result.success is False
        assert result.error is not None

    def test_short_content(self, extractor):
        """Test handling of very short content."""
        result = extractor.extract("Hi", "test_short")
        assert result.success is False


class TestDocumentExtractor:
    """Test documentation extractor."""

    @pytest.fixture
    def extractor(self):
        return DocumentExtractor()

    @pytest.fixture
    def sample_markdown(self):
        return """# Project Documentation

## Overview

This project demonstrates knowledge extraction capabilities with detailed explanations and examples for users.

## Installation

To install the package:

1. First, clone the repository from GitHub
2. Then, run pip install -e . to install in development mode
3. Finally, verify installation by running the test suite

```python
import freya
print(freya.__version__)
```

## API Reference

### Configuration

| Setting | Type | Default |
|---------|------|---------|
| debug   | bool | false   |
| port    | int  | 8080    |

> [!WARNING]
> Do not expose debug mode in production.

## Troubleshooting

Common issues and solutions:

- Import errors: Check PYTHONPATH is set correctly
- Connection issues: Verify network connectivity and firewall settings
"""

    def test_extract_sections(self, extractor, sample_markdown):
        """Test extraction of markdown sections."""
        result = extractor.extract(sample_markdown, "test.md")

        assert result.success is True
        assert len(result.knowledge_objects) > 0

        # Check for sections
        sections = [o for o in result.knowledge_objects if o.metadata.get("extraction_method") == "document_section"]
        assert len(sections) >= 3  # Overview, Installation, API Reference, Troubleshooting

        headings = [o.title for o in sections]
        assert any("Overview" in h for h in headings)
        assert any("Installation" in h for h in headings)

    def test_extract_code_blocks(self, extractor, sample_markdown):
        """Test extraction of code blocks from markdown."""
        result = extractor.extract(sample_markdown, "test.md")

        code_objects = [o for o in result.knowledge_objects if o.category == KnowledgeCategory.ALGORITHM]
        assert len(code_objects) >= 1
        python_code = [o for o in code_objects if o.language == "python"]
        assert len(python_code) == 1
        assert "import freya" in python_code[0].content

    def test_extract_tables(self, extractor, sample_markdown):
        """Test extraction of markdown tables."""
        result = extractor.extract(sample_markdown, "test.md")

        tables = [o for o in result.knowledge_objects if o.category == KnowledgeCategory.REFERENCE
                  and o.metadata.get("extraction_method") == "markdown_table"]
        assert len(tables) >= 1
        table = tables[0]
        assert "debug" in table.content
        assert "port" in table.content
        assert table.metadata["column_count"] == 3
        assert table.metadata["row_count"] == 2  # Two data rows: debug and port

    def test_extract_admonitions(self, extractor, sample_markdown):
        """Test extraction of admonitions (warnings, notes)."""
        result = extractor.extract(sample_markdown, "test.md")

        warnings = [o for o in result.knowledge_objects if o.category == KnowledgeCategory.WARNING
                    and "admonition" in o.tags]
        assert len(warnings) >= 1
        assert "debug mode" in warnings[0].content.lower()

    def test_category_inference(self, extractor):
        """Test category inference from headings."""
        content = """# Installation Guide

Steps to install the package with detailed instructions on how to set up the environment and configure the system properly.

# Best Practices

Follow these guidelines for writing clean and maintainable code that follows established conventions.

# Troubleshooting Errors

Fix common problems that users encounter when setting up or running the application.
"""
        result = extractor.extract(content, "test.md")

        sections = [o for o in result.knowledge_objects if o.metadata.get("extraction_method") == "document_section"]
        titles_cats = {(o.title, o.category) for o in sections}

        assert any(cat == KnowledgeCategory.PROCEDURE for _, cat in titles_cats if "Installation" in _)
        assert any(cat == KnowledgeCategory.BEST_PRACTICE for _, cat in titles_cats if "Best Practices" in _)
        assert any(cat == KnowledgeCategory.TROUBLESHOOTING for _, cat in titles_cats if "Troubleshooting" in _)

    def test_file_extraction(self, sample_markdown):
        """Test extraction from file path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test_doc.md"
            file_path.write_text(sample_markdown)

            result = pipeline.extract_from_file(str(file_path))

            assert result.success is True
            assert len(result.knowledge_objects) > 0

    def test_empty_file(self):
        """Test handling of empty file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "empty.md"
            file_path.write_text("")

            result = pipeline.extract_from_file(str(file_path))
            assert result.success is False

    def test_nonexistent_file(self):
        """Test handling of nonexistent file."""
        result = pipeline.extract_from_file("/nonexistent/path/file.md")
        assert result.success is False
        assert "not found" in result.error.message.lower()


class TestPipeline:
    """Test knowledge extraction pipeline."""

    def test_pipeline_extract_llm(self):
        """Test pipeline with LLM content."""
        content = """
        Fact: The pipeline extracts knowledge from multiple sources.
        Best practice: Always validate extracted knowledge before use.
        """
        result = pipeline.extract(content, "test_conv", SourceType.LLM_RESPONSE)

        assert result.success is True
        assert len(result.knowledge_objects) >= 2

    def test_pipeline_extract_markdown(self):
        """Test pipeline with markdown content."""
        content = """# Test Document

## Section One

This section has enough content to pass the minimum length requirement for extraction.

```python
print("hello")
```
"""
        result = pipeline.extract(content, "test.md", SourceType.DOCUMENTATION)

        assert result.success is True
        assert len(result.knowledge_objects) > 0

    def test_pipeline_auto_detect_markdown(self):
        """Test pipeline auto-detects markdown from file extension."""
        content = "# Test\n\nContent here."
        # Should auto-detect from .md extension
        result = pipeline.extract(content, "document.md")

        assert result.success is True

    def test_pipeline_auto_detect_llm(self):
        """Test pipeline auto-detects LLM from conversation ID."""
        content = "Fact: Test fact with sufficient content length to pass the minimum threshold for extraction."
        result = pipeline.extract(content, "conv_12345")

        assert result.success is True

    def test_pipeline_batch(self):
        """Test batch extraction."""
        items = [
            {"content": "Fact: First fact with enough content to pass minimum length requirement.", "source": "src1", "source_type": SourceType.LLM_RESPONSE},
            {"content": "# Doc\n\nContent with sufficient length for extraction.", "source": "doc.md", "source_type": SourceType.DOCUMENTATION},
            {"content": "Fact: Second fact with enough content for extraction.", "source": "conv_999", "source_type": SourceType.LLM_RESPONSE},
        ]
        results = pipeline.extract_batch(items)

        assert len(results) == 3
        assert results[0].success is True
        assert results[1].success is True
        assert results[2].success is True

    def test_pipeline_stats(self):
        """Test pipeline statistics."""
        stats = pipeline.get_stats()
        assert "total_extractions" in stats
        assert "successful_extractions" in stats
        assert "failed_extractions" in stats
        assert "registered_extractors" in stats
        assert SourceType.LLM_RESPONSE in stats["registered_extractors"]
        assert SourceType.DOCUMENTATION in stats["registered_extractors"]


class TestExtractorRegistry:
    """Test extractor registry."""

    def test_registry_has_default_extractors(self):
        """Test that registry has default extractors registered."""
        assert SourceType.LLM_RESPONSE in registry.list_extractors()
        assert SourceType.DOCUMENTATION in registry.list_extractors()

    def test_registry_get_for_source(self):
        """Test getting extractor for source."""
        ext = registry.get_for_source("test.md")
        assert ext is not None
        assert ext.source_type == SourceType.DOCUMENTATION

        ext = registry.get_for_source("conv_123")
        assert ext is not None
        assert ext.source_type == SourceType.LLM_RESPONSE

    def test_registry_custom_extractor(self):
        """Test registering custom extractor."""
        from app.knowledge_extraction.extractors import Extractor
        from app.knowledge_extraction.models import SourceType

        class CustomExtractor(Extractor):
            source_type = SourceType.UNKNOWN
            supported_extensions = [".custom"]

            def extract(self, content, source, **context):
                return KnowledgeExtractionResult.success_result(
                    knowledge_objects=[KnowledgeObject(title="Custom", content=content, source=source)],
                    source=source,
                    source_type=self.source_type,
                    extraction_time=0.0,
                )

        custom = CustomExtractor()
        registry.register(custom)

        assert SourceType.UNKNOWN in registry.list_extractors()
        ext = registry.get_for_source("file.custom")
        assert ext is custom

        # Cleanup
        registry.unregister(SourceType.UNKNOWN)


class TestIntegration:
    """Integration tests."""

    def test_llm_and_doc_extraction_workflow(self):
        """Test complete workflow: LLM response -> markdown doc -> knowledge objects."""
        # Simulate LLM generating documentation
        llm_response = """
        I've created the following documentation for the API:

        # API Documentation

        ## Authentication

        Use bearer tokens for authentication.

        ```python
        headers = {"Authorization": f"Bearer {token}"}
        ```

        > [!IMPORTANT]
        > Tokens expire after 1 hour.

        ## Endpoints

        | Method | Path | Description |
        |--------|------|-------------|
        | GET | /users | List users |
        | POST | /users | Create user |
        """

        # Extract from LLM response
        llm_result = pipeline.extract(llm_response, "llm_response_1", SourceType.LLM_RESPONSE)
        assert llm_result.success is True

        # Also extract from the markdown portion (simulating saving to file)
        md_result = pipeline.extract(llm_response, "api_docs.md", SourceType.DOCUMENTATION)
        assert md_result.success is True

        # Both should produce knowledge objects
        total_objects = len(llm_result.knowledge_objects) + len(md_result.knowledge_objects)
        assert total_objects > 5

    def test_knowledge_object_structure_completeness(self):
        """Test that extracted objects have all required fields."""
        content = "Fact: Every object must have an ID, title, and source."
        result = pipeline.extract(content, "test_source", SourceType.LLM_RESPONSE)

        assert result.success is True
        for obj in result.knowledge_objects:
            assert obj.id
            assert obj.id.startswith("kobj_")
            assert obj.title
            assert obj.summary
            assert obj.content
            assert obj.source == "test_source"
            assert obj.source_type == SourceType.LLM_RESPONSE
            assert obj.category is not None
            assert 0 <= obj.confidence <= 1
            assert obj.extracted_at
            assert isinstance(obj.tags, list)
            assert isinstance(obj.metadata, dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])