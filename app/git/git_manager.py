"""Git manager for repository operations.

This module provides a high-level interface for git operations
including status, diff, commit, push, pull, and branch management.
"""

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import uuid


class GitAction(Enum):
    """Git actions that can be performed."""
    STATUS = "status"
    DIFF = "diff"
    LOG = "log"
    ADD = "add"
    COMMIT = "commit"
    PUSH = "push"
    PULL = "pull"
    FETCH = "fetch"
    CHECKOUT = "checkout"
    BRANCH = "branch"
    MERGE = "merge"
    REBASE = "rebase"
    RESET = "reset"
    STASH = "stash"
    TAG = "tag"
    CLONE = "clone"
    INIT = "init"
    REMOTE = "remote"
    CONFIG = "config"


class GitStatus(Enum):
    """Status of a git operation or repository."""
    CLEAN = "clean"
    MODIFIED = "modified"
    STAGED = "staged"
    UNTRACKED = "untracked"
    DELETED = "deleted"
    RENAMED = "renamed"
    COPIED = "copied"
    MERGED = "merged"
    CONFLICTED = "conflicted"
    AHEAD = "ahead"
    BEHIND = "behind"
    DIVERGED = "diverged"
    DETACHED = "detached"


class GitConflict(Enum):
    """Types of git conflicts."""
    NONE = "none"
    MERGE = "merge"
    REBASE = "rebase"
    CHERRY_PICK = "cherry_pick"
    FILE = "file"


@dataclass
class GitConfig:
    """Git configuration."""
    user_name: str = ""
    user_email: str = ""
    branch: str = ""
    remote: str = "origin"
    editor: str = ""
    autocrlf: bool = False
    safecrlf: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "user_name": self.user_name,
            "user_email": self.user_email,
            "branch": self.branch,
            "remote": self.remote,
            "editor": self.editor,
            "autocrlf": self.autocrlf,
            "safecrlf": self.safecrlf,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GitConfig":
        """Create from dictionary."""
        return cls(
            user_name=data.get("user_name", ""),
            user_email=data.get("user_email", ""),
            branch=data.get("branch", ""),
            remote=data.get("remote", "origin"),
            editor=data.get("editor", ""),
            autocrlf=data.get("autocrlf", False),
            safecrlf=data.get("safecrlf", True),
        )


@dataclass
class GitBranch:
    """Information about a git branch."""
    name: str
    is_current: bool = False
    commit_hash: str = ""
    commit_message: str = ""
    author: str = ""
    date: str = ""
    is_remote: bool = False
    remote_name: str = ""
    tracking_branch: Optional[str] = None
    ahead: int = 0
    behind: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "is_current": self.is_current,
            "commit_hash": self.commit_hash,
            "commit_message": self.commit_message,
            "author": self.author,
            "date": self.date,
            "is_remote": self.is_remote,
            "remote_name": self.remote_name,
            "tracking_branch": self.tracking_branch,
            "ahead": self.ahead,
            "behind": self.behind,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GitBranch":
        """Create from dictionary."""
        return cls(
            name=data.get("name", ""),
            is_current=data.get("is_current", False),
            commit_hash=data.get("commit_hash", ""),
            commit_message=data.get("commit_message", ""),
            author=data.get("author", ""),
            date=data.get("date", ""),
            is_remote=data.get("is_remote", False),
            remote_name=data.get("remote_name", ""),
            tracking_branch=data.get("tracking_branch"),
            ahead=data.get("ahead", 0),
            behind=data.get("behind", 0),
        )


