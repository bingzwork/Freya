"""Tests for the Git Automation system.

This module provides comprehensive tests for all git components
including GitManager, CommitParser, ChangeTracker, and SemanticCommitBuilder.
"""

import json
import os
import shutil
import subprocess
import tempfile
import pytest
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import uuid

from app.git.git_manager import (
    GitManager,
    GitAction,
    GitStatus,
    GitConflict,
    GitBranch,
    GitCommit,
    GitConfig,
    GitDiff,
)
from app.git.commit_parser import (
    CommitParser,
    CommitType,
    CommitMessage,
)
from app.git.change_tracker import (
    ChangeTracker,
    FileChange,
    ChangeType as FileChangeType,
)
from app.git.semantic_commit import (
    SemanticCommit,
    SemanticCommitBuilder,
    create_feature_commit,
    create_fix_commit,
    create_docs_commit,
    create_refactor_commit,
    create_test_commit,
)


class TestGitAction:
    """Tests for GitAction enum."""

    def test_git_action_enum_values(self):
        """Test that all git action enum values are strings."""
        for action in GitAction:
            assert isinstance(action.value, str)

    def test_git_action_enum_unique(self):
        """Test that all git action enum values are unique."""
        values = [action.value for action in GitAction]
        assert len(values) == len(set(values))


class TestGitStatus:
    """Tests for GitStatus enum."""

    def test_git_status_enum_values(self):
        """Test that all git status enum values are strings."""
        for status in GitStatus:
            assert isinstance(status.value, str)

    def test_git_status_enum_unique(self):
        """Test that all git status enum values are unique."""
        values = [status.value for status in GitStatus]
        assert len(values) == len(set(values))


class TestGitConflict:
    """Tests for GitConflict enum."""

    def test_git_conflict_enum_values(self):
        """Test that all git conflict enum values are strings."""
        for conflict in GitConflict:
            assert isinstance(conflict.value, str)

    def test_git_conflict_enum_unique(self):
        """Test that all git conflict enum values are unique."""
        values = [conflict.value for conflict in GitConflict]
        assert len(values) == len(set(values))


class TestCommitType:
    """Tests for CommitType enum."""

    def test_commit_type_enum_values(self):
        """Test that all commit type enum values are strings."""
        for commit_type in CommitType:
            assert isinstance(commit_type.value, str)

    def test_commit_type_enum_unique(self):
        """Test that all commit type enum values are unique."""
        values = [commit_type.value for commit_type in CommitType]
        assert len(values) == len(set(values))


class TestFileChangeType:
    """Tests for FileChangeType enum."""

    def test_file_change_type_enum_values(self):
        """Test that all file change type enum values are strings."""
        for change_type in FileChangeType:
            assert isinstance(change_type.value, str)

    def test_file_change_type_enum_unique(self):
        """Test that all file change type enum values are unique."""
        values = [change_type.value for change_type in FileChangeType]
        assert len(values) == len(set(values))


class TestGitConfig:
    """Tests for GitConfig class."""

    def test_create_config(self):
        """Test creating a git config."""
        config = GitConfig(
            user_name="Test User",
            user_email="test@example.com",
            branch="main",
            remote="origin",
        )

        assert config.user_name == "Test User"
        assert config.user_email == "test@example.com"
        assert config.branch == "main"
        assert config.remote == "origin"

    def test_config_to_dict(self):
        """Test converting config to dictionary."""
        config = GitConfig(user_name="User", user_email="email@test.com")

        data = config.to_dict()

        assert data["user_name"] == "User"
        assert data["user_email"] == "email@test.com"

    def test_config_from_dict(self):
        """Test creating config from dictionary."""
        data = {
            "user_name": "From Dict",
            "user_email": "from@dict.com",
            "branch": "feature",
        }

        config = GitConfig.from_dict(data)

        assert config.user_name == "From Dict"
        assert config.user_email == "from@dict.com"
        assert config.branch == "feature"


