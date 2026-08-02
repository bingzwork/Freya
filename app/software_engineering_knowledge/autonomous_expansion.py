"""Autonomous Knowledge Expansion for Software Engineering Knowledge.

Automatically extracts and stores engineering knowledge after:
- Task completion
- Debugging sessions
- Code reviews
- Feature implementation
- Incident resolution
"""

import json
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from app.core.logger import logger

from app.software_engineering_knowledge.models import (
    EngineeringDomain,
    EngineeringKnowledgeItem,
    EngineeringKnowledgeType,
    KnowledgeSource,
    ValidationStatus,
)
from app.software_engineering_knowledge.extraction import KnowledgeExtractor
from app.software_engineering_knowledge.import_experience import KnowledgeImporter
from app.software_engineering_knowledge.validation import KnowledgeValidator
from app.core.logger import logger


@dataclass
class ExpansionTrigger:
    """A trigger condition for automatic knowledge expansion."""
    name: str
    condition: Callable[[Dict[str, Any]], bool]
    extractors: List[str]  # Which extractors to run
    priority: int = 5  # 1-10, higher = more important
    cooldown_hours: int = 24  # Min time between executions


@dataclass
class ExpansionResult:
    """Result of an autonomous expansion run."""
    trigger_name: str
    timestamp: str
    items_created: int
    items_validated: int
    errors: List[str]
    extracted_sources: List[str]
    duration_seconds: float


