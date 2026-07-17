"""Git operations as workspace-safe tools."""

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GitStatusResult:
    """Structured result for git status."""
    is_repo: bool
    branch: str
    staged: list[str]
    unstaged: list[str]
    untracked: list[str]
    clean: bool
    error: str = ""


@dataclass(frozen=True)
class GitDiffResult:
    """Structured result for git diff."""
    path: str
    diff: str
    staged: bool
    error: str = ""


@dataclass(frozen=True)
class GitLogResult:
    """Structured result for git log."""
    commits: list[dict[str, str]]
    count: int
    error: str = ""


@dataclass(frozen=True)
class GitOperationResult:
    """Structured result for git operations (add, commit, push, pull)."""
    success: bool
    output: str
    error: str = ""


class GitError(Exception):
    """Raised when a git operation fails."""
    pass


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a git command in the specified working directory."""
    result = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result


def _git_available() -> bool:
    """Check if git CLI is available."""
    result = subprocess.run(
        ["git", "--version"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _find_repo_root(start_path: Path, workspace_path: Path | None = None) -> Path | None:
    """Find the git repository root starting from a path.

    If workspace_path is provided, will not search above it.
    """
    check_path = start_path
    while True:
        git_dir = check_path / ".git"
        if git_dir.exists() and git_dir.is_dir():
            return check_path
        parent = check_path.parent
        if parent == check_path:
            break
        # If workspace_path is provided, don't go above it
        if workspace_path is not None:
            try:
                parent.relative_to(workspace_path)
            except ValueError:
                break
        check_path = parent
    return None


def git_status(workspace: str, path: str = ".") -> GitStatusResult:
    """Get git status for a path within the workspace.

    Args:
        workspace: The workspace root path (used for safety).
        path: The path to check (relative to workspace, or "." for whole repo).

    Returns:
        GitStatusResult with staged, unstaged, untracked files.
    """
    workspace_path = Path(workspace).resolve()
    target_path = (workspace_path / path).resolve()

    if not _git_available():
        return GitStatusResult(
            is_repo=False,
            branch="",
            staged=[],
            unstaged=[],
            untracked=[],
            clean=False,
            error="git CLI not available",
        )

    # Verify target is within workspace
    try:
        target_path.relative_to(workspace_path)
    except ValueError:
        return GitStatusResult(
            is_repo=False,
            branch="",
            staged=[],
            unstaged=[],
            untracked=[],
            clean=False,
            error="Path outside workspace",
        )

    # Find repo root starting from workspace (not from target)
    repo_path = _find_repo_root(workspace_path, workspace_path)
    if repo_path is None:
        return GitStatusResult(
            is_repo=False,
            branch="",
            staged=[],
            unstaged=[],
            untracked=[],
            clean=False,
            error="Not a git repository",
        )

    # Get status in porcelain format
    result = _run_git(["status", "--porcelain"], cwd=repo_path)

    if result.returncode != 0:
        return GitStatusResult(
            is_repo=True,
            branch="",
            staged=[],
            unstaged=[],
            untracked=[],
            clean=True,
            error=result.stderr.strip(),
        )

    # Parse porcelain output
    staged = []
    unstaged = []
    untracked = []

    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        # Porcelain format: <index_status><workspace_status> <space> <filename>
        # The first two characters are status codes, everything after is the path
        # We need to find the first space to separate status from path
        first_space = line.find(" ", 2)  # Look for space after position 2
        if first_space == -1:
            # No space found, take everything after position 2
            status = line[:2] if len(line) >= 2 else line
            filepath = line[2:] if len(line) >= 2 else ""
        else:
            status = line[:2]
            filepath = line[first_space + 1:]

        # Convert to relative path from workspace
        try:
            file_path = str(Path(filepath).relative_to(workspace_path))
        except ValueError:
            file_path = filepath

        if status.startswith("??"):
            untracked.append(file_path)
        else:
            if status[0] != " " and status[0] != "?":
                staged.append(file_path)
            if status[1] != " " and status[1] != "?":
                unstaged.append(file_path)

    # Get current branch
    branch_result = _run_git(["branch", "--show-current"], cwd=repo_path)
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else ""

    return GitStatusResult(
        is_repo=True,
        branch=branch,
        staged=staged,
        unstaged=unstaged,
        untracked=untracked,
        clean=not (staged or unstaged or untracked),
        error="",
    )


def git_diff(workspace: str, path: str, staged: bool = False) -> GitDiffResult:
    """Get git diff for a file.

    Args:
        workspace: The workspace root path.
        path: The file path (relative to workspace).
        staged: If True, show staged diff; otherwise, show unstaged.

    Returns:
        GitDiffResult with the diff content.
    """
    workspace_path = Path(workspace).resolve()
    target_path = (workspace_path / path).resolve()

    if not _git_available():
        return GitDiffResult(
            path=path,
            diff="",
            staged=False,
            error="git CLI not available",
        )

    # Verify target is within workspace
    try:
        target_path.relative_to(workspace_path)
    except ValueError:
        return GitDiffResult(
            path=path,
            diff="",
            staged=False,
            error="Path outside workspace",
        )

    # Find repo root from workspace
    repo_path = _find_repo_root(workspace_path, workspace_path)
    if repo_path is None:
        return GitDiffResult(
            path=path,
            diff="",
            staged=False,
            error="Not a git repository",
        )

    # Get relative path from repo
    try:
        relative_path = target_path.relative_to(repo_path)
    except ValueError:
        return GitDiffResult(
            path=path,
            diff="",
            staged=staged,
            error="Path outside git repository",
        )

    cache_arg = "--cached" if staged else ""
    args = ["diff", cache_arg, str(relative_path)]
    # Filter out empty args
    args = [a for a in args if a]

    result = _run_git(args, cwd=repo_path)

    if result.returncode != 0:
        return GitDiffResult(
            path=path,
            diff="",
            staged=staged,
            error=result.stderr.strip(),
        )

    return GitDiffResult(
        path=path,
        diff=result.stdout,
        staged=staged,
        error="",
    )


def git_log(workspace: str, path: str = ".", limit: int = 10) -> GitLogResult:
    """Get commit history for a path.

    Args:
        workspace: The workspace root path.
        path: The path to get history for (relative to workspace, "." for whole repo).
        limit: Maximum number of commits to return.

    Returns:
        GitLogResult with list of commits.
    """
    workspace_path = Path(workspace).resolve()

    if not _git_available():
        return GitLogResult(
            commits=[],
            count=0,
            error="git CLI not available",
        )

    repo_path = _find_repo_root(workspace_path, workspace_path)
    if repo_path is None:
        return GitLogResult(
            commits=[],
            count=0,
            error="Not a git repository",
        )

    target_path = (workspace_path / path).resolve()

    try:
        relative_path = target_path.relative_to(repo_path)
    except ValueError:
        relative_path = "."

    # Use --format for machine-readable output
    result = _run_git(
        [
            "log",
            f"--max-count={limit}",
            "--format=%H|%an|%ad|%s",
            "--date=iso",
            str(relative_path),
        ],
        cwd=repo_path,
    )

    if result.returncode != 0:
        return GitLogResult(
            commits=[],
            count=0,
            error=result.stderr.strip(),
        )

    commits = []
    for line in result.stdout.strip().splitlines():
        if "|" in line:
            parts = line.split("|", 3)
            hash_val = parts[0].strip() if len(parts) > 0 else ""
            author = parts[1].strip() if len(parts) > 1 else ""
            date = parts[2].strip() if len(parts) > 2 else ""
            message = parts[3].strip() if len(parts) > 3 else ""
            commits.append({
                "hash": hash_val,
                "author": author,
                "date": date,
                "message": message,
            })

    return GitLogResult(
        commits=commits,
        count=len(commits),
        error="",
    )


def git_add(workspace: str, path: str) -> GitOperationResult:
    """Stage a file for commit.

    Args:
        workspace: The workspace root path.
        path: The file path to stage (relative to workspace).

    Returns:
        GitOperationResult with success status.
    """
    workspace_path = Path(workspace).resolve()
    target_path = (workspace_path / path).resolve()

    if not _git_available():
        return GitOperationResult(
            success=False,
            output="",
            error="git CLI not available",
        )

    # Verify target is within workspace
    try:
        target_path.relative_to(workspace_path)
    except ValueError:
        return GitOperationResult(
            success=False,
            output="",
            error="Path outside workspace",
        )

    repo_path = _find_repo_root(workspace_path, workspace_path)
    if repo_path is None:
        return GitOperationResult(
            success=False,
            output="",
            error="Not a git repository",
        )

    try:
        relative_path = target_path.relative_to(repo_path)
    except ValueError:
        return GitOperationResult(
            success=False,
            output="",
            error="Path outside git repository",
        )

    result = _run_git(["add", str(relative_path)], cwd=repo_path)

    if result.returncode != 0:
        return GitOperationResult(
            success=False,
            output="",
            error=result.stderr.strip(),
        )

    return GitOperationResult(
        success=True,
        output=result.stdout.strip(),
        error="",
    )


def git_commit(workspace: str, message: str, all_files: bool = False) -> GitOperationResult:
    """Commit staged changes.

    Args:
        workspace: The workspace root path.
        message: The commit message.
        all_files: If True, commit all tracked files; otherwise, only staged.

    Returns:
        GitOperationResult with success status.
    """
    workspace_path = Path(workspace).resolve()

    if not _git_available():
        return GitOperationResult(
            success=False,
            output="",
            error="git CLI not available",
        )

    repo_path = _find_repo_root(workspace_path, workspace_path)
    if repo_path is None:
        return GitOperationResult(
            success=False,
            output="",
            error="Not a git repository",
        )

    args = ["commit", "-m", message]
    if all_files:
        args.append("--all")

    # Set git author if not configured
    env = dict(os.environ)
    if "GIT_AUTHOR_NAME" not in env:
        env["GIT_AUTHOR_NAME"] = "Freya AI"
    if "GIT_AUTHOR_EMAIL" not in env:
        env["GIT_AUTHOR_EMAIL"] = "freya@ai.local"

    result = subprocess.run(
        ["git"] + args,
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )

    if result.returncode != 0:
        return GitOperationResult(
            success=False,
            output="",
            error=result.stderr.strip(),
        )

    return GitOperationResult(
        success=True,
        output=result.stdout.strip(),
        error="",
    )


def git_push(workspace: str, branch: str = "") -> GitOperationResult:
    """Push to remote repository.

    Args:
        workspace: The workspace root path.
        branch: The branch to push (defaults to current branch).

    Returns:
        GitOperationResult with success status.
    """
    workspace_path = Path(workspace).resolve()

    if not _git_available():
        return GitOperationResult(
            success=False,
            output="",
            error="git CLI not available",
        )

    repo_path = _find_repo_root(workspace_path, workspace_path)
    if repo_path is None:
        return GitOperationResult(
            success=False,
            output="",
            error="Not a git repository",
        )

    args = ["push"]
    if branch:
        args.append(branch)

    result = _run_git(args, cwd=repo_path)

    if result.returncode != 0:
        return GitOperationResult(
            success=False,
            output="",
            error=result.stderr.strip(),
        )

    return GitOperationResult(
        success=True,
        output=result.stdout.strip(),
        error="",
    )


def git_pull(workspace: str, branch: str = "") -> GitOperationResult:
    """Pull from remote repository.

    Args:
        workspace: The workspace root path.
        branch: The branch to pull (defaults to current branch).

    Returns:
        GitOperationResult with success status.
    """
    workspace_path = Path(workspace).resolve()

    if not _git_available():
        return GitOperationResult(
            success=False,
            output="",
            error="git CLI not available",
        )

    repo_path = _find_repo_root(workspace_path, workspace_path)
    if repo_path is None:
        return GitOperationResult(
            success=False,
            output="",
            error="Not a git repository",
        )

    args = ["pull"]
    if branch:
        args.append(branch)

    result = _run_git(args, cwd=repo_path)

    if result.returncode != 0:
        return GitOperationResult(
            success=False,
            output="",
            error=result.stderr.strip(),
        )

    return GitOperationResult(
        success=True,
        output=result.stdout.strip(),
        error="",
    )


def git_checkout(workspace: str, branch: str) -> GitOperationResult:
    """Switch to a branch or create a new one.

    Args:
        workspace: The workspace root path.
        branch: The branch to switch to, or "-b new-branch" to create.

    Returns:
        GitOperationResult with success status.
    """
    workspace_path = Path(workspace).resolve()

    if not _git_available():
        return GitOperationResult(
            success=False,
            output="",
            error="git CLI not available",
        )

    repo_path = _find_repo_root(workspace_path, workspace_path)
    if repo_path is None:
        return GitOperationResult(
            success=False,
            output="",
            error="Not a git repository",
        )

    args = ["checkout"] + branch.split()

    result = _run_git(args, cwd=repo_path)

    if result.returncode != 0:
        return GitOperationResult(
            success=False,
            output="",
            error=result.stderr.strip(),
        )

    return GitOperationResult(
        success=True,
        output=result.stdout.strip(),
        error="",
    )


def git_branch_list(workspace: str) -> list[str]:
    """List all branches in the repository.

    Args:
        workspace: The workspace root path.

    Returns:
        List of branch names.
    """
    workspace_path = Path(workspace).resolve()

    if not _git_available():
        return []

    repo_path = _find_repo_root(workspace_path, workspace_path)
    if repo_path is None:
        return []

    result = _run_git(["branch", "-a"], cwd=repo_path)

    if result.returncode != 0:
        return []

    # Parse branch list (lines starting with *)
    branches = []
    for line in result.stdout.strip().splitlines():
        branch = line.strip()
        if branch.startswith("* "):
            branch = branch[2:]
        elif branch.startswith("remotes/"):
            # Skip remote branches for now
            continue
        branches.append(branch)

    return branches


def git_is_repo(workspace: str, path: str = ".") -> bool:
    """Check if a path is a git repository.

    Args:
        workspace: The workspace root path.
        path: The path to check (relative to workspace).

    Returns:
        True if the path is a git repository.
    """
    workspace_path = Path(workspace).resolve()
    target_path = (workspace_path / path).resolve()

    try:
        target_path.relative_to(workspace_path)
    except ValueError:
        return False

    # Only check within workspace, not parent directories
    check_path = target_path
    while True:
        git_dir = check_path / ".git"
        if git_dir.exists() and git_dir.is_dir():
            return True
        parent = check_path.parent
        if parent == check_path:
            break
        # Don't go above workspace
        try:
            parent.relative_to(workspace_path)
        except ValueError:
            break
        check_path = parent

    return False