@dataclass
class GitCommit:
    """Information about a git commit."""
    hash: str
    message: str = ""
    author: str = ""
    author_email: str = ""
    date: str = ""
    committer: str = ""
    committer_email: str = ""
    commit_date: str = ""
    parents: List[str] = field(default_factory=list)
    tree: str = ""
    is_merge: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "hash": self.hash,
            "message": self.message,
            "author": self.author,
            "author_email": self.author_email,
            "date": self.date,
            "committer": self.committer,
            "committer_email": self.committer_email,
            "commit_date": self.commit_date,
            "parents": self.parents,
            "tree": self.tree,
            "is_merge": self.is_merge,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GitCommit":
        """Create from dictionary."""
        return cls(
            hash=data.get("hash", ""),
            message=data.get("message", ""),
            author=data.get("author", ""),
            author_email=data.get("author_email", ""),
            date=data.get("date", ""),
            committer=data.get("committer", ""),
            committer_email=data.get("committer_email", ""),
            commit_date=data.get("commit_date", ""),
            parents=data.get("parents", []),
            tree=data.get("tree", ""),
            is_merge=data.get("is_merge", False),
        )

    @property
    def short_hash(self) -> str:
        """Get the short hash (first 7 characters)."""
        return self.hash[:7] if self.hash else ""


@dataclass
class GitDiff:
    """Information about a git diff."""
    old_path: str = ""
    new_path: str = ""
    change_type: str = ""
    additions: int = 0
    deletions: int = 0
    hunks: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "old_path": self.old_path,
            "new_path": self.new_path,
            "change_type": self.change_type,
            "additions": self.additions,
            "deletions": self.deletions,
            "hunks": self.hunks,
        }


