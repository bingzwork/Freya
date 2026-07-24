"""Commit message parser for semantic commit messages.

This module provides parsing and validation of commit messages
following conventional commits or other semantic commit standards.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import uuid


class CommitType(Enum):
    """Types of commits following conventional commits."""
    FEAT = "feat"
    FIX = "fix"
    DOCS = "docs"
    STYLE = "style"
    REFACTOR = "refactor"
    PERF = "perf"
    TEST = "test"
    BUILD = "build"
    CI = "ci"
    CHORE = "chore"
    REVERT = "revert"
    BREAKING = "breaking"
    OTHER = "other"


@dataclass
class CommitMessage:
    """Represents a parsed commit message."""
    raw: str
    commit_hash: str = ""
    type: CommitType = CommitType.OTHER
    scope: Optional[str] = None
    subject: str = ""
    body: str = ""
    footer: str = ""
    breaking: bool = False
    issues: List[str] = field(default_factory=list)
    prs: List[str] = field(default_factory=list)
    co_authored_by: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "raw": self.raw,
            "commit_hash": self.commit_hash,
            "type": self.type.value,
            "scope": self.scope,
            "subject": self.subject,
            "body": self.body,
            "footer": self.footer,
            "breaking": self.breaking,
            "issues": self.issues,
            "prs": self.prs,
            "co_authored_by": self.co_authored_by,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CommitMessage":
        """Create from dictionary."""
        msg = cls(
            raw=data.get("raw", ""),
            commit_hash=data.get("commit_hash", ""),
            scope=data.get("scope"),
            subject=data.get("subject", ""),
            body=data.get("body", ""),
            footer=data.get("footer", ""),
            breaking=data.get("breaking", False),
            issues=data.get("issues", []),
            prs=data.get("prs", []),
            co_authored_by=data.get("co_authored_by", []),
        )

        if isinstance(data.get("type"), str):
            msg.type = CommitType(data["type"])

        return msg

    def __str__(self) -> str:
        parts = []
        if self.type.value != "other":
            parts.append(f"{self.type.value}")
        if self.scope:
            parts.append(f"({self.scope})")
        if self.subject:
            parts.append(self.subject)
        return " ".join(parts).strip()


@dataclass
class CommitParser:
    """Parses commit messages following conventional commits.

    Supports:
    - Conventional Commits: https://www.conventionalcommits.org/
    - Gitmoji: https://gitmoji.dev/
    """

    strict: bool = False
    types: List[CommitType] = field(default_factory=lambda: list(CommitType))

    def parse(self, message: str, commit_hash: str = "") -> CommitMessage:
        """Parse a commit message.

        Args:
            message: The raw commit message
            commit_hash: The commit hash

        Returns:
            Parsed CommitMessage
        """
        msg = CommitMessage(raw=message, commit_hash=commit_hash)

        if not message:
            return msg

        # Parse the message
        lines = message.split("\n")

        # Parse header (first line)
        header = lines[0] if lines else ""
        self._parse_header(msg, header)

        # Parse body (lines between header and footer)
        body_lines = []
        footer_start = self._find_footer_start(lines)

        for i in range(1, len(lines)):
            if i >= footer_start:
                break
            body_lines.append(lines[i])

        msg.body = "\n".join(body_lines).strip()

        # Parse footer
        if footer_start < len(lines):
            footer_lines = lines[footer_start:]
            msg.footer = "\n".join(footer_lines).strip()
            self._parse_footer(msg)

        return msg

    def _find_footer_start(self, lines: List[str]) -> int:
        """Find the start of the footer section."""
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            # Footer lines typically start with keywords
            if self._is_footer_line(line):
                return i
        return len(lines)

    def _is_footer_line(self, line: str) -> bool:
        """Check if a line is part of the footer."""
        lower = line.lower().strip()
        # Check for footer keywords at the start of the line
        footer_keywords = [
            "closes",
            "fixes",
            "resolves",
            "ref",
            "see",
            "co-authored-by",
            "breaking change",
            "breaking",
            "pull request",
            "pr",
        ]
        for keyword in footer_keywords:
            if lower.startswith(keyword + " ") or lower.startswith(keyword + ":"):
                return True
            # Also match without space/colon for single words
            if lower == keyword:
                return True
        return False

    def _parse_header(self, msg: CommitMessage, header: str) -> None:
        """Parse the header line."""
        # Pattern: type(scope): subject or type: subject or just subject
        pattern = r"^((?:\w+)(?:\([^)]+\))?:\s*)?(.+?)(?:\s*#\d+)*$"
        match = re.match(pattern, header.strip())

        if not match:
            msg.subject = header.strip()
            return

        type_part = match.group(1).strip() if match.group(1) else ""
        subject = match.group(2).strip()

        msg.subject = subject

        # Parse type and scope
        if type_part:
            # Check for type(scope):
            type_match = re.match(r"^(\w+)(?:\(([^)]+)\))?:", type_part)
            if type_match:
                type_str = type_match.group(1).lower()
                scope = type_match.group(2)

                # Try to match commit type
                try:
                    msg.type = CommitType(type_str)
                except ValueError:
                    msg.type = CommitType.OTHER

                msg.scope = scope

                # Check for breaking change
                if type_str == "breaking" or "!" in type_part:
                    msg.breaking = True

    def _parse_footer(self, msg: CommitMessage) -> None:
        """Parse the footer for references."""
        if not msg.footer:
            return

        # Check for breaking change
        if "breaking change:" in msg.footer.lower() or "breaking:" in msg.footer.lower():
            msg.breaking = True

        # Parse issues
        issue_pattern = r"(?:closes|fixes|resolves)\s*(?:#?)(\d+)"
        msg.issues = re.findall(issue_pattern, msg.footer, re.IGNORECASE)

        # Parse PRs
        pr_pattern = r"(?:pull request|pr)\s*(?:#?)(\d+)"
        msg.prs = re.findall(pr_pattern, msg.footer, re.IGNORECASE)

        # Parse co-authored-by
        co_author_pattern = r"Co-authored-by:\s*(.+)"
        matches = re.findall(co_author_pattern, msg.footer)
        msg.co_authored_by = [m.strip() for m in matches]

    def validate(self, message: str) -> Tuple[bool, List[str]]:
        """Validate a commit message.

        Args:
            message: The commit message to validate

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []

        if not message or not message.strip():
            errors.append("Commit message is empty")
            return False, errors

        # Parse the message
        msg = self.parse(message)

        # Check subject length
        if len(msg.subject) > 72:
            errors.append(f"Subject line exceeds 72 characters: {len(msg.subject)}")

        # Check for valid type (if specified)
        if msg.type == CommitType.OTHER and self.strict:
            errors.append(f"Unknown commit type: {msg.scope if msg.scope else 'unknown'}")

        # Check for subject
        if not msg.subject:
            errors.append("Subject is empty")

        # Check subject starts with uppercase or lowercase letter
        if msg.subject and not re.match(r"^[a-zA-Z]", msg.subject):
            errors.append("Subject should start with a letter")

        # Check for period at end
        if msg.subject and msg.subject.endswith("."):
            errors.append("Subject should not end with a period")

        return len(errors) == 0, errors

    def is_conventional_commit(self, message: str) -> bool:
        """Check if a message follows conventional commits.

        Args:
            message: The commit message

        Returns:
            True if it follows conventional commits
        """
        if not message:
            return False

        msg = self.parse(message)
        return msg.type != CommitType.OTHER

    def get_commit_type(self, message: str) -> CommitType:
        """Get the commit type from a message.

        Args:
            message: The commit message

        Returns:
            CommitType
        """
        msg = self.parse(message)
        return msg.type

    def get_scope(self, message: str) -> Optional[str]:
        """Get the scope from a commit message.

        Args:
            message: The commit message

        Returns:
            Scope string or None
        """
        msg = self.parse(message)
        return msg.scope

    def is_breaking_change(self, message: str) -> bool:
        """Check if a commit is a breaking change.

        Args:
            message: The commit message

        Returns:
            True if it's a breaking change
        """
        msg = self.parse(message)
        return msg.breaking

    def get_issues(self, message: str) -> List[str]:
        """Get referenced issues from a commit message.

        Args:
            message: The commit message

        Returns:
            List of issue numbers
        """
        msg = self.parse(message)
        return msg.issues
