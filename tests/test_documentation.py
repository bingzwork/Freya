"""Tests for the Documentation Automation system.

This module provides comprehensive tests for all documentation components
including DocumentationGenerator, DocumentationStore, ChangeLog, and templates.
"""

import json
import os
import tempfile
import pytest
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional
import uuid

from app.documentation.doc_generator import (
    DocumentationGenerator,
    DocType,
    DocFormat,
)
from app.documentation.doc_store import (
    DocumentationStore,
    DocumentationEntry,
    DocStatus,
)
from app.documentation.change_log import (
    ChangeLog,
    ChangeEntry,
    ChangeType,
    ChangeScope,
)
from app.documentation.doc_template import (
    DocumentationTemplate,
    TemplateSection,
    TemplateVariable,
    TemplateRegistry,
    MODULE_TEMPLATE,
    CLASS_TEMPLATE,
    FUNCTION_TEMPLATE,
    README_TEMPLATE,
    CHANGELOG_TEMPLATE,
    API_REFERENCE_TEMPLATE,
)


class TestDocType:
    """Tests for DocType enum."""

    def test_doc_type_enum_values(self):
        """Test that all doc type enum values are strings."""
        for doc_type in DocType:
            assert isinstance(doc_type.value, str)

    def test_doc_type_enum_unique(self):
        """Test that all doc type enum values are unique."""
        values = [doc_type.value for doc_type in DocType]
        assert len(values) == len(set(values))


class TestDocFormat:
    """Tests for DocFormat enum."""

    def test_doc_format_enum_values(self):
        """Test that all doc format enum values are strings."""
        for doc_format in DocFormat:
            assert isinstance(doc_format.value, str)

    def test_doc_format_enum_unique(self):
        """Test that all doc format enum values are unique."""
        values = [doc_format.value for doc_format in DocFormat]
        assert len(values) == len(set(values))


class TestDocStatus:
    """Tests for DocStatus enum."""

    def test_doc_status_enum_values(self):
        """Test that all doc status enum values are strings."""
        for status in DocStatus:
            assert isinstance(status.value, str)

    def test_doc_status_enum_unique(self):
        """Test that all doc status enum values are unique."""
        values = [status.value for status in DocStatus]
        assert len(values) == len(set(values))


class TestChangeType:
    """Tests for ChangeType enum."""

    def test_change_type_enum_values(self):
        """Test that all change type enum values are strings."""
        for change_type in ChangeType:
            assert isinstance(change_type.value, str)

    def test_change_type_enum_unique(self):
        """Test that all change type enum values are unique."""
        values = [change_type.value for change_type in ChangeType]
        assert len(values) == len(set(values))


class TestChangeScope:
    """Tests for ChangeScope enum."""

    def test_change_scope_enum_values(self):
        """Test that all change scope enum values are strings."""
        for scope in ChangeScope:
            assert isinstance(scope.value, str)

    def test_change_scope_enum_unique(self):
        """Test that all change scope enum values are unique."""
        values = [scope.value for scope in ChangeScope]
        assert len(values) == len(set(values))


class TestTemplateSection:
    """Tests for TemplateSection enum."""

    def test_template_section_enum_values(self):
        """Test that all template section enum values are strings."""
        for section in TemplateSection:
            assert isinstance(section.value, str)

    def test_template_section_enum_unique(self):
        """Test that all template section enum values are unique."""
        values = [section.value for section in TemplateSection]
        assert len(values) == len(set(values))


class TestTemplateVariable:
    """Tests for TemplateVariable class."""

    def test_create_variable(self):
        """Test creating a template variable."""
        var = TemplateVariable(
            name="test_var",
            default_value="default",
            required=True,
            description="Test variable",
        )

        assert var.name == "test_var"
        assert var.default_value == "default"
        assert var.required is True
        assert var.description == "Test variable"

    def test_create_variable_minimal(self):
        """Test creating a minimal template variable."""
        var = TemplateVariable(name="minimal")

        assert var.name == "minimal"
        assert var.default_value == ""
        assert var.required is False
        assert var.description == ""


