"""
Multi-Agent Learning Knowledge Sharing Module

This module provides functionality for sharing learned knowledge between
multiple Freya instances.
"""

import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Any

from app.core.logger import logger
from app.memory.experience_memory import ExperienceMemory, ExperienceEntry
from app.memory.engineering_lessons import EngineeringLessonStorage, EngineeringLesson
from app.memory.long_term_memory import LongTermMemory, LongTermEntry
from app.memory.semantic_memory import SemanticMemory, SemanticEntry
from app.memory.validation import KnowledgeValidator


class KnowledgeSharer:
    """Shares learned knowledge with other agents via a shared directory."""

    def __init__(
        self,
        shared_dir: str,
        instance_id: str,
        experience_memory: ExperienceMemory,
        engineering_lessons: EngineeringLessonStorage,
        long_term_memory: LongTermMemory,
        semantic_memory: SemanticMemory,
        knowledge_validator: KnowledgeValidator,
    ):
        """
        Initialize the knowledge sharer.

        Args:
            shared_dir: Path to the shared directory for knowledge exchange
            instance_id: Unique identifier for this agent instance
            experience_memory: Local experience memory storage
            engineering_lessons: Local engineering lessons storage
            long_term_memory: Local long-term memory storage
            semantic_memory: Local semantic memory storage
            knowledge_validator: Knowledge validator for validating shared knowledge
        """
        self.shared_dir = Path(shared_dir)
        self.instance_id = instance_id
        self.experience_memory = experience_memory
        self.engineering_lessons = engineering_lessons
        self.long_term_memory = long_term_memory
        self.semantic_memory = semantic_memory
        self.knowledge_validator = knowledge_validator
        self.logger = logger

        # Create shared directory structure
        self.incoming_dir = self.shared_dir / "incoming"
        self.processed_dir = self.shared_dir / "processed"
        self.exported_dir = self.shared_dir / "exported"

        for dir_path in [self.incoming_dir, self.processed_dir, self.exported_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)

    def export_knowledge(self, since_time: Optional[datetime] = None) -> int:
        """
        Export knowledge learned since the given time to the shared directory.

        Args:
            since_time: Only export knowledge created after this time

        Returns:
            Number of knowledge items exported
        """
        exported_count = 0

        # Export experiences
        exported_count += self._export_experiences(since_time)
        # Export engineering lessons
        exported_count += self._export_lessons(since_time)
        # Export long-term memory entries
        exported_count += self._export_long_term(since_time)
        # Export semantic memory entries
        exported_count += self._export_semantic(since_time)

        self.logger.info(f"Exported {exported_count} knowledge items to shared directory")
        return exported_count

    def _export_experiences(self, since_time: Optional[datetime]) -> int:
        """Export experience entries."""
        experiences = self.experience_memory.all()
        count = 0
        for exp in experiences:
            exp_time = datetime.fromisoformat(exp.timestamp.replace('Z', '+00:00'))
            if since_time and exp_time <= since_time:
                continue
            # Only export experiences that originated from this instance (optional)
            # For now, we export all experiences
            data = {
                "type": "experience",
                "id": exp.id,
                "title": exp.title,
                "description": exp.description,
                "category": exp.category,
                "tags": exp.tags,
                "outcome": exp.outcome,
                "confidence": exp.confidence,
                "metadata": exp.metadata,
                "timestamp": exp.timestamp,
                "source_instance": self.instance_id,
            }
            self._write_knowledge_file(data, "experience")
            count += 1
        return count

    def _export_lessons(self, since_time: Optional[datetime]) -> int:
        """Export engineering lessons."""
        lessons = self.engineering_lessons.all()
        count = 0
        for lesson in lessons:
            # We don't have a timestamp on lessons, so we export all for now
            # In a real implementation, lessons would have a timestamp
            data = {
                "type": "lesson",
                "id": lesson.id,
                "title": lesson.title,
                "description": lesson.description,
                "lesson_type": lesson.lesson_type.value if hasattr(lesson.lesson_type, 'value') else str(lesson.lesson_type),
                "category": lesson.category,
                "tags": lesson.tags,
                "confidence": lesson.confidence,
                "rationale": lesson.rationale,
                "metadata": lesson.metadata,
                "source_instance": self.instance_id,
            }
            self._write_knowledge_file(data, "lesson")
            count += 1
        return count

    def _export_long_term(self, since_time: Optional[datetime]) -> int:
        """Export long-term memory entries."""
        entries = self.long_term_memory.all()
        count = 0
        for entry in entries:
            entry_time = datetime.fromisoformat(entry.timestamp.replace('Z', '+00:00'))
            if since_time and entry_time <= since_time:
                continue
            data = {
                "type": "long_term",
                "key": entry.key,
                "value": entry.value,
                "description": entry.description,
                "category": entry.category,
                "tags": entry.tags,
                "confidence": entry.confidence,
                "metadata": entry.metadata,
                "timestamp": entry.timestamp,
                "source_instance": self.instance_id,
            }
            self._write_knowledge_file(data, "long_term")
            count += 1
        return count

    def _export_semantic(self, since_time: Optional[datetime]) -> int:
        """Export semantic memory entries."""
        entries = self.semantic_memory.all()
        count = 0
        for entry in entries:
            entry_time = datetime.fromisoformat(entry.timestamp.replace('Z', '+00:00'))
            if since_time and entry_time <= since_time:
                continue
            data = {
                "type": "semantic",
                "key": entry.key,
                "value": entry.value,
                "description": entry.description,
                "category": entry.category,
                "tags": entry.tags,
                "confidence": entry.confidence,
                "metadata": entry.metadata,
                "timestamp": entry.timestamp,
                "source_instance": self.instance_id,
            }
            self._write_knowledge_file(data, "semantic")
            count += 1
        return count

    def _write_knowledge_file(self, data: Dict[str, Any], kind: str) -> None:
        """Write a knowledge item to a JSON file in the exported directory."""
        # Create a unique filename
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        filename = f"{kind}_{timestamp}_{unique_id}.json"
        filepath = self.exported_dir / filename

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            self.logger.error(f"Failed to write knowledge file {filepath}: {e}")


