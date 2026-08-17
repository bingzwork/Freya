"""Executable Capability Implementations for Central Orchestrator.

This module provides concrete implementations of the 14 built-in capabilities
that integrate with FreyaAgent's subsystems.
"""

import importlib.metadata
import json
import logging
import mimetypes
import os
import shlex
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse

from app.orchestrator.capability_registry import Capability, CapabilityMetadata, CapabilityCategory, CapabilityState
from app.core.events import get_event_bus, Event

logger = logging.getLogger(__name__)


class BaseCapability(Capability):
    """Base class for executable capabilities."""

    def __init__(self, metadata: CapabilityMetadata):
        super().__init__(metadata)
        self._event_bus = get_event_bus()

    def execute(self, action: str, inputs: Dict[str, Any]) -> Any:
        """Execute a declared, callable action only."""
        if not self.supports_action(action):
            raise NotImplementedError(
                f"Capability '{self.name}' does not support executable action '{action}'"
            )
        return getattr(self, f"action_{action}")(inputs)

    def _get_event_bus(self):
        """Get event bus, lazy-initializing if needed."""
        if self._event_bus is None:
            self._event_bus = get_event_bus()
        return self._event_bus

    def _publish_event(self, event_type: str, payload: Dict[str, Any]):
        """Publish an event to the event bus."""
        try:
            event = Event(
                name=event_type,
                data=payload,
                source=f"capability:{self.metadata.name}",
            )
            self._get_event_bus().publish(event)
        except Exception as e:
            logger.warning(f"Failed to publish event {event_type}: {e}")


# =============================================================================
# Memory Management Capability
# =============================================================================

