"""Semantic commit builder for creating standardized commit messages.

This module provides a builder for creating semantic commit messages
following conventional commits or other standards.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import uuid

from app.git.commit_parser import CommitMessage, CommitType, CommitParser


@dataclass
class SemanticCommit:
    """Represents a semantic commit."""
    message: str
    commit_hash: str = ""
    type: CommitType = CommitType.OTHER
    scope: Optional[str] = None
    subject: str = ""
    body: str = ""
    footer: str = ""
    issues: List[str] = field(default_factory=list)
    breaking: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "message": self.message,
            "commit_hash": self.commit_hash,
            "type": self.type.value,
            "scope": self.scope,
            "subject": self.subject,
            "body": self.body,
            "footer": self.footer,
            "issues": self.issues,
            "breaking": self.breaking,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SemanticCommit":
        """Create from dictionary."""
        commit = cls(
            message=data.get("message", ""),
            commit_hash=data.get("commit_hash", ""),
            scope=data.get("scope"),
            subject=data.get("subject", ""),
            body=data.get("body", ""),
            footer=data.get("footer", ""),
            issues=data.get("issues", []),
            breaking=data.get("breaking", False),
            timestamp=data.get("timestamp", ""),
        )

        if isinstance(data.get("type"), str):
            commit.type = CommitType(data["type"])

        return commit

    def __str__(self) -> str:
        return self.message


@dataclass
class SemanticCommitBuilder:
    """Builder for creating semantic commit messages."""

    commit_type: CommitType = CommitType.FEAT
    scope: Optional[str] = None
    subject: str = ""
    body: str = ""
    breaking: bool = False
    issues: List[str] = field(default_factory=list)
    co_authored_by: List[str] = field(default_factory=list)
    parser: CommitParser = field(default_factory=CommitParser)

    def with_type(self, commit_type: CommitType) -> "SemanticCommitBuilder":
        """Set the commit type.

        Args:
            commit_type: The commit type

        Returns:
            Self for chaining
        """
        self.commit_type = commit_type
        return self

    def with_scope(self, scope: str) -> "SemanticCommitBuilder":
        """Set the commit scope.

        Args:
            scope: The scope (e.g., module name)

        Returns:
            Self for chaining
        """
        self.scope = scope
        return self

    def with_subject(self, subject: str) -> "SemanticCommitBuilder":
        """Set the commit subject.

        Args:
            subject: The subject line

        Returns:
            Self for chaining
        """
        self.subject = subject
        return self

    def with_body(self, body: str) -> "SemanticCommitBuilder":
        """Set the commit body.

        Args:
            body: The body text

        Returns:
            Self for chaining
        """
        self.body = body
        return self

    def with_breaking(self, breaking: bool = True) -> "SemanticCommitBuilder":
        """Set if this is a breaking change.

        Args:
            breaking: True if breaking change

        Returns:
            Self for chaining
        """
        self.breaking = breaking
        return self

    def with_issue(self, issue: str) -> "SemanticCommitBuilder":
        """Add a referenced issue.

        Args:
            issue: The issue number or identifier

        Returns:
            Self for chaining
        """
        if issue not in self.issues:
            self.issues.append(issue)
        return self

    def with_issues(self, issues: List[str]) -> "SemanticCommitBuilder":
        """Set referenced issues.

        Args:
            issues: List of issue numbers or identifiers

        Returns:
            Self for chaining
        """
        self.issues = [i for i in issues if i not in self.issues]
        return self

    def with_co_author(self, author: str) -> "SemanticCommitBuilder":
        """Add a co-author.

        Args:
            author: The co-author name/email

        Returns:
            Self for chaining
        """
        if author not in self.co_authored_by:
            self.co_authored_by.append(author)
        return self

    def build(self) -> SemanticCommit:
        """Build the semantic commit.

        Returns:
            SemanticCommit object
        """
        message = self._build_message()

        commit = SemanticCommit(
            message=message,
            type=self.commit_type,
            scope=self.scope,
            subject=self.subject,
            body=self.body,
            breaking=self.breaking,
            issues=self.issues.copy(),
        )

        return commit

    def _build_message(self) -> str:
        """Build the commit message string."""
        lines = []

        # Header line
        header = self.commit_type.value
        if self.scope:
            header += f"({self.scope})"
        if self.breaking:
            header += "!"
        if self.subject:
            header += ": " + self.subject
        lines.append(header)

        # Body
        if self.body:
            lines.append("")
            lines.append(self.body)

        # Footer
        footer_parts = []

        # Issues
        for issue in self.issues:
            footer_parts.append(f"Closes #{issue}")

        # Co-authors
        for author in self.co_authored_by:
            footer_parts.append(f"Co-authored-by: {author}")

        # Breaking change note
        if self.breaking and self.commit_type != CommitType.BREAKING:
            footer_parts.append("BREAKING CHANGE: " + (self.body.split(".")[0] + "." if self.body else ""))

        if footer_parts:
            lines.append("")
            lines.extend(footer_parts)

        return "\n".join(lines)

    def build_message(self) -> str:
        """Build and return just the message string.

        Returns:
            The commit message string
        """
        return self._build_message()

    def validate(self) -> Tuple[bool, List[str]]:
        """Validate the current commit being built.

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        message = self._build_message()
        return self.parser.validate(message)

    def reset(self) -> "SemanticCommitBuilder":
        """Reset the builder to default state.

        Returns:
            Self for chaining
        """
        self.commit_type = CommitType.FEAT
        self.scope = None
        self.subject = ""
        self.body = ""
        self.breaking = False
        self.issues = []
        self.co_authored_by = []
        return self