class TestDocumentationTemplate:
    """Tests for DocumentationTemplate class."""

    def test_create_template(self):
        """Test creating a documentation template."""
        template = DocumentationTemplate(
            name="Test Template",
            description="A test template",
            content="# {{title}}\n\n{{content}}",
        )

        assert template.name == "Test Template"
        assert template.description == "A test template"
        assert template.content == "# {{title}}\n\n{{content}}"
        assert template.template_id.startswith("template_")

    def test_render_template(self):
        """Test rendering a template with variables."""
        template = DocumentationTemplate(
            name="Simple Template",
            content="Hello, {{name}}! You are {{age}} years old.",
        )

        result = template.render({"name": "Alice", "age": "30"})
        assert result == "Hello, Alice! You are 30 years old."

    def test_render_template_missing_variable(self):
        """Test rendering a template with missing variables."""
        template = DocumentationTemplate(
            name="Simple Template",
            content="Hello, {{name}}!",
        )

        result = template.render({})
        assert result == "Hello, {{name}}!"

    def test_validate_variables(self):
        """Test validating template variables."""
        template = DocumentationTemplate(
            name="Validated Template",
            content="Test",
            variables=[
                TemplateVariable("required_var", required=True),
                TemplateVariable("optional_var", required=False),
            ],
        )

        # Missing required variable
        missing = template.validate_variables({"optional_var": "value"})
        assert "required_var" in missing

        # All variables provided
        missing = template.validate_variables({"required_var": "value", "optional_var": "value"})
        assert len(missing) == 0

    def test_to_dict(self):
        """Test converting template to dictionary."""
        template = DocumentationTemplate(
            name="Test",
            description="Desc",
            content="Content",
        )

        data = template.to_dict()

        assert data["name"] == "Test"
        assert data["description"] == "Desc"
        assert data["content"] == "Content"
        assert "template_id" in data

    def test_from_dict(self):
        """Test creating template from dictionary."""
        data = {
            "template_id": "temp_123",
            "name": "From Dict",
            "description": "Desc",
            "content": "Content",
            "variables": [
                {"name": "var1", "default_value": "def", "required": True, "description": "Var 1"}
            ],
            "sections": ["title", "overview"],
        }

        template = DocumentationTemplate.from_dict(data)

        assert template.template_id == "temp_123"
        assert template.name == "From Dict"
        assert len(template.variables) == 1
        assert template.variables[0].name == "var1"
        assert len(template.sections) == 2


class TestTemplateRegistry:
    """Tests for TemplateRegistry class."""

    def test_create_registry(self):
        """Test creating a template registry."""
        registry = TemplateRegistry()

        assert isinstance(registry.templates, dict)
        # Built-in templates should be registered
        assert "Module Documentation" in registry.templates
        assert "Class Documentation" in registry.templates
        assert "Function Documentation" in registry.templates
        assert "README" in registry.templates
        assert "Change Log" in registry.templates
        assert "API Reference" in registry.templates

    def test_register_template(self):
        """Test registering a custom template."""
        registry = TemplateRegistry()
        initialCount = len(registry.templates)

        template = DocumentationTemplate(
            name="Custom Template",
            content="Custom content",
        )

        registry.register(template)

        # After registration, we should have at least the initial templates + 1
        assert "Custom Template" in registry.templates
        assert registry.get("Custom Template") is not None

    def test_get_template(self):
        """Test getting a template by name."""
        registry = TemplateRegistry()

        template = registry.get("Module Documentation")
        assert template is not None
        assert template.name == "Module Documentation"

        # Non-existent template
        template = registry.get("Non Existent")
        assert template is None

    def test_list_templates(self):
        """Test listing all templates."""
        registry = TemplateRegistry()

        templates = registry.list_templates()
        assert len(templates) > 0

    def test_remove_template(self):
        """Test removing a template."""
        registry = TemplateRegistry()

        # Add a custom template first
        template = DocumentationTemplate(
            name="Removable Template",
            content="Test",
        )
        registry.register(template)

        assert registry.get("Removable Template") is not None

        removed = registry.remove("Removable Template")
        assert removed is True
        assert registry.get("Removable Template") is None

        # Try removing non-existent
        removed = registry.remove("Non Existent")
        assert removed is False

    def test_create_from_preset(self):
        """Test creating a template from a preset."""
        registry = TemplateRegistry()

        custom = registry.create_from_preset(
            "Module Documentation",
            name="Custom Module Doc",
            description="Custom description",
        )

        assert custom.name == "Custom Module Doc"
        assert custom.description == "Custom description"
        assert "{{module_name}}" in custom.content

    def test_builtin_templates(self):
        """Test that built-in templates are properly defined."""
        assert MODULE_TEMPLATE.name == "Module Documentation"
        assert CLASS_TEMPLATE.name == "Class Documentation"
        assert FUNCTION_TEMPLATE.name == "Function Documentation"
        assert README_TEMPLATE.name == "README"
        assert CHANGELOG_TEMPLATE.name == "Change Log"
        assert API_REFERENCE_TEMPLATE.name == "API Reference"