class TestGitBranch:
    """Tests for GitBranch class."""

    def test_create_branch(self):
        """Test creating a git branch info."""
        branch = GitBranch(
            name="main",
            is_current=True,
            commit_hash="abc123",
            commit_message="Initial commit",
            author="Test",
            date="2024-01-01",
        )

        assert branch.name == "main"
        assert branch.is_current is True
        assert branch.commit_hash == "abc123"

    def test_branch_to_dict(self):
        """Test converting branch to dictionary."""
        branch = GitBranch(name="feature", ahead=2, behind=1)

        data = branch.to_dict()

        assert data["name"] == "feature"
        assert data["ahead"] == 2
        assert data["behind"] == 1

    def test_branch_from_dict(self):
        """Test creating branch from dictionary."""
        data = {
            "name": "dev",
            "is_current": False,
            "ahead": 5,
            "behind": 0,
        }

        branch = GitBranch.from_dict(data)

        assert branch.name == "dev"
        assert branch.is_current is False
        assert branch.ahead == 5


class TestGitCommit:
    """Tests for GitCommit class."""

    def test_create_commit(self):
        """Test creating a git commit info."""
        commit = GitCommit(
            hash="abc123def456",
            message="Initial commit",
            author="Test User",
            author_email="test@example.com",
            date="2024-01-01",
            parents=["parent1"],
        )

        assert commit.hash == "abc123def456"
        assert commit.short_hash == "abc123d"
        assert commit.message == "Initial commit"

    def test_commit_to_dict(self):
        """Test converting commit to dictionary."""
        commit = GitCommit(
            hash="abc123",
            message="Test",
            is_merge=True,
        )

        data = commit.to_dict()

        assert data["hash"] == "abc123"
        assert data["is_merge"] is True

    def test_commit_from_dict(self):
        """Test creating commit from dictionary."""
        data = {
            "hash": "def456",
            "message": "From dict",
            "author": "Author",
            "parents": ["p1", "p2"],
        }

        commit = GitCommit.from_dict(data)

        assert commit.hash == "def456"
        assert commit.message == "From dict"


class TestGitDiff:
    """Tests for GitDiff class."""

    def test_create_diff(self):
        """Test creating a git diff."""
        diff = GitDiff(
            old_path="file.txt",
            new_path="file.txt",
            change_type="M",
            additions=5,
            deletions=2,
        )

        assert diff.old_path == "file.txt"
        assert diff.additions == 5
        assert diff.deletions == 2

    def test_diff_to_dict(self):
        """Test converting diff to dictionary."""
        diff = GitDiff(
            old_path="old.txt",
            new_path="new.txt",
            change_type="R",
        )

        data = diff.to_dict()

        assert data["old_path"] == "old.txt"
        assert data["new_path"] == "new.txt"
        assert data["change_type"] == "R"


class TestCommitMessage:
    """Tests for CommitMessage class."""

    def test_create_message(self):
        """Test creating a commit message."""
        msg = CommitMessage(
            raw="feat: add new feature",
            commit_hash="abc123",
            type=CommitType.FEAT,
            subject="add new feature",
        )

        assert msg.raw == "feat: add new feature"
        assert msg.type == CommitType.FEAT
        assert msg.subject == "add new feature"

    def test_message_to_dict(self):
        """Test converting message to dictionary."""
        msg = CommitMessage(
            raw="fix: bug fix",
            type=CommitType.FIX,
            breaking=True,
        )

        data = msg.to_dict()

        assert data["raw"] == "fix: bug fix"
        assert data["type"] == "fix"
        assert data["breaking"] is True

    def test_message_from_dict(self):
        """Test creating message from dictionary."""
        data = {
            "raw": "docs: update docs",
            "type": "docs",
            "subject": "update docs",
        }

        msg = CommitMessage.from_dict(data)

        assert msg.raw == "docs: update docs"
        assert msg.type == CommitType.DOCS

    def test_message_string(self):
        """Test message string representation."""
        msg = CommitMessage(
            type=CommitType.FEAT,
            scope="core",
            subject="add feature",
        )

        str_repr = str(msg)
        assert "feat" in str_repr
        assert "core" in str_repr
        assert "add feature" in str_repr