# Convenience functions

def create_feature_commit(
    subject: str,
    scope: Optional[str] = None,
    body: str = "",
    breaking: bool = False,
    issues: Optional[List[str]] = None,
) -> SemanticCommit:
    """Create a feature commit.

    Args:
        subject: The commit subject
        scope: The commit scope
        body: The commit body
        breaking: If this is a breaking change
        issues: List of referenced issues

    Returns:
        SemanticCommit object
    """
    builder = SemanticCommitBuilder()
    builder.with_type(CommitType.FEAT)
    if scope:
        builder.with_scope(scope)
    builder.with_subject(subject)
    if body:
        builder.with_body(body)
    if breaking:
        builder.with_breaking(True)
    if issues:
        builder.with_issues(issues)
    return builder.build()


def create_fix_commit(
    subject: str,
    scope: Optional[str] = None,
    body: str = "",
    issues: Optional[List[str]] = None,
) -> SemanticCommit:
    """Create a fix commit.

    Args:
        subject: The commit subject
        scope: The commit scope
        body: The commit body
        issues: List of referenced issues

    Returns:
        SemanticCommit object
    """
    builder = SemanticCommitBuilder()
    builder.with_type(CommitType.FIX)
    if scope:
        builder.with_scope(scope)
    builder.with_subject(subject)
    if body:
        builder.with_body(body)
    if issues:
        builder.with_issues(issues)
    return builder.build()


def create_docs_commit(
    subject: str,
    scope: Optional[str] = None,
    body: str = "",
) -> SemanticCommit:
    """Create a documentation commit.

    Args:
        subject: The commit subject
        scope: The commit scope
        body: The commit body

    Returns:
        SemanticCommit object
    """
    builder = SemanticCommitBuilder()
    builder.with_type(CommitType.DOCS)
    if scope:
        builder.with_scope(scope)
    builder.with_subject(subject)
    if body:
        builder.with_body(body)
    return builder.build()


def create_refactor_commit(
    subject: str,
    scope: Optional[str] = None,
    body: str = "",
) -> SemanticCommit:
    """Create a refactor commit.

    Args:
        subject: The commit subject
        scope: The commit scope
        body: The commit body

    Returns:
        SemanticCommit object
    """
    builder = SemanticCommitBuilder()
    builder.with_type(CommitType.REFACTOR)
    if scope:
        builder.with_scope(scope)
    builder.with_subject(subject)
    if body:
        builder.with_body(body)
    return builder.build()


def create_test_commit(
    subject: str,
    scope: Optional[str] = None,
    body: str = "",
) -> SemanticCommit:
    """Create a test commit.

    Args:
        subject: The commit subject
        scope: The commit scope
        body: The commit body

    Returns:
        SemanticCommit object
    """
    builder = SemanticCommitBuilder()
    builder.with_type(CommitType.TEST)
    if scope:
        builder.with_scope(scope)
    builder.with_subject(subject)
    if body:
        builder.with_body(body)
    return builder.build()