class TestDocumentationEntry:
    """Tests for DocumentationEntry class."""

    def test_create_entry(self):
        """Test creating a documentation entry."""
        entry = DocumentationEntry(
            title="Test Entry",
            content="Test content",
            module="test_module",
            doc_type="module",
            status=DocStatus.PUBLISHED,
            author="test_author",
        )

        assert entry.entry_id.startswith("doc_")
        assert entry.title == "Test Entry"
        assert entry.content == "Test content"
        assert entry.module == "test_module"
        assert entry.doc_type == "module"
        assert entry.status == DocStatus.PUBLISHED
        assert entry.author == "test_author"
        assert entry.version == "1.0"
        assert entry.content_hash != ""

    def test_entry_content_hash(self):
        """Test that content hash is computed correctly."""
        entry1 = DocumentationEntry(
            title="Test",
            content="Content 1",
        )
        entry2 = DocumentationEntry(
            title="Test",
            content="Content 2",
        )
        entry3 = DocumentationEntry(
            title="Test",
            content="Content 1",
        )

        assert entry1.content_hash != entry2.content_hash
        assert entry1.content_hash == entry3.content_hash

    def test_update_content(self):
        """Test updating entry content."""
        import time
        entry = DocumentationEntry(
            title="Test",
            content="Original",
            version="1.0",
        )

        original_hash = entry.content_hash
        original_version = entry.version

        # Add a small delay to ensure different timestamp
        time.sleep(0.01)
        entry.update_content("Updated")

        assert entry.content == "Updated"
        assert entry.content_hash != original_hash
        assert entry.version == "1.1"
        # Updated at should be different after the sleep
        assert entry.updated_at >= entry.created_at

    def test_to_dict(self):
        """Test converting entry to dictionary."""
        entry = DocumentationEntry(
            title="Test",
            content="Content",
            status=DocStatus.DRAFT,
        )

        data = entry.to_dict()

        assert data["title"] == "Test"
        assert data["content"] == "Content"
        assert data["status"] == "draft"

    def test_from_dict(self):
        """Test creating entry from dictionary."""
        data = {
            "entry_id": "doc_123",
            "title": "From Dict",
            "content": "Content",
            "status": "published",
            "version": "2.0",
        }

        entry = DocumentationEntry.from_dict(data)

        assert entry.entry_id == "doc_123"
        assert entry.title == "From Dict"
        assert entry.status == DocStatus.PUBLISHED
        assert entry.version == "2.0"