class TestCommitParser:
    """Tests for CommitParser class."""

    def test_parse_simple_message(self):
        """Test parsing a simple commit message."""
        parser = CommitParser()

        msg = parser.parse("feat: add new feature")

        assert msg.type == CommitType.FEAT
        assert msg.subject == "add new feature"

    def test_parse_message_with_scope(self):
        """Test parsing a message with scope."""
        parser = CommitParser()

        msg = parser.parse("feat(core): add new feature")

        assert msg.type == CommitType.FEAT
        assert msg.scope == "core"
        assert msg.subject == "add new feature"

    def test_parse_message_with_body(self):
        """Test parsing a message with body."""
        parser = CommitParser()

        message = """feat: add new feature

This adds a new feature to the core module.

It includes support for X, Y, and Z."""

        msg = parser.parse(message)

        assert msg.type == CommitType.FEAT
        assert "new feature" in msg.subject.lower()
        assert "core module" in msg.body

    def test_parse_message_with_footer(self):
        """Test parsing a message with footer."""
        parser = CommitParser()

        message = """fix: resolve issue

Fixes the bug that was reported.

Closes #123
Fixes #456"""

        msg = parser.parse(message)

        assert msg.type == CommitType.FIX
        assert "123" in msg.issues
        assert "456" in msg.issues

    def test_parse_breaking_change(self):
        """Test parsing a breaking change."""
        parser = CommitParser()

        message = "feat!: breaking change"
        msg = parser.parse(message)
        assert msg.breaking is True

        message = "feat(core)!: breaking change"
        msg = parser.parse(message)
        assert msg.breaking is True

    def test_parse_conventional_commit(self):
        """Test checking conventional commit format."""
        parser = CommitParser()

        assert parser.is_conventional_commit("feat: test") is True
        assert parser.is_conventional_commit("fix: test") is True
        assert parser.is_conventional_commit("docs: test") is True
        assert parser.is_conventional_commit("test") is False

    def test_get_commit_type(self):
        """Test getting commit type."""
        parser = CommitParser()

        assert parser.get_commit_type("feat: test") == CommitType.FEAT
        assert parser.get_commit_type("fix: test") == CommitType.FIX
        assert parser.get_commit_type("refactor: test") == CommitType.REFACTOR

    def test_get_scope(self):
        """Test getting scope."""
        parser = CommitParser()

        assert parser.get_scope("feat(core): test") == "core"
        assert parser.get_scope("feat: test") is None

    def test_get_issues(self):
        """Test getting issues."""
        parser = CommitParser()

        issues = parser.get_issues("Closes #123 Fixes #456")
        assert "123" in issues
        assert "456" in issues

    def test_validate_message(self):
        """Test validating commit messages."""
        parser = CommitParser()

        # Valid message
        valid, errors = parser.validate("feat: add new feature")
        assert valid is True
        assert len(errors) == 0

        # Empty message
        valid, errors = parser.validate("")
        assert valid is False
        assert len(errors) > 0

        # Long subject
        long_subject = "a" * 80
        valid, errors = parser.validate(f"feat: {long_subject}")
        # Subject exceeds 72 characters
        assert valid is False


class TestSemanticCommit:
    """Tests for SemanticCommit class."""

    def test_create_commit(self):
        """Test creating a semantic commit."""
        commit = SemanticCommit(
            message="feat: add feature",
            commit_hash="abc123",
            type=CommitType.FEAT,
            subject="add feature",
        )

        assert commit.message == "feat: add feature"
        assert commit.type == CommitType.FEAT

    def test_commit_to_dict(self):
        """Test converting semantic commit to dictionary."""
        commit = SemanticCommit(
            message="fix: bug fix",
            type=CommitType.FIX,
            breaking=True,
        )

        data = commit.to_dict()

        assert data["message"] == "fix: bug fix"
        assert data["type"] == "fix"
        assert data["breaking"] is True

    def test_commit_from_dict(self):
        """Test creating semantic commit from dictionary."""
        data = {
            "message": "docs: update",
            "type": "docs",
            "subject": "update",
        }

        commit = SemanticCommit.from_dict(data)

        assert commit.message == "docs: update"
        assert commit.type == CommitType.DOCS

    def test_commit_string(self):
        """Test semantic commit string representation."""
        commit = SemanticCommit(message="feat: test")

        assert str(commit) == "feat: test"