class MemoryManagementCapability(BaseCapability):
    """Core memory management capability."""

    def __init__(self):
        super().__init__(CapabilityMetadata(
            name="memory_management",
            version="1.0.0",
            description="Core memory management - store, retrieve, and organize memories",
            category=CapabilityCategory.MEMORY,
            is_singleton=True,
            auto_discoverable=True,
            default_action="store",
            supported_actions=["store", "retrieve", "consolidate"],
        ))
        self._memory = None

    def _initialize(self) -> bool:
        return True

    def _activate(self) -> bool:
        return True

    def _deactivate(self) -> bool:
        return True

    def set_memory_coordinator(self, memory):
        """Bind the initializer-owned MemoryCoordinator."""
        self._memory = memory

    @staticmethod
    def _entry_value(value: Any) -> Any:
        return value.to_dict() if hasattr(value, "to_dict") else value

    def action_store(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Store through MemoryCoordinator and its owned memory modules."""
        if not self._memory:
            return {"success": False, "error": "MemoryCoordinator unavailable"}
        content = str(inputs.get("content", "")).strip()
        memory_type = inputs.get("type", "experience")
        metadata = inputs.get("metadata", {}) or {}
        if not content:
            return {"success": False, "error": "content required"}
        try:
            if memory_type == "experience":
                from app.memory.experience_memory import ExperienceEntry
                entry = self._memory.add_experience(ExperienceEntry(
                    id="",
                    title=str(metadata.get("title", "Capability memory")),
                    description=content,
                    category=str(metadata.get("category", "capability")),
                    tags=list(metadata.get("tags", [])),
                    outcome=str(metadata.get("outcome", "neutral")),
                    confidence=float(metadata.get("confidence", 0.5)),
                    metadata=metadata,
                    source="memory_management",
                ))
                result_id = getattr(entry, "id", None)
            elif memory_type == "project":
                result = self._memory.project_memory.record(
                    str(metadata.get("kind", "memory")),
                    {"content": content, **metadata},
                )
                result_id = result.get("timestamp") if isinstance(result, dict) else result
            elif memory_type == "semantic":
                result_id = self._memory.store_learned({
                    "learning_type": "knowledge",
                    "title": str(metadata.get("title", "Capability knowledge")),
                    "content": content,
                    "category": str(metadata.get("category", "general")),
                    "confidence": float(metadata.get("confidence", 0.5)),
                    "source": "memory_management",
                    "tags": list(metadata.get("tags", [])),
                    "metadata": metadata,
                })
            else:
                return {"success": False, "error": f"Unknown memory type: {memory_type}"}
            self._publish_event("memory.stored", {"type": memory_type, "content": content[:100]})
            return {"success": True, "stored": True, "id": str(result_id) if result_id else None}
        except Exception as e:
            logger.error(f"Memory store failed: {e}")
            return {"success": False, "error": str(e)}

    def action_retrieve(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Retrieve through MemoryCoordinatorÃ¢â‚¬â„¢s unified or owned read surfaces."""
        if not self._memory:
            return {"success": False, "error": "MemoryCoordinator unavailable"}
        query = str(inputs.get("query", ""))
        memory_type = inputs.get("type", "unified")
        limit = max(1, min(int(inputs.get("limit", 10)), 100))
        try:
            if memory_type == "unified":
                results = self._memory.unified_retrieval.retrieve(query)[:limit]
            elif memory_type == "experience":
                results = self._memory.experience_memory.search(query, limit=limit)
            elif memory_type == "project":
                results = self._memory.project_memory.search(query, limit=limit)
            elif memory_type == "semantic":
                results = self._memory.semantic_memory.search(query, limit=limit)
            else:
                return {"success": False, "error": f"Unknown memory type: {memory_type}"}
            return {"success": True, "results": [self._entry_value(result) for result in results]}
        except Exception as e:
            logger.error(f"Memory retrieve failed: {e}")
            return {"success": False, "error": str(e)}

    def action_consolidate(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Trigger consolidation through the coordinator-owned engine."""
        if not self._memory or not hasattr(self._memory, "consolidation_engine"):
            return {"success": False, "error": "MemoryCoordinator unavailable"}
        try:
            result = self._memory.consolidation_engine.run_consolidation()
            self._publish_event("memory.consolidated", {})
            return {"success": True, "consolidated": True, "result": result}
        except Exception as e:
            logger.error(f"Memory consolidation failed: {e}")
            return {"success": False, "error": str(e)}


# =============================================================================
# Planning Engine Capability
# =============================================================================

class PlanningEngineCapability(BaseCapability):
    """Task and goal planning capability."""

    def __init__(self):
        super().__init__(CapabilityMetadata(
            name="planning_engine",
            version="1.0.0",
            description="Task and goal planning with adaptive replanning",
            category=CapabilityCategory.PLANNING,
            is_singleton=True,
            auto_discoverable=True,
            default_action="create_plan",
            supported_actions=["create_plan", "replan", "get_plan"],
        ))
        self._planner = None
        self._plan_manager = None
        self._decision_manager = None

    def _initialize(self) -> bool:
        return True

    def _activate(self) -> bool:
        return True

    def _deactivate(self) -> bool:
        return True

    def set_components(self, planner, plan_manager, decision_manager):
        self._planner = planner
        self._plan_manager = plan_manager
        self._decision_manager = decision_manager

    def action_create_plan(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Create a plan through the initializer-owned production planner."""
        if not self._planner:
            return {"success": False, "error": "Planner not initialized"}

        task = inputs.get("task", "")
        context = inputs.get("context", {})
        external_context = context if isinstance(context, str) else json.dumps(context)

        try:
            if hasattr(self._planner, "_agent_planner"):
                plan = self._planner.create_plan(
                    task,
                    external_context,
                    inputs.get("allow_mutations", True),
                )
            else:
                plan = self._planner.create_plan(
                    task,
                    name=inputs.get("name", "Generated Plan"),
                    external_context=external_context,
                )
            if plan is None:
                return {"success": False, "error": "Planner returned no plan"}
            if self._plan_manager and hasattr(self._plan_manager, "register_plan"):
                self._plan_manager.register_plan(plan)
            self._publish_event("plan.created", {"plan_id": plan.id, "task": task[:100]})
            return {
                "success": True,
                "plan_id": plan.id,
                "plan_name": plan.config.name,
                "steps": [{"id": t.id, "title": t.title} for t in plan.tasks],
            }
        except Exception as e:
            logger.error(f"Plan creation failed: {e}")
            return {"success": False, "error": str(e)}

    def action_replan(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing plan after a failure or changed constraints."""
        if not self._plan_manager:
            return {"success": False, "error": "Plan manager not initialized"}
        if not self._planner:
            return {"success": False, "error": "Planner not initialized"}
        if not self._decision_manager:
            return {"success": False, "error": "Decision manager not initialized"}

        plan_id = inputs.get("plan_id")
        plan = self._plan_manager.load_plan(plan_id) if plan_id else self._plan_manager.get_active_plan()
        if plan is None:
            return {"success": False, "error": "Plan not found"}

        failed_task_id = inputs.get("failed_task_id")
        if not failed_task_id:
            failed_task_id = next(
                (task.id for task in plan.tasks if getattr(task.status, "value", task.status) in {"failed", "blocked"}),
                None,
            )
        if not failed_task_id:
            return {"success": False, "error": "failed_task_id required"}

        new_steps = inputs.get("new_steps")
        proposal_id = None
        try:
            if not isinstance(new_steps, list) or not new_steps:
                context = inputs.get("context", {})
                failure = inputs.get("failure", inputs.get("task", ""))
                prompt = f"Replan the existing task after this failure: {failure}. Context: {context}"
                if hasattr(self._planner, "_agent_planner"):
                    proposal = self._planner.create_plan(prompt, "", inputs.get("allow_mutations", True))
                else:
                    proposal = self._planner.create_plan(prompt, external_context="")
                if proposal is None:
                    return {"success": False, "error": "Planner returned no replacement plan"}
                proposal_id = proposal.id
                new_steps = [task.title for task in proposal.tasks]
                if proposal_id != plan.id and hasattr(self._plan_manager, "delete_plan"):
                    self._plan_manager.delete_plan(proposal_id)
                self._plan_manager.set_active_plan(plan.id)

            new_steps = [str(step).strip() for step in new_steps if str(step).strip()]
            if not new_steps:
                return {"success": False, "error": "new_steps must contain at least one replacement step"}
            result = plan.replan_after_failure(
                failed_task_id,
                new_steps,
                anchor_task_id=inputs.get("anchor_task_id"),
            )
            self._plan_manager.save_plan(plan)
            self._publish_event("plan.replanned", {
                "plan_id": plan.id,
                "failed_task_id": failed_task_id,
                "added_task_ids": result["added"],
            })
            return {
                "success": True,
                "replanned": True,
                "plan_id": plan.id,
                "invalidated": result["invalidated"],
                "added": result["added"],
                "steps": new_steps,
            }
        except Exception as e:
            logger.error(f"Replanning failed: {e}")
            return {"success": False, "error": str(e)}

    def action_get_plan(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Get a plan by ID."""
        if not self._plan_manager:
            return {"success": False, "error": "Plan manager not initialized"}

        plan_id = inputs.get("plan_id")
        if not plan_id:
            return {"success": False, "error": "plan_id required"}

        try:
            plan = self._plan_manager.load_plan(plan_id)
            if not plan:
                return {"success": False, "error": "Plan not found"}

            return {
                "success": True,
                "plan_id": plan.id,
                "plan_name": plan.config.name,
                "status": "completed" if all(t.status.value == "completed" for t in plan.tasks) else "active",
                "steps": [{"id": t.id, "title": t.title, "status": t.status.value} for t in plan.tasks],
            }
        except Exception as e:
            logger.error(f"Get plan failed: {e}")
            return {"success": False, "error": str(e)}


# =============================================================================
# Code Execution Capability
# =============================================================================

class CodeExecutionCapability(BaseCapability):
    """Code execution and tools capability."""

    def __init__(self):
        super().__init__(CapabilityMetadata(
            name="code_execution",
            version="1.0.0",
            description="Code execution, patch application, and verification",
            category=CapabilityCategory.EXECUTION,
            is_singleton=True,
            auto_discoverable=True,
            default_action="run_command",
            supported_actions=["apply_patch", "verify", "run_command"],
        ))
        self._executor = None
        self._verifier = None
        self._patch_engine = None
        self._tools = None

    def _initialize(self) -> bool:
        return True

    def _activate(self) -> bool:
        return True

    def _deactivate(self) -> bool:
        return True

    def set_components(self, executor, verifier, patch_engine, tools):
        self._executor = executor
        self._verifier = verifier
        self._patch_engine = patch_engine
        self._tools = tools

    def action_apply_patch(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Apply a patch proposal."""
        if not self._patch_engine:
            return {"success": False, "error": "Patch engine not initialized"}

        operations = inputs.get("operations", [])
        try:
            result = self._patch_engine.apply(self._tools, operations)
            self._publish_event("code.patch_applied", {"operations": len(operations)})
            return {"success": True, "result": result}
        except Exception as e:
            logger.error(f"Patch apply failed: {e}")
            return {"success": False, "error": str(e)}

    def action_verify(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Run verification/tests."""
        if not self._verifier:
            return {"success": False, "error": "Verifier not initialized"}

        try:
            result = self._verifier.run_tests()
            self._publish_event("code.verified", {"success": result.success})
            return {
                "success": True,
                "verified": result.success,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except Exception as e:
            logger.error(f"Verification failed: {e}")
            return {"success": False, "error": str(e)}

    def action_run_command(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Run a terminal command."""
        if not self._tools:
            return {"success": False, "error": "Tools not initialized"}

        command = inputs.get("command", "")
        try:
            result = self._tools.run_terminal(command)
            return {"success": True, "stdout": result.get("stdout", ""), "stderr": result.get("stderr", "")}
        except Exception as e:
            logger.error(f"Command execution failed: {e}")
            return {"success": False, "error": str(e)}


# =============================================================================
# Decision Engine Capability
# =============================================================================

class DecisionEngineCapability(BaseCapability):
    """Decision making capability."""

    def __init__(self):
        super().__init__(CapabilityMetadata(
            name="decision_engine",
            version="1.0.0",
            description="Automated decision making with confidence scoring and risk assessment",
            category=CapabilityCategory.DECISION,
            is_singleton=True,
            auto_discoverable=True,
            default_action="decide",
            supported_actions=["decide"],
        ))
        self._decision_manager = None

    def _initialize(self) -> bool:
        return True

    def _activate(self) -> bool:
        return True

    def _deactivate(self) -> bool:
        return True

    def set_decision_manager(self, dm):
        self._decision_manager = dm

    def action_decide(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Make a decision."""
        if not self._decision_manager:
            return {"success": False, "error": "Decision manager not initialized"}

        task = inputs.get("task", "")
        context = inputs.get("context", {})
        options = inputs.get("options", [])

        try:
            from app.decision.models import DecisionContext, DecisionOption
            decision_context = DecisionContext(
                task_description=task,
                available_context=str(context),
                project_state=context if isinstance(context, dict) else {},
                metadata=context if isinstance(context, dict) else {},
                component="decision_engine",
            )
            decision_options = [
                DecisionOption.from_dict(option) if isinstance(option, dict) else option
                for option in options
            ]
            result = self._decision_manager.decide(decision_context, decision_options)
            choice = result.chosen_option.name if result.chosen_option else None
            self._publish_event("decision.made", {"task": task[:100], "choice": choice})
            return {
                "success": True,
                "decision": choice,
                "confidence": result.confidence,
                "rationale": result.rationale,
                "risk_level": result.risk_level.value if hasattr(result.risk_level, 'value') else str(result.risk_level),
            }
        except Exception as e:
            logger.error(f"Decision failed: {e}")
            return {"success": False, "error": str(e)}


# =============================================================================
# Learning Pipeline Capability
# =============================================================================

class LearningPipelineCapability(BaseCapability):
    """Thin adapter over the authoritative LearningPipeline."""
    def __init__(self):
        super().__init__(CapabilityMetadata(
            name="learning_pipeline",
            version="1.0.0",
            description="Continuous learning from experiences and outcomes",
            category=CapabilityCategory.LEARNING,
            is_singleton=True,
            auto_discoverable=True,
            default_action="reflect",
            supported_actions=["reflect", "consolidate", "store_lesson"],
        ))
        self._pipeline = None
        self._memory = None


    def _initialize(self) -> bool:
        return True

    def _activate(self) -> bool:
        return True

    def _deactivate(self) -> bool:
        return True

    def set_learning_pipeline(self, pipeline, memory=None):
        """Bind the initializer-owned LearningPipeline and MemoryCoordinator."""
        self._pipeline = pipeline
        self._memory = memory or getattr(pipeline, "_memory", None)

    @staticmethod
    def _candidate(inputs: Dict[str, Any], *, raw_observation: Dict[str, Any], tags=None):
        from app.learning.models import LearningCandidate, LearningCandidateType
        return LearningCandidate(
            candidate_type=LearningCandidateType.MANUAL_INPUT,
            source_component="LearningPipelineCapability",
            source_session_id=str(inputs.get("session_id", "")),
            raw_observation=raw_observation,
            context=inputs.get("context", {}) or {},
            tags=list(tags or inputs.get("tags", []) or []),
            metadata=inputs.get("metadata", {}) or {},
        )

    def _run_candidate(self, inputs: Dict[str, Any], raw_observation: Dict[str, Any], tags=None):
        if not self._pipeline:
            return {"success": False, "error": "LearningPipeline unavailable"}
        try:
            result = self._pipeline.run(self._candidate(
                inputs,
                raw_observation=raw_observation,
                tags=tags,
            ))
            return {"success": True, "result": result.to_dict() if hasattr(result, "to_dict") else result}
        except Exception as e:
            logger.error(f"Learning pipeline run failed: {e}")
            return {"success": False, "error": str(e)}

    def action_reflect(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Run an observation through the real learning pipeline."""
        task_description = str(inputs.get("task", ""))
        if not task_description:
            return {"success": False, "error": "task required"}
        return self._run_candidate(
            inputs,
            raw_observation={
                "task": task_description,
                "outcome": inputs.get("outcome", "success"),
                "eval_result": inputs.get("eval_result"),
            },
            tags=["reflection"],
        )

    def action_consolidate(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Run the coordinator-owned consolidation engine."""
        if not self._memory:
            return {"success": False, "error": "MemoryCoordinator unavailable"}
        try:
            result = self._memory.consolidation_engine.run_consolidation()
            self._publish_event("learning.consolidated", {})
            return {"success": True, "consolidated": True, "result": result}
        except Exception as e:
            logger.error(f"Consolidation failed: {e}")
            return {"success": False, "error": str(e)}

    def action_store_lesson(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Submit a lesson observation to the real learning pipeline."""
        title = str(inputs.get("title", "")).strip()
        description = str(inputs.get("description", "")).strip()
        if not title or not description:
            return {"success": False, "error": "title and description required"}
        return self._run_candidate(
            inputs,
            raw_observation={
                "title": title,
                "description": description,
                "category": inputs.get("category", "task"),
                "severity": inputs.get("severity", "recommended"),
                "rationale": inputs.get("rationale", ""),
            },
            tags=list(inputs.get("tags", []) or []) + ["lesson"],
        )


# =============================================================================
# System Monitoring Capability
# =============================================================================

class SystemMonitoringCapability(BaseCapability):
    """System health monitoring capability."""

    def __init__(self):
        super().__init__(CapabilityMetadata(
            name="system_monitoring",
            version="1.0.0",
            description="System health monitoring and metrics collection",
            category=CapabilityCategory.MONITORING,
            is_singleton=True,
            auto_discoverable=True,
            default_action="get_health",
            supported_actions=["get_health", "get_metrics", "check_component"],
        ))
        self._observability = None

    def _initialize(self) -> bool:
        return True

    def _activate(self) -> bool:
        return True

    def _deactivate(self) -> bool:
        return True

    def set_observability(self, obs):
        self._observability = obs

    def action_get_health(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Get system health status."""
        if not self._observability:
            return {"success": False, "error": "Observability not initialized"}

        try:
            health = self._observability.get_health()
            return {"success": True, "health": health}
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {"success": False, "error": str(e)}

    def action_get_metrics(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Get system metrics."""
        if not self._observability:
            return {"success": False, "error": "Observability not initialized"}

        try:
            metrics = self._observability.get_system_metrics()
            return {"success": True, "metrics": metrics}
        except Exception as e:
            logger.error(f"Metrics retrieval failed: {e}")
            return {"success": False, "error": str(e)}

    def action_check_component(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Check health of a specific component."""
        if not self._observability:
            return {"success": False, "error": "Observability not initialized"}

        component = inputs.get("component")
        if not component:
            return {"success": False, "error": "component required"}

        try:
            result = self._observability.get_health(component=component)
            status = result.get("status") if isinstance(result, dict) else getattr(result, "status", result)
            if hasattr(status, "value"):
                status = status.value
            message = result.get("message", "") if isinstance(result, dict) else getattr(result, "message", "")
            return {"success": True, "component": component, "status": status, "message": message}
        except Exception as e:
            logger.error(f"Component check failed: {e}")
            return {"success": False, "error": str(e)}


# =============================================================================
# Communication Hub Capability
# =============================================================================

class CommunicationHubCapability(BaseCapability):
    """Inter-component communication capability."""

    def __init__(self):
        super().__init__(CapabilityMetadata(
            name="communication_hub",
            version="1.0.0",
            description="Event publishing and subscription for inter-component communication",
            category=CapabilityCategory.COMMUNICATION,
            is_singleton=True,
            auto_discoverable=True,
            default_action="publish",
            supported_actions=["publish", "get_history"],
        ))

    def _initialize(self) -> bool:
        return True

    def _activate(self) -> bool:
        return True

    def _deactivate(self) -> bool:
        return True

    def set_event_bus(self, eb):
        self._event_bus = eb

    def action_publish(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Publish an event through the shared EventBus."""
        if not self._event_bus:
            return {"success": False, "error": "Event bus not initialized"}

        event_type = inputs.get("event_type", "")
        if not isinstance(event_type, str) or not event_type.strip():
            return {"success": False, "error": "event_type required"}
        data = inputs.get("data", {})
        priority_name = str(inputs.get("priority", "normal")).upper()

        try:
            from app.core.events import EventPriority
            priority = EventPriority[priority_name]
            event = self._event_bus.emit(
                event_type,
                data,
                source="capability:communication_hub",
                priority=priority,
            )
            return {"success": True, "published": True, "event": event.to_dict()}
        except KeyError:
            return {"success": False, "error": f"Unknown event priority: {priority_name.lower()}"}
        except Exception as e:
            logger.error(f"Event publish failed: {e}")
            return {"success": False, "error": str(e)}

    def action_get_history(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Return recent events from the shared EventBus history."""
        if not self._event_bus:
            return {"success": False, "error": "Event bus not initialized"}

        try:
            limit = max(1, min(int(inputs.get("limit", 100)), 1000))
            events = self._event_bus.history().get_recent(limit)
            return {
                "success": True,
                "events": [event.to_dict() if hasattr(event, "to_dict") else event for event in events],
            }
        except (TypeError, ValueError):
            return {"success": False, "error": "limit must be an integer"}
        except Exception as e:
            logger.error(f"Event history failed: {e}")
            return {"success": False, "error": str(e)}


# =============================================================================
# Debugging Capability
# =============================================================================

class DebuggingCapability(BaseCapability):
    """Repository diagnostics built on the canonical tools and verifier."""

    def __init__(self):
        super().__init__(CapabilityMetadata(
            name="debugging",
            version="1.0.0",
            description="Inspect errors, run targeted diagnostics, and validate fixes",
            category=CapabilityCategory.CUSTOM,
            is_singleton=True,
            auto_discoverable=True,
            default_action="inspect_error",
            supported_actions=["inspect_error", "run_diagnostics", "validate_fix"],
        ))
        self._tools = None
        self._verifier = None
        self._safety_gate = None

    def set_components(self, tools, verifier, safety_gate):
        self._tools = tools
        self._verifier = verifier
        self._safety_gate = safety_gate

    def action_inspect_error(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Inspect an error message or a workspace file containing one."""
        if not self._tools:
            return {"success": False, "error": "Tools not initialized"}
        path = inputs.get("path")
        try:
            if path:
                result = self._tools.execute("read_file", path=path)
                if not result.success:
                    return {"success": False, "error": result.error}
                details = result.output
            else:
                details = inputs.get("error", inputs.get("message", ""))
                if not details:
                    return {"success": False, "error": "path or error required"}
            return {"success": True, "details": details}
        except Exception as e:
            logger.error(f"Error inspection failed: {e}")
            return {"success": False, "error": str(e)}

    def _authorize(self, operation: str, operation_type: str) -> Optional[Dict[str, Any]]:
        if not self._safety_gate:
            return {"success": False, "error": "Safety gate not initialized"}
        try:
            self._safety_gate.check_and_enforce(
                operation,
                operation_type,
                {"capability": self.name},
            )
            return None
        except Exception as e:
            return {"success": False, "error": str(e)}

    def action_run_diagnostics(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Run a bounded diagnostic or targeted test command through SafetyGate."""
        if not self._tools:
            return {"success": False, "error": "Tools not initialized"}
        command = inputs.get("command", "pytest -q")
        execution_command = command
        if os.name == "nt" and command.lstrip().lower().startswith("printf "):
            execution_command = "echo " + command.lstrip()[7:]
        if not isinstance(command, str) or not command.strip():
            return {"success": False, "error": "command required"}
        denied = self._authorize(command, "test_execution")
        if denied:
            return denied
        try:
            result = self._tools.execute("run_terminal", command=execution_command)
            return {
                "success": result.success and result.output.get("code", 1) == 0,
                "stdout": (result.output.get("stdout", "") if result.success else "").strip(),
                "stderr": result.output.get("stderr", result.error or "") if result.success else result.error,
                "return_code": result.output.get("code", 1) if result.success else 1,
            }
        except Exception as e:
            logger.error(f"Diagnostics failed: {e}")
            return {"success": False, "error": str(e)}

    def action_validate_fix(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Run the existing verification runner after the workflow safety check."""
        if not self._verifier:
            return {"success": False, "error": "Verifier not initialized"}
        denied = self._authorize("validate proposed fix", "test_execution")
        if denied:
            return denied
        try:
            result = self._verifier.run_tests()
            return {
                "success": result.success,
                "verified": result.success,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "return_code": result.return_code,
            }
        except Exception as e:
            logger.error(f"Fix validation failed: {e}")
            return {"success": False, "error": str(e)}


# =============================================================================
# Dependency Management Capability
# =============================================================================

class DependencyManagementCapability(BaseCapability):
    """Dependency inspection and explicitly authorized environment changes."""

    def __init__(self):
        super().__init__(CapabilityMetadata(
            name="dependency_management",
            version="1.0.0",
            description="Inspect, validate, and safely manage project dependencies",
            category=CapabilityCategory.CUSTOM,
            is_singleton=True,
            auto_discoverable=True,
            default_action="inspect",
            supported_actions=[
                "inspect", "check_installed", "validate", "install", "update",
                "remove", "verify_environment",
            ],
        ))
        self._tools = None
        self._verifier = None
        self._safety_gate = None
        self._auditor = None

    def set_components(self, tools, verifier, safety_gate, auditor):
        self._tools = tools
        self._verifier = verifier
        self._safety_gate = safety_gate
        self._auditor = auditor

    def _dependency_report(self) -> Dict[str, Any]:
        if not self._auditor:
            raise RuntimeError("Dependency auditor not initialized")
        return self._auditor.check_dependencies()

    def action_inspect(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Inspect declared dependency files using the existing auditor."""
        try:
            return {"success": True, "dependencies": self._dependency_report()}
        except Exception as e:
            logger.error(f"Dependency inspection failed: {e}")
            return {"success": False, "error": str(e)}

    def action_check_installed(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Compare declared packages with installed package metadata."""
        try:
            report = self._dependency_report()
            requested = inputs.get("packages") or list(report["packages"])
            installed = {}
            for package in requested:
                try:
                    installed[package] = {
                        "installed": True,
                        "version": importlib.metadata.version(package),
                    }
                except importlib.metadata.PackageNotFoundError:
                    installed[package] = {"installed": False, "version": None}
            return {"success": True, "packages": installed}
        except Exception as e:
            logger.error(f"Installed dependency check failed: {e}")
            return {"success": False, "error": str(e)}

    def action_validate(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Validate that supported dependency files parse and contain packages."""
        try:
            report = self._dependency_report()
            valid = bool(report["sources"]) and all(
                isinstance(name, str) and name.strip()
                for name in report["packages"]
            )
            return {
                "success": valid,
                "valid": valid,
                "sources": report["sources"],
                "package_count": len(report["packages"]),
                "error": None if valid else "No supported dependency declarations found",
            }
        except Exception as e:
            logger.error(f"Dependency validation failed: {e}")
            return {"success": False, "valid": False, "error": str(e)}

    def _mutate(self, action: str, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not self._tools:
            return {"success": False, "error": "Tools not initialized"}
        if not self._safety_gate:
            return {"success": False, "error": "Safety gate not initialized"}
        if inputs.get("authorized") is not True:
            return {"success": False, "error": "Explicit authorization is required"}
        package = inputs.get("package")
        if not isinstance(package, str) or not package.strip():
            return {"success": False, "error": "package required"}
        ecosystem = str(inputs.get("ecosystem", "python")).lower()
        if ecosystem == "python":
            executable = shlex.quote(sys.executable)
            package_arg = shlex.quote(package)
            if action == "install":
                command = f"{executable} -m pip install {package_arg}"
            elif action == "update":
                command = f"{executable} -m pip install --upgrade {package_arg}"
            else:
                command = f"{executable} -m pip uninstall -y {package_arg}"
        elif ecosystem in {"node", "npm"}:
            package_arg = shlex.quote(package)
            command = {
                "install": f"npm install {package_arg}",
                "update": f"npm update {package_arg}",
                "remove": f"npm uninstall {package_arg}",
            }[action]
        else:
            return {"success": False, "error": f"Unsupported ecosystem: {ecosystem}"}
        try:
            self._safety_gate.check_and_enforce(
                command,
                "system_modification",
                {"capability": self.name, "ecosystem": ecosystem, "package": package},
            )
            result = self._tools.execute("run_terminal", command=command)
            return {
                "success": result.success and result.output.get("code", 1) == 0,
                "command": command,
                "stdout": result.output.get("stdout", "") if result.success else "",
                "stderr": result.output.get("stderr", result.error or "") if result.success else result.error,
                "return_code": result.output.get("code", 1) if result.success else 1,
            }
        except Exception as e:
            logger.error(f"Dependency {action} failed: {e}")
            return {"success": False, "error": str(e)}

    def action_install(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        return self._mutate("install", inputs)

    def action_update(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        return self._mutate("update", inputs)

    def action_remove(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        return self._mutate("remove", inputs)

    def action_verify_environment(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Run the existing environment verification command through ToolManager."""
        if not self._tools:
            return {"success": False, "error": "Tools not initialized"}
        command = inputs.get("command", f"{shlex.quote(sys.executable)} -m pip check")
        if not self._safety_gate:
            return {"success": False, "error": "Safety gate not initialized"}
        try:
            self._safety_gate.check_and_enforce(
                command,
                "dependency_verification",
                {"capability": self.name},
            )
            result = self._tools.execute("run_terminal", command=command)
            return {
                "success": result.success and result.output.get("code", 1) == 0,
                "stdout": result.output.get("stdout", "") if result.success else "",
                "stderr": result.output.get("stderr", result.error or "") if result.success else result.error,
                "return_code": result.output.get("code", 1) if result.success else 1,
            }
        except Exception as e:
            logger.error(f"Dependency environment verification failed: {e}")
            return {"success": False, "error": str(e)}


# =============================================================================
# Tool Registry Capability
# =============================================================================

class ToolRegistryCapability(BaseCapability):
    """Tool management capability."""

    def __init__(self):
        super().__init__(CapabilityMetadata(
            name="tool_registry",
            version="1.0.0",
            description="Tool registration, discovery, and execution",
            category=CapabilityCategory.TOOL,
            is_singleton=True,
            auto_discoverable=True,
            default_action="list_tools",
            supported_actions=["list_tools", "execute_tool"],
        ))
        self._tools = None

    def _initialize(self) -> bool:
        return True

    def _activate(self) -> bool:
        return True

    def _deactivate(self) -> bool:
        return True

    def set_tools(self, tools):
        self._tools = tools

    def action_list_tools(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """List available tools."""
        if not self._tools:
            return {"success": False, "error": "Tools not initialized"}

        try:
            if hasattr(self._tools, "get_available_tools"):
                tools = self._tools.get_available_tools()
            else:
                tools = sorted(getattr(self._tools, "tools", {}).keys())
            return {"success": True, "tools": tools}
        except Exception as e:
            logger.error(f"List tools failed: {e}")
            return {"success": False, "error": str(e)}

    def action_execute_tool(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool."""
        if not self._tools:
            return {"success": False, "error": "Tools not initialized"}

        tool_name = inputs.get("tool", "")
        args = inputs.get("args", {})

        try:
            result = self._tools.execute(tool_name, **args)
            return {"success": True, "result": result}
        except Exception as e:
            logger.error(f"Tool execution failed: {e}")
            return {"success": False, "error": str(e)}


# =============================================================================
# Safety Guard Capability
# =============================================================================

class SafetyGuardCapability(BaseCapability):
    """Safety enforcement capability."""

    def __init__(self):
        super().__init__(CapabilityMetadata(
            name="safety_guard",
            version="1.0.0",
            description="Safety enforcement with risk analysis and human oversight",
            category=CapabilityCategory.SAFETY,
            is_singleton=True,
            auto_discoverable=True,
            default_action="check",
            supported_actions=["check"],
        ))
        self._safety_gate = None

    def _initialize(self) -> bool:
        return True

    def _activate(self) -> bool:
        return True

    def _deactivate(self) -> bool:
        return True

    def set_safety_gate(self, safety_gate):
        self._safety_gate = safety_gate

    def action_check(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Check safety of an operation."""
        if not self._safety_gate:
            return {"success": False, "error": "Safety gate not initialized"}

        operation = inputs.get("operation", "")
        operation_type = inputs.get("operation_type", "")
        context = inputs.get("context", {})

        try:
            result = self._safety_gate.check_and_enforce(operation, operation_type, context)
            allowed = result.allowed
            self._publish_event("safety.checked", {
                "operation_type": operation_type,
                "allowed": allowed,
                "risk_level": result.risk_level.value if hasattr(result.risk_level, 'value') else str(result.risk_level),
            })
            return {
                "success": True,
                "allowed": allowed,
                "risk_level": result.risk_level.value if hasattr(result.risk_level, 'value') else str(result.risk_level),
                "requires_approval": result.requires_approval,
                "reason": result.reason,
            }
        except Exception as e:
            logger.error(f"Safety check failed: {e}")
            return {"success": False, "error": str(e)}


# =============================================================================
# Knowledge Base Capability
# =============================================================================

class KnowledgeBaseCapability(BaseCapability):
    """Thin adapter over MemoryCoordinatorÃ¢â‚¬â„¢s UnifiedRetrieval path."""
    def __init__(self):
        super().__init__(CapabilityMetadata(
            name="knowledge_base",
            version="1.0.0",
            description="Knowledge storage, retrieval, and semantic search",
            category=CapabilityCategory.KNOWLEDGE,
            is_singleton=True,
            auto_discoverable=True,
            default_action="search",
            supported_actions=["search", "store_knowledge"],
        ))
        self._memory = None
        self._retrieval = None


    def _initialize(self) -> bool:
        return True

    def _activate(self) -> bool:
        return True

    def _deactivate(self) -> bool:
        return True

    def set_memory_services(self, memory, retrieval=None):
        """Bind the canonical MemoryCoordinator and UnifiedRetrieval instances."""
        self._memory = memory
        self._retrieval = retrieval or getattr(memory, "unified_retrieval", None)

    def action_search(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Search the shared UnifiedRetrieval stack."""
        if not self._retrieval:
            return {"success": False, "error": "UnifiedRetrieval unavailable"}
        query = str(inputs.get("query", "")).strip()
        if not query:
            return {"success": False, "error": "query required"}
        limit = max(1, min(int(inputs.get("limit", 10)), 100))
        memory_type = inputs.get("memory_type", "unified")
        try:
            if memory_type == "unified":
                results = self._retrieval.retrieve(query)[:limit]
            else:
                results = self._retrieval.retrieve(
                    query if memory_type == "semantic" else query,
                )
                results = [result for result in results if result.source == memory_type][:limit]
            return {
                "success": True,
                "results": [result.to_dict() if hasattr(result, "to_dict") else result for result in results],
            }
        except Exception as e:
            logger.error(f"Knowledge search failed: {e}")
            return {"success": False, "error": str(e)}


    def action_store_knowledge(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Store knowledge through MemoryCoordinatorÃ¢â‚¬â„¢s canonical learning write."""
        if not self._memory:
            return {"success": False, "error": "MemoryCoordinator unavailable"}
        content = str(inputs.get("content", "")).strip()
        title = str(inputs.get("title", "")).strip()
        if not content or not title:
            return {"success": False, "error": "title and content required"}
        metadata = inputs.get("metadata", {}) or {}
        try:
            entry_id = self._memory.store_learned({
                "learning_type": "knowledge",
                "title": title,
                "content": content,
                "category": str(inputs.get("category", "general")),
                "confidence": float(inputs.get("confidence", 0.8)),
                "source": "knowledge_base",
                "tags": list(inputs.get("tags", []) or []),
                "metadata": metadata,
            })
            self._publish_event("knowledge.stored", {"content": content[:100], "id": entry_id})
            return {"success": True, "stored": True, "id": entry_id}
        except Exception as e:
            logger.error(f"Knowledge storage failed: {e}")
            return {"success": False, "error": str(e)}


# =============================================================================
# Reasoning Engine Capability
# =============================================================================

class ReasoningEngineCapability(BaseCapability):
    """Thin adapter over IntelligenceÃ¢â‚¬â„¢s knowledge-first reasoning support."""

    def __init__(self):
        super().__init__(CapabilityMetadata(
            name="reasoning_engine",
            version="1.0.0",
            description="Logical reasoning and problem solving",
            category=CapabilityCategory.REASONING,
            is_singleton=True,
            auto_discoverable=True,
            default_action="analyze",
            supported_actions=["analyze", "synthesize"],
        ))
        self._intelligence = None

    def _initialize(self) -> bool:
        return True

    def _activate(self) -> bool:
        return True

    def _deactivate(self) -> bool:
        return True

    def set_intelligence(self, intelligence):
        """Bind the initializer-owned Intelligence service."""
        self._intelligence = intelligence

    def action_analyze(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze through Intelligence answerability and routing decisions."""
        if not self._intelligence:
            return {"success": False, "error": "Intelligence unavailable"}
        problem = str(inputs.get("problem", "")).strip()
        if not problem:
            return {"success": False, "error": "problem required"}
        context = inputs.get("context", {})
        context = context if isinstance(context, dict) else {"context": context}
        try:
            assessment = self._intelligence.assess_answerability(problem, context)
            decision = self._intelligence.decide_next_action(problem, context)
            self._publish_event("reasoning.analyzed", {"problem": problem[:100]})
            return {
                "success": True,
                "analysis": {
                    "answerability": assessment.to_dict() if hasattr(assessment, "to_dict") else assessment,
                    "next_action": decision,
                },
            }
        except Exception as e:
            logger.error(f"Reasoning analysis failed: {e}")
            return {"success": False, "error": str(e)}

    def action_synthesize(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Return a knowledge-first synthesis route without bypassing answer handling."""
        if not self._intelligence:
            return {"success": False, "error": "Intelligence unavailable"}
        task = str(inputs.get("task", "")).strip()
        if not task:
            return {"success": False, "error": "task required"}
        sources = inputs.get("sources", [])
        context = {"sources": sources} if isinstance(sources, list) else {"sources": [sources]}
        try:
            assessment = self._intelligence.assess_answerability(task, context)
            decision = self._intelligence.decide_next_action(task, context)
            self._publish_event("reasoning.synthesized", {"task": task[:100]})
            return {
                "success": True,
                "synthesis": {
                    "answerability": assessment.to_dict() if hasattr(assessment, "to_dict") else assessment,
                    "next_action": decision,
                    "sources": sources,
                },
            }
        except Exception as e:
            logger.error(f"Reasoning synthesis failed: {e}")
            return {"success": False, "error": str(e)}


# =============================================================================
# Orchestration Core Capability
# =============================================================================

class OrchestrationCoreCapability(BaseCapability):
    """Core orchestration capability."""

    def __init__(self):
        super().__init__(CapabilityMetadata(
            name="orchestration_core",
            version="1.0.0",
            description="Core orchestration - workflow composition and execution",
            category=CapabilityCategory.ORCHESTRATION,
            is_singleton=True,
            auto_discoverable=True,
            default_action="execute_workflow",
            supported_actions=["execute_workflow", "get_status"],
        ))
        self._orchestrator = None

    def _initialize(self) -> bool:
        return True

    def _activate(self) -> bool:
        return True

    def _deactivate(self) -> bool:
        return True

    def set_orchestrator(self, orchestrator):
        self._orchestrator = orchestrator

    def action_execute_workflow(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a workflow."""
        if not self._orchestrator:
            return {"success": False, "error": "Orchestrator not initialized"}

        user_input = inputs.get("input", "")
        context = inputs.get("context", {})

        try:
            workflow_id = self._orchestrator.execute_intent(user_input, context)
            self._publish_event("orchestration.workflow_started", {"workflow_id": workflow_id})
            return {"success": True, "workflow_id": workflow_id}
        except Exception as e:
            logger.error(f"Workflow execution failed: {e}")
            return {"success": False, "error": str(e)}

    def action_get_status(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Get orchestrator status."""
        if not self._orchestrator:
            return {"success": False, "error": "Orchestrator not initialized"}

        try:
            return {"success": True, "status": self._orchestrator.get_system_status()}
        except Exception as e:
            logger.error(f"Status check failed: {e}")
            return {"success": False, "error": str(e)}


# =============================================================================
# Failure Recovery Capability
# =============================================================================

class FailureRecoveryCapability(BaseCapability):
    """Failure detection and recovery capability."""

    def __init__(self):
        super().__init__(CapabilityMetadata(
            name="failure_recovery",
            version="1.0.0",
            description="Failure detection, root cause analysis, and recovery orchestration",
            category=CapabilityCategory.RECOVERY,
            is_singleton=True,
            auto_discoverable=True,
            default_action="detect",
            supported_actions=["detect", "recover", "get_recovery_status"],
        ))
        self._agent = None

    def _initialize(self) -> bool:
        return True

    def _activate(self) -> bool:
        return True

    def _deactivate(self) -> bool:
        return True

    def set_agent(self, agent):
        self._agent = agent

    def action_detect(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Detect failures."""
        if not self._agent or not hasattr(self._agent, 'failure_detector'):
            return {"success": False, "error": "Failure detector not available"}

        # This is typically called internally
        return {"success": True, "message": "Failure detection is automatic"}

    def action_recover(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Attempt recovery from failure."""
        if not self._agent or not hasattr(self._agent, 'recovery_orchestrator'):
            return {"success": False, "error": "Recovery orchestrator not available"}

        failure_context = inputs.get("context", {})

        try:
            # This would be called with a specific failure event
            self._publish_event("recovery.attempted", {"context": failure_context})
            return {"success": True, "message": "Recovery initiated"}
        except Exception as e:
            logger.error(f"Recovery failed: {e}")
            return {"success": False, "error": str(e)}

    def action_get_recovery_status(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Get recovery status."""
        if not self._agent or not hasattr(self._agent, 'recovery_orchestrator'):
            return {"success": False, "error": "Recovery orchestrator not available"}

        return {"success": True, "status": "Recovery system ready"}


# =============================================================================
# File Input and Output Capabilities
# =============================================================================

class _FileCapabilityBase(BaseCapability):
    """Shared policy and metadata helpers for file intake and export."""

    def __init__(self, metadata: CapabilityMetadata, file_allowlist=None, output_root=None):
        super().__init__(metadata)
        from app.core.file_allowlist import get_file_allowlist, normalize_path

        self._file_allowlist = file_allowlist or get_file_allowlist()
        self._normalize_path = normalize_path
        self._output_root = self._normalize_path(output_root or Path.cwd())

    @staticmethod
    def _error(message: str) -> Dict[str, Any]:
        return {"success": False, "error": message, "message": message}

    @staticmethod
    def _coerce_path(value: Any, *, base: Optional[Path] = None) -> Path:
        if isinstance(value, Path):
            path = value
        elif isinstance(value, str) and value.strip():
            path = Path(value.strip()).expanduser()
        else:
            raise ValueError("A non-empty local file path is required")

        if base is not None and not path.is_absolute():
            path = base / path
        return path

    def _validate_access(self, path: Path, operation, source: str) -> Tuple[Optional[Path], Optional[str]]:
        """Validate one file operation through Freya's centralized allowlist."""
        from app.core.file_allowlist import AccessDecision, PathType

        try:
            result = self._file_allowlist.validate_path(
                path,
                operation,
                source=source,
                path_type=PathType.FILE,
            )
        except (OSError, ValueError, TypeError) as error:
            return None, f"Invalid file path: {error}"

        if result.decision != AccessDecision.ALLOWED:
            return None, f"File access denied: {result.reason}"

        try:
            return self._normalize_path(path), None
        except (OSError, ValueError, TypeError) as error:
            return None, f"Unable to normalize file path: {error}"

    @staticmethod
    def _metadata(path: Path) -> Dict[str, Any]:
        from app.core.file_allowlist import FileTypeDetector

        stat = path.stat()
        mime_type, _ = mimetypes.guess_type(path.name)
        return {
            "uri": path.as_uri(),
            "path": str(path),
            "filename": path.name,
            "extension": path.suffix.lower(),
            "mime_type": mime_type or "application/octet-stream",
            "file_type": FileTypeDetector.detect_type(path),
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        }

    @staticmethod
    def _path_from_reference(reference: Any) -> Optional[str]:
        """Extract a local path from current or future UI file-reference shapes."""
        if isinstance(reference, str):
            if reference.startswith("file://"):
                parsed = urlparse(reference)
                path = parsed.path if parsed.netloc.lower() in ("", "localhost") else f"//{parsed.netloc}{parsed.path}"
                path = unquote(path)
                if os.name == "nt":
                    if len(path) >= 3 and path[0] == "/" and path[2] == ":":
                        path = path[1:]
                    path = path.replace("/", "\\")
                return path
            return reference
        if isinstance(reference, dict):
            for key in ("path", "local_path", "file_path", "uri"):
                value = reference.get(key)
                if isinstance(value, str) and value.strip():
                    return _FileCapabilityBase._path_from_reference(value)
        return None


class FileInputCapability(_FileCapabilityBase):
    """Validate and normalize local file references without processing contents."""

    def __init__(self, file_allowlist=None):
        super().__init__(
            CapabilityMetadata(
                name="file_input",
                version="1.0.0",
                description="Validate and normalize a local file reference for downstream capabilities",
                category=CapabilityCategory.TOOL,
                is_singleton=True,
                auto_discoverable=True,
                safe_query=True,
                default_action="intake",
                supported_actions=["intake"],
                tags=["file", "input", "upload", "import", "attachment"],
                provides=["normalized_file_reference"],
            ),
            file_allowlist=file_allowlist,
        )

    def action_intake(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Return a validated file reference and basic metadata for a local file."""
        from app.core.file_allowlist import FileOperation

        reference = inputs.get("file_reference")
        path_value = (
            inputs.get("file_path")
            or inputs.get("path")
            or self._path_from_reference(reference)
        )
        if not path_value:
            return self._error(
                "File input requires 'file_path', 'path', or a local 'file_reference'."
            )

        try:
            requested_path = self._coerce_path(path_value)
        except ValueError as error:
            return self._error(str(error))

        normalized_path, access_error = self._validate_access(
            requested_path,
            FileOperation.READ,
            "FileInputCapability",
        )
        if access_error:
            return self._error(access_error)
        if normalized_path is None:
            return self._error("Unable to normalize the input file path")
        if not normalized_path.exists():
            return self._error(f"Input file does not exist: {normalized_path}")

        if not normalized_path.is_file():
            return self._error(f"Input path is not a regular file: {normalized_path}")
        if not os.access(normalized_path, os.R_OK):
            return self._error(f"Input file is not readable: {normalized_path}")

        try:
            file_reference = self._metadata(normalized_path)
        except OSError as error:
            return self._error(f"Unable to inspect input file: {error}")

        if isinstance(reference, dict) and reference.get("id"):
            file_reference["source_reference_id"] = reference["id"]

        self._publish_event(
            "file.input.accepted",
            {"path": str(normalized_path), "size_bytes": file_reference["size_bytes"]},
        )
        return {
            "success": True,
            "file_reference": file_reference,
            "message": f"File input accepted: {file_reference['filename']}",
        }


class FileOutputCapability(_FileCapabilityBase):
    """Safely persist artifacts supplied by other capabilities without generating content."""

    def __init__(self, file_allowlist=None, output_root=None):
        super().__init__(
            CapabilityMetadata(
                name="file_output",
                version="1.0.0",
                description="Safely save an existing artifact and return its normalized file reference",
                category=CapabilityCategory.TOOL,
                is_singleton=True,
                auto_discoverable=True,
                safe_query=True,
                default_action="write",
                supported_actions=["write"],
                tags=["file", "output", "save", "export", "download"],
                provides=["saved_file_reference"],
            ),
            file_allowlist=file_allowlist,
            output_root=output_root,
        )

    @staticmethod
    def _clean_filename(filename: Any) -> str:
        if not isinstance(filename, str) or not filename.strip():
            raise ValueError("Output filename must be a non-empty string")
        name = filename.strip()
        if "\x00" in name or "/" in name or "\\" in name:
            raise ValueError("Output filename must not contain path separators")
        if name in {".", ".."} or Path(name).name != name:
            raise ValueError("Output filename is invalid")
        return name

    @staticmethod
    def _normalize_extension(value: Any) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Output extension must be a non-empty string")
        extension = value.strip().lower()
        if not extension.startswith("."):
            extension = f".{extension}"
        if len(extension) == 1 or any(char in extension for char in "/\\\x00"):
            raise ValueError("Output extension is invalid")
        return extension

    def _artifact_extension(self, inputs: Dict[str, Any], source_path: Optional[Path], content: Optional[bytes]) -> str:
        requested = self._normalize_extension(inputs.get("extension") or inputs.get("file_extension"))
        if requested:
            return requested
        if source_path and source_path.suffix:
            return source_path.suffix.lower()
        mime_type = inputs.get("mime_type")
        if isinstance(mime_type, str):
            guessed = mimetypes.guess_extension(mime_type, strict=False)
            if guessed:
                return guessed
        # Text is the safe default for inline artifacts. Binary producers should
        # provide a source artifact, MIME type, or explicit extension.
        return ".txt" if content is not None else ".txt"

    def _resolve_target(
        self,
        inputs: Dict[str, Any],
        extension: str,
    ) -> Tuple[Optional[Path], Optional[str]]:
        destination = inputs.get("destination_path") or inputs.get("destination")
        output_dir = inputs.get("output_dir")
        filename = inputs.get("filename") or inputs.get("output_filename")

        try:
            if destination:
                destination_value = str(destination)
                target_or_directory = self._coerce_path(destination_value, base=self._output_root)
                destination_is_directory = bool(inputs.get("destination_is_directory")) or (
                    target_or_directory.exists() and target_or_directory.is_dir()
                ) or destination_value.endswith(("/", "\\"))
                if destination_is_directory:
                    filename = self._clean_filename(filename) if filename else self._generated_filename(extension)
                    target = target_or_directory / filename
                else:
                    if filename:
                        return None, "Specify either a destination file path or a destination directory with filename."
                    target = target_or_directory
            else:
                directory = self._coerce_path(
                    output_dir,
                    base=self._output_root,
                ) if output_dir else self._output_root / "outputs"
                safe_filename = self._clean_filename(filename) if filename else self._generated_filename(extension)
                target = directory / safe_filename
        except ValueError as error:
            return None, str(error)

        if not target.name or target.name in {".", ".."}:
            return None, "Output path must include a file name"
        if not target.suffix:
            target = target.with_name(f"{target.name}{extension}")
        return target, None

    @staticmethod
    def _generated_filename(extension: str) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        return f"artifact-{timestamp}{extension}"

    def _source_path(self, inputs: Dict[str, Any]) -> Optional[str]:
        source = inputs.get("artifact_path") or inputs.get("source_path")
        if source:
            return str(source)
        artifact = inputs.get("artifact") or inputs.get("file_reference")
        return self._path_from_reference(artifact)

    def action_write(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Save inline bytes/text or an existing artifact to an approved destination."""
        from app.core.file_allowlist import FileOperation

        has_content = "content" in inputs
        source_value = self._source_path(inputs)
        if has_content and source_value:
            return self._error("Provide either inline content or one source artifact, not both.")
        if not has_content and not source_value:
            return self._error(
                "File output requires inline 'content' or an existing 'artifact_path' or 'file_reference'."
            )

        content: Optional[bytes] = None
        source_path: Optional[Path] = None
        if has_content:
            raw_content = inputs["content"]
            if isinstance(raw_content, str):
                content = raw_content.encode(inputs.get("encoding", "utf-8"))
            elif isinstance(raw_content, (bytes, bytearray, memoryview)):
                content = bytes(raw_content)
            else:
                return self._error("Inline output content must be text or bytes.")
        else:
            try:
                requested_source = self._coerce_path(source_value)
            except ValueError as error:
                return self._error(str(error))
            source_path, source_error = self._validate_access(
                requested_source,
                FileOperation.READ,
                "FileOutputCapability.source",
            )
            if source_error:
                return self._error(source_error)
            if source_path is None:
                return self._error("Unable to normalize the source artifact path")
            if not source_path.exists() or not source_path.is_file():
                return self._error(f"Source artifact does not exist or is not a file: {source_path}")

        try:
            extension = self._artifact_extension(inputs, source_path, content)
        except ValueError as error:
            return self._error(str(error))
        target, target_error = self._resolve_target(inputs, extension)
        if target_error:
            return self._error(target_error)
        if target is None:
            return self._error("Unable to resolve output path")

        overwrite = bool(inputs.get("overwrite", False))
        normalized_target, access_error = self._validate_access(
            target,
            FileOperation.WRITE if overwrite else FileOperation.CREATE,
            "FileOutputCapability",
        )
        if access_error:
            return self._error(access_error)
        if normalized_target is None:
            return self._error("Unable to normalize the output path")

        if source_path and source_path == normalized_target:
            return self._error("Source artifact and output path must be different.")
        if normalized_target.exists() and not overwrite:
            return self._error(
                f"Refusing to overwrite existing file without overwrite=True: {normalized_target}"
            )
        if not normalized_target.parent.exists() and not bool(inputs.get("create_directories", True)):
            return self._error(f"Output directory does not exist: {normalized_target.parent}")

        try:
            normalized_target.parent.mkdir(parents=True, exist_ok=True)
            mode = "wb" if overwrite else "xb"
            with normalized_target.open(mode) as destination_file:
                if source_path:
                    with source_path.open("rb") as source_file:
                        shutil.copyfileobj(source_file, destination_file)
                else:
                    destination_file.write(content or b"")
            file_reference = self._metadata(normalized_target)
        except FileExistsError:
            return self._error(
                f"Refusing to overwrite existing file without overwrite=True: {normalized_target}"
            )
        except (OSError, ValueError) as error:
            return self._error(f"Unable to save output file: {error}")

        self._publish_event(
            "file.output.saved",
            {
                "path": str(normalized_target),
                "size_bytes": file_reference["size_bytes"],
                "overwritten": overwrite,
            },
        )
        return {
            "success": True,
            "path": str(normalized_target),
            "saved_path": str(normalized_target),
            "file_reference": file_reference,
            "overwritten": overwrite,
            "message": f"Saved output file: {file_reference['filename']}",
        }


# =============================================================================
# Factory function to create all capabilities
# =============================================================================

def create_all_capabilities(agent=None) -> List[Capability]:
    """Create all built-in capabilities and wire them to the agent."""
    # Imported lazily because ResearchCapability is a registry-facing adapter
    # that is intentionally kept in its own research domain module.
    from app.research.capability import ResearchCapability
    from app.browser.capability import BrowserCapability
    from app.document.capability import DocumentEditingCapability
    from app.automation.capability import AutomationCapability
    from app.vision.capability import VisionCapability
    from app.api_connector.capability import APIConnectorCapability
    from app.simulation.capability import SimulationCapability
    capabilities = [

        MemoryManagementCapability(),
        PlanningEngineCapability(),
        CodeExecutionCapability(),
        DecisionEngineCapability(),
        LearningPipelineCapability(),
        SystemMonitoringCapability(),
        CommunicationHubCapability(),
        DebuggingCapability(),
        DependencyManagementCapability(),
        ToolRegistryCapability(),
        SafetyGuardCapability(),
        KnowledgeBaseCapability(),
        ResearchCapability(),
        BrowserCapability(),
        ReasoningEngineCapability(),
        OrchestrationCoreCapability(),
        FileInputCapability(),
        FileOutputCapability(),
        DocumentEditingCapability(),
        AutomationCapability(),
        VisionCapability(),
        APIConnectorCapability(),
        SimulationCapability(),
    ]

    if agent:
        # Wire capabilities to agent
        for cap in capabilities:
            if isinstance(cap, MemoryManagementCapability):
                memory = getattr(agent, "memory_coordinator", getattr(agent, "memory", None))
                if memory is not None:
                    cap.set_memory_coordinator(memory)
            elif isinstance(cap, PlanningEngineCapability):
                cap.set_components(
                    agent.planner,
                    agent.plan_manager,
                    getattr(agent, 'decision_manager', None)
                )
            elif isinstance(cap, CodeExecutionCapability):
                cap.set_components(
                    agent.executor,
                    agent.verifier,
                    agent.patch_engine,
                    agent.tools
                )
            elif isinstance(cap, DecisionEngineCapability):
                cap.set_decision_manager(getattr(agent, 'decision_manager', None))
            elif isinstance(cap, LearningPipelineCapability):
                pipeline = getattr(agent, "learning_pipeline", None)
                if pipeline is not None:
                    cap.set_learning_pipeline(pipeline, getattr(agent, "memory_coordinator", None))
            elif isinstance(cap, SystemMonitoringCapability) and hasattr(agent, 'observability'):
                cap.set_observability(agent.observability)
            elif isinstance(cap, CommunicationHubCapability) and hasattr(agent, 'event_bus'):
                cap.set_event_bus(agent.event_bus)
            elif isinstance(cap, DebuggingCapability) and hasattr(agent, 'tools'):
                cap.set_components(
                    agent.tools,
                    getattr(agent, 'verifier', None),
                    getattr(agent, 'safety_gate', None),
                )
            elif isinstance(cap, DependencyManagementCapability) and hasattr(agent, 'tools'):
                from app.audit.capability_auditor import CapabilityAuditor
                cap.set_components(
                    agent.tools,
                    getattr(agent, 'verifier', None),
                    getattr(agent, 'safety_gate', None),
                    CapabilityAuditor(workspace=str(getattr(agent, 'workspace', '.'))),
                )
            elif isinstance(cap, ToolRegistryCapability):
                cap.set_tools(agent.tools)
            elif isinstance(cap, SafetyGuardCapability) and hasattr(agent, 'safety_gate'):
                cap.set_safety_gate(agent.safety_gate)
            elif isinstance(cap, KnowledgeBaseCapability):
                memory = getattr(agent, "memory_coordinator", getattr(agent, "memory", None))
                if memory is not None:
                    cap.set_memory_services(memory, getattr(agent, "unified_retrieval", None))
            elif isinstance(cap, ReasoningEngineCapability):
                intelligence = getattr(agent, "intelligence", None)
                if intelligence is not None:
                    cap.set_intelligence(intelligence)
            elif isinstance(cap, OrchestrationCoreCapability) and hasattr(agent, 'orchestrator'):
                cap.set_orchestrator(agent.orchestrator)
            elif isinstance(cap, FailureRecoveryCapability):
                cap.set_agent(agent)

    return capabilities