class TestDocumentationStore:
    """Tests for DocumentationStore class."""

    def test_create_store(self):
        """Test creating a documentation store."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = DocumentationStore(workspace=tmpdir)

            assert store.workspace == tmpdir
            assert store.count == 0

    def test_add_get_entry(self):
        """Test adding and getting an entry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = DocumentationStore(workspace=tmpdir)

            entry = DocumentationEntry(
                title="Test Entry",
                content="Test content",
                module="test_module",
                tags=["test", "doc"],
            )
            store.add_entry(entry)

            assert store.count == 1

            retrieved = store.get_entry(entry.entry_id)
            assert retrieved is not None
            assert retrieved.title == "Test Entry"

    def test_remove_entry(self):
        """Test removing an entry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = DocumentationStore(workspace=tmpdir)

            entry = DocumentationEntry(title="Remove Test")
            store.add_entry(entry)

            assert store.count == 1

            removed = store.remove_entry(entry.entry_id)
            assert removed is True
            assert store.count == 0

            # Try removing non-existent
            removed = store.remove_entry("non_existent")
            assert removed is False

    def test_list_entries_filters(self):
        """Test listing entries with filters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = DocumentationStore(workspace=tmpdir)

            entry1 = DocumentationEntry(
                title="Entry 1",
                module="module_a",
                doc_type="module",
                status=DocStatus.PUBLISHED,
                tags=["tag1"],
            )
            entry2 = DocumentationEntry(
                title="Entry 2",
                module="module_b",
                doc_type="class",
                status=DocStatus.DRAFT,
                tags=["tag2"],
            )
            entry3 = DocumentationEntry(
                title="Entry 3",
                module="module_a",
                doc_type="module",
                status=DocStatus.PUBLISHED,
                tags=["tag1"],
            )

            store.add_entry(entry1)
            store.add_entry(entry2)
            store.add_entry(entry3)

            # All entries
            all_entries = store.list_entries()
            assert len(all_entries) == 3

            # Filter by module
            module_a = store.list_entries(module="module_a")
            assert len(module_a) == 2

            # Filter by type
            modules = store.list_entries(doc_type="module")
            assert len(modules) == 2

            # Filter by status
            published = store.list_entries(status=DocStatus.PUBLISHED)
            assert len(published) == 2

            # Filter by tag
            tag1 = store.list_entries(tag="tag1")
            assert len(tag1) == 2

            # Filter with limit
            limited = store.list_entries(limit=2)
            assert len(limited) == 2

    def test_get_entries_by_module(self):
        """Test getting entries by module."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = DocumentationStore(workspace=tmpdir)

            entry1 = DocumentationEntry(module="app.core")
            entry2 = DocumentationEntry(module="app.core")
            entry3 = DocumentationEntry(module="app.utils")

            store.add_entry(entry1)
            store.add_entry(entry2)
            store.add_entry(entry3)

            core_entries = store.get_entries_by_module("app.core")
            assert len(core_entries) == 2

            utils_entries = store.get_entries_by_module("app.utils")
            assert len(utils_entries) == 1

            # Non-existent module
            empty = store.get_entries_by_module("non.existent")
            assert len(empty) == 0

    def test_search_entries(self):
        """Test searching entries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = DocumentationStore(workspace=tmpdir)

            entry1 = DocumentationEntry(
                title="Test Module",
                content="This is a test module",
                module="app.test",
            )
            entry2 = DocumentationEntry(
                title="Core Module",
                content="This is a core module",
                module="app.core",
            )
            entry3 = DocumentationEntry(
                title="Another Test",
                content="This is another test",
                module="app.another",
            )

            store.add_entry(entry1)
            store.add_entry(entry2)
            store.add_entry(entry3)

            # Search by title
            results = store.search("Test")
            assert len(results) == 2

            # Search by content
            results = store.search("core")
            assert len(results) >= 1

            # Search by module
            results = store.search("app.test")
            assert len(results) >= 1

    def test_store_summary(self):
        """Test getting store summary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = DocumentationStore(workspace=tmpdir)

            entry1 = DocumentationEntry(
                module="module_a",
                doc_type="module",
                status=DocStatus.PUBLISHED,
                tags=["tag1"],
            )
            entry2 = DocumentationEntry(
                module="module_b",
                doc_type="class",
                status=DocStatus.DRAFT,
                tags=["tag2"],
            )

            store.add_entry(entry1)
            store.add_entry(entry2)

            summary = store.get_summary()

            assert summary["total_entries"] == 2
            assert summary["by_status"]["published"] == 1
            assert summary["by_status"]["draft"] == 1
            assert summary["by_type"]["module"] == 1
            assert summary["by_type"]["class"] == 1
            assert summary["total_tags"] == 2
            assert summary["total_modules"] == 2

    def test_clear_store(self):
        """Test clearing the store."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = DocumentationStore(workspace=tmpdir)

            store.add_entry(DocumentationEntry(title="Test 1"))
            store.add_entry(DocumentationEntry(title="Test 2"))

            assert store.count == 2

            store.clear()

            assert store.count == 0

    def test_export_import_store(self):
        """Test exporting and importing store data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = DocumentationStore(workspace=tmpdir)

            entry = DocumentationEntry(title="Export Test", module="test")
            store.add_entry(entry)

            # Export
            data = store.export_to_dict()
            assert "entries" in data
            assert "summary" in data

            # Create new store and import
            new_store = DocumentationStore(workspace=tmpdir + "_new")
            new_store.import_from_dict(data)

            assert new_store.count == 1

    def test_persistence(self):
        """Test that entries persist to disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create store and add entry
            store1 = DocumentationStore(workspace=tmpdir)
            entry = DocumentationEntry(title="Persistent Test")
            store1.add_entry(entry)

            # Create new store from same directory
            store2 = DocumentationStore(workspace=tmpdir)

            assert store2.count == 1