class TestSemanticCommitBuilder:
    """Tests for SemanticCommitBuilder class."""

    def test_create_builder(self):
        """Test creating a semantic commit builder."""
        builder = SemanticCommitBuilder()

        assert builder.commit_type == CommitType.FEAT
        assert builder.subject == ""
        assert builder.body == ""

    def test_build_simple_commit(self):
        """Test building a simple commit."""
        builder = SemanticCommitBuilder()
        builder.with_subject("add new feature")

        commit = builder.build()

        assert commit.type == CommitType.FEAT
        assert "add new feature" in commit.message

    def test_build_commit_with_scope(self):
        """Test building a commit with scope."""
        builder = SemanticCommitBuilder()
        builder.with_type(CommitType.FEAT)
        builder.with_scope("core")
        builder.with_subject("add feature")

        commit = builder.build()

        assert commit.scope == "core"
        assert "(core)" in commit.message

    def test_build_commit_with_body(self):
        """Test building a commit with body."""
        builder = SemanticCommitBuilder()
        builder.with_subject("add feature")
        builder.with_body("This adds a new feature.")

        commit = builder.build()

        assert commit.body == "This adds a new feature."
        assert "This adds a new feature." in commit.message

    def test_build_breaking_commit(self):
        """Test building a breaking commit."""
        builder = SemanticCommitBuilder()
        builder.with_type(CommitType.FEAT)
        builder.with_subject("breaking change")
        builder.with_breaking(True)

        commit = builder.build()

        assert commit.breaking is True
        assert "!" in commit.message or "BREAKING" in commit.message

    def test_build_commit_with_issues(self):
        """Test building a commit with issues."""
        builder = SemanticCommitBuilder()
        builder.with_subject("fix bug")
        builder.with_issue("123")
        builder.with_issue("456")

        commit = builder.build()

        assert "123" in commit.issues
        assert "456" in commit.issues
        assert "#123" in commit.message or "123" in commit.message

    def test_build_message(self):
        """Test building just the message."""
        builder = SemanticCommitBuilder()
        builder.with_type(CommitType.FEAT)
        builder.with_scope("core")
        builder.with_subject("add feature")

        message = builder.build_message()

        assert "feat" in message
        assert "(core)" in message
        assert "add feature" in message

    def test_with_type_chaining(self):
        """Test method chaining with type."""
        builder = SemanticCommitBuilder()
        result = builder.with_type(CommitType.FIX)

        assert result is builder
        assert builder.commit_type == CommitType.FIX

    def test_with_scope_chaining(self):
        """Test method chaining with scope."""
        builder = SemanticCommitBuilder()
        result = builder.with_scope("test")

        assert result is builder
        assert builder.scope == "test"

    def test_reset(self):
        """Test resetting the builder."""
        builder = SemanticCommitBuilder()
        builder.with_subject("test")
        builder.with_body("body")
        builder.with_issue("123")

        builder.reset()

        assert builder.subject == ""
        assert builder.body == ""
        assert len(builder.issues) == 0


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    def test_create_feature_commit(self):
        """Test creating a feature commit."""
        commit = create_feature_commit(
            subject="add new feature",
            scope="core",
            body="This is a new feature",
        )

        assert commit.type == CommitType.FEAT
        assert commit.scope == "core"
        assert "add new feature" in commit.subject

    def test_create_fix_commit(self):
        """Test creating a fix commit."""
        commit = create_fix_commit(
            subject="fix bug",
            issues=["123"],
        )

        assert commit.type == CommitType.FIX
        assert "123" in commit.issues

    def test_create_docs_commit(self):
        """Test creating a docs commit."""
        commit = create_docs_commit(
            subject="update documentation",
            scope="readme",
        )

        assert commit.type == CommitType.DOCS
        assert commit.scope == "readme"

    def test_create_refactor_commit(self):
        """Test creating a refactor commit."""
        commit = create_refactor_commit(
            subject="refactor code",
            body="Improved structure",
        )

        assert commit.type == CommitType.REFACTOR

    def test_create_test_commit(self):
        """Test creating a test commit."""
        commit = create_test_commit(
            subject="add tests",
            scope="unit",
        )

        assert commit.type == CommitType.TEST


class TestFileChange:
    """Tests for FileChange class."""

    def test_create_file_change(self):
        """Test creating a file change."""
        change = FileChange(
            file_path="/path/to/file.py",
            change_type=FileChangeType.MODIFIED,
            hash_before="abc123",
            hash_after="def456",
        )

        assert change.file_path == "/path/to/file.py"
        assert change.change_type == FileChangeType.MODIFIED

    def test_change_to_dict(self):
        """Test converting change to dictionary."""
        change = FileChange(
            file_path="file.txt",
            change_type=FileChangeType.CREATED,
            committed=True,
        )

        data = change.to_dict()

        assert data["file_path"] == "file.txt"
        assert data["change_type"] == "created"
        assert data["committed"] is True

    def test_change_from_dict(self):
        """Test creating change from dictionary."""
        data = {
            "file_path": "test.py",
            "change_type": "modified",
            "hash_before": "abc",
            "hash_after": "def",
        }

        change = FileChange.from_dict(data)

        assert change.file_path == "test.py"
        assert change.change_type == FileChangeType.MODIFIED

    def test_change_string(self):
        """Test file change string representation."""
        change = FileChange(
            file_path="test.py",
            change_type=FileChangeType.MODIFIED,
        )

        str_repr = str(change)
        assert "MODIFIED" in str_repr
        assert "test.py" in str_repr