@dataclass
class GitManager:
    """Manages git operations for a repository."""

    workspace: Optional[str] = None
    config: GitConfig = field(default_factory=GitConfig)

    def __post_init__(self):
        self._workspace_path = Path(self.workspace) if self.workspace else Path.cwd()
        self._git_path = self._find_git_executable()
        self._load_config()

    def _find_git_executable(self) -> Path:
        """Find the git executable."""
        # Try common locations
        for name in ["git", "git.exe"]:
            try:
                result = subprocess.run(
                    [name, "--version"],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    return Path(name)
            except FileNotFoundError:
                continue

        # Try in PATH
        import shutil
        git_path = shutil.which("git")
        if git_path:
            return Path(git_path)

        raise RuntimeError("Git executable not found")

    def _load_config(self) -> None:
        """Load git configuration."""
        try:
            # Get user name
            result = self._run_git(["config", "user.name"])
            if result and result.stdout:
                self.config.user_name = result.stdout.strip()

            # Get user email
            result = self._run_git(["config", "user.email"])
            if result and result.stdout:
                self.config.user_email = result.stdout.strip()

            # Get current branch
            result = self._run_git(["branch", "--show-current"])
            if result and result.stdout:
                self.config.branch = result.stdout.strip()

        except Exception:
            pass

    def _run_git(self, args: List[str], cwd: Optional[Path] = None):
        """Run a git command.

        Args:
            args: Git command arguments
            cwd: Working directory (defaults to workspace)

        Returns:
            CompletedProcess with the result
        """
        cmd = [str(self._git_path)] + args
        working_dir = cwd or self._workspace_path

        try:
            result = subprocess.run(
                cmd,
                cwd=working_dir,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Git command timed out: {' '.join(args)}")
        except Exception as e:
            raise RuntimeError(f"Git command failed: {e}")

        return result

    def get_status(self) -> Dict[str, Any]:
        """Get the current git status.

        Returns:
            Dictionary with status information
        """
        result = self._run_git(["status", "--porcelain", "-z"])

        status: Dict[str, Any] = {
            "staged": [],
            "unstaged": [],
            "untracked": [],
            "ahead": 0,
            "behind": 0,
            "branch": self.config.branch,
        }

        if not result.stdout:
            status["clean"] = True
            return status

        # Parse porcelain status output
        lines = result.stdout.strip().split("\x00") if "\x00" in result.stdout else result.stdout.strip().split("\n")

        for i in range(0, len(lines) - 1, 2):
            change_type = lines[i]
            file_path = lines[i + 1]

            if change_type.startswith("A"):
                status["staged"].append(file_path)
            elif change_type.startswith("M"):
                if len(change_type) > 1 and change_type[1] == "M":
                    status["staged"].append(file_path)
                    status["unstaged"].append(file_path)
                else:
                    status["staged"].append(file_path)
            elif change_type.startswith("D"):
                status["staged"].append(file_path)
            elif change_type.startswith("?"):
                status["untracked"].append(file_path)
            elif change_type.startswith(""):
                status["untracked"].append(file_path)

        # Check ahead/behind
        try:
            result = self._run_git(["rev-list", "--left-right", "--count", f"{self.config.branch}...origin/{self.config.branch}"])
            if result.stdout:
                parts = result.stdout.strip().split("\t")
                status["ahead"] = int(parts[0]) if parts else 0
                status["behind"] = int(parts[1]) if len(parts) > 1 else 0
        except Exception:
            pass

        status["clean"] = (
            len(status["staged"]) == 0
            and len(status["unstaged"]) == 0
            and len(status["untracked"]) == 0
        )

        return status

    def get_diff(self, file_path: Optional[str] = None, staged: bool = False, unified: int = 3) -> List[GitDiff]:
        """Get the diff for files.

        Args:
            file_path: Specific file to diff (None for all)
            staged: If True, show staged changes
            unified: Number of context lines

        Returns:
            List of GitDiff objects
        """
        args = ["diff", f"-U{unified}", "--no-color"]
        if staged:
            args.insert(1, "--cached")
        if file_path:
            args.append(file_path)

        result = self._run_git(args)
        return self._parse_diff(result.stdout)

    def _parse_diff(self, diff_output: str) -> List[GitDiff]:
        """Parse git diff output."""
        diffs = []
        if not diff_output:
            return diffs

        lines = diff_output.split("\n")
        current_diff: Optional[GitDiff] = None

        for line in lines:
            if line.startswith("diff --git"):
                # New diff
                if current_diff:
                    diffs.append(current_diff)
                current_diff = GitDiff()
                parts = line.split()
                if len(parts) >= 3:
                    current_diff.old_path = parts[2]
                if len(parts) >= 4:
                    current_diff.new_path = parts[3]
            elif line.startswith("@@"):
                # New hunk
                if current_diff:
                    current_diff.hunks.append({"header": line})
            elif line.startswith("+") and not line.startswith("+++"):
                if current_diff:
                    current_diff.additions += 1
            elif line.startswith("-") and not line.startswith("---"):
                if current_diff:
                    current_diff.deletions += 1

        if current_diff:
            diffs.append(current_diff)

        return diffs

    def get_log(self, limit: int = 10, oneline: bool = False, all_branches: bool = False) -> List[GitCommit]:
        """Get commit log.

        Args:
            limit: Maximum number of commits
            oneline: If True, use oneline format
            all_branches: If True, include all branches

        Returns:
            List of GitCommit objects
        """
        args = ["log"]
        if oneline:
            args.append("--oneline")
        if all_branches:
            args.append("--all")
        args.extend([f"-n{limit}", "--no-color"])

        result = self._run_git(args)
        return self._parse_log(result.stdout)

    def _parse_log(self, log_output: str) -> List[GitCommit]:
        """Parse git log output."""
        commits = []
        if not log_output:
            return commits

        lines = log_output.split("\n")
        current_commit: Optional[GitCommit] = None

        for line in lines:
            if line.startswith("commit "):
                # New commit
                if current_commit:
                    commits.append(current_commit)
                hash_value = line[7:].strip()
                current_commit = GitCommit(hash=hash_value)
            elif line.startswith("Merge:"):
                if current_commit:
                    current_commit.is_merge = True
            elif line.startswith("Author:"):
                if current_commit:
                    parts = line[7:].strip().split("<", 1)
                    current_commit.author = parts[0].strip()
                    if len(parts) > 1:
                        current_commit.author_email = parts[1].rstrip(">").strip()
            elif line.startswith("Date:"):
                if current_commit:
                    current_commit.date = line[6:].strip()
            elif line.startswith("    "):
                if current_commit and not current_commit.message:
                    current_commit.message = line[4:].strip()

        if current_commit:
            commits.append(current_commit)

        return commits

    def get_branches(self, all_branches: bool = True) -> List[GitBranch]:
        """Get list of branches.

        Args:
            all_branches: If True, include remote branches

        Returns:
            List of GitBranch objects
        """
        branches = []

        # Get local branches
        result = self._run_git(["branch", "-v"])
        if result.stdout:
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue

                is_current = line.startswith("*")
                name = line[1:].strip() if is_current else line.strip()

                # Extract commit info
                commit_info = ""
                if " " in name:
                    name, commit_info = name.rsplit(" ", 1)

                branch = GitBranch(
                    name=name,
                    is_current=is_current,
                    commit_message=commit_info,
                    is_remote=False,
                )
                branches.append(branch)

        # Get remote branches
        if all_branches:
            try:
                result = self._run_git(["branch", "-r", "-v"])
                if result.stdout:
                    for line in result.stdout.strip().split("\n"):
                        line = line.strip()
                        if not line:
                            continue

                        parts = line.split()
                        if len(parts) >= 2:
                            name = parts[0]
                            if name.startswith("origin/"):
                                remote_name = name[len("origin/"):]
                                commit_info = " ".join(parts[1:])

                                branch = GitBranch(
                                    name=remote_name,
                                    is_remote=True,
                                    remote_name="origin",
                                    commit_message=commit_info,
                                )
                                branches.append(branch)
            except Exception:
                pass

        return branches

    def get_current_branch(self) -> GitBranch:
        """Get the current branch.

        Returns:
            GitBranch for the current branch
        """
        result = self._run_git(["branch", "--show-current"])
        if result.stdout:
            name = result.stdout.strip()
            return GitBranch(name=name, is_current=True)
        return GitBranch(name="", is_current=True)

    def add(self, file_paths: List[str]) -> Dict[str, Any]:
        """Add files to staging area.

        Args:
            file_paths: List of file paths to add

        Returns:
            Result dictionary
        """
        args = ["add"] + file_paths
        result = self._run_git(args)

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def commit(self, message: str, all_files: bool = False, allow_empty: bool = False, amend: bool = False) -> Dict[str, Any]:
        """Create a commit.

        Args:
            message: Commit message
            all_files: If True, commit all files (including untracked)
            allow_empty: If True, allow empty commits
            amend: If True, amend the previous commit

        Returns:
            Result dictionary
        """
        args = ["commit"]
        if allow_empty:
            args.append("--allow-empty")
        if amend:
            args.append("--amend")
        if all_files:
            args.append("-a")
        args.append("-m")
        args.append(message)

        result = self._run_git(args)

        return {
            "success": result.returncode == 0,
            "hash": self._extract_hash(result.stdout) if result.stdout else "",
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def _extract_hash(self, output: str) -> str:
        """Extract commit hash from output."""
        # Look for commit hash in output
        match = re.search(r"\[([a-f0-9]{7,})\]", output)
        if match:
            return match.group(1)
        return ""

    def push(self, remote: str = "origin", branch: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
        """Push changes to remote.

        Args:
            remote: Remote name
            branch: Branch to push (defaults to current)
            force: If True, force push

        Returns:
            Result dictionary
        """
        args = ["push"]
        if force:
            args.append("--force")
        target_branch = branch or self.config.branch
        if target_branch:
            args.append(f"{remote} {target_branch}")
        else:
            args.append(remote)

        result = self._run_git(args)

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def pull(self, remote: str = "origin", branch: Optional[str] = None, rebase: bool = False) -> Dict[str, Any]:
        """Pull changes from remote.

        Args:
            remote: Remote name
            branch: Branch to pull (defaults to current)
            rebase: If True, rebase instead of merge

        Returns:
            Result dictionary
        """
        args = ["pull"]
        if rebase:
            args.append("--rebase")
        target_branch = branch or self.config.branch
        if target_branch:
            args.append(f"{remote} {target_branch}")
        else:
            args.append(remote)

        result = self._run_git(args)

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def fetch(self, remote: str = "origin", all_branches: bool = False) -> Dict[str, Any]:
        """Fetch changes from remote.

        Args:
            remote: Remote name
            all_branches: If True, fetch all branches

        Returns:
            Result dictionary
        """
        args = ["fetch"]
        if all_branches:
            args.append("--all")
        args.append(remote)

        result = self._run_git(args)

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def checkout(self, ref: str, create_branch: bool = False) -> Dict[str, Any]:
        """Checkout a branch or commit.

        Args:
            ref: Branch name, tag, or commit hash
            create_branch: If True, create the branch

        Returns:
            Result dictionary
        """
        args = ["checkout"]
        if create_branch:
            args.append("-b")
        args.append(ref)

        result = self._run_git(args)

        if result.returncode == 0 and create_branch:
            self.config.branch = ref

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def create_branch(self, name: str, from_branch: Optional[str] = None) -> Dict[str, Any]:
        """Create a new branch.

        Args:
            name: New branch name
            from_branch: Branch to create from (defaults to current)

        Returns:
            Result dictionary
        """
        args = ["branch", name]
        if from_branch:
            args.append(from_branch)

        result = self._run_git(args)

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def delete_branch(self, name: str, force: bool = False) -> Dict[str, Any]:
        """Delete a branch.

        Args:
            name: Branch name to delete
            force: If True, force delete

        Returns:
            Result dictionary
        """
        args = ["branch", "-D" if force else "-d", name]
        result = self._run_git(args)

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def merge(self, branch: str, no_ff: bool = False, squash: bool = False) -> Dict[str, Any]:
        """Merge a branch.

        Args:
            branch: Branch to merge
            no_ff: If True, no fast-forward
            squash: If True, squash commits

        Returns:
            Result dictionary
        """
        args = ["merge"]
        if no_ff:
            args.append("--no-ff")
        if squash:
            args.append("--squash")
        args.append(branch)

        result = self._run_git(args)

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "conflict": result.returncode != 0 and "CONFLICT" in result.stdout or result.returncode != 0 and "conflict" in result.stderr.lower(),
        }

    def get_config(self) -> GitConfig:
        """Get the current git configuration.

        Returns:
            GitConfig object
        """
        return self.config

    def get_remotes(self) -> List[str]:
        """Get list of remotes.

        Returns:
            List of remote names
        """
        result = self._run_git(["remote"])
        if result.stdout:
            return [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
        return []

    def get_tags(self) -> List[str]:
        """Get list of tags.

        Returns:
            List of tag names
        """
        result = self._run_git(["tag"])
        if result.stdout:
            return [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
        return []

    def is_repo(self) -> bool:
        """Check if the current directory is a git repository.

        Returns:
            True if it's a git repository, False otherwise
        """
        return (self._workspace_path / ".git").exists()

    def is_clean(self) -> bool:
        """Check if the repository is clean.

        Returns:
            True if clean, False otherwise
        """
        status = self.get_status()
        return status.get("clean", False)

    def has_changes(self) -> bool:
        """Check if there are any changes.

        Returns:
            True if there are changes, False otherwise
        """
        return not self.is_clean()

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the git repository state.

        Returns:
            Summary dictionary
        """
        status = self.get_status()
        branches = self.get_branches()
        remotes = self.get_remotes()

        return {
            "is_repo": self.is_repo(),
            "is_clean": status.get("clean", False),
            "current_branch": self.config.branch,
            "branches": [b.to_dict() for b in branches],
            "remotes": remotes,
            "status": status,
            "has_changes": self.has_changes(),
        }