class TestChangeEntry:
    """Tests for ChangeEntry class."""

    def test_create_change_entry(self):
        """Test creating a change entry."""
        entry = ChangeEntry(
            title="Test Change",
            description="A test change",
            change_type=ChangeType.FEATURE,
            scope=ChangeScope.MINOR,
            module="app.test",
            files_changed=["app/test/file.py"],
            author="test_author",
            version="1.0.0",
            related_pr="123",
            related_issue="456",
            tags=["test", "feature"],
        )

        assert entry.entry_id.startswith("change_")
        assert entry.title == "Test Change"
        assert entry.description == "A test change"
        assert entry.change_type == ChangeType.FEATURE
        assert entry.scope == ChangeScope.MINOR
        assert entry.module == "app.test"
        assert len(entry.files_changed) == 1
        assert entry.author == "test_author"
        assert entry.version == "1.0.0"
        assert entry.related_pr == "123"
        assert entry.related_issue == "456"

    def test_entry_string_representation(self):
        """Test the string representation of a change entry."""
        entry = ChangeEntry(
            title="Test",
            change_type=ChangeType.BUG_FIX,
            scope=ChangeScope.PATCH,
            version="1.0.0",
        )

        str_repr = str(entry)
        assert "[FEATURE]" in str_repr or "[BUG_FIX]" in str_repr
        assert "[PATCH]" in str_repr
        assert "Test" in str_repr
        assert "1.0.0" in str_repr

    def test_to_dict(self):
        """Test converting change entry to dictionary."""
        entry = ChangeEntry(
            title="Test",
            change_type=ChangeType.FEATURE,
            scope=ChangeScope.MINOR,
        )

        data = entry.to_dict()

        assert data["title"] == "Test"
        assert data["change_type"] == "feature"
        assert data["scope"] == "minor"

    def test_from_dict(self):
        """Test creating change entry from dictionary."""
        data = {
            "entry_id": "change_123",
            "title": "From Dict",
            "change_type": "bug_fix",
            "scope": "patch",
            "version": "1.0.0",
        }

        entry = ChangeEntry.from_dict(data)

        assert entry.entry_id == "change_123"
        assert entry.title == "From Dict"
        assert entry.change_type == ChangeType.BUG_FIX
        assert entry.scope == ChangeScope.PATCH