class AutonomousExpander:
    """Automatically expands the engineering knowledge base."""

    def __init__(
        self,
        project_root: Path,
        storage_path: Optional[str] = None,
        triggers: Optional[List[ExpansionTrigger]] = None,
    ):
        self.project_root = Path(project_root)
        self.storage_path = storage_path
        self.extractor = KnowledgeExtractor(project_root)
        self.importer = KnowledgeImporter(project_root=project_root)
        self.validator = KnowledgeValidator(storage_path=storage_path)
        self.triggers = triggers or self._default_triggers()
        self.expansion_log_path = Path(storage_path or "data/software_engineering_knowledge") / "expansion_log.jsonl"

    def _default_triggers(self) -> List[ExpansionTrigger]:
        """Define default expansion triggers."""
        return [
            ExpansionTrigger(
                name="post_task_completion",
                condition=lambda ctx: ctx.get("event") == "task_completed",
                extractors=["code", "documentation"],
                priority=8,
                cooldown_hours=1,
            ),
            ExpansionTrigger(
                name="post_debugging",
                condition=lambda ctx: ctx.get("event") == "debugging_completed",
                extractors=["code"],
                priority=9,
                cooldown_hours=2,
            ),
            ExpansionTrigger(
                name="post_code_review",
                condition=lambda ctx: ctx.get("event") == "code_review_completed",
                extractors=["code"],
                priority=7,
                cooldown_hours=4,
            ),
            ExpansionTrigger(
                name="post_incident",
                condition=lambda ctx: ctx.get("event") == "incident_resolved",
                extractors=["code", "documentation", "experience", "lessons"],
                priority=10,
                cooldown_hours=0,  # No cooldown for incidents
            ),
            ExpansionTrigger(
                name="post_deployment",
                condition=lambda ctx: ctx.get("event") == "deployment_completed",
                extractors=["documentation", "experience"],
                priority=6,
                cooldown_hours=1,
            ),
            ExpansionTrigger(
                name="periodic_full_scan",
                condition=lambda ctx: ctx.get("event") == "scheduled_scan",
                extractors=["code", "documentation", "experience", "lessons", "reflection"],
                priority=3,
                cooldown_hours=168,  # Weekly
            ),
        ]

    def check_triggers(self, context: Dict[str, Any]) -> List[ExpansionTrigger]:
        """Check which triggers should fire based on context."""
        fired = []
        for trigger in self.triggers:
            try:
                if trigger.condition(context):
                    # Check cooldown
                    if self._check_cooldown(trigger.name, trigger.cooldown_hours):
                        fired.append(trigger)
            except Exception:
                pass
        return fired

    def _check_cooldown(self, trigger_name: str, cooldown_hours: int) -> bool:
        """Check if trigger is past its cooldown period."""
        if cooldown_hours <= 0:
            return True

        if not self.expansion_log_path.exists():
            return True

        cutoff = datetime.now(timezone.utc).timestamp() - (cooldown_hours * 3600)

        try:
            with open(self.expansion_log_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        if entry.get("trigger") == trigger_name:
                            entry_time = datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00")).timestamp()
                            if entry_time > cutoff:
                                return False  # Still in cooldown
                    except Exception:
                        continue
        except Exception:
            pass

        return True

    def run_expansion(self, trigger: ExpansionTrigger, context: Dict[str, Any]) -> ExpansionResult:
        """Run knowledge expansion for a trigger."""
        import time

        start_time = time.time()
        all_items = []
        errors = []
        sources_used = []
        validated_count = 0

        try:
            # Run extractors
            for extractor_name in trigger.extractors:
                result = self._run_extractor(extractor_name, context)
                if result.success:
                    all_items.extend(result.items)
                    sources_used.append(extractor_name)
                else:
                    errors.extend(result.errors)

            # Validate and store items
            for item in all_items:
                validation = self.validator.validate(item)
                if validation.is_valid:
                    item.validation_status = validation.validation_status
                    item.confidence = validation.confidence

                    # Store
                    from app.software_engineering_knowledge.storage import get_knowledge_storage
                    storage = get_knowledge_storage(self.storage_path)
                    storage.create(item)
                    validated_count += 1
                else:
                    errors.append(f"Validation failed for {item.title}: {validation.notes}")

        except Exception as e:
            errors.append(f"Expansion error: {str(e)}")

        duration = time.time() - start_time

        # Log expansion
        result = ExpansionResult(
            trigger_name=trigger.name,
            timestamp=datetime.now(timezone.utc).isoformat(),
            items_created=len(all_items),
            items_validated=validated_count,
            errors=errors,
            extracted_sources=sources_used,
            duration_seconds=duration,
        )

        self._log_expansion(result)
        return result

    def _run_extractor(self, extractor_name: str, context: Dict[str, Any]) -> Any:
        """Run a specific extractor by name."""
        if extractor_name == "code":
            # Extract from relevant files based on context
            file_paths = context.get("changed_files", [])
            if not file_paths:
                # Get all source files
                result = self.extractor.extract_all()
                return result.get("code", ExtractionResult(success=True, items=[], errors=[], source="", source_type=None))
            else:
                paths = [self.project_root / p for p in file_paths if (self.project_root / p).exists()]
                return self.extractor.code_extractor.extract(paths)

        elif extractor_name == "documentation":
            return self.extractor.extractor(doc_extractor=...)  # Need to fix this

        elif extractor_name == "experience":
            return self.importer.import_from_source(KnowledgeSource.EXPERIENCE_MEMORY)

        elif extractor_name == "lessons":
            return self.importer.import_from_source(KnowledgeSource.ENGINEERING_LESSONS)

        elif extractor_name == "reflection":
            return self.importer.import_from_source(KnowledgeSource.REFLECTION)

        return ExtractionResult(success=False, items=[], errors=[f"Unknown extractor: {extractor_name}"], source="", source_type=None)

    def _log_expansion(self, result: ExpansionResult) -> None:
        """Log expansion result to file."""
        log_entry = {
            "trigger": result.trigger_name,
            "timestamp": result.timestamp,
            "items_created": result.items_created,
            "items_validated": result.items_validated,
            "errors": result.errors,
            "sources": result.extracted_sources,
            "duration": result.duration_seconds,
        }

        try:
            with open(self.expansion_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception:
            pass

    def get_expansion_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get history of autonomous expansions."""
        if not self.expansion_log_path.exists():
            return []

        results = []
        try:
            with open(self.expansion_log_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        results.append(json.loads(line))
                    except Exception:
                        continue
        except Exception:
            pass

        return results[-limit:]


class TaskCompletionExpander:
    """Specialized expander for post-task knowledge extraction."""

    def __init__(self, project_root: Path, storage_path: Optional[str] = None):
        self.project_root = Path(project_root)
        self.storage_path = storage_path
        self.extractor = KnowledgeExtractor(project_root)
        self.validator = KnowledgeValidator(storage_path=storage_path)

    def expand_from_task(
        self,
        task_description: str,
        task_result: Dict[str, Any],
        changed_files: List[str],
        technologies: List[str],
    ) -> ExpansionResult:
        """Extract knowledge from a completed task."""
        import time

        start_time = time.time()
        all_items = []
        errors = []
        sources = []

        # 1. Extract from changed files
        if changed_files:
            paths = [self.project_root / f for f in changed_files if (self.project_root / f).exists()]
            if paths:
                code_result = self.extractor.code_extractor.extract(paths)
                if code_result.success:
                    all_items.extend(code_result.items)
                    sources.append("code")
                errors.extend(code_result.errors)

        # 2. Create task summary knowledge
        task_item = self._create_task_summary(task_description, task_result, technologies)
        all_items.append(task_item)
        sources.append("task_summary")

        # 3. Extract patterns from result
        if task_result.get("patterns_used"):
            pattern_items = self._create_pattern_items(task_result["patterns_used"], technologies)
            all_items.extend(pattern_items)
            sources.append("patterns")

        # 4. Extract lessons if any issues
        if task_result.get("issues_encountered"):
            lesson_items = self._create_lesson_items(task_result["issues_encountered"], technologies)
            all_items.extend(lesson_items)
            sources.append("lessons")

        # Validate and store
        validated = 0
        from app.software_engineering_knowledge.storage import get_knowledge_storage
        storage = get_knowledge_storage(self.storage_path)

        for item in all_items:
            validation = self.validator.validate(item)
            if validation.is_valid:
                item.validation_status = validation.validation_status
                item.confidence = validation.confidence
                storage.create(item)
                validated += 1
            else:
                errors.append(f"Validation failed: {validation.notes}")

        duration = time.time() - start_time

        return ExpansionResult(
            trigger_name="task_completion",
            timestamp=datetime.now(timezone.utc).isoformat(),
            items_created=len(all_items),
            items_validated=validated,
            errors=errors,
            extracted_sources=sources,
            duration_seconds=duration,
        )

    def _create_task_summary(
        self,
        description: str,
        result: Dict[str, Any],
        technologies: List[str],
    ) -> EngineeringKnowledgeItem:
        """Create a task summary knowledge item."""
        summary = result.get("summary", "Task completed")
        outcome = result.get("outcome", "success")

        content = f"Task: {description}\n\nOutcome: {outcome}\n\nSummary: {summary}\n\n"
        if result.get("details"):
            content += f"Details: {result['details']}\n\n"
        if technologies:
            content += f"Technologies: {', '.join(technologies)}\n"

        return EngineeringKnowledgeItem(
            title=f"Task: {description[:60]}...",
            summary=summary[:200],
            content=content,
            domain=EngineeringDomain.ENGINEERING_LESSONS,
            sub_category="task_summary",
            knowledge_type=EngineeringKnowledgeType.EXAMPLE,
            source=KnowledgeSource.EXPERIENCE_MEMORY,
            source_uri="task_completion",
            source_metadata={"task": description, "result": result, "technologies": technologies},
            tags=["task", "experience"] + technologies,
            confidence=0.8,
            validation_status=ValidationStatus.PENDING,
        )

    def _create_pattern_items(self, patterns: List[str], technologies: List[str]) -> List[EngineeringKnowledgeItem]:
        """Create knowledge items for patterns used."""
        items = []
        for pattern in patterns:
            item = EngineeringKnowledgeItem(
                title=f"Pattern Used: {pattern}",
                summary=f"Applied {pattern} pattern in task",
                content=f"Pattern: {pattern}\n\nThis pattern was successfully applied in a recent task using technologies: {', '.join(technologies)}.",
                domain=EngineeringDomain.DESIGN_PATTERNS,
                sub_category="applied_patterns",
                knowledge_type=EngineeringKnowledgeType.CODE_PATTERN,
                source=KnowledgeSource.EXPERIENCE_MEMORY,
                source_uri="task_completion",
                source_metadata={"pattern": pattern, "technologies": technologies},
                tags=["pattern", "applied"] + technologies,
                confidence=0.85,
                validation_status=ValidationStatus.PENDING,
            )
            items.append(item)
        return items

    def _create_lesson_items(self, issues: List[str], technologies: List[str]) -> List[EngineeringKnowledgeItem]:
        """Create knowledge items for lessons learned from issues."""
        items = []
        for i, issue in enumerate(issues):
            item = EngineeringKnowledgeItem(
                title=f"Lesson: {issue[:60]}...",
                summary=f"Encountered issue: {issue}",
                content=f"Issue encountered: {issue}\n\nThis issue was encountered during a task using: {', '.join(technologies)}.\nResolution approach should be documented for future reference.",
                domain=EngineeringDomain.ENGINEERING_LESSONS,
                sub_category="lessons_learned",
                knowledge_type=EngineeringKnowledgeType.LESSON_LEARNED,
                source=KnowledgeSource.EXPERIENCE_MEMORY,
                source_uri="task_completion",
                source_metadata={"issue": issue, "technologies": technologies},
                tags=["lesson", "issue", "troubleshooting"] + technologies,
                confidence=0.8,
                validation_status=ValidationStatus.PENDING,
            )
            items.append(item)
        return items


# === Event-based autonomous expansion ===

class ExpansionEventHandler:
    """Handle events that trigger knowledge expansion."""

    def __init__(self, expander: AutonomousExpander):
        self.expander = expander

    def handle_event(self, event_type: str, context: Dict[str, Any]) -> List[ExpansionResult]:
        """Handle an event and run applicable expansions."""
        context["event"] = event_type
        triggers = self.expander.check_triggers(context)

        results = []
        for trigger in triggers:
            result = self.expander.run_expansion(trigger, context)
            results.append(result)

        return results

    # Convenience methods for common events
    def on_task_completed(self, task_description: str, result: Dict[str, Any],
                          changed_files: List[str], technologies: List[str]) -> List[ExpansionResult]:
        context = {
            "event": "task_completed",
            "task_description": task_description,
            "result": result,
            "changed_files": changed_files,
            "technologies": technologies,
        }
        return self.handle_event("task_completed", context)

    def on_debugging_completed(self, bug_description: str, root_cause: str,
                                fix: str, files_changed: List[str]) -> List[ExpansionResult]:
        context = {
            "event": "debugging_completed",
            "bug_description": bug_description,
            "root_cause": root_cause,
            "fix": fix,
            "changed_files": files_changed,
        }
        return self.handle_event("debugging_completed", context)

    def on_code_review_completed(self, pr_description: str, comments: List[str],
                                  files_reviewed: List[str]) -> List[ExpansionResult]:
        context = {
            "event": "code_review_completed",
            "pr_description": pr_description,
            "comments": comments,
            "changed_files": files_reviewed,
        }
        return self.handle_event("code_review_completed", context)

    def on_incident_resolved(self, incident_description: str, root_cause: str,
                              resolution: str, timeline: List[str]) -> List[ExpansionResult]:
        context = {
            "event": "incident_resolved",
            "incident_description": incident_description,
            "root_cause": root_cause,
            "resolution": resolution,
            "timeline": timeline,
        }
        return self.handle_event("incident_resolved", context)

    def on_deployment_completed(self, version: str, changes: List[str],
                                 success: bool, notes: str) -> List[ExpansionResult]:
        context = {
            "event": "deployment_completed",
            "version": version,
            "changes": changes,
            "success": success,
            "notes": notes,
        }
        return self.handle_event("deployment_completed", context)


# === Background Scheduler for Autonomous Expansion ===

class AutonomousExpansionScheduler:
    """Background scheduler that runs autonomous knowledge expansion on a schedule."""

    def __init__(
        self,
        expander: AutonomousExpander,
        event_handler: ExpansionEventHandler,
        check_interval_seconds: int = 300,  # 5 minutes default
    ):
        """Initialize the scheduler.

        Args:
            expander: The AutonomousExpander instance
            event_handler: The ExpansionEventHandler instance
            check_interval_seconds: How often to check for triggers (default 5 minutes)
        """
        self.expander = expander
        self.event_handler = event_handler
        self.check_interval = check_interval_seconds
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Start the background scheduler."""
        async with self._lock:
            if self._running:
                logger.warning("Scheduler already running")
                return

            self._running = True
            self._task = asyncio.create_task(self._run_loop())
            logger.info(f"Autonomous expansion scheduler started (interval: {self.check_interval}s)")

    async def stop(self) -> None:
        """Stop the background scheduler."""
        async with self._lock:
            if not self._running:
                return

            self._running = False
            if self._task:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
            logger.info("Autonomous expansion scheduler stopped")

    async def _run_loop(self) -> None:
        """Main scheduler loop."""
        while self._running:
            try:
                # Check for scheduled triggers (periodic_full_scan, etc.)
                await self._check_scheduled_triggers()

                # Sleep until next check
                await asyncio.sleep(self.check_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")
                await asyncio.sleep(self.check_interval)

    async def _check_scheduled_triggers(self) -> None:
        """Check for time-based triggers that should fire."""
        context = {"event": "scheduled_scan"}

        triggers = self.expander.check_triggers(context)
        for trigger in triggers:
            if trigger.name == "periodic_full_scan":
                logger.info("Running scheduled full knowledge expansion scan")
                try:
                    result = self.expander.run_expansion(trigger, context)
                    logger.info(f"Scheduled expansion completed: {result.items_created} items created, {result.items_validated} validated")
                except Exception as e:
                    logger.error(f"Scheduled expansion failed: {e}")

    def trigger_manual_expansion(self, trigger_name: str, context: Dict[str, Any]) -> List[ExpansionResult]:
        """Manually trigger an expansion (synchronous - for testing/CLI).

        Args:
            trigger_name: Name of the trigger to fire
            context: Context for the expansion

        Returns:
            List of ExpansionResult objects
        """
        # Find the trigger
        trigger = next((t for t in self.expander.triggers if t.name == trigger_name), None)
        if not trigger:
            logger.warning(f"Unknown trigger: {trigger_name}")
            return []

        # Override cooldown for manual triggers
        context["manual_trigger"] = True
        original_cooldown = trigger.cooldown_hours
        trigger.cooldown_hours = 0

        try:
            result = self.expander.run_expansion(trigger, context)
            return [result]
        finally:
            trigger.cooldown_hours = original_cooldown


def create_expansion_system(
    project_root: Path,
    storage_path: Optional[str] = None,
    scheduler_interval: int = 300,
) -> tuple[AutonomousExpander, ExpansionEventHandler, AutonomousExpansionScheduler]:
    """Factory function to create the complete expansion system.

    Args:
        project_root: Root path of the project
        storage_path: Path for knowledge storage
        scheduler_interval: Scheduler check interval in seconds

    Returns:
        Tuple of (expander, event_handler, scheduler)
    """
    expander = AutonomousExpander(project_root, storage_path)
    event_handler = ExpansionEventHandler(expander)
    scheduler = AutonomousExpansionScheduler(expander, event_handler, scheduler_interval)
    return expander, event_handler, scheduler