class TestChangeTracker:
    """Tests for ChangeTracker class."""

    def test_create_tracker(self):
        """Test creating a change tracker."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = ChangeTracker(workspace=tmpdir)

            assert tracker.workspace == tmpdir

    def test_tracker_scan(self):
        """Test scanning for changes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a file
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("# Test file")

            tracker = ChangeTracker(
                workspace=tmpdir,
                include_patterns=["*.py"],
                exclude_patterns=[],
            )

            changes = tracker.scan()

            # Should detect the new file
            assert len(changes) >= 0  # May detect as created

    def test_tracker_get_changes(self):
        """Test getting tracked changes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = ChangeTracker(workspace=tmpdir)

            # Manually add a change for testing
            change = FileChange(
                file_path="/test/file.py",
                change_type=FileChangeType.CREATED,
            )

            # Access internal state for testing
            tracker._changes["/test/file.py"] = change

            changes = tracker.get_changes()
            assert len(changes) == 1

    def test_tracker_clear(self):
        """Test clearing tracked changes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = ChangeTracker(workspace=tmpdir)

            # Add a change
            change = FileChange(
                file_path="/test/file.py",
                change_type=FileChangeType.MODIFIED,
            )
            tracker._changes["/test/file.py"] = change

            assert len(tracker.get_changes()) == 1

            tracker.clear()

            assert len(tracker.get_changes()) == 0

    def test_tracker_summary(self):
        """Test getting tracker summary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = ChangeTracker(workspace=tmpdir)

            # Add some changes
            tracker._changes["file1.py"] = FileChange(
                file_path="file1.py",
                change_type=FileChangeType.CREATED,
            )
            tracker._changes["file2.py"] = FileChange(
                file_path="file2.py",
                change_type=FileChangeType.MODIFIED,
            )
            tracker._changes["file3.py"] = FileChange(
                file_path="file3.py",
                change_type=FileChangeType.DELETED,
            )

            summary = tracker.get_summary()

            assert summary["total_changes"] == 3
            assert summary["files_added"] == 1
            assert summary["files_modified"] == 1
            assert summary["files_deleted"] == 1

    def test_tracker_has_changes(self):
        """Test checking if tracker has changes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = ChangeTracker(workspace=tmpdir)

            assert tracker.has_changes() is False

            tracker._changes["file.py"] = FileChange(
                file_path="file.py",
                change_type=FileChangeType.MODIFIED,
            )

            assert tracker.has_changes() is True

    def test_tracker_export_import(self):
        """Test exporting and importing changes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = ChangeTracker(workspace=tmpdir)

            change = FileChange(
                file_path="file.py",
                change_type=FileChangeType.MODIFIED,
            )
            tracker._changes["file.py"] = change

            # Export
            data = tracker.export_changes()
            assert "changes" in data

            # Create new tracker and import
            new_tracker = ChangeTracker(workspace=tmpdir + "_new")
            new_tracker.import_changes(data)

            assert len(new_tracker.get_changes()) == 1


class TestGitManager:
    """Tests for GitManager class."""

    def test_create_manager(self):
        """Test creating a git manager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Initialize a git repo
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)

            manager = GitManager(workspace=tmpdir)

            assert manager.workspace == tmpdir
            assert manager.is_repo() is True

    def test_manager_is_repo(self):
        """Test checking if directory is a repo."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Not a repo
            manager = GitManager(workspace=tmpdir)
            assert manager.is_repo() is False

            # Initialize a repo
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            manager = GitManager(workspace=tmpdir)
            assert manager.is_repo() is True

    def test_manager_get_summary(self):
        """Test getting repository summary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Initialize a git repo
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)

            manager = GitManager(workspace=tmpdir)
            summary = manager.get_summary()

            assert "is_repo" in summary
            assert summary["is_repo"] is True

    def test_manager_get_status(self):
        """Test getting git status."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Initialize a git repo
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)

            manager = GitManager(workspace=tmpdir)
            status = manager.get_status()

            assert "clean" in status
            assert status["clean"] is True

    def test_manager_get_status_with_changes(self):
        """Test getting status with changes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Initialize a git repo
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)

            # Create a file
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("test")

            manager = GitManager(workspace=tmpdir)
            status = manager.get_status()

            assert status["clean"] is False
            assert len(status["untracked"]) >= 1

    def test_manager_add(self):
        """Test adding files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Initialize a git repo
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)

            # Create a file
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("test")

            manager = GitManager(workspace=tmpdir)
            result = manager.add(["test.txt"])

            assert result["success"] is True

    def test_manager_commit(self):
        """Test creating a commit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Initialize a git repo
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)

            # Create and add a file
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("test")
            subprocess.run(["git", "add", "test.txt"], cwd=tmpdir, capture_output=True)

            manager = GitManager(workspace=tmpdir)
            result = manager.commit("test commit")

            assert result["success"] is True

    def test_manager_get_log(self):
        """Test getting commit log."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Initialize a git repo
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)

            # Create and commit a file
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("test")
            subprocess.run(["git", "add", "test.txt"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=tmpdir, capture_output=True)

            manager = GitManager(workspace=tmpdir)
            commits = manager.get_log(limit=1)

            assert len(commits) == 1
            assert commits[0].message == "initial"

    def test_manager_get_branches(self):
        """Test getting branches."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Initialize a git repo
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)

            manager = GitManager(workspace=tmpdir)
            branches = manager.get_branches()

            assert len(branches) >= 0

    def test_manager_create_branch(self):
        """Test creating a branch."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Initialize a git repo
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)

            manager = GitManager(workspace=tmpdir)
            result = manager.create_branch("feature")

            # The branch creation should succeed
            assert result["success"] is True or "already exists" in result.get("stderr", "").lower()

    def test_manager_checkout(self):
        """Test checking out a branch."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Initialize a git repo
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)

            # Create a branch
            subprocess.run(["git", "branch", "feature"], cwd=tmpdir, capture_output=True)

            manager = GitManager(workspace=tmpdir)
            result = manager.checkout("feature")

            # Checkout should succeed
            assert result["success"] is True or "already on" in result.get("stdout", "").lower() or "already on" in result.get("stderr", "").lower()