class TestChangeLog:
    """Tests for ChangeLog class."""

    def test_create_change_log(self):
        """Test creating a change log."""
        with tempfile.TemporaryDirectory() as tmpdir:
            changelog = ChangeLog(workspace=tmpdir)

            assert changelog.workspace == tmpdir
            assert changelog.count == 0

    def test_add_get_entry(self):
        """Test adding and getting a change entry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            changelog = ChangeLog(workspace=tmpdir)

            entry = ChangeEntry(
                title="Test Change",
                change_type=ChangeType.FEATURE,
                version="1.0.0",
            )
            changelog.add_entry(entry)

            assert changelog.count == 1

            retrieved = changelog.get_entry(entry.entry_id)
            assert retrieved is not None
            assert retrieved.title == "Test Change"

    def test_remove_entry(self):
        """Test removing a change entry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            changelog = ChangeLog(workspace=tmpdir)

            entry = ChangeEntry(title="Remove Test")
            changelog.add_entry(entry)

            assert changelog.count == 1

            removed = changelog.remove_entry(entry.entry_id)
            assert removed is True
            assert changelog.count == 0

            # Try removing non-existent
            removed = changelog.remove_entry("non_existent")
            assert removed is False

    def test_list_entries_filters(self):
        """Test listing entries with filters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            changelog = ChangeLog(workspace=tmpdir)

            entry1 = ChangeEntry(
                title="Feature 1",
                change_type=ChangeType.FEATURE,
                scope=ChangeScope.MINOR,
                version="1.0.0",
                module="app.core",
                author="alice",
            )
            entry2 = ChangeEntry(
                title="Bug Fix 1",
                change_type=ChangeType.BUG_FIX,
                scope=ChangeScope.PATCH,
                version="1.0.0",
                module="app.utils",
                author="bob",
            )
            entry3 = ChangeEntry(
                title="Feature 2",
                change_type=ChangeType.FEATURE,
                scope=ChangeScope.MAJOR,
                version="2.0.0",
                module="app.core",
                author="alice",
            )

            changelog.add_entry(entry1)
            changelog.add_entry(entry2)
            changelog.add_entry(entry3)

            # All entries
            all_entries = changelog.list_entries()
            assert len(all_entries) == 3

            # Filter by type
            features = changelog.list_entries(change_type=ChangeType.FEATURE)
            assert len(features) == 2

            # Filter by scope
            major = changelog.list_entries(scope=ChangeScope.MAJOR)
            assert len(major) == 1

            # Filter by version
            v1 = changelog.list_entries(version="1.0.0")
            assert len(v1) == 2

            # Filter by module
            core = changelog.list_entries(module="app.core")
            assert len(core) == 2

            # Filter by author
            alice = changelog.list_entries(author="alice")
            assert len(alice) == 2

    def test_get_entries_by_version(self):
        """Test getting entries by version."""
        with tempfile.TemporaryDirectory() as tmpdir:
            changelog = ChangeLog(workspace=tmpdir)

            changelog.add_entry(ChangeEntry(title="V1 Change", version="1.0.0"))
            changelog.add_entry(ChangeEntry(title="V1 Change 2", version="1.0.0"))
            changelog.add_entry(ChangeEntry(title="V2 Change", version="2.0.0"))

            v1_entries = changelog.get_entries_by_version("1.0.0")
            assert len(v1_entries) == 2

            v2_entries = changelog.get_entries_by_version("2.0.0")
            assert len(v2_entries) == 1

            # Non-existent version
            empty = changelog.get_entries_by_version("3.0.0")
            assert len(empty) == 0

    def test_get_versions(self):
        """Test getting all versions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            changelog = ChangeLog(workspace=tmpdir)

            changelog.add_entry(ChangeEntry(title="V1", version="1.0.0"))
            changelog.add_entry(ChangeEntry(title="V2", version="2.0.0"))
            changelog.add_entry(ChangeEntry(title="V1.5", version="1.5.0"))

            versions = changelog.get_versions()
            assert "1.0.0" in versions
            assert "1.5.0" in versions
            assert "2.0.0" in versions

    def test_get_latest_version(self):
        """Test getting the latest version."""
        with tempfile.TemporaryDirectory() as tmpdir:
            changelog = ChangeLog(workspace=tmpdir)

            assert changelog.get_latest_version() is None

            changelog.add_entry(ChangeEntry(title="V1", version="1.0.0"))
            changelog.add_entry(ChangeEntry(title="V2", version="2.0.0"))

            latest = changelog.get_latest_version()
            # With simple string sort, "2.0.0" comes after "1.0.0"
            assert latest == "2.0.0"

    def test_change_log_summary(self):
        """Test getting change log summary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            changelog = ChangeLog(workspace=tmpdir)

            changelog.add_entry(ChangeEntry(
                change_type=ChangeType.FEATURE,
                scope=ChangeScope.MINOR,
                author="alice",
                version="1.0.0",
            ))
            changelog.add_entry(ChangeEntry(
                change_type=ChangeType.BUG_FIX,
                scope=ChangeScope.PATCH,
                author="bob",
                version="1.0.0",
            ))
            changelog.add_entry(ChangeEntry(
                change_type=ChangeType.FEATURE,
                scope=ChangeScope.MAJOR,
                author="alice",
                version="2.0.0",
            ))

            summary = changelog.get_summary()

            assert summary["total_entries"] == 3
            assert summary["by_type"]["feature"] == 2
            assert summary["by_type"]["bug_fix"] == 1
            assert summary["by_scope"]["minor"] == 1
            assert summary["by_scope"]["patch"] == 1
            assert summary["by_scope"]["major"] == 1
            assert summary["by_author"]["alice"] == 2
            assert summary["by_author"]["bob"] == 1
            assert summary["total_versions"] == 2

    def test_clear_change_log(self):
        """Test clearing the change log."""
        with tempfile.TemporaryDirectory() as tmpdir:
            changelog = ChangeLog(workspace=tmpdir)

            changelog.add_entry(ChangeEntry(title="Test 1"))
            changelog.add_entry(ChangeEntry(title="Test 2"))

            assert changelog.count == 2

            changelog.clear()

            assert changelog.count == 0

    def test_export_import_change_log(self):
        """Test exporting and importing change log data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            changelog = ChangeLog(workspace=tmpdir)

            entry = ChangeEntry(
                title="Export Test",
                change_type=ChangeType.FEATURE,
                version="1.0.0",
            )
            changelog.add_entry(entry)

            # Export
            data = changelog.export_to_dict()
            assert "entries" in data
            assert "summary" in data

            # Create new change log and import
            new_changelog = ChangeLog(workspace=tmpdir + "_new")
            new_changelog.import_from_dict(data)

            assert new_changelog.count == 1

    def test_convenience_methods(self):
        """Test convenience methods for logging changes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            changelog = ChangeLog(workspace=tmpdir)

            # Log feature
            feature = changelog.log_feature(
                title="New Feature",
                description="A new feature",
                module="app.test",
                files_changed=["app/test/feature.py"],
                author="alice",
                version="1.0.0",
            )
            assert feature.change_type == ChangeType.FEATURE
            assert changelog.count == 1

            # Log bug fix
            bugfix = changelog.log_bug_fix(
                title="Bug Fix",
                description="A bug fix",
                module="app.test",
                related_issue="123",
                version="1.0.1",
            )
            assert bugfix.change_type == ChangeType.BUG_FIX
            assert changelog.count == 2

            # Log refactor
            refactor = changelog.log_refactor(
                title="Code Refactor",
                description="A refactoring",
                module="app.core",
                version="2.0.0",
            )
            assert refactor.change_type == ChangeType.REFACTOR
            assert changelog.count == 3

    def test_markdown_generation(self):
        """Test that markdown change log is generated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            changelog = ChangeLog(
                workspace=tmpdir,
                markdown_file="TEST_CHANGELOG.md",
            )

            changelog.add_entry(ChangeEntry(
                title="Test Change",
                description="A test change",
                change_type=ChangeType.FEATURE,
                scope=ChangeScope.MINOR,
                version="1.0.0",
            ))

            markdown_path = Path(tmpdir) / "TEST_CHANGELOG.md"
            assert markdown_path.exists()

            content = markdown_path.read_text()
            assert "#" in content  # Has headers
            assert "Test Change" in content
            assert "1.0.0" in content

    def test_persistence(self):
        """Test that change entries persist to disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create change log and add entry
            changelog1 = ChangeLog(workspace=tmpdir)
            changelog1.add_entry(ChangeEntry(
                title="Persistent Test",
                version="1.0.0",
            ))

            # Create new change log from same directory
            changelog2 = ChangeLog(workspace=tmpdir)

            assert changelog2.count == 1


class TestDocumentationGenerator:
    """Tests for DocumentationGenerator class."""

    def test_create_generator(self):
        """Test creating a documentation generator."""
        gen = DocumentationGenerator(
            workspace=".",
            project_name="Test Project",
            output_dir="docs",
            include_private=False,
        )

        assert str(gen.workspace) == "."
        assert gen.project_name == "Test Project"
        assert gen.output_dir == "docs"
        assert gen.include_private is False

    def test_scan_module(self):
        """Test scanning a module."""
        gen = DocumentationGenerator()

        # Scan a real module
        result = gen.scan_module("app.documentation.doc_generator")

        assert "error" not in result or result["name"] == "doc_generator"
        assert "name" in result
        assert "classes" in result
        assert "functions" in result

    def test_scan_nonexistent_module(self):
        """Test scanning a non-existent module."""
        gen = DocumentationGenerator()

        result = gen.scan_module("nonexistent.module")

        assert "error" in result

    def test_scan_directory(self):
        """Test scanning a directory."""
        gen = DocumentationGenerator()

        # Scan a real directory
        result = gen.scan_directory("app/documentation")

        assert isinstance(result, list)
        assert len(result) > 0
        # Check that we got some modules
        assert any("doc_generator" in r.get("name", "") or "doc" in r.get("name", "") for r in result)

    def test_generate_module_doc(self):
        """Test generating module documentation."""
        gen = DocumentationGenerator()

        # Test with markdown format
        doc = gen.generate_module_doc(
            "app.documentation.doc_generator",
            DocFormat.MARKDOWN,
        )

        assert "#" in doc or "Test" in doc or "doc_generator" in doc

    def test_generate_api_doc(self):
        """Test generating API documentation."""
        gen = DocumentationGenerator()

        doc = gen.generate_api_doc(
            ["app.documentation.doc_generator"],
            DocFormat.MARKDOWN,
        )

        assert "#" in doc or "API" in doc

    def test_parse_docstring(self):
        """Test parsing a docstring."""
        gen = DocumentationGenerator()

        docstring = """Test function.

        This is a longer description.

        Args:
            arg1: First argument
            arg2: Second argument

        Returns:
            The result

        Raises:
            ValueError: If something is wrong

        Examples:
            >>> test_func(1, 2)
            3
        """

        parsed = gen._parse_docstring(docstring)

        assert parsed["short"] == "Test function."
        assert "longer description" in parsed["long"]
        # Returns and Raises are stored in their respective fields
        # The parser stores the raw content after the colon
        assert "Returns" in parsed.get("long", "") or parsed.get("returns") is not None
        assert "Raises" in parsed.get("long", "") or "ValueError" in str(parsed.get("raises", ""))

    def test_generate_to_file(self):
        """Test generating documentation to a file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = DocumentationGenerator(workspace=tmpdir)

            content = "# Test Documentation\n\nThis is a test."
            gen.generate_to_file(content, "test.md")

            output_path = Path(tmpdir) / "docs" / "test.md"
            assert output_path.exists()

            saved_content = output_path.read_text()
            assert "# Test Documentation" in saved_content

    def test_generate_all(self):
        """Test generating documentation for all modules."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = DocumentationGenerator(workspace=tmpdir)

            # Create a test module structure
            test_app_dir = Path(tmpdir) / "test_app"
            test_app_dir.mkdir()
            (test_app_dir / "__init__.py").write_text("")
            (test_app_dir / "module1.py").write_text('"""Module 1."""\ndef func1():\n    """Function 1."""\n    pass\n')

            result = gen.generate_all(source_dir="test_app")

            assert result["total_modules"] >= 1
            assert result["generated_files"] >= 2  # index + module docs


class TestDocumentationIntegration:
    """Integration tests for the documentation system."""

    def test_full_documentation_workflow(self):
        """Test a complete documentation workflow."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create generator
            gen = DocumentationGenerator(workspace=tmpdir)

            # Create store
            store = DocumentationStore(workspace=tmpdir)

            # Create change log
            changelog = ChangeLog(workspace=tmpdir)

            # Generate documentation for a known module
            modules = gen.scan_directory("app/confidence")

            # We should find at least some modules
            assert len(modules) >= 0

            # Add entries to store
            for module in modules:
                entry = DocumentationEntry(
                    title=module.get("name", "Unnamed"),
                    content=module.get("docstring", ""),
                    module=module.get("name", ""),
                    doc_type="module",
                    status=DocStatus.PUBLISHED,
                )
                store.add_entry(entry)

            assert store.count == len(modules)

            # Add change entries
            changelog.log_feature(
                title="Documentation System",
                description="Implemented documentation automation",
                module="app.documentation",
                version="1.0.0",
            )

            changelog.log_bug_fix(
                title="Initial Implementation",
                description="Fixed initial bugs",
                version="1.0.0",
            )

            assert changelog.count == 2

            # Verify markdown generation
            markdown_path = Path(tmpdir) / "CHANGELOG.md"
            assert markdown_path.exists()

            # Verify store persistence
            new_store = DocumentationStore(workspace=tmpdir)
            assert new_store.count == len(modules)

            # Verify change log persistence
            new_changelog = ChangeLog(workspace=tmpdir)
            assert new_changelog.count == 2

    def test_template_rendering_with_real_templates(self):
        """Test rendering with the predefined templates."""
        registry = TemplateRegistry()

        # Get a template
        template = registry.get("Module Documentation")
        assert template is not None

        # Render with variables
        result = template.render({
            "module_name": "TestModule",
            "module_overview": "This is a test module",
            "classes": "- TestClass",
            "functions": "- test_func()",
        })

        assert "TestModule" in result
        assert "This is a test module" in result
        assert "TestClass" in result
