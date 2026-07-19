"""Checklist module for review checklists."""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
import uuid


@dataclass
class ChecklistItem:
    """An item in a review checklist."""
    title: str
    description: str = ""
    category: str = "general"
    required: bool = True
    passed: bool = False
    skipped: bool = False
    comments: str = ""
    id: str = field(default_factory=lambda: f"item_{uuid.uuid4().hex[:8]}")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "required": self.required,
            "passed": self.passed,
            "skipped": self.skipped,
            "comments": self.comments,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChecklistItem":
        """Create from dictionary."""
        return cls(
            id=data.get("id", f"item_{uuid.uuid4().hex[:8]}"),
            title=data.get("title", ""),
            description=data.get("description", ""),
            category=data.get("category", "general"),
            required=data.get("required", True),
            passed=data.get("passed", False),
            skipped=data.get("skipped", False),
            comments=data.get("comments", ""),
        )

    @property
    def status(self) -> str:
        """Get the status of the item."""
        if self.skipped:
            return "skipped"
        if self.passed:
            return "passed"
        if self.required:
            return "failed"
        return "optional"


@dataclass
class ReviewChecklist:
    """A checklist for code reviews."""
    name: str
    review_id: str = ""
    description: str = ""
    completed: bool = False
    items: List[ChecklistItem] = field(default_factory=list)
    id: str = field(default_factory=lambda: f"checklist_{uuid.uuid4().hex[:8]}")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "items": [item.to_dict() for item in self.items],
            "review_id": self.review_id,
            "completed": self.completed,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReviewChecklist":
        """Create from dictionary."""
        return cls(
            id=data.get("id", f"checklist_{uuid.uuid4().hex[:8]}"),
            name=data.get("name", ""),
            description=data.get("description", ""),
            items=[ChecklistItem.from_dict(item) for item in data.get("items", [])],
            review_id=data.get("review_id", ""),
            completed=data.get("completed", False),
        )

    def add_item(
        self,
        title: str,
        description: str = "",
        category: str = "general",
        required: bool = True,
    ) -> ChecklistItem:
        """Add an item to the checklist."""
        item = ChecklistItem(
            title=title,
            description=description,
            category=category,
            required=required,
        )
        self.items.append(item)
        return item

    def remove_item(self, item_id: str) -> bool:
        """Remove an item from the checklist."""
        for i, item in enumerate(self.items):
            if item.id == item_id:
                self.items.pop(i)
                return True
        return False

    def mark_passed(self, item_id: str, comments: str = "") -> bool:
        """Mark an item as passed."""
        for item in self.items:
            if item.id == item_id:
                item.passed = True
                item.comments = comments
                return True
        return False

    def mark_failed(self, item_id: str, comments: str = "") -> bool:
        """Mark an item as failed."""
        for item in self.items:
            if item.id == item_id:
                item.passed = False
                item.skipped = False
                item.comments = comments
                return True
        return False

    def mark_skipped(self, item_id: str, comments: str = "") -> bool:
        """Mark an item as skipped."""
        for item in self.items:
            if item.id == item_id:
                item.skipped = True
                item.comments = comments
                return True
        return False

    @property
    def completion_percentage(self) -> float:
        """Get the completion percentage."""
        if not self.items:
            return 0.0
        required_items = [i for i in self.items if i.required]
        if not required_items:
            return 100.0
        passed_items = [i for i in required_items if i.passed or i.skipped]
        return (len(passed_items) / len(required_items)) * 100

    @property
    def all_passed(self) -> bool:
        """Check if all required items are passed."""
        for item in self.items:
            if item.required and not (item.passed or item.skipped):
                return False
        return True

    @property
    def failed_items(self) -> List[ChecklistItem]:
        """Get all failed items."""
        return [item for item in self.items if item.required and not (item.passed or item.skipped)]

    @property
    def summary(self) -> Dict[str, Any]:
        """Get a summary of the checklist."""
        total = len(self.items)
        required = len([i for i in self.items if i.required])
        passed = len([i for i in self.items if i.passed])
        failed = len([i for i in self.items if i.required and not (i.passed or i.skipped)])
        skipped = len([i for i in self.items if i.skipped])

        return {
            "total_items": total,
            "required_items": required,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "completion_percentage": self.completion_percentage,
            "all_passed": self.all_passed,
        }
