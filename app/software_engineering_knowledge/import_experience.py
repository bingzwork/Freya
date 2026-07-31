"""Experience and Lesson Importer for Software Engineering Knowledge.

Imports knowledge from:
- ExperienceMemory entries (episodic experiences)
- EngineeringLessons storage (distilled lessons)
- Reflection/synthesis outputs
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from app.software_engineering_knowledge.models import (
    EngineeringDomain,
    EngineeringKnowledgeItem,
    EngineeringKnowledgeType,
    ExtractionResult,
    KnowledgeSource,
    ValidationStatus,
)
from app.software_engineering_knowledge.categories import get_category_registry


class ExperienceImporter:
    """Import engineering knowledge from ExperienceMemory."""

    def __init__(self, experience_memory_path: Optional[Path] = None):
        self.memory_path = experience_memory_path or Path("data/experience_memory")
        self.registry = get_category_registry()

    def import_all(self) -> ExtractionResult:
        """Import all experience entries as engineering knowledge."""
        items = []
        errors = []

        if not self.memory_path.exists():
            return ExtractionResult(
                success=True,
                items=[],
                errors=["Experience memory directory not found"],
                source=str(self.memory_path),
                source_type=KnowledgeSource.EXPERIENCE_MEMORY,
            )

        # Find all experience files
        exp_files = list(self.memory_path.glob("*.json")) + list(self.memory_path.glob("*.jsonl"))

        for exp_file in exp_files:
            try:
                file_items = self._import_from_file(exp_file)
                items.extend(file_items)
            except Exception as e:
                errors.append(f"{exp_file}: {str(e)}")

        return ExtractionResult(
            success=len(errors) == 0,
            items=items,
            errors=errors,
            source=str(self.memory_path),
            source_type=KnowledgeSource.EXPERIENCE_MEMORY,
            metadata={"files_imported": len(exp_files)},
        )

    def _import_from_file(self, file_path: Path) -> List[EngineeringKnowledgeItem]:
        """Import from a single experience memory file."""
        import json

        items = []

        try:
            content = file_path.read_text(encoding="utf-8")
            if file_path.suffix == ".jsonl":
                entries = [json.loads(line) for line in content.strip().split("\n") if line.strip()]
            else:
                entries = json.loads(content)
                if not isinstance(entries, list):
                    entries = [entries]
        except Exception:
            return items

        for entry in entries:
            item = self._convert_entry(entry, str(file_path))
            if item:
                items.append(item)

        return items

    def _convert_entry(self, entry: Dict[str, Any], source_file: str) -> Optional[EngineeringKnowledgeItem]:
        """Convert an experience entry to engineering knowledge."""
        # Expected entry fields: task, outcome, lessons, tags, domain, etc.
        task = entry.get("task", "")
        outcome = entry.get("outcome", "")
        lessons = entry.get("lessons", [])
        tags = entry.get("tags", [])
        domain_str = entry.get("domain", "")
        confidence = entry.get("confidence", 0.6)

        if not (task or outcome or lessons):
            return None

        # Determine domain
        domain = EngineeringDomain.UNKNOWN
        if domain_str:
            try:
                domain = EngineeringDomain(domain_str)
            except ValueError:
                # Try to infer from tags/task
                domain = self._infer_domain(task, tags)

        # Determine knowledge type
        if lessons:
            ktype = EngineeringKnowledgeType.LESSON_LEARNED
        elif "error" in task.lower() or "bug" in task.lower() or "fix" in task.lower():
            ktype = EngineeringKnowledgeType.TROUBLESHOOTING
        elif "how to" in task.lower() or "implement" in task.lower():
            ktype = EngineeringKnowledgeType.PROCEDURE
        else:
            ktype = EngineeringKnowledgeType.EXPERIENCE_MEMORY

        # Build content
        content_parts = []
        if task:
            content_parts.append(f"Task: {task}")
        if outcome:
            content_parts.append(f"Outcome: {outcome}")
        if lessons:
            content_parts.append("Lessons Learned:")
            for lesson in lessons:
                content_parts.append(f"  - {lesson}")

        content = "\n".join(content_parts)

        # Generate title
        title_words = task.split()[:8]
        title = " ".join(title_words) + ("..." if len(task.split()) > 8 else "")
        if not title.strip():
            title = "Experience Entry"

        item = EngineeringKnowledgeItem(
            title=title,
            summary=outcome[:200] if outcome else (lessons[0][:200] if lessons else task[:200]),
            content=content,
            domain=domain,
            sub_category="experience",
            knowledge_type=ktype,
            source=KnowledgeSource.EXPERIENCE_MEMORY,
            source_uri=source_file,
            source_metadata={
                "original_entry": entry,
                "entry_id": entry.get("id", ""),
            },
            tags=tags + ["experience"],
            confidence=confidence,
            validation_status=ValidationStatus.PENDING,
        )

        return item

    def _infer_domain(self, task: str, tags: List[str]) -> EngineeringDomain:
        """Infer engineering domain from task and tags."""
        text = (task + " " + " ".join(tags)).lower()

        domain_keywords = {
            EngineeringDomain.DEBUGGING: ["debug", "bug", "error", "fix", "crash", "exception"],
            EngineeringDomain.TESTING: ["test", "testing", "coverage", "pytest", "jest"],
            EngineeringDomain.PERFORMANCE_OPTIMIZATION: ["performance", "optimize", "slow", "speed", "memory", "profile"],
            EngineeringDomain.SECURITY: ["security", "auth", "vulnerability", "encryption", "jwt", "oauth"],
            EngineeringDomain.DATABASES: ["database", "sql", "query", "migration", "orm", "postgres", "mongodb"],
            EngineeringDomain.APIS: ["api", "rest", "graphql", "grpc", "endpoint", "route"],
            EngineeringDomain.CI_CD: ["ci", "cd", "pipeline", "deploy", "github actions", "gitlab"],
            EngineeringDomain.GIT: ["git", "branch", "merge", "rebase", "commit", "push"],
            EngineeringDomain.DOCKER: ["docker", "container", "kubernetes", "k8s"],
            EngineeringDomain.SOFTWARE_ARCHITECTURE: ["architect", "design", "pattern", "microservice", "monolith"],
            EngineeringDomain.REFACTORING: ["refactor", "clean code", "technical debt", "legacy"],
        }

        for domain, keywords in domain_keywords.items():
            if any(kw in text for kw in keywords):
                return domain

        return EngineeringDomain.ENGINEERING_LESSONS


class EngineeringLessonsImporter:
    """Import engineering knowledge from EngineeringLessons storage."""

    def __init__(self, lessons_path: Optional[Path] = None):
        self.lessons_path = lessons_path or Path("data/engineering_lessons")
        self.registry = get_category_registry()

    def import_all(self) -> ExtractionResult:
        """Import all engineering lessons."""
        items = []
        errors = []

        if not self.lessons_path.exists():
            return ExtractionResult(
                success=True,
                items=[],
                errors=["Engineering lessons directory not found"],
                source=str(self.lessons_path),
                source_type=KnowledgeSource.ENGINEERING_LESSONS,
            )

        # Find lesson files
        lesson_files = list(self.lessons_path.glob("*.json")) + list(self.lessons_path.glob("*.jsonl"))

        for lesson_file in lesson_files:
            try:
                file_items = self._import_from_file(lesson_file)
                items.extend(file_items)
            except Exception as e:
                errors.append(f"{lesson_file}: {str(e)}")

        return ExtractionResult(
            success=len(errors) == 0,
            items=items,
            errors=errors,
            source=str(self.lessons_path),
            source_type=KnowledgeSource.ENGINEERING_LESSONS,
            metadata={"files_imported": len(lesson_files)},
        )

    def _import_from_file(self, file_path: Path) -> List[EngineeringKnowledgeItem]:
        """Import from a single lessons file."""
        import json

        items = []

        try:
            content = file_path.read_text(encoding="utf-8")
            if file_path.suffix == ".jsonl":
                entries = [json.loads(line) for line in content.strip().split("\n") if line.strip()]
            else:
                entries = json.loads(content)
                if not isinstance(entries, list):
                    entries = [entries]
        except Exception:
            return items

        for entry in entries:
            item = self._convert_lesson(entry, str(file_path))
            if item:
                items.append(item)

        return items

    def _convert_lesson(self, entry: Dict[str, Any], source_file: str) -> Optional[EngineeringKnowledgeItem]:
        """Convert a lesson entry to engineering knowledge."""
        # Expected fields: title, description, lesson_type, domain, tags, confidence, etc.
        title = entry.get("title", "")
        description = entry.get("description", "") or entry.get("content", "")
        lesson_type = entry.get("lesson_type", "") or entry.get("type", "")
        domain_str = entry.get("domain", "")
        tags = entry.get("tags", [])
        confidence = entry.get("confidence", 0.8)

        if not (title or description):
            return None

        # Determine domain
        domain = EngineeringDomain.ENGINEERING_LESSONS
        if domain_str:
            try:
                domain = EngineeringDomain(domain_str)
            except ValueError:
                pass

        # Determine knowledge type from lesson_type
        ktype_map = {
            "best_practice": EngineeringKnowledgeType.BEST_PRACTICE,
            "anti_pattern": EngineeringKnowledgeType.ANTI_PATTERN,
            "pattern": EngineeringKnowledgeType.CODE_PATTERN,
            "troubleshooting": EngineeringKnowledgeType.TROUBLESHOOTING,
            "decision": EngineeringKnowledgeType.DECISION_RATIONALE,
            "warning": EngineeringKnowledgeType.WARNING,
            "recommendation": EngineeringKnowledgeType.RECOMMENDATION,
        }
        ktype = ktype_map.get(lesson_type.lower(), EngineeringKnowledgeType.LESSON_LEARNED)

        item = EngineeringKnowledgeItem(
            title=title,
            summary=description[:200],
            content=description,
            domain=domain,
            sub_category="lessons",
            knowledge_type=ktype,
            source=KnowledgeSource.ENGINEERING_LESSONS,
            source_uri=source_file,
            source_metadata={"original_entry": entry, "lesson_type": lesson_type},
            tags=tags + ["lesson", lesson_type] if lesson_type else tags + ["lesson"],
            confidence=confidence,
            validation_status=ValidationStatus.PENDING,
        )

        return item


class ReflectionImporter:
    """Import engineering knowledge from self-reflection outputs."""

    def __init__(self, reflection_path: Optional[Path] = None):
        self.reflection_path = reflection_path or Path("data/reflections")
        self.registry = get_category_registry()

    def import_all(self) -> ExtractionResult:
        """Import all reflection entries."""
        items = []
        errors = []

        if not self.reflection_path.exists():
            return ExtractionResult(
                success=True,
                items=[],
                errors=["Reflection directory not found"],
                source=str(self.reflection_path),
                source_type=KnowledgeSource.REFLECTION,
            )

        reflect_files = list(self.reflection_path.glob("*.json")) + list(self.reflection_path.glob("*.jsonl"))

        for rf in reflect_files:
            try:
                file_items = self._import_from_file(rf)
                items.extend(file_items)
            except Exception as e:
                errors.append(f"{rf}: {str(e)}")

        return ExtractionResult(
            success=len(errors) == 0,
            items=items,
            errors=errors,
            source=str(self.reflection_path),
            source_type=KnowledgeSource.REFLECTION,
            metadata={"files_imported": len(reflect_files)},
        )

    def _import_from_file(self, file_path: Path) -> List[EngineeringKnowledgeItem]:
        """Import from reflection file."""
        import json

        items = []

        try:
            content = file_path.read_text(encoding="utf-8")
            if file_path.suffix == ".jsonl":
                entries = [json.loads(line) for line in content.strip().split("\n") if line.strip()]
            else:
                entries = json.loads(content)
                if not isinstance(entries, list):
                    entries = [entries]
        except Exception:
            return items

        for entry in entries:
            item = self._convert_reflection(entry, str(file_path))
            if item:
                items.append(item)

        return items

    def _convert_reflection(self, entry: Dict[str, Any], source_file: str) -> Optional[EngineeringKnowledgeItem]:
        """Convert reflection entry."""
        insight = entry.get("insight", "") or entry.get("reflection", "")
        context = entry.get("context", "")
        tags = entry.get("tags", [])
        confidence = entry.get("confidence", 0.7)

        if not insight:
            return None

        item = EngineeringKnowledgeItem(
            title=f"Reflection: {insight[:60]}...",
            summary=insight[:200],
            content=f"Context: {context}\n\nInsight: {insight}",
            domain=EngineeringDomain.ENGINEERING_LESSONS,
            sub_category="reflection",
            knowledge_type=EngineeringKnowledgeType.LESSON_LEARNED,
            source=KnowledgeSource.REFLECTION,
            source_uri=source_file,
            source_metadata={"original_entry": entry},
            tags=tags + ["reflection"],
            confidence=confidence,
            validation_status=ValidationStatus.PENDING,
        )

        return item


class UserKnowledgeImporter:
    """Import engineering knowledge directly taught by user."""

    def __init__(self, user_knowledge_path: Optional[Path] = None):
        self.knowledge_path = user_knowledge_path or Path("data/user_knowledge")
        self.registry = get_category_registry()

    def import_all(self) -> ExtractionResult:
        """Import all user-taught knowledge."""
        items = []
        errors = []

        if not self.knowledge_path.exists():
            return ExtractionResult(
                success=True,
                items=[],
                errors=["User knowledge directory not found"],
                source=str(self.knowledge_path),
                source_type=KnowledgeSource.USER_INPUT,
            )

        knowledge_files = list(self.knowledge_path.glob("*.json")) + list(self.knowledge_path.glob("*.jsonl"))

        for kf in knowledge_files:
            try:
                file_items = self._import_from_file(kf)
                items.extend(file_items)
            except Exception as e:
                errors.append(f"{kf}: {str(e)}")

        return ExtractionResult(
            success=len(errors) == 0,
            items=items,
            errors=errors,
            source=str(self.knowledge_path),
            source_type=KnowledgeSource.USER_INPUT,
            metadata={"files_imported": len(knowledge_files)},
        )

    def _import_from_file(self, file_path: Path) -> List[EngineeringKnowledgeItem]:
        """Import from user knowledge file."""
        import json

        items = []

        try:
            content = file_path.read_text(encoding="utf-8")
            if file_path.suffix == ".jsonl":
                entries = [json.loads(line) for line in content.strip().split("\n") if line.strip()]
            else:
                entries = json.loads(content)
                if not isinstance(entries, list):
                    entries = [entries]
        except Exception:
            return items

        for entry in entries:
            item = self._convert_user_knowledge(entry, str(file_path))
            if item:
                items.append(item)

        return items

    def _convert_user_knowledge(self, entry: Dict[str, Any], source_file: str) -> Optional[EngineeringKnowledgeItem]:
        """Convert user knowledge entry."""
        # User can provide all fields directly
        title = entry.get("title", "")
        content = entry.get("content", "")
        summary = entry.get("summary", content[:200])
        domain_str = entry.get("domain", "")
        knowledge_type_str = entry.get("knowledge_type", "")
        sub_category = entry.get("sub_category", "")
        tags = entry.get("tags", [])
        confidence = entry.get("confidence", 0.9)
        language = entry.get("language")
        frameworks = entry.get("frameworks", [])

        if not (title or content):
            return None

        # Parse domain
        domain = EngineeringDomain.UNKNOWN
        if domain_str:
            try:
                domain = EngineeringDomain(domain_str)
            except ValueError:
                pass

        # Parse knowledge type
        ktype = EngineeringKnowledgeType.CUSTOM
        if knowledge_type_str:
            try:
                ktype = EngineeringKnowledgeType(knowledge_type_str)
            except ValueError:
                pass

        item = EngineeringKnowledgeItem(
            title=title,
            summary=summary,
            content=content,
            domain=domain,
            sub_category=sub_category,
            knowledge_type=ktype,
            source=KnowledgeSource.USER_INPUT,
            source_uri=source_file,
            source_metadata={"original_entry": entry},
            tags=tags,
            language=language,
            frameworks=frameworks,
            confidence=confidence,
            validation_status=ValidationStatus.PENDING,
        )

        return item


# === Unified Importer ===

class KnowledgeImporter:
    """Unified importer for all engineering knowledge sources."""

    def __init__(
        self,
        project_root: Optional[Path] = None,
        experience_path: Optional[Path] = None,
        lessons_path: Optional[Path] = None,
        reflection_path: Optional[Path] = None,
        user_knowledge_path: Optional[Path] = None,
    ):
        self.project_root = project_root or Path(".")
        self.experience_importer = ExperienceImporter(experience_path)
        self.lessons_importer = EngineeringLessonsImporter(lessons_path)
        self.reflection_importer = ReflectionImporter(reflection_path)
        self.user_importer = UserKnowledgeImporter(user_knowledge_path)

    def import_all(self) -> Dict[str, ExtractionResult]:
        """Import from all available sources."""
        return {
            "experience": self.experience_importer.import_all(),
            "lessons": self.lessons_importer.import_all(),
            "reflection": self.reflection_importer.import_all(),
            "user_knowledge": self.user_importer.import_all(),
        }

    def import_from_source(self, source: KnowledgeSource) -> ExtractionResult:
        """Import from a specific source."""
        importers = {
            KnowledgeSource.EXPERIENCE_MEMORY: self.experience_importer,
            KnowledgeSource.ENGINEERING_LESSONS: self.lessons_importer,
            KnowledgeSource.REFLECTION: self.reflection_importer,
            KnowledgeSource.USER_INPUT: self.user_importer,
        }

        importer = importers.get(source)
        if importer:
            return importer.import_all()

        return ExtractionResult(
            success=False,
            items=[],
            errors=[f"No importer for source type: {source}"],
            source=str(source),
            source_type=source,
        )