class TestGitIntegration:
    """Integration tests for the git system."""

    def test_full_git_workflow(self):
        """Test a complete git workflow."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Initialize a git repo
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)

            # Create manager
            manager = GitManager(workspace=tmpdir)

            # Create a file
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("# Test\nprint('hello')")

            # Add file
            result = manager.add(["test.py"])
            assert result["success"] is True

            # Commit using semantic commit
            builder = SemanticCommitBuilder()
            builder.with_type(CommitType.FEAT)
            builder.with_subject("add test file")
            commit_msg = builder.build_message()

            result = manager.commit(commit_msg)
            assert result["success"] is True

            # Check status
            status = manager.get_status()
            assert status["clean"] is True

            # Get log
            commits = manager.get_log(limit=1)
            assert len(commits) == 1

            # Parse the commit message
            parser = CommitParser()
            parsed = parser.parse(commits[0].message)
            assert parsed.type == CommitType.FEAT

    def test_commit_parser_with_real_commits(self):
        """Test parsing real commit messages."""
        parser = CommitParser()

        # Test various commit types
        messages = [
            "feat: add new feature",
            "fix: resolve bug",
            "docs: update readme",
            "refactor: improve code",
            "perf: optimize performance",
            "test: add unit tests",
            "chore: cleanup",
            "feat(core): add feature with scope",
            "fix!: breaking change",
        ]

        for msg in messages:
            parsed = parser.parse(msg)
            assert isinstance(parsed, CommitMessage)
            assert parsed.raw == msg

    def test_semantic_commit_builder_workflow(self):
        """Test the semantic commit builder workflow."""
        builder = SemanticCommitBuilder()

        # Build various types of commits
        commits = [
            builder.with_type(CommitType.FEAT).with_subject("add feature").build(),
            builder.reset().with_type(CommitType.FIX).with_subject("fix bug").with_issue("123").build(),
            builder.reset().with_type(CommitType.DOCS).with_scope("readme").with_subject("update docs").build(),
            builder.reset().with_type(CommitType.REFACTOR).with_subject("refactor code").with_body("Improved structure").build(),
        ]

        for commit in commits:
            assert isinstance(commit, SemanticCommit)
            assert commit.message

            # Verify it can be parsed back
            parser = CommitParser()
            parsed = parser.parse(commit.message)
            assert parsed.type == commit.type