class KnowledgeReceiver:
    """Receives and imports knowledge from other agents via a shared directory."""

    def __init__(
        self,
        shared_dir: str,
        instance_id: str,
        experience_memory: ExperienceMemory,
        engineering_lessons: EngineeringLessonStorage,
        long_term_memory: LongTermMemory,
        semantic_memory: SemanticMemory,
        knowledge_validator: KnowledgeValidator,
    ):
        """
        Initialize the knowledge receiver.

        Args:
            shared_dir: Path to the shared directory for knowledge exchange
            instance_id: Unique identifier for this agent instance (to avoid re-importing own knowledge)
            experience_memory: Local experience memory storage
            engineering_lessons: Local engineering lessons storage
            long_term_memory: Local long-term memory storage
            semantic_memory: Local semantic memory storage
            knowledge_validator: Knowledge validator for validating imported knowledge
        """
        self.shared_dir = Path(shared_dir)
        self.instance_id = instance_id
        self.experience_memory = experience_memory
        self.engineering_lessons = engineering_lessons
        self.long_term_memory = long_term_memory
        self.semantic_memory = semantic_memory
        self.knowledge_validator = knowledge_validator
        self.logger = logger

        # Create shared directory structure
        self.incoming_dir = self.shared_dir / "incoming"
        self.processed_dir = self.shared_dir / "processed"
        self.exported_dir = self.shared_dir / "exported"

        for dir_path in [self.incoming_dir, self.processed_dir, self.exported_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)

        # Keep track of imported knowledge IDs to avoid duplicates
        self.imported_ids_file = self.shared_dir / "imported_ids.json"
        self.imported_ids: Set[str] = self._load_imported_ids()

    def import_knowledge(self) -> int:
        """
        Import knowledge from the incoming directory.

        Returns:
            Number of knowledge items imported
        """
        imported_count = 0
        incoming_files = list(self.incoming_dir.glob("*.json"))

        for file_path in incoming_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # Skip knowledge that originated from this instance
                if data.get("source_instance") == self.instance_id:
                    self._move_to_processed(file_path)
                    continue

                # Check if we've already imported this knowledge (by ID)
                knowledge_id = data.get("id")
                if knowledge_id and knowledge_id in self.imported_ids:
                    self._move_to_processed(file_path)
                    continue

                # Import based on type
                success = False
                knowledge_type = data.get("type")
                if knowledge_type == "experience":
                    success = self._import_experience(data)
                elif knowledge_type == "lesson":
                    success = self._import_lesson(data)
                elif knowledge_type == "long_term":
                    success = self._import_long_term(data)
                elif knowledge_type == "semantic":
                    success = self._import_semantic(data)

                if success:
                    if knowledge_id:
                        self.imported_ids.add(knowledge_id)
                    imported_count += 1
                    self._move_to_processed(file_path)
                else:
                    # If import failed, still move to processed to avoid retrying indefinitely
                    self._move_to_processed(file_path)
                    self.logger.warning(f"Failed to import knowledge from {file_path.name}")

            except Exception as e:
                self.logger.error(f"Error processing knowledge file {file_path.name}: {e}")
                # Move to processed to avoid blocking
                self._move_to_processed(file_path)

        # Save imported IDs periodically
        if imported_count > 0:
            self._save_imported_ids()

        self.logger.info(f"Imported {imported_count} knowledge items from shared directory")
        return imported_count

    def _import_experience(self, data: Dict[str, Any]) -> bool:
        """Import an experience entry."""
        try:
            # Validate the knowledge if a validator is available
            # For experiences, we might not have a direct validation method,
            # but we can check basic validity
            if not data.get("title") or not data.get("description"):
                return False

            self.experience_memory.store(
                title=data["title"],
                description=data["description"],
                category=data.get("category", "general"),
                tags=data.get("tags", []),
                outcome=data.get("outcome", "unknown"),
                confidence=data.get("confidence", 0.5),
                metadata=data.get("metadata", {}),
            )
            return True
        except Exception as e:
            self.logger.error(f"Failed to import experience: {e}")
            return False

    def _import_lesson(self, data: Dict[str, Any]) -> bool:
        """Import an engineering lesson."""
        try:
            if not data.get("title") or not data.get("description"):
                return False

            # Convert lesson_type string to enum if needed
            lesson_type_str = data.get("lesson_type", "lesson_learned")
            # Assuming lesson_type is stored as string; we'll pass it as-is
            # The EngineeringLessonStorage.store method expects a string lesson_type
            self.engineering_lessons.store(
                title=data["title"],
                description=data["description"],
                lesson_type=lesson_type_str,
                category=data.get("category", "general"),
                tags=data.get("tags", []),
                confidence=data.get("confidence", 0.5),
                rationale=data.get("rationale", ""),
                metadata=data.get("metadata", {}),
            )
            return True
        except Exception as e:
            self.logger.error(f"Failed to import lesson: {e}")
            return False

    def _import_long_term(self, data: Dict[str, Any]) -> bool:
        """Import a long-term memory entry."""
        try:
            if not data.get("key") or not data.get("value"):
                return False

            self.long_term_memory.store(
                key=data["key"],
                value=data["value"],
                description=data.get("description", ""),
                category=data.get("category", "general"),
                tags=data.get("tags", []),
                confidence=data.get("confidence", 0.5),
                metadata=data.get("metadata", {}),
            )
            return True
        except Exception as e:
            self.logger.error(f"Failed to import long-term memory: {e}")
            return False

    def _import_semantic(self, data: Dict[str, Any]) -> bool:
        """Import a semantic memory entry."""
        try:
            if not data.get("key") or not data.get("value"):
                return False

            self.semantic_memory.store(
                key=data["key"],
                value=data["value"],
                description=data.get("description", ""),
                category=data.get("category", "general"),
                tags=data.get("tags", []),
                confidence=data.get("confidence", 0.5),
                metadata=data.get("metadata", {}),
            )
            return True
        except Exception as e:
            self.logger.error(f"Failed to import semantic memory: {e}")
            return False

    def _move_to_processed(self, file_path: Path) -> None:
        """Move a file from incoming to processed directory."""
        try:
            dest_path = self.processed_dir / file_path.name
            shutil.move(str(file_path), str(dest_path))
        except Exception as e:
            self.logger.error(f"Failed to move {file_path.name} to processed: {e}")

    def _load_imported_ids(self) -> Set[str]:
        """Load the set of imported knowledge IDs from disk."""
        if self.imported_ids_file.exists():
            try:
                with open(self.imported_ids_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return set(data.get("ids", []))
            except Exception as e:
                self.logger.error(f"Failed to load imported IDs: {e}")
        return set()

    def _save_imported_ids(self) -> None:
        """Save the set of imported knowledge IDs to disk."""
        try:
            with open(self.imported_ids_file, 'w', encoding='utf-8') as f:
                json.dump({"ids": list(self.imported_ids)}, f, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to save imported IDs: {e}")