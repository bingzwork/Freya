"""Git Automation for Freya AI.

This module provides enhanced git automation with semantic commits,
change tracking, and repository management.
"""

from app.git.git_manager import (
    GitManager,
    GitAction,
    GitConflict,
    GitBranch,
    GitCommit,
    GitStatus,
    GitConfig,
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
    SemanticCommitBuilder,
    SemanticCommit,
)

__all__ = [
    "GitManager",
    "GitAction",
    "GitConflict",
    "GitBranch",
    "GitCommit",
    "GitStatus",
    "GitConfig",
    "CommitParser",
    "CommitType",
    "CommitMessage",
    "ChangeTracker",
    "FileChange",
    "FileChangeType",
    "SemanticCommitBuilder",
    "SemanticCommit",
]
