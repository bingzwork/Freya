"""Tests for git_tools module."""

import subprocess
from pathlib import Path

import pytest

from app.core.tool_manager import ToolManager


def is_git_available():
    """Check if git is available on the system."""
    result = subprocess.run(
        ["git", "--version"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a temporary git repository for testing."""
    # Initialize git repo
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path,
        capture_output=True,
        check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=tmp_path,
        capture_output=True,
        check=True
    )

    # Create a test file and commit it
    (tmp_path / "test.txt").write_text("original content")
    subprocess.run(["git", "add", "test.txt"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=tmp_path,
        capture_output=True,
        check=True
    )

    return tmp_path


@pytest.fixture
def non_git_dir(tmp_path: Path) -> Path:
    """Create a directory that is not a git repository."""
    # Create a subdirectory that won't have .git
    subdir = tmp_path / "non_git"
    subdir.mkdir()
    (subdir / "file.txt").write_text("content")
    return subdir


@pytest.mark.skipif(not is_git_available(), reason="git CLI not available")
class TestGitTools:

    def test_git_is_repo_true(self, git_repo: Path) -> None:
        tools = ToolManager(str(git_repo))
        result = tools.execute("git_is_repo")
        assert result.success
        assert result.output is True

    def test_git_is_repo_false(self, non_git_dir: Path) -> None:
        tools = ToolManager(str(non_git_dir))
        result = tools.execute("git_is_repo")
        assert result.success
        assert result.output is False

    def test_git_status(self, git_repo: Path) -> None:
        tools = ToolManager(str(git_repo))
        result = tools.execute("git_status")
        assert result.success
        status = result.output
        assert status.is_repo is True
        assert status.branch == "master"  # Default branch name
        assert status.clean is True  # Only initial commit, no changes

    def test_git_status_with_changes(self, git_repo: Path) -> None:
        # Modify a file
        (git_repo / "test.txt").write_text("modified content")

        tools = ToolManager(str(git_repo))
        result = tools.execute("git_status")
        assert result.success
        status = result.output
        assert status.is_repo is True
        assert status.clean is False
        # File should appear in either unstaged or staged
        assert "test.txt" in status.unstaged or "test.txt" in status.staged

    def test_git_diff_no_changes(self, git_repo: Path) -> None:
        tools = ToolManager(str(git_repo))
        result = tools.execute("git_diff", path="test.txt")
        assert result.success
        diff_result = result.output
        assert diff_result.diff == ""

    def test_git_diff_with_changes(self, git_repo: Path) -> None:
        (git_repo / "test.txt").write_text("modified content")

        tools = ToolManager(str(git_repo))
        result = tools.execute("git_diff", path="test.txt")
        assert result.success
        diff_result = result.output
        assert "original content" in diff_result.diff
        assert "modified content" in diff_result.diff

    def test_git_log(self, git_repo: Path) -> None:
        tools = ToolManager(str(git_repo))
        result = tools.execute("git_log", limit=5)
        assert result.success
        log_result = result.output
        assert log_result.count >= 1
        assert len(log_result.commits) >= 1
        assert log_result.commits[0]["message"] == "Initial commit"

    def test_git_add(self, git_repo: Path) -> None:
        # Create a new file
        (git_repo / "new.txt").write_text("new content")

        tools = ToolManager(str(git_repo))
        result = tools.execute("git_add", path="new.txt")
        assert result.success

        # Check status - file should now be staged
        status_result = tools.execute("git_status")
        assert status_result.success
        assert "new.txt" in status_result.output.staged

    def test_git_commit(self, git_repo: Path) -> None:
        # Create and add a new file
        (git_repo / "commit_test.txt").write_text("commit test")
        tools = ToolManager(str(git_repo))
        tools.execute("git_add", path="commit_test.txt")

        # Commit
        result = tools.execute("git_commit", message="Test commit")
        assert result.success

        # Verify commit was created
        log_result = tools.execute("git_log")
        assert log_result.success
        assert len(log_result.output.commits) >= 2
        assert log_result.output.commits[0]["message"] == "Test commit"

    def test_git_branch_list(self, git_repo: Path) -> None:
        tools = ToolManager(str(git_repo))
        result = tools.execute("git_branch_list")
        assert result.success
        branches = result.output
        assert isinstance(branches, list)
        assert len(branches) >= 1
        # Check that master or main is in the list
        assert any(b in branches for b in ["master", "main"])

    def test_git_checkout_new_branch(self, git_repo: Path) -> None:
        tools = ToolManager(str(git_repo))

        # Create a new branch using -b flag
        result = tools.execute("git_checkout", branch="-b new-branch")
        assert result.success

        # Verify we're on the new branch
        status_result = tools.execute("git_status")
        assert status_result.success
        assert status_result.output.branch == "new-branch"


@pytest.mark.skipif(not is_git_available(), reason="git CLI not available")
class TestGitToolsWorkspaceSafety:

    def test_git_tools_path_outside_workspace(self, tmp_path: Path) -> None:
        tools = ToolManager(str(tmp_path))

        # Try to access a path outside workspace
        result = tools.execute("git_is_repo", path="../outside")
        assert result.success
        # Should return False since we can't go outside workspace
        assert result.output is False


@pytest.mark.skipif(not is_git_available(), reason="git CLI not available")
class TestGitToolsErrorHandling:

    def test_git_tools_not_git_repo(self, non_git_dir: Path) -> None:
        tools = ToolManager(str(non_git_dir))

        result = tools.execute("git_status")
        assert result.success
        assert result.output.is_repo is False

    def test_git_diff_not_git_repo(self, non_git_dir: Path) -> None:
        tools = ToolManager(str(non_git_dir))

        result = tools.execute("git_diff", path="file.txt")
        assert result.success
        assert "Not a git repository" in result.output.error or result.output.error == ""
